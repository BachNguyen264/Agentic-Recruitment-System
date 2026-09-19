"""Test SCH-2 — nối đặt lịch vào luồng. PRD §10b, §12.4 FR-BOOK-1/2, §13.

Phủ bốn thứ dễ hỏng nhất của lát này (mock email/DB — KHÔNG gửi thật, KHÔNG chạm Neon):
  A) **Thứ tự gửi thư mời** (bất biến 08d): email THÀNH CÔNG rồi mới `AWAITING_BOOKING`; gửi trượt →
     `PENDING_REVIEW` + phiên đặt lịch bị HUỶ (đừng để SCH-3 nhắc một lời mời chưa từng gửi).
  B) **Thứ tự xác nhận** (§3.3, CỐ Ý khác 08d): DB trước → email sau → `INTERVIEW_SCHEDULED`. Email
     hỏng KHÔNG được huỷ lịch — chỉ gắn cờ cho HR.
  C) **Projection công khai**: payload chỉ có tiêu đề JD + tên + slot. Test khẳng định sự VẮNG MẶT
     của rubric/điểm/gate/parsed_data/trạng thái (kỷ luật 08b).
  D) Thư mời KHÔNG có link là lỗi lập trình → nổ ngay, không âm thầm bỏ ứng viên mắc kẹt.

Phần cần Postgres thật (token 404/410, không one-time, race → 409) nằm ở `test_booking_db.py`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.models.job_posting import JobPosting
from app.services import booking_flow, booking_service


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    """AsyncSession tối thiểu (mock) — đủ cho add/get/commit của tầng flow."""

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

    async def execute(self, *_a, **_kw):  # noqa: ANN201
        return _EmptyResult()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass

    def audits(self) -> list[tuple[str, str]]:
        return [(a.node, a.action) for a in self.added if isinstance(a, AuditLog)]

    def sessions(self) -> list[BookingSession]:
        return [o for o in self.added if isinstance(o, BookingSession)]


def _app(status: str = ApplicationStatus.SCHEDULING.value) -> Application:
    row = Application(id=5, applicant_email="me@e.com", job_id=2, status=status)
    row.parsed_data = {"full_name": "Nguyễn Văn A"}
    return row


def _booking(bid: int = 11) -> InterviewBooking:
    start = _now() + timedelta(days=3)
    return InterviewBooking(
        id=bid, application_id=5, start_at=start, end_at=start + timedelta(hours=1),
        status=BookingStatus.BOOKED.value,
    )


# ── A) Gửi thư mời: email TRƯỚC, trạng thái SAU (bất biến 08d) ────────────────────────────


async def test_invite_sets_awaiting_booking_only_after_email_sent(monkeypatch) -> None:
    captured: dict = {}

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001
        captured.update(mode=mode, **kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_notify)
    session, app_row = FakeSession(), _app()

    sent = await booking_flow.dispatch_booking_invite(
        session, app_row, applicant_email="me@e.com",
        job_title="Backend", audit_node="gate",
    )

    assert sent is True
    assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value
    assert app_row.escalation_reason is None
    assert captured["mode"] == "invite"
    # Link phải chứa CHÍNH token của phiên vừa tạo — lệch nhau là ứng viên mở link gặp 404.
    rows = session.sessions()
    assert len(rows) == 1
    assert rows[0].token in captured["booking_url"] and "/booking/" in captured["booking_url"]
    assert rows[0].cancelled_at is None
    assert ("gate", "booking_invite_sent") in session.audits()


async def test_invite_email_failure_keeps_case_with_hr_and_kills_session(monkeypatch) -> None:
    """Gửi trượt → PENDING_REVIEW (KHÔNG auto-reject) + phiên bị huỷ.

    Huỷ phiên là phần dễ quên: để nó sống thì SCH-3 sẽ đi nhắc rồi hạ hồ sơ vì "không phản hồi" một
    lời mời chưa bao giờ rời khỏi máy chủ."""

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001
        return {"mode": mode, "email_sent": False, "error": "resend down"}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_notify)
    session, app_row = FakeSession(), _app()

    sent = await booking_flow.dispatch_booking_invite(
        session, app_row, applicant_email="me@e.com",
        job_title="Backend", audit_node="gate",
    )

    assert sent is False
    assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
    assert app_row.escalation_reason and "thư mời" in app_row.escalation_reason
    assert session.sessions()[0].cancelled_at is not None
    assert ("gate", "booking_invite_failed") in session.audits()


async def test_invite_link_uses_configured_frontend_base(monkeypatch) -> None:
    captured: dict = {}

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001
        captured.update(**kw)
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_notify)
    monkeypatch.setattr(booking_flow.settings, "frontend_base_url", "https://ars.example.com/")

    await booking_flow.dispatch_booking_invite(
        FakeSession(), _app(), applicant_email="a@e.com",
        job_title="B", audit_node="gate",
    )
    # Bỏ "/" thừa — "https://x.com//booking/tok" vẫn chạy nhưng trông như lỗi trong email gửi ứng viên.
    assert captured["booking_url"].startswith("https://ars.example.com/booking/")


# ── D) Thư mời KHÔNG link = lỗi lập trình, phải nổ ────────────────────────────────────────


async def test_notify_decision_invite_requires_booking_url() -> None:
    """Không có link thì ứng viên nhận lời mời rồi... không làm gì được. Nổ ngay còn hơn hỏng câm."""
    from app.agents.nodes import scheduler

    with pytest.raises(ValueError, match="booking_url"):
        await scheduler.notify_decision(
            FakeSession(), "invite", application_id=1, applicant_email="a@e.com",
            job_title="B",
        )


# ── B) Xác nhận: DB trước → email sau → INTERVIEW_SCHEDULED (§3.3) ────────────────────────


def _patch_confirm(monkeypatch, session_row: BookingSession, booking: InterviewBooking) -> list[str]:
    """Ghim load_valid_session/confirm_booking (đã có test riêng trên DB thật) + ghi lại THỨ TỰ."""
    order: list[str] = []

    async def fake_load(_s, _token, **_kw):
        return session_row

    async def fake_confirm(_s, _app_id, _booking_id, **_kw):
        order.append("db")
        return booking

    monkeypatch.setattr(booking_service, "load_valid_session", fake_load)
    monkeypatch.setattr(booking_service, "confirm_booking", fake_confirm)
    return order


async def test_confirm_writes_db_then_email_then_status(monkeypatch) -> None:
    session_row = BookingSession(id=1, application_id=5, token="tok", expires_at=_now() + timedelta(hours=1))
    booking = _booking()
    order = _patch_confirm(monkeypatch, session_row, booking)
    app_row = _app(ApplicationStatus.AWAITING_BOOKING.value)
    session = FakeSession({(Application, 5): app_row, (JobPosting, 2): JobPosting(id=2, title="Backend")})

    async def fake_confirmed(_s, **kw):  # noqa: ANN001
        order.append("email")
        assert kw["booking"] is booking  # .ics phải sinh từ ĐÚNG khung giờ vừa chốt
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", fake_confirmed)

    out = await booking_flow.confirm_and_notify(session, "tok", 11)

    assert order == ["db", "email"], "DB phải chốt TRƯỚC email (§3.3 — thứ thắng race phải bền trước)"
    assert app_row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value
    assert app_row.escalation_reason is None
    assert session_row.booked_at is not None
    assert out["email_sent"] is True and out["start_at"] == booking.start_at
    assert ("scheduler", "booking_confirmed") in session.audits()


async def test_confirm_keeps_booking_when_email_fails(monkeypatch) -> None:
    """CỐ Ý khác 08d: ứng viên tự bấm và ĐANG NHÌN màn xác nhận nên họ đã biết — thư chỉ là biên
    nhận. Huỷ lịch vì gửi thư hỏng sẽ lấy mất khung giờ họ vừa chọn, tệ hơn nhiều."""
    session_row = BookingSession(id=1, application_id=5, token="tok", expires_at=_now() + timedelta(hours=1))
    booking = _booking()
    _patch_confirm(monkeypatch, session_row, booking)
    app_row = _app(ApplicationStatus.AWAITING_BOOKING.value)
    session = FakeSession({(Application, 5): app_row, (JobPosting, 2): JobPosting(id=2, title="Backend")})

    async def boom(_s, **_kw):
        raise RuntimeError("Resend sập")

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", boom)

    out = await booking_flow.confirm_and_notify(session, "tok", 11)

    assert app_row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value  # lịch VẪN được giữ
    assert out["email_sent"] is False
    # Cờ để HR gọi lại thủ công — nếu không, ứng viên có lịch mà không ai báo cho họ biết.
    assert app_row.escalation_reason and "THẤT BẠI" in app_row.escalation_reason
    assert ("scheduler", "booking_confirmed") in session.audits()


async def test_confirm_race_loss_propagates_as_slot_taken(monkeypatch) -> None:
    """Thua race → lỗi ném RA NGOÀI để route dịch 409. Trạng thái KHÔNG được đổi."""
    session_row = BookingSession(id=1, application_id=5, token="tok", expires_at=_now() + timedelta(hours=1))
    app_row = _app(ApplicationStatus.AWAITING_BOOKING.value)
    session = FakeSession({(Application, 5): app_row, (JobPosting, 2): JobPosting(id=2, title="Backend")})

    async def fake_load(_s, _token, **_kw):
        return session_row

    async def fake_confirm(_s, _a, _b, **_kw):
        raise booking_service.SlotTaken("Giờ này vừa có người đặt mất.")

    monkeypatch.setattr(booking_service, "load_valid_session", fake_load)
    monkeypatch.setattr(booking_service, "confirm_booking", fake_confirm)

    with pytest.raises(booking_service.SlotTaken):
        await booking_flow.confirm_and_notify(session, "tok", 11)

    assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value
    assert session_row.booked_at is None


# ── C) Projection công khai: chỉ những gì ứng viên cần thấy ───────────────────────────────


def test_public_booking_payload_has_no_internal_fields() -> None:
    from app.schemas.booking import PublicBookingRead, PublicSlot

    dumped = PublicBookingRead(
        job_title="Backend",
        slots=[PublicSlot(booking_id=1, start_at=_now(), end_at=_now())],
    ).model_dump()

    assert set(dumped) == {
        "job_title", "already_booked",
        "booked_start_at", "booked_end_at", "slots", "hold_expires_at",
    }
    # Khẳng định sự VẮNG MẶT — thêm field vào model KHÔNG được tự động rò ra trang công khai.
    for leaked in (
        "rubric", "score", "score_breakdown", "gate_config", "parsed_data", "confidence",
        "uncertainty_flags", "status", "escalation_reason", "cv_file_ref", "applicant_email",
        "screener_questions", "application_id",
    ):
        assert leaked not in dumped, f"projection công khai rò {leaked}"


def test_public_slot_exposes_only_time_and_id() -> None:
    from app.schemas.booking import PublicSlot

    dumped = PublicSlot(booking_id=1, start_at=_now(), end_at=_now()).model_dump()
    assert set(dumped) == {"booking_id", "start_at", "end_at"}


def test_confirm_response_tells_truth_about_email() -> None:
    """UI phải nói THẬT: hứa "đã gửi thư xác nhận" khi chưa gửi được đúng là lớp lỗi dự án né."""
    from app.schemas.booking import BookingConfirmResponse

    dumped = BookingConfirmResponse(
        job_title="Backend", start_at=_now(), end_at=_now(), email_sent=False
    ).model_dump()
    assert dumped["email_sent"] is False
    assert set(dumped) == {"job_title", "start_at", "end_at", "email_sent"}
