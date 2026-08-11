"""email_delivery — biến sự kiện giao hàng của Resend thành hành động nghiệp vụ (EMAIL-1).

Nguyên tắc trên hết, kế thừa thẳng bài học SCH-3 **"hỏi sự thật, đừng hỏi cờ"**: webhook tới SAU
vài phút, và trong khoảng đó HR có thể đã xử lý, ứng viên có thể đã đặt lịch. Vì vậy mọi lượt hạ
trạng thái đều CÓ ĐIỀU KIỆN — chỉ hạ khi hồ sơ **vẫn đang đứng đúng ở trạng thái mà lá thư đó thiết
lập**, và điều kiện phải hỏi **BẢNG** (`interview_booking`, `screening_session`) chứ không chỉ hỏi
cột trạng thái. Đã đi tiếp thì **chỉ gắn cờ**.

**KHÔNG auto-reject ở bất kỳ nhánh nào.** Thư không tới được ≠ ứng viên bị loại.

Vì sao bounce thư **`reject`** chỉ gắn cờ chứ không hạ về `PENDING_REVIEW`: hàng chờ HR chỉ có hai
nút — "Duyệt → mời phỏng vấn" (mời một người vừa bị từ chối) và "Từ chối → gửi thư từ chối" (bounce
vòng hai vào đúng địa chỉ chết). Hạ trạng thái ở đó là lật ngược một quyết định đã ghi mà không mở
ra hành động đúng nào. HR thấy nhãn ⚠ trên hồ sơ và liên hệ tay.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingStatus, InterviewBooking
from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind, outranks
from app.models.screening_session import ScreeningSession
from app.services import audit_service
from app.services.booking_flow import with_flag

logger = get_logger("app.services.email_delivery")

__all__ = ["EMAIL_BOUNCED_FLAG", "handle_event"]

EMAIL_BOUNCED_FLAG = "email_bounced"

# Lý do escalation là chuỗi CỐ ĐỊNH (không nhét chi tiết bounce vào): chi tiết sống ở
# `email_delivery.bounce_reason` và hiện riêng cho HR. Cố định thì lúc `delivered` về sau, ta so
# khớp được ĐÚNG câu này để gỡ — không xoá nhầm lý do escalation của một chuyện khác.
_REASON_INVITE = "Thư MỜI phỏng vấn không tới được ứng viên — cần liên hệ thủ công."
_REASON_SCREENER = "Thư SÀNG LỌC không tới được ứng viên — cần liên hệ thủ công."
_BOUNCE_REASONS = frozenset({_REASON_INVITE, _REASON_SCREENER})

# kind -> (trạng thái mà thư đó thiết lập, lý do escalation).
# `reject` VẮNG MẶT có chủ ý (xem docstring). `submission_ack` vắng mặt vì chưa có đường phát nào.
# Bốn loại thư đặt lịch còn lại là BIÊN NHẬN — ứng viên đã thấy màn xác nhận trên web hoặc tự bấm,
# nên thư không tới không đổi được sự thật nào; chỉ gắn cờ.
_SINGLE_CHANNEL: dict[str, tuple[str, str]] = {
    EmailKind.INVITE.value: (ApplicationStatus.AWAITING_BOOKING.value, _REASON_INVITE),
    EmailKind.SCREENER.value: (ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER),
    EmailKind.SCREENER_REMINDER.value: (
        ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER
    ),
}

_EVENT_STATUS: dict[str, str] = {
    "email.sent": DeliveryStatus.SENT.value,
    "email.delivered": DeliveryStatus.DELIVERED.value,
    "email.bounced": DeliveryStatus.BOUNCED.value,
    "email.complained": DeliveryStatus.COMPLAINED.value,
}

_NEGATIVE = frozenset({DeliveryStatus.BOUNCED.value, DeliveryStatus.COMPLAINED.value})

# Lý do bounce là văn bản do BÊN NGOÀI gửi tới — cắt ngắn trước khi vào DB/UI.
_MAX_REASON = 500


def status_for_event(event_type: str) -> str | None:
    """`email.bounced` → `BOUNCED`. Sự kiện không quan tâm (`opened`/`clicked`/…) → None."""
    return _EVENT_STATUS.get(event_type or "")


def email_id_of(event: dict) -> str | None:
    """Khoá đối chiếu. Payload Resend đã đổi hình dạng giữa các bản tài liệu (`email_id` vs `id`) —
    đọc cả hai thay vì đoán một rồi im lặng bỏ lỡ mọi sự kiện."""
    data = event.get("data") or {}
    value = data.get("email_id") or data.get("id")
    return str(value) if value else None


def bounce_reason_of(data: dict) -> str | None:
    """Gộp `type/subType/message` của Resend thành một câu cho HR đọc. Không có → None."""
    bounce = (data or {}).get("bounce") or {}
    parts = [str(bounce.get(k)) for k in ("type", "subType", "message") if bounce.get(k)]
    if not parts:
        return None
    return " · ".join(parts)[:_MAX_REASON]


async def handle_event(session: AsyncSession, event: dict) -> None:
    """Điểm vào DUY NHẤT từ webhook. KHÔNG BAO GIỜ ném: route đã trả 204 là hứa với Resend rằng sự
    kiện được nhận, và ném ở đây chỉ khiến Resend thử lại một thứ sẽ hỏng y hệt."""
    try:
        await _process(session, event)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("Webhook Resend: xử lý sự kiện lỗi — bỏ qua, KHÔNG bắt Resend thử lại.")
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("Webhook Resend: rollback cũng lỗi.")


async def _process(session: AsyncSession, event: dict) -> None:
    """Thân thật. Tên KHÁC `webhooks._handle` (bí danh của route) có chủ ý — hai tên giống nhau ở
    hai module là thứ làm người đọc tưởng mình đang nhìn cùng một hàm."""
    new_status = status_for_event(str(event.get("type") or ""))
    if new_status is None:
        return
    email_id = email_id_of(event)
    if not email_id:
        logger.warning("Webhook Resend: sự kiện %r không có email id — bỏ qua.", event.get("type"))
        return

    # Khoá HÀNG: Resend có thể bắn `delivered` và `bounced` gần như cùng lúc, và cả hai đều đọc-rồi-ghi.
    row = (
        await session.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == email_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        # Thư gửi TRƯỚC khi có bảng này, hoặc webhook trỏ nhầm môi trường. Không phải lỗi.
        logger.info("Webhook Resend: không có vết giao hàng cho id=%s — bỏ qua.", email_id)
        await session.commit()  # đóng transaction đọc, đừng ôm connection
        return

    if not outranks(new_status, row.status):
        # Sự kiện trùng / tới muộn. Đây LÀ tính idempotent, không phải trường hợp lạ.
        await session.commit()
        return

    # Nguyên thuỷ, lấy TRƯỚC mọi thao tác có thể hỏng (bẫy expire — gotcha SCH-2 #3).
    kind, application_id, recipient = row.kind, row.application_id, row.recipient
    row.status = new_status
    # Chỉ ghi/đọc lý do ở sự kiện XẤU. Đọc `row.bounce_reason` cho một sự kiện `delivered` sẽ lôi ra
    # lý do của lần bounce TRƯỚC và nhét nó vào dòng audit "đã giao hàng" — đọc log lên tưởng lá thư
    # vừa tới cũng có vấn đề.
    reason_text: str | None = None
    if new_status in _NEGATIVE:
        reason_text = bounce_reason_of(event.get("data") or {})
        row.bounce_reason = reason_text

    app_row = (
        await session.get(Application, application_id) if application_id is not None else None
    )
    final_status = app_row.status if app_row is not None else None

    if app_row is not None:
        if new_status in _NEGATIVE:
            final_status = await _apply_bounce(session, app_row, kind=kind)
        elif new_status == DeliveryStatus.DELIVERED.value:
            _clear_bounce(app_row, recipient=recipient)

    await audit_service.record(
        session,
        application_id=application_id,
        node="scheduler",
        action=f"email_{new_status.lower()}",
        escalation_reason=EMAIL_BOUNCED_FLAG if new_status in _NEGATIVE else None,
        detail={
            "kind": kind, "email_id": email_id, "reason": reason_text,
            "final_status": final_status,
        },
        commit=True,
    )
    # `record(commit=True)` kết thúc bằng `refresh()` — nó autobegin một transaction MỚI và giữ lại
    # connection (gotcha refresh(), AI_GUIDE). Đóng nó ngay. `commit()` chứ không `rollback()`:
    # rollback expire mọi object bất kể `expire_on_commit=False`.
    await session.commit()
    logger.info(
        "Webhook Resend: id=%s kind=%s → %s (app=%s, status=%s)",
        email_id, kind, new_status, application_id, final_status,
    )


async def _apply_bounce(session: AsyncSession, app_row: Application, *, kind: str) -> str:
    """Gắn cờ + (có điều kiện) hạ về PENDING_REVIEW. Trả trạng thái CUỐI của hồ sơ."""
    app_row.uncertainty_flags = with_flag(app_row.uncertainty_flags, EMAIL_BOUNCED_FLAG)

    mapping = _SINGLE_CHANNEL.get(kind)
    if mapping is None:
        return app_row.status  # thư biên nhận / thư từ chối → chỉ cờ

    expected_status, reason = mapping
    if app_row.status != expected_status:
        # Hồ sơ đã đi tiếp trong lúc webhook đang trên đường. KHÔNG kéo ngược.
        return app_row.status
    if await _already_moved_on(session, app_row.id, kind=kind):
        # Cờ trạng thái nói một đằng, BẢNG nói một nẻo. Tin bảng (bài học SCH-3).
        logger.warning(
            "Webhook Resend: app=%s trạng thái %s nhưng bảng cho thấy đã đi tiếp — chỉ gắn cờ.",
            app_row.id, app_row.status,
        )
        return app_row.status

    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = reason
    return app_row.status


async def _already_moved_on(session: AsyncSession, application_id: int, *, kind: str) -> bool:
    """Hỏi BẢNG, không hỏi cờ. Hai câu hỏi khác nhau cho hai họ thư khác nhau."""
    if kind == EmailKind.INVITE.value:
        count = await session.scalar(
            select(func.count())
            .select_from(InterviewBooking)
            .where(
                InterviewBooking.application_id == application_id,
                InterviewBooking.status == BookingStatus.BOOKED.value,
            )
        )
        return bool(count)
    count = await session.scalar(
        select(func.count())
        .select_from(ScreeningSession)
        .where(
            ScreeningSession.application_id == application_id,
            ScreeningSession.answers.isnot(None),
        )
    )
    return bool(count)


def _clear_bounce(app_row: Application, *, recipient: str) -> None:
    """GỠ cờ khi một lá thư sau ĐÃ tới cùng địa chỉ đó (bài học SCH-3: gắn cờ thì phải có đường gỡ).

    Không gỡ thì hồ sơ mang nhãn báo động vĩnh viễn kể cả sau khi địa chỉ đã hoạt động trở lại — và
    cảnh báo không bao giờ tắt là cảnh báo sẽ bị phớt lờ.
    """
    if recipient != app_row.applicant_email:
        return
    flags = list(app_row.uncertainty_flags or [])
    if EMAIL_BOUNCED_FLAG not in flags:
        return
    app_row.uncertainty_flags = [f for f in flags if f != EMAIL_BOUNCED_FLAG]
    # Chỉ xoá lý do NẾU nó đúng là câu ta đặt — đừng xoá lý do escalation của một chuyện khác.
    if app_row.escalation_reason in _BOUNCE_REASONS:
        app_row.escalation_reason = None
