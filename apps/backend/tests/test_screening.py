"""Test slice 08b — Screener magic-link (token/expiry/one-time/resume + projection an toàn).

PRD §7.3, §10, §12.2. Đơn vị hóa bằng FAKE session (không chạm DB thật; row-lock + concurrency
kiểm ở Verify live). Bảo mật là trọng tâm: token entropy, hết hạn, one-time, đúng trạng thái,
KHÔNG lộ nội bộ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import Application, ApplicationStatus
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.services import screening


def _future() -> datetime:
    return datetime.now(timezone.utc) + timedelta(hours=1)


def _past() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=1)


class _Result:
    def __init__(self, obj) -> None:
        self._obj = obj

    def scalar_one_or_none(self):
        return self._obj


class _FakeSession:
    """AsyncSession tối thiểu: execute → trả session token cố định; get → tra (Model, pk)."""

    def __init__(self, screening_row=None, rows=None) -> None:
        self._screening = screening_row
        self._rows = rows or {}
        self.commits = 0
        self.rollbacks = 0
        self.added: list = []

    async def execute(self, _stmt):  # noqa: ANN001 — token lookup (kể cả with_for_update)
        return _Result(self._screening)

    async def get(self, model, pk):  # noqa: ANN001
        return self._rows.get((model, pk))

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _obj) -> None:
        pass


def _sess_row(**kw) -> ScreeningSession:
    defaults = dict(
        id=1, application_id=1, token="tok", questions=["Lương kỳ vọng?", "Khi nào nhận việc?"],
        answers=None, expires_at=_future(), used_at=None,
    )
    defaults.update(kw)
    return ScreeningSession(**defaults)


def _awaiting_app(**kw) -> Application:
    defaults = dict(id=1, applicant_email="a@e.com", job_id=2, status=ApplicationStatus.AWAITING_SCREENER.value)
    defaults.update(kw)
    return Application(**defaults)


# ── create_session: token an toàn + ảnh chụp câu hỏi ─────────────────────────


def test_create_session_secure_token_and_snapshot() -> None:
    session = _FakeSession()
    row = screening.create_session(session, 7, ["Q1", "Q2"])
    assert row.application_id == 7
    assert row.questions == ["Q1", "Q2"]  # ảnh chụp
    assert row.used_at is None
    assert row.expires_at > datetime.now(timezone.utc)  # có hạn tương lai
    # token entropy: url-safe, đủ dài, không tuần tự/đoán được
    assert len(row.token) >= 40
    row2 = screening.create_session(session, 7, ["Q1"])
    assert row.token != row2.token  # ngẫu nhiên, không trùng
    assert session.added == [row, row2]  # add vào session, CHƯA commit (caller commit)
    assert session.commits == 0


def test_mark_screener_sent_stamps_application_for_hr_display() -> None:
    # Trước fix: screener_sent_at/screener_deadline là cột scaffold KHÔNG ai ghi → luôn null (HR thấy
    # "—" dù email đã gửi). mark_screener_sent điền chúng CÙNG commit với create_session.
    from datetime import datetime, timezone

    from app.models.application import Application
    from app.models.screening_session import ScreeningSession

    app_row = Application(applicant_email="a@e.com", job_id=1)
    deadline = datetime(2030, 1, 1, tzinfo=timezone.utc)
    sess = ScreeningSession(application_id=1, token="t", questions=[], expires_at=deadline)

    assert app_row.screener_sent_at is None and app_row.screener_deadline is None  # bug cũ
    screening.mark_screener_sent(app_row, sess)
    assert app_row.screener_sent_at is not None  # đã ghi
    assert app_row.screener_deadline == deadline  # khớp hạn của session (nguồn chân lý timeout)


# ── get_form: validate token → chỉ câu hỏi + tiêu đề JD ──────────────────────


async def test_get_form_valid_returns_title_and_questions() -> None:
    row = _sess_row()
    session = _FakeSession(
        screening_row=row,
        rows={(Application, 1): _awaiting_app(), (JobPosting, 2): JobPosting(id=2, title="Backend Intern")},
    )
    title, questions = await screening.get_form(session, "tok")
    assert title == "Backend Intern"
    assert questions == ["Lương kỳ vọng?", "Khi nào nhận việc?"]


async def test_get_form_token_not_found_404() -> None:
    session = _FakeSession(screening_row=None)
    with pytest.raises(screening.TokenNotFound) as exc:
        await screening.get_form(session, "bogus")
    assert exc.value.status_code == 404


async def test_get_form_expired_410() -> None:
    row = _sess_row(expires_at=_past())
    session = _FakeSession(screening_row=row, rows={(Application, 1): _awaiting_app()})
    with pytest.raises(screening.TokenExpired) as exc:
        await screening.get_form(session, "tok")
    assert exc.value.status_code == 410


async def test_get_form_used_409() -> None:
    row = _sess_row(used_at=datetime.now(timezone.utc))
    session = _FakeSession(screening_row=row, rows={(Application, 1): _awaiting_app()})
    with pytest.raises(screening.TokenUsed) as exc:
        await screening.get_form(session, "tok")
    assert exc.value.status_code == 409


async def test_get_form_wrong_status_409() -> None:
    # Application đã xử lý (PENDING_REVIEW) → không cho trả lời nữa (tránh resume ca đã quyết).
    row = _sess_row()
    session = _FakeSession(
        screening_row=row, rows={(Application, 1): _awaiting_app(status="PENDING_REVIEW")}
    )
    with pytest.raises(screening.NotAwaitingScreener) as exc:
        await screening.get_form(session, "tok")
    assert exc.value.status_code == 409


# ── submit_answers: resume + one-time (mark used) ────────────────────────────


async def test_submit_answers_resumes_and_marks_used(monkeypatch) -> None:
    row = _sess_row()
    session = _FakeSession(screening_row=row, rows={(Application, 1): _awaiting_app()})

    captured = {}

    async def fake_resume(_sess, app_id, payload, *, pre_commit=None):  # noqa: ANN001
        captured["app_id"] = app_id
        captured["payload"] = payload
        if pre_commit is not None:
            pre_commit()  # mô phỏng: chạy hook TRƯỚC commit (đánh dấu used)
        return {"application_id": app_id, "status": "PENDING_REVIEW", "branch": "human_review"}

    monkeypatch.setattr(screening.background, "resume_screener", fake_resume)

    res = await screening.submit_answers(session, "tok", ["150 triệu", "Ngay lập tức"])

    assert res["status"] == "submitted"
    assert captured["app_id"] == 1
    # resume_payload mang câu trả lời ghép câu hỏi (đúng thứ tự)
    assert captured["payload"]["answers"] == [
        {"question": "Lương kỳ vọng?", "answer": "150 triệu"},
        {"question": "Khi nào nhận việc?", "answer": "Ngay lập tức"},
    ]
    # one-time: used_at set + answers lưu (qua pre_commit)
    assert row.used_at is not None
    assert row.answers == captured["payload"]["answers"]


async def test_submit_answers_token_used_rejected(monkeypatch) -> None:
    row = _sess_row(used_at=datetime.now(timezone.utc))
    session = _FakeSession(screening_row=row, rows={(Application, 1): _awaiting_app()})

    async def fake_resume(*_a, **_kw):  # KHÔNG được gọi
        raise AssertionError("resume KHÔNG được chạy cho token đã dùng")

    monkeypatch.setattr(screening.background, "resume_screener", fake_resume)
    with pytest.raises(screening.TokenUsed):
        await screening.submit_answers(session, "tok", ["x"])


async def test_submit_answers_caps_long_answer() -> None:
    row = _sess_row(questions=["Q1"])
    session = _FakeSession(screening_row=row, rows={(Application, 1): _awaiting_app()})
    import app.services.screening as scr

    async def fake_resume(_sess, app_id, payload, *, pre_commit=None):  # noqa: ANN001
        if pre_commit:
            pre_commit()
        return {"branch": "human_review", "status": "PENDING_REVIEW"}

    original = scr.background.resume_screener
    scr.background.resume_screener = fake_resume
    try:
        await screening.submit_answers(session, "tok", ["a" * 10000])
    finally:
        scr.background.resume_screener = original
    assert len(row.answers[0]["answer"]) == scr._MAX_ANSWER_LEN  # cắt về giới hạn


# ── projection AN TOÀN: KHÔNG lộ nội bộ ──────────────────────────────────────


def test_public_screening_read_only_safe_fields() -> None:
    from app.schemas.screening import PublicScreeningRead

    dumped = PublicScreeningRead(job_title="X", questions=["Q1"]).model_dump()
    assert set(dumped.keys()) == {"job_title", "questions"}  # KHÔNG rubric/gate/score/parsed_data
