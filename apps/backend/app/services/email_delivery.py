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

from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingStatus, InterviewBooking
from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind, outranks
from app.models.screening_session import ScreeningSession
from app.services import audit_service, booking_service
from app.services.booking_flow import with_flag

logger = get_logger("app.services.email_delivery")

__all__ = ["EMAIL_BOUNCED_FLAG", "handle_event"]

EMAIL_BOUNCED_FLAG = "email_bounced"


def _now() -> datetime:
    return datetime.now(timezone.utc)


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

# Trạng thái ĐƯỢC PHÉP hạ ứng dụng — tập CON của `_NEGATIVE` (adversarial review I3). `COMPLAINED`
# cố ý VẮNG MẶT: complaint là ứng viên tự bấm "đây là spam" trên một lá thư ĐÃ TỚI TAY — không có gì
# "hỏng" để cứu bằng cách hạ về `PENDING_REVIEW`. Hạ nhầm đẩy hồ sơ ra khỏi `_BOOKABLE_STATUSES` của
# `booking_flow` / lưới sweep của `screening_timeout` (cả hai đều đòi đúng trạng thái đang chờ), tức
# giết một liên kết đặt lịch/sàng lọc vẫn đang sống tốt. Complaint vẫn được gắn cờ + audit (xem
# `_NEGATIVE`) — chỉ không đổi trạng thái.
_DEMOTABLE = frozenset({DeliveryStatus.BOUNCED.value})

# Lý do bounce là văn bản do BÊN NGOÀI gửi tới — cắt ngắn trước khi vào DB/UI.
_MAX_REASON = 500

# Lỗi HÌNH DẠNG payload (C1, adversarial review) — Resend gửi field sai kiểu (`data` không phải
# dict, `bounce` là chuỗi, thiếu khoá...). Đây là những gì `.get()`/tương tự trên một giá trị sai
# kiểu THỰC SỰ ném ra; liệt kê TƯỜNG MINH (không dùng `Exception` trần) để `handle_event` phân biệt
# được với lỗi hạ tầng — xem docstring `handle_event`.
_PAYLOAD_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError, TypeError, KeyError, ValueError, IndexError,
)


def status_for_event(event_type: str) -> str | None:
    """`email.bounced` → `BOUNCED`. Sự kiện không quan tâm (`opened`/`clicked`/…) → None."""
    return _EVENT_STATUS.get(event_type or "")


def email_id_of(event: dict) -> str | None:
    """Khoá đối chiếu. Payload Resend đã đổi hình dạng giữa các bản tài liệu (`email_id` vs `id`) —
    đọc cả hai thay vì đoán một rồi im lặng bỏ lỡ mọi sự kiện.

    `data` không phải dict (Resend gửi sai hình dạng, hoặc field đổi kiểu ở phiên bản sau) → coi như
    KHÔNG có id, KHÔNG ném. Kiểm kiểu TƯỜNG MINH ở đây thay vì để `.get()` tự ném rồi bắt lại ở tầng
    trên — payload rác là ĐƯỜNG BÌNH THƯỜNG của webhook công khai, không cần đi vòng qua exception.
    """
    data = event.get("data")
    if not isinstance(data, dict):
        return None
    value = data.get("email_id") or data.get("id")
    return str(value) if value else None


def bounce_reason_of(data: dict) -> str | None:
    """Gộp `type/subType/message` của Resend thành một câu cho HR đọc. Không có → None.

    `data`/`bounce` không phải dict → coi như KHÔNG có lý do, KHÔNG ném. **C1 (adversarial review):**
    trước đây thiếu kiểm kiểu này — `bounce` là một CHUỖI thay vì object khiến `.get()` ném
    `AttributeError` NGAY GIỮA `_process`, sau khi `row.status` đã gán trong bộ nhớ nhưng TRƯỚC khi
    commit; khối `except Exception` trần ở `handle_event` nuốt lỗi rồi rollback, nên CẢ sự kiện bounce
    biến mất — `EmailDelivery.status` vẫn `SENT`, hồ sơ vẫn `AWAITING_BOOKING`, route vẫn trả 204 nên
    Resend không bao giờ gửi lại. Không dựng được MỘT câu lý do không phải lý do để đánh mất CẢ sự
    kiện.
    """
    if not isinstance(data, dict):
        return None
    bounce = data.get("bounce")
    if not isinstance(bounce, dict):
        return None
    parts = [str(bounce.get(k)) for k in ("type", "subType", "message") if bounce.get(k)]
    if not parts:
        return None
    return " · ".join(parts)[:_MAX_REASON]


