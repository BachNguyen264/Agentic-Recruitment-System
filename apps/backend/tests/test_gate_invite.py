"""Test slice 08d — Gate auto-mời SAU screener (đối xứng auto-reject 03c). PRD §9, §8.3.

Phủ (mock scheduler/email — KHÔNG gửi thật, KHÔNG chạm DB thật):
  1) route_after_screener: ca SẠCH + auto_invite ON → auto_invite; OFF → human_review;
     ca KHÔNG sạch (no_response / cờ / low-conf / error) + gate ON → human_review LUÔN ("cờ thắng gate").
  2) scheduler_node = marker SCHEDULING (quyết định mời, chưa gửi — pure, không email).
  3) background.resume_screener nhánh auto_invite → notify_decision("invite"); email OK → INTERVIEW_SCHEDULED,
     email FAIL → PENDING_REVIEW (KHÔNG "trạng thái nói dối").

BẤT BIẾN (PRD §9 FR-GATE-2): gate CHỈ áp ca tự tin/sạch; ca bất định/no_response LUÔN → human_review.
"""

from __future__ import annotations

from app.agents.policy import route_after_screener


def _state(
    *,
    confidence: float = 1.0,
    flags: list[str] | None = None,
    error: str | None = None,
    auto_invite: bool = False,
) -> dict:
    return {
        "error": error,
        "confidence": confidence,
        "uncertainty_flags": flags or [],
        "input": {"jd": {"gate_config": {"auto_reject": False, "auto_invite": auto_invite}}},
    }


# ── route_after_screener: ca sạch để gate quyết; ca không sạch LUÔN về người ──────────────


def test_route_clean_gate_on_auto_invites() -> None:
    # Đã trả lời (confident, không cờ) + auto_invite BẬT → auto_invite.
    assert route_after_screener(_state(auto_invite=True)) == "auto_invite"


def test_route_clean_gate_off_human_review() -> None:
    # Cùng ca nhưng auto_invite TẮT → human_review (mặc định, hành vi trước 08d KHÔNG đổi).
    assert route_after_screener(_state(auto_invite=False)) == "human_review"


def test_route_no_response_gate_on_still_human_review() -> None:
    # Timeout (no_response) + gate BẬT → human_review LUÔN (an toàn — im lặng ≠ mời).
    assert route_after_screener(_state(flags=["no_response"], auto_invite=True)) == "human_review"


def test_route_flagged_gate_on_still_human_review() -> None:
    # Cờ bất định + gate BẬT → human_review (gate no-op).
    assert route_after_screener(_state(flags=["weak_match"], auto_invite=True)) == "human_review"


def test_route_low_confidence_gate_on_still_human_review() -> None:
    assert route_after_screener(_state(confidence=0.3, auto_invite=True)) == "human_review"


def test_route_error_gate_on_still_human_review() -> None:
    assert route_after_screener(_state(error="boom", auto_invite=True)) == "human_review"


def test_route_no_jd_defaults_human_review() -> None:
    # Không JD/không gate_config → auto_invite mặc định TẮT → human_review.
    assert route_after_screener({"confidence": 1.0, "uncertainty_flags": [], "input": {}}) == "human_review"


# ── graph end-to-end: cạnh conditional sau screener + node auto-mời + nhãn nhánh ──────────

from typing import Any  # noqa: E402

from langgraph.types import Command  # noqa: E402

from app.agents.graph import compile_graph  # noqa: E402
from app.agents.runner import _branch, initial_state  # noqa: E402
from app.models.application import ApplicationStatus  # noqa: E402

_JD_INVITE_ON = {"title": "Backend", "gate_config": {"auto_reject": False, "auto_invite": True}}
_JD_INVITE_OFF = {"title": "Backend", "gate_config": {"auto_reject": False, "auto_invite": False}}


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    async for _ in graph.astream(graph_input, config, stream_mode="updates"):
        pass


