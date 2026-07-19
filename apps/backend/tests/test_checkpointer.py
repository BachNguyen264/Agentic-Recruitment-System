"""Test slice 08a — Screener suspend/resume (nền bất đồng bộ). PRD §10, §7.3, NFR-2.

Chứng minh CƠ CHẾ (node stub, MemorySaver — KHÔNG chạm Neon/LLM; bài DURABILITY qua restart là
Verify thủ công, xem plan §4):
  1) ca ĐẠT + tự tin → pipeline DỪNG ở screener (interrupt): snapshot.next == ('screener',),
     parser+ranker đã chạy, CHƯA tới human_review.
  2) resume (Command) → screener chạy tiếp → human_review → PENDING_REVIEW; parser/ranker KHÔNG
     chạy lại; screener nhận đúng payload resume.
  3) ca BẤT ĐỊNH (uncertain) KHÔNG đi qua screener — chạy thẳng human_review, KHÔNG suspend.

thread_id ổn định theo lần chạy: dùng cùng config cho chạy đầu + resume (khớp checkpoint).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from app.agents.graph import compile_graph
from app.agents.runner import initial_state
from app.models.application import ApplicationStatus


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    """Chạy hết một lượt astream (bỏ qua sự kiện interrupt) — dừng khi suspend hoặc tới END."""
    async for _update in graph.astream(graph_input, config, stream_mode="updates"):
        pass


def _count(messages: list[str], marker: str) -> int:
    return sum(marker in m for m in messages)


async def test_confident_pass_suspends_at_screener() -> None:
    graph = compile_graph()  # MemorySaver (fresh, cô lập theo test)
    config = {"configurable": {"thread_id": "cp-suspend"}}

    # JD-2b: JD CÓ câu hỏi → suspend ở screener (rỗng câu hỏi thì bỏ qua — test riêng ở test_screener_optional).
    await _drive(graph, initial_state(force_review=False, application_id=1,
                                      jd={"screener_questions": ["Mức lương kỳ vọng?"]}), config)

    snap = await graph.aget_state(config)
    # Đang DỪNG ở screener: còn node chờ chạy.
    assert snap.next == ("screener",)
    # parser + ranker đã chạy, screener CHƯA hoàn tất, CHƯA tới human_review.
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[parser]") == 1
    assert _count(msgs, "[ranker]") == 1
    assert _count(msgs, "[human_review]") == 0
    assert snap.values.get("status") != ApplicationStatus.PENDING_REVIEW.value
    # Payload interrupt (placeholder 08a) mang application_id để 08b gắn form đúng ứng viên.
    interrupts = snap.tasks[0].interrupts
    assert interrupts and interrupts[0].value.get("application_id") == 1


async def test_resume_continues_from_screener_without_rerun() -> None:
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-resume"}}

    await _drive(graph, initial_state(force_review=False, application_id=2,
                                      jd={"screener_questions": ["Mức lương kỳ vọng?"]}), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    # Resume bằng payload MOCK (08b sẽ là câu trả lời thật).
    await _drive(graph, Command(resume={"q1": "mock answer"}), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # đã tới END
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    # parser/ranker KHÔNG chạy lại (checkpointer nạp state cũ) — mỗi cái đúng 1 lần.
    assert _count(msgs, "[parser]") == 1
    assert _count(msgs, "[ranker]") == 1
    # screener resume rồi human_review.
    assert _count(msgs, "[screener] resume") == 1
    assert _count(msgs, "[human_review]") == 1
    # screener nhận đúng payload resume.
    assert snap.values.get("screener_answers") == {"q1": "mock answer"}


# ── Pool BỀN với Neon autosuspend (13 re-verify): guard cấu hình, KHÔNG kết nối Neon ──
def test_pool_configured_for_neon_autosuspend_resilience() -> None:
    """Neon (serverless) ngủ sau ~5 phút và GIẾT kết nối pool → request kế mượn phải kết nối chết →
    `psycopg.errors.AdminShutdown`, cả pipeline hỏng (đúng lỗi gặp trên prod). Pool PHẢI có:
      - `check` khi mượn (ping `execute("")`) → loại + thay kết nối chết thay vì ném lỗi;
      - `max_idle` < ngưỡng autosuspend Neon (~300s) → tự đóng kết nối nhàn rỗi trước khi Neon giết.
    `open=False` nên KHÔNG kết nối Neon — chỉ kiểm cấu hình (guard hồi quy nếu ai gỡ mất).
    """
    from app.agents.checkpointer import _build_pool
    from app.core.config import settings

    pool = _build_pool()
    try:
        assert pool.check is not None, "pool thiếu `check` → kết nối chết sau autosuspend sẽ ném lỗi"
        assert pool.max_idle == settings.checkpointer_pool_max_idle_seconds
        assert pool.max_idle < 300, "max_idle phải < ngưỡng autosuspend Neon (~300s)"
    finally:
        # Chưa từng open (open=False) — không có kết nối để đóng; chỉ dọn cho gọn.
        pass


async def test_uncertain_does_not_go_through_screener() -> None:
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-uncertain"}}

    await _drive(graph, initial_state(force_review=True, application_id=3), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # KHÔNG suspend
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[human_review]") == 1
    assert _count(msgs, "[screener]") == 0  # bất định đi thẳng review, KHÔNG qua screener


# ── background.resume_screener: persist + error handling (mock resume_with_trace + DB) ──


class _FakeSession:
    """AsyncSession tối thiểu cho resume_screener (mock — KHÔNG chạm DB thật)."""

    def __init__(self, rows: dict) -> None:
        self._rows = rows
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0

    async def get(self, model, pk):  # noqa: ANN001
        return self._rows.get((model, pk))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass

    async def rollback(self) -> None:
        self.rollbacks += 1


async def _await_value(value):
    return value


def _resume_out() -> dict:
    return {
        "branch": "human_review",
        "final": {
            "status": ApplicationStatus.PENDING_REVIEW.value,
            "confidence": 1.0,
            "uncertainty_flags": [],
            "escalation_reason": None,
        },
        "trace": [
            {"node": "screener", "status": "SCREENING", "uncertainty_flags": []},
            {"node": "human_review", "status": "PENDING_REVIEW", "uncertainty_flags": []},
        ],
        "suspended": False,
    }


async def test_resume_screener_persists_pending_review(monkeypatch) -> None:
    from app.models.application import Application
    from app.models.audit_log import AuditLog
    from app.tasks import background

    app_row = Application(id=5, applicant_email="a@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 5): app_row})
    monkeypatch.setattr(background, "resume_with_trace", lambda **_kw: _await_value(_resume_out()))

    res = await background.resume_screener(session, 5, {"mock": True})

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert res["status"] == ApplicationStatus.PENDING_REVIEW.value and res["branch"] == "human_review"
    actions = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("screener", "screener_resumed") in actions
    assert ("human_review", "queued_for_human_review") in actions


async def test_resume_screener_error_escalates_not_stuck(monkeypatch) -> None:
    # resume lỗi kỹ thuật (vd commit Neon lỗi sau khi checkpoint đã tiến) KHÔNG được để hồ sơ kẹt câm
    # ở AWAITING_SCREENER → nuốt lỗi → PENDING_REVIEW[error] (hiện trong hàng chờ HR).
    from app.models.application import Application
    from app.tasks import background

    app_row = Application(id=6, applicant_email="a@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 6): app_row})

    async def boom(**_kw):
        raise RuntimeError("neon blip during resume")

    monkeypatch.setattr(background, "resume_with_trace", boom)

    res = await background.resume_screener(session, 6, {"mock": True})  # KHÔNG raise ra ngoài

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # KHÔNG kẹt ở AWAITING_SCREENER
    assert app_row.escalation_reason  # có lý do lỗi cho HR
    assert session.rollbacks == 1
    assert res["branch"] == "error"
