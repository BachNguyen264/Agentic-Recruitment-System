"""Test EMAIL-1 — bảng lưu vết giao hàng + thứ bậc trạng thái.

Không cần DB: đây là bất biến của MÔ HÌNH (từ vựng `kind` + luật chuyển trạng thái). Phần chạm
DB thật nằm ở `test_webhook_resend.py` (gated).
"""

from __future__ import annotations

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
