"""Test slice 03b — human_review THẬT (quyết định duyệt/từ chối → delegate scheduler + audit).

MOCK session (không chạm DB/Neon) theo pattern test_jd_embedding. Phủ: recommendation dẫn xuất;
scheduler.notify_decision (stub log, KHÔNG email); review_decision chuyển trạng thái đúng
(approve→INTERVIEW_SCHEDULED, reject→REJECTED) + ghi audit (human_review + scheduler) + delegate
scheduler đúng mode; guard trạng thái (chỉ PENDING_REVIEW mới quyết, else InvalidReviewState);
không tồn tại → ApplicationNotFound.
"""

from __future__ import annotations

import pytest

from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.job_posting import JobPosting
from app.services import review


class _EmptyResult:
    """Kết quả rỗng cho `session.execute` trong mock: SCH-2 tra "đã có link đặt lịch còn sống chưa"
    (active_session) và huỷ link khi từ chối (cancel_sessions). Mặc định: chưa có, không huỷ gì."""

    rowcount = 0

    def scalar_one_or_none(self):  # noqa: ANN201
        return None

    def scalars(self):  # noqa: ANN201
        return self

    def all(self) -> list:
        return []


class FakeSession:
    """AsyncSession tối thiểu cho review_decision: get/add/flush/commit/refresh."""

    def __init__(self, app_row: Application | None) -> None:
        self._app = app_row
        self.added: list = []
        self.commits = 0

    async def get(self, _model, pk):  # noqa: ANN001
        return self._app if (self._app is not None and self._app.id == pk) else None

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def execute(self, *_a, **_kw):  # noqa: ANN201
        return _EmptyResult()

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass


def _app(*, status: str = ApplicationStatus.PENDING_REVIEW.value, app_id: int = 1) -> Application:
    return Application(id=app_id, applicant_email="ung.vien@example.com", job_id=2, status=status)


def _audit_actions(session: FakeSession) -> list[tuple[str, str]]:
    return [(a.node, a.action) for a in session.added if isinstance(a, AuditLog)]


# ── recommendation (gợi ý hiển thị, thuần) ───────────────────────────────────


def test_recommendation_invite_when_pass_and_clean() -> None:
    assert review.recommendation(85.0, []) == "invite"


def test_recommendation_consider_reject_when_low_and_clean() -> None:
    assert review.recommendation(35.0, []) == "consider_reject"


def test_recommendation_review_carefully_when_flagged() -> None:
    # Có cờ bất định (kể cả điểm cao) → xem kỹ.
    assert review.recommendation(90.0, ["score_signal_mismatch"]) == "review_carefully"


def test_recommendation_review_carefully_when_no_score() -> None:
    assert review.recommendation(None, []) == "review_carefully"


# notify_decision (gửi email THẬT) test riêng ở test_scheduler_email.py (slice 04).


# ── review_decision (mutation cốt lõi) ───────────────────────────────────────


async def test_review_approve_sets_interview_and_audits(monkeypatch) -> None:
    captured: dict = {}

    async def fake_notify(_session, mode, **kw):  # noqa: ANN001 — khớp chữ ký notify_decision (04)
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(review.scheduler, "notify_decision", fake_notify)
    app_row = _app()
    session = FakeSession(app_row)

    out = await review.review_decision(session, 1, "approve", "hồ sơ tốt")

    # SCH-2: HR duyệt KHÔNG còn ra thẳng "đã hẹn phỏng vấn" — ứng viên phải tự chọn giờ trước
    # (PRD §10b). Đường HR và đường gate đi CHUNG một hàm dispatch nên không thể lệch nhau.
    assert out.status == ApplicationStatus.AWAITING_BOOKING.value
    assert captured["mode"] == "invite"  # delegate scheduler đúng mode
    assert "/booking/" in captured["booking_url"], "thư mời từ đường HR cũng phải kèm link"
    assert ("human_review", "approve") in _audit_actions(session)
    assert ("human_review", "booking_invite_sent") in _audit_actions(session)
    # Ba commit, theo đúng thứ tự an toàn: (1) quyết định HR, (2) phiên đặt lịch BỀN trước khi thư
    # rời máy chủ — gửi xong mới ghi mà tiến trình chết ở giữa là ứng viên cầm link 404, (3) thư đã
    # gửi → AWAITING_BOOKING.
    assert session.commits == 3


