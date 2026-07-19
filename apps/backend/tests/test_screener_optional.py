"""Test JD-2b — Screener TÙY CHỌN (PRD §7.3 FR-SCR-0, §8.3, §10).

CV đạt + JD KHÔNG câu hỏi → BỎ QUA screener (KHÔNG suspend/email) → gate mời/human_review.
CV đạt + JD CÓ câu hỏi → GIỮ NGUYÊN đường suspend/resume (08a-d) — BẤT BIẾN.

Phủ (mock — KHÔNG gửi email/chạm DB thật):
  1) screener_node: no-questions → pass-through sạch (KHÔNG cờ, KHÔNG no_response).
  2) graph e2e: no-questions → KHÔNG dừng ở screener; gate OFF→human_review / ON→scheduler.
     has-questions → VẪN dừng (suspend) + resume vẫn chạy (không hồi quy).
  3) background.process_application: no-questions + auto_invite ON → thư mời THẬT (INTERVIEW_SCHEDULED);
     OFF → human_review KHÔNG email/không session; lỗi dispatch CÔ LẬP (không "mời xong lại từ chối").

GOTCHA (bất biến): "bỏ-qua" ≠ "no_response". Bỏ-qua = không có gì để hỏi → sạch. no_response = có câu
hỏi nhưng im lặng → human_review (đường timeout, KHÔNG đụng ở đây).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from app.agents.graph import compile_graph
from app.agents.nodes.screener import screener_node
from app.agents.runner import _branch, initial_state
from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.job_posting import JobPosting

_GATE_OFF = {"auto_reject": False, "auto_invite": False}
_GATE_INVITE_ON = {"auto_reject": False, "auto_invite": True}
_JD_NOQ_OFF = {"title": "Backend", "gate_config": _GATE_OFF, "screener_questions": []}
_JD_NOQ_ON = {"title": "Backend", "gate_config": _GATE_INVITE_ON, "screener_questions": []}
_JD_HASQ = {"title": "Backend", "gate_config": _GATE_OFF, "screener_questions": ["Mức lương kỳ vọng?"]}


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    async for _ in graph.astream(graph_input, config, stream_mode="updates"):
        pass


async def _await_value(value: Any) -> Any:
    return value


# ── 1) screener_node unit: no-questions → pass-through sạch ───────────────────


def test_screener_node_no_questions_passthrough() -> None:
    out = screener_node({"input": {"jd": _JD_NOQ_OFF}, "application_id": 5})
    assert out["awaiting_screener"] is False
    assert out["screener_answers"] is None
    assert out["uncertainty_flags"] == []            # KHÔNG cờ
    assert "no_response" not in out["uncertainty_flags"]  # KHÔNG ghosting (khác timeout)
    assert out["confidence"] == 1.0
    assert out["status"] == ApplicationStatus.SCREENING.value


def test_screener_node_no_jd_skips_no_empty_form() -> None:
    # App KHÔNG có JD (jd rỗng) → không gì để sàng lọc → BỎ QUA (KHÔNG suspend-form-rỗng). Pass-through
    # sạch; route sau đó về human_review (auto_invite OFF vì không gate_config). Chốt contract null-JD.
    out = screener_node({"input": {}})
    assert out["awaiting_screener"] is False
    assert out["uncertainty_flags"] == []
    assert out["screener_answers"] is None


# ── 1b) ADVERSARIAL FIXES: parse_failed KHÔNG bị auto-mời + cross-deploy snapshot cũ an toàn ──────


async def test_ranker_parse_failed_not_laundered_to_clean() -> None:
    """Finding ① (safety auditor): CV parse-fail (cờ parse_failed, parsed_data=None) → ranker KHÔNG được
    coi là stub sạch (xóa cờ + confidence 1.0). GIỮ cờ → route_after_ranker → human_review (KHÔNG tới
    screener/gate mời dù auto_invite ON). Nếu không, CV-không-đọc-được bị AUTO-MỜI."""
    from app.agents.nodes.ranker import ranker_node
    from app.agents.policy import route_after_ranker

    state = {
        "parsed_data": None,
        "confidence": 0.0,
        "uncertainty_flags": ["parse_failed"],
        "escalation_reason": "Không đọc được file CV.",
        "input": {"jd": {"gate_config": _GATE_INVITE_ON, "screener_questions": []}},
    }
    out = await ranker_node(state)

    assert "parse_failed" in out["uncertainty_flags"]  # cờ KHÔNG bị erase
    assert out["score"] is None and out["confidence"] == 0.0
    assert route_after_ranker({**state, **out}) == "human_review"  # KHÔNG screener/auto_invite


async def test_old_snapshot_missing_key_suspends_not_skips() -> None:
    """Finding ② (correctness): snapshot CŨ (suspend TRƯỚC JD-2b) THIẾU key screener_questions + auto_invite
    ON. Guard chạy lúc resume PHẢI coi như CÓ câu hỏi (interrupt, KHÔNG skip) → timeout resume no_response
    → human_review (KHÔNG auto-mời ứng viên ghosting)."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "old-snap"}}
    jd_no_key = {"title": "Backend", "gate_config": _GATE_INVITE_ON}  # THIẾU screener_questions (snapshot cũ)

    await _drive(graph, initial_state(force_review=False, application_id=30, jd=jd_no_key), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # suspend dù thiếu key (KHÔNG skip)

    await _drive(graph, Command(resume={"no_response": True}), config)  # timeout
    snap = await graph.aget_state(config)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value  # human_review
    assert "no_response" in (snap.values.get("uncertainty_flags") or [])
    assert sum("[scheduler]" in m for m in snap.values.get("messages", [])) == 0  # KHÔNG auto-mời


# ── 2) graph e2e: bỏ-qua vs suspend ──────────────────────────────────────────


async def test_no_questions_skips_screener_to_human_review() -> None:
    """JD không câu hỏi + gate mời TẮT → KHÔNG suspend, đi thẳng human_review (PENDING_REVIEW)."""
    graph = compile_graph()  # MemorySaver
    config = {"configurable": {"thread_id": "nq-off"}}
    await _drive(graph, initial_state(force_review=False, application_id=1, jd=_JD_NOQ_OFF), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # KHÔNG dừng ở screener (không suspend)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    assert sum("BỎ QUA" in m for m in msgs) == 1                      # screener skip
    assert sum("[human_review]" in m for m in msgs) == 1
    assert "no_response" not in (snap.values.get("uncertainty_flags") or [])


async def test_no_questions_auto_invite_routes_scheduler() -> None:
    """JD không câu hỏi + auto_invite BẬT → CV sạch → scheduler (SCHEDULING), branch=auto_invite."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "nq-on"}}
    await _drive(graph, initial_state(force_review=False, application_id=2, jd=_JD_NOQ_ON), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # KHÔNG suspend
    assert snap.values.get("status") == ApplicationStatus.SCHEDULING.value
    assert sum("[human_review]" in m for m in snap.values.get("messages", [])) == 0
    assert _branch(suspended=False, nodes_run={"parser", "ranker", "screener", "scheduler"}) == "auto_invite"


async def test_has_questions_still_suspends() -> None:
    """BẤT BIẾN (08a): JD CÓ câu hỏi → interrupt → DỪNG ở screener (AWAITING_SCREENER)."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "hq"}}
    await _drive(graph, initial_state(force_review=False, application_id=3, jd=_JD_HASQ), config)

    assert (await graph.aget_state(config)).next == ("screener",)  # suspend giữ nguyên


async def test_has_questions_resume_no_regression() -> None:
    """BẤT BIẾN (08b): đường CÓ câu hỏi vẫn suspend → resume bằng answers → human_review (gate OFF)."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "hq-resume"}}
    await _drive(graph, initial_state(force_review=False, application_id=4, jd=_JD_HASQ), config)
    assert (await graph.aget_state(config)).next == ("screener",)

    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)
    snap = await graph.aget_state(config)
    assert snap.next == ()
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    assert sum("[parser]" in m for m in snap.values.get("messages", [])) == 1  # KHÔNG rerun parser


# ── 3) background.process_application: ca bỏ-qua ──────────────────────────────


class _FakeSession:
    def __init__(self, rows: dict) -> None:
        self._rows = rows
        self.added: list = []
        self.commits = 0

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
        pass


class _Ctx:
    def __init__(self, session: _FakeSession) -> None:
        self._s = session

    async def __aenter__(self) -> _FakeSession:
        return self._s

    async def __aexit__(self, *_a) -> bool:
        return False


def _no_q_out(branch: str, status: str) -> dict:
    return {
        "branch": branch,
        "final": {
            "status": status,
            "parsed_data": {"full_name": "Nguyễn Văn A"},
            "score": 85.0,
            "semantic_similarity": 0.8,
            "confidence": 1.0,
            "uncertainty_flags": [],
            "escalation_reason": None,
            "scratchpad": {},
            "input": {"jd": {"title": "Backend Intern"}},
        },
        "trace": [
            {"node": "parser", "status": "PARSED", "uncertainty_flags": []},
            {"node": "ranker", "status": "RANKING", "uncertainty_flags": []},
            {"node": "screener", "status": "SCREENING", "uncertainty_flags": []},
            {"node": "scheduler" if branch == "auto_invite" else "human_review",
             "status": status, "uncertainty_flags": []},
        ],
        "suspended": False,
    }


async def test_process_no_questions_auto_invite_sends_invite(monkeypatch) -> None:
    """No-questions + auto_invite ON: ca sạch → thư mời THẬT (INTERVIEW_SCHEDULED) NGAY lần chạy đầu."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=20, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern")
    session = _FakeSession({(Application, 20): app_row, (JobPosting, 2): job})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_no_q_out("auto_invite", ApplicationStatus.SCHEDULING.value)),
    )

    captured: dict = {}

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(scheduler, "notify_decision", fake_notify)

    await background.process_application(20)

    assert app_row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value  # chỉ đặt khi thư mời đã gửi
    assert captured["mode"] == "invite" and captured["applicant_email"] == "me@e.com"
    assert captured["candidate_name"] == "Nguyễn Văn A" and captured["job_title"] == "Backend Intern"
    audits = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("gate", "auto_invite") in audits
    assert ("screener", "screener_skipped") in audits  # audit ghi rõ đã BỎ QUA


