"""Test slice 08c — Screener timeout (nhắc + hết hạn + trả lời trễ). PRD §10 FR-SCR-3/4/5.

Ba mảng:
  A) screener node phân biệt resume câu-trả-lời (08b) vs tín hiệu `no_response` (timeout) — qua graph
     + MemorySaver (KHÔNG chạm Neon/LLM).
  B) handlers nghiệp vụ (send_screening_reminder / handle_screening_timeout) + sweep_once — mock DB
     + mock resume/scheduler (đơn vị hóa; row-lock/concurrency kiểm ở Verify live).
  C) trả lời trễ: session hết hạn / đã timeout → _load_valid từ chối êm (không resume lại).

Ranh giới: im lặng ≠ từ chối — timeout LUÔN → human_review + cờ no_response, KHÔNG auto-reject.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from langgraph.types import Command

from app.agents.graph import compile_graph
from app.agents.runner import initial_state
from app.models.application import ApplicationStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    async for _update in graph.astream(graph_input, config, stream_mode="updates"):
        pass


def _count(messages: list[str], marker: str) -> int:
    return sum(marker in m for m in messages)


# ── A) screener node: resume no_response → human_review + cờ, KHÔNG auto-reject ──────────


async def test_resume_no_response_routes_human_review_with_flag() -> None:
    """Timeout resume (`{"no_response": True}`) → screener đi tiếp human_review với cờ no_response +
    escalation_reason; parser/ranker KHÔNG chạy lại; status PENDING_REVIEW (KHÔNG REJECTED)."""
    graph = compile_graph()  # MemorySaver, cô lập
    config = {"configurable": {"thread_id": "cp-timeout"}}

    # JD-2b: JD CÓ câu hỏi → đi nhánh suspend (timeout chỉ áp đường có câu hỏi).
    await _drive(graph, initial_state(force_review=False, application_id=9,
                                      jd={"screener_questions": ["Mức lương kỳ vọng?"]}), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    await _drive(graph, Command(resume={"no_response": True}), config)  # tín hiệu timeout

    snap = await graph.aget_state(config)
    assert snap.next == ()  # tới END
    # KHÔNG auto-reject: đi human_review → PENDING_REVIEW.
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    assert "no_response" in (snap.values.get("uncertainty_flags") or [])
    assert snap.values.get("escalation_reason")  # có lý do "không phản hồi" cho HR
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[parser]") == 1 and _count(msgs, "[ranker]") == 1  # KHÔNG rerun
    assert _count(msgs, "[human_review]") == 1


async def test_resume_real_answers_still_works_no_flag() -> None:
    """Không hồi quy 08b: resume câu-trả-lời-thật (payload có `answers`) KHÔNG gắn cờ no_response."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-answers"}}

    await _drive(graph, initial_state(force_review=False, application_id=10,
                                      jd={"screener_questions": ["Mức lương kỳ vọng?"]}), config)
    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    assert "no_response" not in (snap.values.get("uncertainty_flags") or [])
    assert snap.values.get("screener_answers") == {"answers": [{"question": "Q", "answer": "A"}]}


# ── B) handlers + sweep: mock DB (fake session) + mock resume/scheduler ───────────────────

from app.models.application import Application  # noqa: E402
from app.models.audit_log import AuditLog  # noqa: E402
from app.models.job_posting import JobPosting  # noqa: E402
from app.models.screening_session import ScreeningSession  # noqa: E402
from app.services import screening_timeout  # noqa: E402


class _FakeSession:
    """AsyncSession tối thiểu cho handler (get/add/flush/commit) — KHÔNG chạm DB thật."""

    def __init__(self, rows: dict | None = None) -> None:
        self._rows = rows or {}
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

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_a) -> bool:
        return False


def _sess(**kw) -> ScreeningSession:
    defaults = dict(id=1, application_id=1, token="tok123", expires_at=_now() + timedelta(hours=1))
    defaults.update(kw)
    return ScreeningSession(**defaults)


async def test_send_reminder_marks_once_and_calls_scheduler(monkeypatch) -> None:
    """Nhắc: set reminded_at + commit + gọi scheduler reminder=True với magic-link cũ (điểm phát email)."""
    app_row = Application(
        id=1, applicant_email="me@e.com", job_id=2,
        parsed_data={"full_name": "Bách"}, status=ApplicationStatus.AWAITING_SCREENER.value,
    )
    session = _FakeSession({(Application, 1): app_row, (JobPosting, 2): JobPosting(id=2, title="Backend")})
    sess = _sess()
    calls: dict = {}

    async def fake_notify(_s, **kw):  # noqa: ANN001
        calls.update(kw)
        return {"email_sent": True}

    monkeypatch.setattr(screening_timeout.scheduler, "notify_screener", fake_notify)
    await screening_timeout.send_screening_reminder(session, sess)

    assert sess.reminded_at is not None  # once-only marker
    assert session.commits >= 1  # chốt reminded_at TRƯỚC gửi
    assert calls["reminder"] is True and calls["application_id"] == 1
    assert "tok123" in calls["form_url"]  # DÙNG LẠI magic-link cũ