async def test_graph_clean_resume_auto_invite_routes_scheduler() -> None:
    """Ca sạch + JD auto_invite ON: resume → screener → scheduler (SCHEDULING), KHÔNG human_review."""
    graph = compile_graph()  # MemorySaver
    config = {"configurable": {"thread_id": "gi-on"}}
    await _drive(graph, initial_state(force_review=False, application_id=1, jd=_JD_INVITE_ON), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()
    # scheduler node đặt SCHEDULING (marker mời — chưa INTERVIEW_SCHEDULED); KHÔNG qua human_review.
    assert snap.values.get("status") == ApplicationStatus.SCHEDULING.value
    msgs = snap.values.get("messages", [])
    assert sum("[scheduler] auto-mời" in m for m in msgs) == 1
    assert sum("[human_review]" in m for m in msgs) == 0
    assert sum("[parser]" in m for m in msgs) == 1  # KHÔNG rerun parser/ranker
    # nhãn nhánh (_branch) = auto_invite (background sẽ gửi thư mời).
    nodes_run = {"parser", "ranker", "screener", "scheduler"}
    assert _branch(suspended=False, nodes_run=nodes_run) == "auto_invite"


async def test_graph_clean_resume_gate_off_human_review() -> None:
    """Ca sạch + JD auto_invite OFF: resume → human_review (mặc định, KHÔNG auto-mời)."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "gi-off"}}
    await _drive(graph, initial_state(force_review=False, application_id=2, jd=_JD_INVITE_OFF), config)
    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    assert sum("[human_review]" in m for m in msgs) == 1
    assert sum("[scheduler]" in m for m in msgs) == 0


# ── background.resume_screener: nhánh auto_invite → thư mời THẬT; lỗi gửi KHÔNG "nói dối" ──

from app.models.application import Application  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402


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

    async def rollback(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


async def _await_value(v):
    return v


def _auto_invite_out() -> dict:
    return {
        "branch": "auto_invite",
        "final": {
            "status": ApplicationStatus.SCHEDULING.value,
            "parsed_data": {"full_name": "Nguyễn Văn A"},
            "input": {"jd": {"title": "Backend Intern"}},
            "confidence": 1.0,
            "uncertainty_flags": [],
            "escalation_reason": None,
        },
        "trace": [
            {"node": "screener", "status": "SCHEDULING", "uncertainty_flags": []},
            {"node": "scheduler", "status": "SCHEDULING", "uncertainty_flags": []},
        ],
        "suspended": False,
    }


async def test_resume_auto_invite_sends_invite_and_schedules(monkeypatch) -> None:
    """auto_invite + email gửi OK → INTERVIEW_SCHEDULED + delegate scheduler(invite) đúng + audit."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=7, applicant_email="me@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 7): app_row})
    monkeypatch.setattr(background, "resume_with_trace", lambda **_kw: _await_value(_auto_invite_out()))

    captured: dict = {}

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001 — khớp chữ ký notify_decision
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(scheduler, "notify_decision", fake_notify)

    res = await background.resume_screener(session, 7, {"answers": [{"question": "Q", "answer": "A"}]})

    assert app_row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value  # chỉ đặt khi thư mời đã gửi
    assert res["status"] == ApplicationStatus.INTERVIEW_SCHEDULED.value and res["branch"] == "auto_invite"
    assert captured["mode"] == "invite" and captured["applicant_email"] == "me@e.com"
    assert captured["candidate_name"] == "Nguyễn Văn A" and captured["job_title"] == "Backend Intern"
    actions = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("gate", "auto_invite") in actions


async def test_resume_auto_invite_email_fail_goes_review_no_lie(monkeypatch) -> None:
    """auto_invite + email gửi TRƯỢT → KHÔNG đặt INTERVIEW_SCHEDULED (không "nói dối") → PENDING_REVIEW + cờ."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=8, applicant_email="me@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 8): app_row})
    monkeypatch.setattr(background, "resume_with_trace", lambda **_kw: _await_value(_auto_invite_out()))

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001 — email trượt (notify_decision nuốt lỗi)
        return {"mode": mode, "email_sent": False, "error": "resend down"}

    monkeypatch.setattr(scheduler, "notify_decision", fake_notify)

    res = await background.resume_screener(session, 8, {"answers": [{"question": "Q", "answer": "A"}]})

    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # KHÔNG giả "đã hẹn"
    assert app_row.escalation_reason and "thư mời" in app_row.escalation_reason
    assert res["status"] == ApplicationStatus.PENDING_REVIEW.value
    actions = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("gate", "auto_invite_failed") in actions


async def test_resume_human_review_branch_never_invites(monkeypatch) -> None:
    """Không hồi quy: branch human_review (gate OFF / no_response) KHÔNG gọi scheduler (không auto-mời)."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=9, applicant_email="me@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 9): app_row})
    hr_out = {
        "branch": "human_review",
        "final": {"status": ApplicationStatus.PENDING_REVIEW.value, "confidence": 1.0,
                  "uncertainty_flags": [], "escalation_reason": None},
        "trace": [{"node": "screener", "status": "SCREENING", "uncertainty_flags": []},
                  {"node": "human_review", "status": "PENDING_REVIEW", "uncertainty_flags": []}],
        "suspended": False,
    }
    monkeypatch.setattr(background, "resume_with_trace", lambda **_kw: _await_value(hr_out))

    async def boom_notify(*_a, **_kw):
        raise AssertionError("notify_decision KHÔNG được gọi cho branch human_review")

    monkeypatch.setattr(scheduler, "notify_decision", boom_notify)

    res = await background.resume_screener(session, 9, {"no_response": True})
    assert res["branch"] == "human_review" and app_row.status == ApplicationStatus.PENDING_REVIEW.value


async def test_resume_auto_invite_dispatch_error_isolated(monkeypatch) -> None:
    """BUG (adversarial 08d): lỗi SAU khi VÀO nhánh gửi mời (thư mời CÓ THỂ đã gửi) KHÔNG được để outer
    handler reset về PENDING_REVIEW[error] → tránh "mời xong lại từ chối". Dispatch phải CÔ LẬP (như
    auto_reject 03c): case giữ SCHEDULING (đã commit), KHÔNG rơi vào nhánh lỗi kỹ thuật."""
    from app.agents.nodes import scheduler
    from app.tasks import background

    app_row = Application(id=11, applicant_email="me@e.com", job_id=2, status="AWAITING_SCREENER")
    session = _FakeSession({(Application, 11): app_row})
    monkeypatch.setattr(background, "resume_with_trace", lambda **_kw: _await_value(_auto_invite_out()))

    async def raising_notify(*_a, **_kw):  # lỗi SAU khi có thể đã gửi thư (vd commit audit lỗi)
        raise RuntimeError("neon blip after invite email may have been sent")

    monkeypatch.setattr(scheduler, "notify_decision", raising_notify)

    await background.resume_screener(session, 11, {"answers": [{"question": "Q", "answer": "A"}]})

    # KHÔNG reset về PENDING_REVIEW[error]: giữ SCHEDULING (trạng thái đã commit ở main commit).
    assert app_row.status == ApplicationStatus.SCHEDULING.value
    assert app_row.escalation_reason != "Lỗi kỹ thuật khi resume screener (error)."