async def test_process_no_questions_gate_off_human_review_no_email(monkeypatch) -> None:
    """No-questions + auto_invite OFF: → human_review, KHÔNG gửi email, KHÔNG tạo screening_session."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=21, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern")
    session = _FakeSession({(Application, 21): app_row, (JobPosting, 2): job})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_no_q_out("human_review", ApplicationStatus.PENDING_REVIEW.value)),
    )

    async def boom_notify(*_a, **_kw):
        raise AssertionError("KHÔNG được gửi email cho ca bỏ-qua + gate OFF")

    def boom_session(*_a, **_kw):
        raise AssertionError("KHÔNG được tạo screening_session khi bỏ-qua screener")

    monkeypatch.setattr(scheduler, "notify_decision", boom_notify)
    monkeypatch.setattr("app.services.screening.create_session", boom_session)

    await background.process_application(21)

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # thẳng human_review


async def test_process_no_questions_auto_invite_error_isolated(monkeypatch) -> None:
    """An toàn: lỗi SAU khi VÀO nhánh gửi mời (thư CÓ THỂ đã gửi) KHÔNG reset về error — giữ SCHEDULING."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=22, applicant_email="me@e.com", job_id=2, status="SUBMITTED")
    job = JobPosting(id=2, title="Backend Intern")
    session = _FakeSession({(Application, 22): app_row, (JobPosting, 2): job})
    monkeypatch.setattr(background, "AsyncSessionLocal", lambda: _Ctx(session))
    monkeypatch.setattr(
        background, "run_with_trace",
        lambda **_kw: _await_value(_no_q_out("auto_invite", ApplicationStatus.SCHEDULING.value)),
    )

    async def raising_notify(*_a, **_kw):
        raise RuntimeError("neon blip after invite email may have been sent")

    monkeypatch.setattr(scheduler, "notify_decision", raising_notify)

    await background.process_application(22)  # KHÔNG raise ra ngoài

    assert app_row.status == ApplicationStatus.SCHEDULING.value  # KHÔNG reset về PENDING_REVIEW[error]
    assert app_row.escalation_reason != "Lỗi kỹ thuật khi xử lý pipeline (error)."