async def handle_event(session: AsyncSession, event: dict) -> None:
    """Điểm vào DUY NHẤT từ webhook. Nuốt lỗi HÌNH DẠNG payload (route đã trả 204 là hứa với Resend
    rằng sự kiện được nhận, và bắt Resend thử lại một payload sẽ hỏng Y HỆT là vô ích).

    **C1 (adversarial review):** KHÔNG còn nuốt `Exception` trần. Chỉ nuốt `_PAYLOAD_ERRORS` — nhóm
    lỗi PHÁT SINH TỪ hình dạng dữ liệu (đọc code: mọi lỗi ta từng thấy ở đây đều là `.get()`/`.lower()`
    trên một giá trị sai kiểu). Lỗi TẠM THỜI — mất kết nối Neon giữa chừng (autosuspend, xem
    `docs/deploy-live-issues.md`), deadlock, timeout — KHÔNG bị nuốt: chúng NỔI LÊN cho route xử lý,
    và Resend thử lại LÀ đúng hướng cho loại lỗi này (payload y hệt sẽ thành công nếu DB đã sống lại).
    Nuốt cả hai loại như cũ từng khiến MỘT sự cố hạ tầng thoáng qua biến thành mất tín hiệu bounce
    VĨNH VIỄN — mà log ERROR không phân biệt được với nhiễu payload.
    """
    try:
        await _process(session, event)
    except _PAYLOAD_ERRORS:
        logger.exception(
            "Webhook Resend: payload có hình dạng bất thường — bỏ qua, KHÔNG bắt Resend thử lại."
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001 — dọn dẹp phụ; đừng để lỗi dọn dẹp che lỗi gốc
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
        reason_text = bounce_reason_of(event.get("data"))
        row.bounce_reason = reason_text

    if application_id is not None:
        # I5 (adversarial review) — khoá tư vấn TRƯỚC khi đọc hàng application, để `_already_moved_on`
        # hỏi bảng ở TRONG cùng khoá với `dispatch_booking_invite`/`generate_slots` (cả hai đều lấy
        # CÙNG khoá này — booking_flow.py/booking_service.py). GIỚI HẠN ĐÃ BIẾT: khoá tư vấn chỉ chặn
        # được các bên CÙNG xin nó; `confirm_booking` (ứng viên tự chốt giờ) không lấy khoá này (nó
        # dựa vào SELECT…FOR UPDATE + partial unique index riêng của mình), nên cửa sổ đua với ĐÚNG
        # lượt xác nhận đó không được khoá này đóng tuyệt đối — chỉ còn hẹp lại nhờ `_already_moved_on`
        # đọc BẢNG ngay trước khi ghi. Khoá tự nhả khi transaction kết thúc (commit/rollback bên dưới).
        await booking_service.lock_application(session, application_id)
    app_row = (
        await session.get(Application, application_id) if application_id is not None else None
    )
    final_status = app_row.status if app_row is not None else None

    if app_row is not None:
        if new_status in _NEGATIVE:
            final_status = await _apply_bounce(session, app_row, kind=kind, new_status=new_status)
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


async def _apply_bounce(
    session: AsyncSession, app_row: Application, *, kind: str, new_status: str
) -> str:
    """Gắn cờ + (có điều kiện) hạ về PENDING_REVIEW. Trả trạng thái CUỐI của hồ sơ.

    `new_status` quyết ĐƯỢC hạ hay không (I3, adversarial review — xem `_DEMOTABLE`): complaint
    KHÔNG được hạ, chỉ bounce THẬT mới đáng đưa về tay HR.
    """
    app_row.uncertainty_flags = with_flag(app_row.uncertainty_flags, EMAIL_BOUNCED_FLAG)

    if new_status not in _DEMOTABLE:
        return app_row.status  # complaint: thư ĐÃ TỚI tay ứng viên — chỉ cờ, không hạ

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
    await _abandon_in_flight_session(session, app_row.id, kind=kind)
    return app_row.status


async def _abandon_in_flight_session(
    session: AsyncSession, application_id: int, *, kind: str
) -> None:
    """I4 (adversarial review): hồ sơ vừa bị HẠ khỏi hướng đang chờ — dọn PHIÊN tương ứng đang bay,
    nếu không nó sống sót ngoài vòng đời hồ sơ (AI_GUIDE: "thêm đường đưa hồ sơ rời khỏi hướng phỏng
    vấn → nhớ cancel_sessions").

    - `invite`: huỷ MỌI liên kết đặt lịch còn sống (`booking_service.cancel_sessions`) — không thì
      ứng viên vẫn mở được một link mà hồ sơ đã rời `AWAITING_BOOKING`, và `confirm_and_notify` sẽ
      ghi đè `PENDING_REVIEW` thành `INTERVIEW_SCHEDULED` sau lưng HR.
    - `screener`/`screener_reminder`: đặt `timed_out_at` cho phiên sàng lọc còn mở. Sweep
      (`screening_timeout.py`) đã TỰ ĐỘNG bỏ qua hồ sơ này (câu JOIN của nó đòi
      `Application.status == AWAITING_SCREENER`, mà ta vừa đổi sang `PENDING_REVIEW`) — nhưng không
      đặt cờ thì hàng `screening_session` sống mãi ở trạng thái MẬP MỜ (không dùng, không hết hạn):
      HR đọc bảng thô sẽ không hiểu vì sao một phiên "còn mở" lại không đi tới đâu.

    **GIỚI HẠN ĐÃ BIẾT (chốt của người dùng — KHÔNG phải bỏ sót):** hàm này KHÔNG resume graph
    LangGraph từ webhook. `handle_screening_timeout` (screening_timeout.py) bình thường resume graph
    với `{"no_response": True}` khi hết hạn; ở đây ta CHỈ đóng `ScreeningSession` bằng field, KHÔNG
    đụng graph — một luồng LangGraph đang treo ở `interrupt()` cho hồ sơ này vẫn RÒ một thread trong
    checkpointer. Dọn graph từ webhook là thay đổi nặng, đụng vào phần lõi screener nằm NGOÀI phạm
    vi EMAIL-1 — ghi rõ ở đây để không ai tưởng nhầm là đã xử lý xong.
    """
    if kind == EmailKind.INVITE.value:
        await booking_service.cancel_sessions(session, application_id)
        return
    await session.execute(
        update(ScreeningSession)
        .where(
            ScreeningSession.application_id == application_id,
            ScreeningSession.used_at.is_(None),
            ScreeningSession.timed_out_at.is_(None),
        )
        .values(timed_out_at=_now())
    )


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
