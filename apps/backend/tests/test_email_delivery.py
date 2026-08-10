"""Test EMAIL-1 — bảng lưu vết giao hàng + thứ bậc trạng thái.

Không cần DB: đây là bất biến của MÔ HÌNH (từ vựng `kind` + luật chuyển trạng thái). Phần chạm
DB thật nằm ở `test_webhook_resend.py` (gated).
"""

from __future__ import annotations

import pytest

from app.agents.nodes import scheduler
from app.models.audit_log import AuditLog
from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind, outranks


def test_kind_values_match_scheduler_modes() -> None:
    """`kind` PHẢI là đúng chuỗi `mode` mà scheduler dùng — audit ghi `email_sent:{mode}`, nên đặt
    tên thứ hai là tạo hai từ vựng cho một thứ và không đối soát audit ↔ delivery được nữa."""
    assert {k.value for k in EmailKind} == {
        "invite", "reject", "screener", "screener_reminder",
        "booking_confirmed", "interview_reminder", "booking_reminder", "booking_cancelled",
        "submission_ack",
    }


def test_delivered_outranks_sent() -> None:
    assert outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.SENT.value)


def test_bounce_can_arrive_after_delivered() -> None:
    """Máy chủ nhận báo lại bounce SAU khi đã nhận thư — chuyện thật, phải áp được."""
    assert outranks(DeliveryStatus.BOUNCED.value, DeliveryStatus.DELIVERED.value)


def test_late_delivered_never_erases_bounce() -> None:
    assert not outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.BOUNCED.value)


def test_duplicate_event_is_noop() -> None:
    """Resend gửi lại sự kiện trùng là bình thường — cùng hạng thì KHÔNG áp lại (idempotent)."""
    for s in DeliveryStatus:
        assert not outranks(s.value, s.value)


def test_unknown_status_never_applied() -> None:
    """Mã lạ (Resend thêm sự kiện mới) KHÔNG được lọt vào cột status."""
    assert not outranks("OPENED", DeliveryStatus.SENT.value)


def test_model_column_default_is_sent() -> None:
    """Cột `status` phải mặc định SENT ở TẦNG MODEL (không phải chỉ ở `_dispatch`): mọi đường ghi
    một hàng giao hàng đều bắt đầu từ 'đã gửi', và webhook chỉ nâng cấp lên từ đó."""
    assert EmailDelivery.__table__.c.status.default.arg == DeliveryStatus.SENT.value
    assert EmailDelivery.__table__.c.resend_email_id.unique is True
    assert EmailDelivery.__table__.c.bounce_reason.nullable is True


# ── Task 2: _dispatch ghi hàng email_delivery cho mỗi thư gửi THÀNH CÔNG ─────


class FakeSession:
    """AsyncSession tối thiểu — cùng khuôn với tests/test_scheduler_email.py."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


def _deliveries(session: FakeSession) -> list[EmailDelivery]:
    return [o for o in session.added if isinstance(o, EmailDelivery)]


async def _async_value(value):  # noqa: ANN001, ANN202
    return value


async def test_dispatch_records_delivery_row(monkeypatch) -> None:
    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return "email_abc123"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "invite", application_id=42, applicant_email="a@e.com",
        candidate_name="A", job_title="Backend",
        booking_url="http://localhost:3000/booking/tok", deadline_text="72 giờ",
    )

    assert out["email_sent"] is True
    rows = _deliveries(session)
    assert len(rows) == 1
    assert rows[0].resend_email_id == "email_abc123"
    assert rows[0].kind == EmailKind.INVITE.value
    assert rows[0].application_id == 42
    assert rows[0].recipient == "a@e.com"
    assert rows[0].status == DeliveryStatus.SENT.value


async def test_dispatch_skips_delivery_row_when_no_email_id(monkeypatch) -> None:
    """Không có id thì webhook không bao giờ tra được — hàng đó vô dụng, đừng ghi rác."""

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return None

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()
    await scheduler.notify_decision(
        session, "reject", application_id=43, applicant_email="b@e.com",
        candidate_name="B", job_title="Kế toán",
    )
    assert _deliveries(session) == []
    assert any(isinstance(o, AuditLog) for o in session.added)  # audit VẪN ghi


async def test_dispatch_records_no_row_when_send_fails(monkeypatch) -> None:
    async def boom(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        raise scheduler.email_service.EmailError("Resend down")

    monkeypatch.setattr(scheduler.email_service, "send_email", boom)
    session = FakeSession()
    out = await scheduler.notify_decision(
        session, "reject", application_id=44, applicant_email="c@e.com",
        candidate_name="C", job_title="X",
    )
    assert out["email_sent"] is False
    assert _deliveries(session) == []


async def test_dispatch_uses_mode_verbatim_as_kind(monkeypatch) -> None:
    """Bất biến từ vựng, kiểm qua ĐƯỜNG THẬT: `kind` của hàng ghi ra phải khớp hậu tố của dòng audit
    `email_sent:{mode}`. Hai giá trị đó lệch nhau là lúc audit và vết giao hàng thôi đối soát được."""
    monkeypatch.setattr(
        scheduler.email_service, "send_email",
        lambda **_kw: _async_value("e_mode"),  # xem helper bên dưới
    )
    session = FakeSession()
    await scheduler.notify_screener(
        session, application_id=7, applicant_email="a@e.com", candidate_name="A",
        job_title="B", form_url="http://x.test/screening/t", deadline_text="72 giờ",
        reminder=True,
    )
    kind = _deliveries(session)[0].kind
    actions = [a.action for a in session.added if isinstance(a, AuditLog)]
    assert f"email_sent:{kind}" in actions
    assert kind == EmailKind.SCREENER_REMINDER.value
