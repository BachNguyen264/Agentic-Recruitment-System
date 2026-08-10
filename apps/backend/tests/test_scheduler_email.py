"""Test slice 04 — scheduler.notify_decision gửi email THẬT (mock Resend).

Phủ: invite → gửi email mời (đúng recipient + template mời) + audit email_sent:invite;
reject → template từ chối + audit email_sent:reject; lỗi gửi → KHÔNG raise (nuốt có kiểm soát)
+ audit email_failed, quyết định vẫn giữ. KHÔNG gửi thật (monkeypatch email_service.send_email).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.nodes import scheduler
from app.models.audit_log import AuditLog
from app.models.booking import BookingStatus, InterviewBooking
from app.services import email_service


def _booked_slot() -> InterviewBooking:
    """Khung giờ đã chốt, rời khỏi DB — chỉ cần start_at/end_at cho template + `.ics`."""
    start = datetime(2026, 8, 10, 1, 0, tzinfo=timezone.utc)  # 08:00 giờ VN
    return InterviewBooking(
        id=7, application_id=9, start_at=start, end_at=start + timedelta(hours=1),
        status=BookingStatus.BOOKED.value,
    )


class FakeSession:
    """AsyncSession tối thiểu cho audit_service.record(commit=True): add/commit/refresh/flush."""

    def __init__(self) -> None:
        self.added: list = []
        self.commits = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass


def _audit_actions(session: FakeSession) -> list[str]:
    return [a.action for a in session.added if isinstance(a, AuditLog) and a.node == "scheduler"]


async def test_notify_invite_sends_invite_email(monkeypatch) -> None:
    captured: dict = {}

    async def fake_send(*, to: str, subject: str, html: str, attachments=None) -> None:
        captured.update(to=to, subject=subject, html=html)

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "invite", application_id=1, applicant_email="a@e.com",
        candidate_name="Nguyễn Văn A", job_title="Backend Intern",
        booking_url="http://localhost:3000/booking/tok", deadline_text="72 giờ",
    )

    assert out["email_sent"] is True
    assert captured["to"] == "a@e.com"
    assert "Nguyễn Văn A" in captured["html"] and "Backend Intern" in captured["html"]
    assert "mời" in captured["subject"].lower()
    assert "email_sent:invite" in _audit_actions(session)


async def test_notify_reject_sends_rejection_email(monkeypatch) -> None:
    captured: dict = {}

    async def fake_send(*, to: str, subject: str, html: str, attachments=None) -> None:
        captured.update(subject=subject, html=html)

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "reject", application_id=2, applicant_email="b@e.com",
        candidate_name="Trần Văn B", job_title="Kế toán",
    )

    assert out["email_sent"] is True
    assert "Kế toán" in captured["html"]
    assert "Kết quả ứng tuyển".lower() in captured["subject"].lower()
    assert "email_sent:reject" in _audit_actions(session)


async def test_booking_confirmed_email_still_goes_out_when_ics_fails(monkeypatch) -> None:
    """Sinh `.ics` hỏng KHÔNG được nuốt luôn thư XÁC NHẬN (SCH-3 review).

    Lịch đã `BOOKED` trong DB và ứng viên vừa bấm xong: thư là BIÊN NHẬN của việc đó. Bỏ thư vì
    thiếu một tệp đính kèm là để người vừa đặt lịch không nhận được gì, đồng thời gắn cờ "cần gọi
    tay" cho HR — trong khi hai thư anh em (nhắc buổi PV, báo huỷ) đã luôn xuống cấp êm.
    """
    sent: dict = {}

    async def fake_send(*, to: str, subject: str, html: str, attachments=None) -> None:
        sent.update(to=to, attachments=attachments)

    class BrokenCalendar:
        async def create_event(self, *_a, **_kw):  # noqa: ANN001, ANN202
            raise RuntimeError("tzdata thiếu trong image")

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    monkeypatch.setattr(scheduler, "get_calendar_provider", lambda: BrokenCalendar())
    session = FakeSession()

    out = await scheduler.notify_booking_confirmed(
        session, application_id=9, applicant_email="d@e.com", candidate_name="Lê C",
        job_title="Backend Intern", booking=_booked_slot(),
    )

    assert out["email_sent"] is True  # thư ĐI, chỉ thiếu tệp đính kèm
    assert sent["to"] == "d@e.com"
    assert sent["attachments"] is None
    assert "email_sent:booking_confirmed" in _audit_actions(session)


async def test_notify_swallows_send_error(monkeypatch) -> None:
    async def boom(*, to: str, subject: str, html: str, attachments=None) -> None:
        raise email_service.EmailError("Resend down")

    monkeypatch.setattr(scheduler.email_service, "send_email", boom)
    session = FakeSession()

    # KHÔNG raise — quyết định 03b đã commit, email lỗi không được làm sập luồng.
    out = await scheduler.notify_decision(
        session, "invite", application_id=3, applicant_email="c@e.com",
        candidate_name="X", job_title="Y",
        booking_url="http://localhost:3000/booking/tok", deadline_text="72 giờ",
    )

    assert out["email_sent"] is False
    assert "email_failed" in _audit_actions(session)