async def test_handle_timeout_resumes_no_response_and_marks(monkeypatch) -> None:
    """Timeout: resume `{"no_response": True}` + mark timed_out_at (pre_commit) + audit screener_timeout.
    KHÔNG auto-reject (đi qua resume_screener → human_review)."""
    session = _FakeSession()
    sess = _sess(id=1, application_id=1, expires_at=_now() - timedelta(minutes=1))
    captured: dict = {}

    async def fake_resume(_s, app_id, payload, *, pre_commit=None):  # noqa: ANN001
        captured["app_id"] = app_id
        captured["payload"] = payload
        if pre_commit is not None:
            pre_commit()  # mô phỏng: chạy hook TRƯỚC commit (đánh dấu timed_out)
        return {"branch": "human_review", "status": ApplicationStatus.PENDING_REVIEW.value}

    monkeypatch.setattr(screening_timeout.background, "resume_screener", fake_resume)
    await screening_timeout.handle_screening_timeout(session, sess)

    assert captured["app_id"] == 1
    assert captured["payload"] == {"no_response": True}  # KHÔNG câu trả lời — chỉ tín hiệu timeout
    assert sess.timed_out_at is not None  # idempotent marker (nguyên tử với resume)
    actions = [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]
    assert ("screener", "screener_timeout") in actions


# ── sweep_once: dispatch + idempotent re-check + cô lập lỗi ───────────────────────────────


def _factory(session: _FakeSession):
    """session_factory giả: mỗi lần gọi trả CÙNG fake session (đủ cho test dispatch/re-check)."""
    return lambda: session


async def test_sweep_dispatches_reminder_and_timeout(monkeypatch) -> None:
    session = _FakeSession()
    monkeypatch.setattr(screening_timeout, "_due_reminder_ids", lambda *_a: _await([1]))
    monkeypatch.setattr(screening_timeout, "_due_timeout_ids", lambda *_a: _await([2]))
    monkeypatch.setattr(
        screening_timeout, "_lock_session",
        lambda _s, sid: _await(_sess(id=sid, application_id=sid)),  # fresh, chưa mark
    )
    reminded, timed_out = [], []
    monkeypatch.setattr(screening_timeout, "send_screening_reminder", lambda _s, r: _record(reminded, r))
    monkeypatch.setattr(screening_timeout, "handle_screening_timeout", lambda _s, r: _record(timed_out, r))

    counts = await screening_timeout.sweep_once(_factory(session))

    assert counts == {"reminded": 1, "timed_out": 1, "errors": 0}
    assert [r.id for r in reminded] == [1] and [r.id for r in timed_out] == [2]


async def test_sweep_skips_already_marked_idempotent(monkeypatch) -> None:
    """Re-check trong lock: session đã reminded/timed_out/used → KHÔNG xử đôi (idempotent + đua submit)."""
    session = _FakeSession()
    monkeypatch.setattr(screening_timeout, "_due_reminder_ids", lambda *_a: _await([1]))
    monkeypatch.setattr(screening_timeout, "_due_timeout_ids", lambda *_a: _await([2, 3]))

    def _lock(_s, sid):  # id=1 đã nhắc; id=2 đã trả lời (used_at); id=3 đã timeout
        marks = {
            1: _sess(id=1, reminded_at=_now()),
            2: _sess(id=2, used_at=_now()),
            3: _sess(id=3, timed_out_at=_now()),
        }
        return _await(marks[sid])

    monkeypatch.setattr(screening_timeout, "_lock_session", _lock)
    reminded, timed_out = [], []
    monkeypatch.setattr(screening_timeout, "send_screening_reminder", lambda _s, r: _record(reminded, r))
    monkeypatch.setattr(screening_timeout, "handle_screening_timeout", lambda _s, r: _record(timed_out, r))

    counts = await screening_timeout.sweep_once(_factory(session))

    assert counts == {"reminded": 0, "timed_out": 0, "errors": 0}  # tất cả bị re-check chặn
    assert reminded == [] and timed_out == []


async def test_sweep_one_error_does_not_kill_loop(monkeypatch) -> None:
    """Lỗi một session KHÔNG làm chết cả vòng — các session khác vẫn xử lý."""
    session = _FakeSession()
    monkeypatch.setattr(screening_timeout, "_due_reminder_ids", lambda *_a: _await([]))
    monkeypatch.setattr(screening_timeout, "_due_timeout_ids", lambda *_a: _await([2, 3]))
    monkeypatch.setattr(
        screening_timeout, "_lock_session",
        lambda _s, sid: _await(_sess(id=sid, application_id=sid)),
    )
    ok: list = []

    async def _boom_then_ok(_s, r):
        if r.id == 2:
            raise RuntimeError("neon blip on id=2")
        ok.append(r)

    monkeypatch.setattr(screening_timeout, "handle_screening_timeout", _boom_then_ok)

    counts = await screening_timeout.sweep_once(_factory(session))

    assert counts == {"reminded": 0, "timed_out": 1, "errors": 1}
    assert [r.id for r in ok] == [3]  # id=3 vẫn được xử dù id=2 lỗi


# ── C) trả lời trễ: _load_valid từ chối ÊM khi đã timeout (KHÔNG resume lại) ──────────────


async def test_load_valid_timed_out_returns_expired_message() -> None:
    """Session đã timeout (dù expires_at có thể chưa tới) → TokenExpired 410 thông điệp trấn an."""
    from app.services import screening

    class _R:
        def __init__(self, obj):
            self._obj = obj

        def scalar_one_or_none(self):
            return self._obj

    class _S:
        def __init__(self, row):
            self._row = row

        async def execute(self, _stmt):
            return _R(self._row)

        async def get(self, *_a):
            return None

    row = _sess(timed_out_at=_now(), expires_at=_now() + timedelta(hours=1))  # timed out, chưa hết hạn
    with pytest.raises(screening.TokenExpired) as exc:
        await screening.get_form(_S(row), "tok123")
    assert exc.value.status_code == 410
    assert "đang được" in exc.value.message  # thông điệp trấn an, không lộ nội bộ


# ── helpers: bọc giá trị thành coroutine cho monkeypatch async ────────────────────────────


async def _await(value):
    return value


async def _record(bucket: list, row) -> None:
    bucket.append(row)