async def test_review_approve_email_fail_stays_pending_review(monkeypatch) -> None:
    """HR duyệt nhưng thư mời gửi TRƯỢT → ca Ở LẠI hàng chờ để HR bấm lại.

    Đây là điểm khác đường gate: ca này VỐN đã ở PENDING_REVIEW. Nếu đặt một trạng thái trung gian
    rồi mới gửi thư, lúc gửi hỏng ca sẽ biến mất khỏi hàng chờ mà chẳng ai gửi thư mời cả."""
    async def fake_notify(_session, mode, **kw):  # noqa: ANN001
        return {"mode": mode, "email_sent": False, "error": "resend down"}

    monkeypatch.setattr(review.scheduler, "notify_decision", fake_notify)
    app_row = _app()
    session = FakeSession(app_row)

    out = await review.review_decision(session, 1, "approve", None)

    assert out.status == ApplicationStatus.PENDING_REVIEW.value
    assert out.escalation_reason and "thư mời" in out.escalation_reason
    assert ("human_review", "booking_invite_failed") in _audit_actions(session)


async def test_review_reject_sets_rejected_and_keeps_note(monkeypatch) -> None:
    async def fake_notify(_session, mode, **kw):  # noqa: ANN001 — khớp chữ ký notify_decision (04)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(review.scheduler, "notify_decision", fake_notify)
    session = FakeSession(_app())

    out = await review.review_decision(session, 1, "reject", "lệch ngành")

    assert out.status == ApplicationStatus.REJECTED.value
    hr_rows = [a for a in session.added if isinstance(a, AuditLog) and a.node == "human_review"]
    assert hr_rows and hr_rows[0].action == "reject"
    assert hr_rows[0].detail.get("note") == "lệch ngành"


async def test_review_rejects_wrong_status(monkeypatch) -> None:
    called = {"scheduler": False}
    monkeypatch.setattr(review.scheduler, "notify_decision",
                        lambda *a, **k: called.update(scheduler=True))
    session = FakeSession(_app(status=ApplicationStatus.INTERVIEW_SCHEDULED.value))

    with pytest.raises(review.InvalidReviewState):
        await review.review_decision(session, 1, "approve", None)

    assert called["scheduler"] is False  # KHÔNG delegate khi trạng thái sai
    assert session.commits == 0


async def test_review_missing_application() -> None:
    with pytest.raises(review.ApplicationNotFound):
        await review.review_decision(FakeSession(None), 99, "approve", None)


async def test_review_passes_candidate_and_job_to_scheduler(monkeypatch) -> None:
    # Wiring 04: review_decision phải trích ĐÚNG tên (parsed_data.full_name) + vị trí (JD.title)
    # + email và truyền vào notify_decision (điểm phát email). Chống swap-arg / sai key.
    captured: dict = {}

    async def fake_notify(_session, mode, **kw):  # noqa: ANN001
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(review.scheduler, "notify_decision", fake_notify)

    app_row = _app(app_id=1)
    app_row.job_id = 7
    app_row.parsed_data = {"full_name": "Nguyễn Văn A"}
    job = JobPosting(id=7, title="Backend Intern (Node.js)")

    class SessionWithJob(FakeSession):
        async def get(self, model, pk):  # noqa: ANN001
            if model is JobPosting and pk == 7:
                return job
            return await super().get(model, pk)

    await review.review_decision(SessionWithJob(app_row), 1, "approve", None)

    assert captured["applicant_email"] == "ung.vien@example.com"
    assert captured["candidate_name"] == "Nguyễn Văn A"
    assert captured["job_title"] == "Backend Intern (Node.js)"


async def test_review_falls_back_when_no_parsed_name_or_job(monkeypatch) -> None:
    # Không có full_name / không gắn JD → fallback an toàn (không vỡ, không None).
    captured: dict = {}

    async def fake_notify(_session, mode, **kw):  # noqa: ANN001
        captured.update(**kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(review.scheduler, "notify_decision", fake_notify)
    app_row = _app(app_id=1)  # parsed_data=None, job_id=2 (FakeSession.get trả None cho JobPosting)

    await review.review_decision(FakeSession(app_row), 1, "reject", None)

    assert captured["candidate_name"] == "Ứng viên"
    assert captured["job_title"] == "vị trí ứng tuyển"
