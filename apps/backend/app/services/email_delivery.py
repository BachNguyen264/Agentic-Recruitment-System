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

__all__ = [
    "EMAIL_BOUNCED_FLAG",
    "EMAIL_COMPLAINED_FLAG",
    "EMAIL_SEND_FAILED_FLAG",
    "handle_event",
]

EMAIL_BOUNCED_FLAG = "email_bounced"

# Cờ RIÊNG cho complaint — KHÔNG dùng chung với `EMAIL_BOUNCED_FLAG` (fix sau adversarial review,
# vòng 3). Từ khi COMPLAINED thôi hạ trạng thái (I3), cờ là TÍN HIỆU DUY NHẤT một complaint để lại
# cho HR — dùng chung tên "bounced" cho một lá thư ĐÃ TỚI NƠI vừa sai nghĩa vừa NGUY HIỂM: `_clear_
# bounce` gỡ cờ khi có thư SAU tới cùng địa chỉ, nên nếu dùng chung tên, một lượt gửi THÀNH CÔNG về
# sau sẽ XOÁ ÂM THẦM dấu vết "người này đã báo chúng ta là spam" — trong khi giao hàng thành công
# KHÔNG hề phủ nhận việc họ từng bấm spam. Hai tình huống cần hai hành động NGƯỢC nhau: bounce ⇒ tìm
# địa chỉ đúng rồi liên hệ lại; complaint ⇒ NGỪNG gửi cho người này. Resend là kênh email DUY NHẤT
# của cả hệ thống — tiếp tục gửi cho người đã báo spam là cách nhanh nhất làm hỏng danh tiếng domain
# rồi làm câm thư của MỌI ứng viên khác.
EMAIL_COMPLAINED_FLAG = "email_complained"

# Cờ thứ BA: Resend báo `email.failed` — lá thư KHÔNG BAO GIỜ rời khỏi Resend. Cờ RIÊNG, không gộp
# vào `email_bounced`, vì nó chỉ về phía NGƯỢC LẠI: bounce nói "địa chỉ ứng viên có vấn đề, tìm địa
# chỉ khác"; failed nói "PHÍA TA có vấn đề" (cạn hạn mức, domain chưa xác thực, khoá API hỏng, địa
# chỉ sai định dạng) — hành động đúng là sửa cấu hình rồi gửi LẠI, không phải đi tìm số điện thoại.
#
# ⚠ TÊN: cố ý KHÔNG phải `"email_failed"`. Chuỗi đó ĐÃ được `scheduler._dispatch` dùng làm tên
# `action` trong `audit_log` cho một chuyện KHÁC HẲN — lượt gọi Resend NÉM lỗi ngay tại chỗ, trường
# hợp thậm chí không tạo nổi hàng `email_delivery` nào. Cùng một chuỗi mang hai nghĩa ở hai bảng là
# đúng lớp lỗi đã phải vá một lần rồi (commit d4fbfd5, audit của complaint ghi nhầm "email_bounced").
EMAIL_SEND_FAILED_FLAG = "email_send_failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Lý do escalation là chuỗi CỐ ĐỊNH (không nhét chi tiết bounce vào): chi tiết sống ở
# `email_delivery.bounce_reason` và hiện riêng cho HR. Cố định thì lúc `delivered` về sau, ta so
# khớp được ĐÚNG câu này để gỡ — không xoá nhầm lý do escalation của một chuyện khác.
_REASON_INVITE = "Thư MỜI phỏng vấn không tới được ứng viên — cần liên hệ thủ công."
_REASON_SCREENER = "Thư SÀNG LỌC không tới được ứng viên — cần liên hệ thủ công."
# Câu RIÊNG cho `email.failed`: thư chưa hề rời hệ thống gửi, nên việc cần làm KHÁC hẳn bounce —
# xem lý do kỹ thuật (hiện ngay cạnh) rồi gửi lại, thay vì đi tìm địa chỉ khác của ứng viên.
_REASON_INVITE_FAILED = (
    "Hệ thống KHÔNG GỬI ĐƯỢC thư mời phỏng vấn (lỗi phía dịch vụ gửi) — kiểm tra lý do rồi gửi lại."
)
_REASON_SCREENER_FAILED = (
    "Hệ thống KHÔNG GỬI ĐƯỢC thư sàng lọc (lỗi phía dịch vụ gửi) — kiểm tra lý do rồi gửi lại."
)
_BOUNCE_REASONS = frozenset(
    {_REASON_INVITE, _REASON_SCREENER, _REASON_INVITE_FAILED, _REASON_SCREENER_FAILED}
)

# kind -> (trạng thái mà thư đó thiết lập, lý do khi BOUNCE, lý do khi FAILED).
# `reject` VẮNG MẶT có chủ ý (xem docstring). `submission_ack` vắng mặt vì chưa có đường phát nào.
# Bốn loại thư đặt lịch còn lại là BIÊN NHẬN — ứng viên đã thấy màn xác nhận trên web hoặc tự bấm,
# nên thư không tới không đổi được sự thật nào; chỉ gắn cờ.
# Hai câu nằm CHUNG một hàng (thay vì hai bảng rời) để danh sách kind chỉ tồn tại MỘT bản: thêm một
# loại thư đơn-kênh mới mà quên cập nhật bảng thứ hai là lỗi câm, không có gì bắt được.
_SINGLE_CHANNEL: dict[str, tuple[str, str, str]] = {
    EmailKind.INVITE.value: (
        ApplicationStatus.AWAITING_BOOKING.value, _REASON_INVITE, _REASON_INVITE_FAILED
    ),
    EmailKind.SCREENER.value: (
        ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER, _REASON_SCREENER_FAILED
    ),
    # Ô thứ BA ở hàng NÀY không tới được: `_apply_bounce` chặn `FAILED` của thư nhắc bằng early-
    # return ngay TRƯỚC lượt tra bảng. Chết đúng MỘT Ô — KHÔNG phải cả hàng (hai ô đầu chạy thật ở
    # đường bounce Permanent của thư nhắc) và KHÔNG phải hằng `_REASON_SCREENER_FAILED` (nó sống ở
    # hàng `SCREENER` và trong `_BOUNCE_REASONS`). Giữ nguyên câu đó chứ KHÔNG để `None`: nếu chốt
    # chặn kia có ngày được gỡ, thứ lộ ra phải là câu ĐÚNG, không phải một hồ sơ bị hạ về
    # PENDING_REVIEW mà HR không thấy lý do nào — và `tuple[str, str, str]` còn nguyên sức bắt hàng
    # nào QUÊN câu FAILED.
    EmailKind.SCREENER_REMINDER.value: (
        ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER, _REASON_SCREENER_FAILED
    ),
}

_EVENT_STATUS: dict[str, str] = {
    "email.sent": DeliveryStatus.SENT.value,
    "email.delivered": DeliveryStatus.DELIVERED.value,
    "email.failed": DeliveryStatus.FAILED.value,
    "email.bounced": DeliveryStatus.BOUNCED.value,
    "email.complained": DeliveryStatus.COMPLAINED.value,
}

# Sự kiện XẤU -> cờ HR tương ứng. Bảng TƯỜNG MINH thay cho ternary hai nhánh cũ
# (`BOUNCED if ... else COMPLAINED`): ternary đó ngầm giả định `_NEGATIVE` có ĐÚNG hai phần tử, nên
# loại thứ ba lặng lẽ rơi vào nhánh `else` và bị gắn cờ "ứng viên báo spam" — một cờ KHÔNG BAO GIỜ
# được gỡ, và chỉ HR đúng hướng hành động ngược lại hoàn toàn.
_STATUS_FLAG: dict[str, str] = {
    DeliveryStatus.BOUNCED.value: EMAIL_BOUNCED_FLAG,
    DeliveryStatus.COMPLAINED.value: EMAIL_COMPLAINED_FLAG,
    DeliveryStatus.FAILED.value: EMAIL_SEND_FAILED_FLAG,
}

# DẪN XUẤT từ `_STATUS_FLAG`, KHÔNG viết tay: "sự kiện xấu" và "sự kiện có cờ" phải là cùng một tập
# theo định nghĩa. Hai danh sách viết tay song song chính là cách một loại mới được thêm vào một bên
# rồi im lặng vắng mặt ở bên kia.
_NEGATIVE = frozenset(_STATUS_FLAG)

# Trạng thái ĐƯỢC PHÉP hạ ứng dụng — tập CON của `_NEGATIVE` (adversarial review I3). `COMPLAINED`
# cố ý VẮNG MẶT: complaint là ứng viên tự bấm "đây là spam" trên một lá thư ĐÃ TỚI TAY — không có gì
# "hỏng" để cứu bằng cách hạ về `PENDING_REVIEW`. Hạ nhầm đẩy hồ sơ ra khỏi `_BOOKABLE_STATUSES` của
# `booking_flow` / lưới sweep của `screening_timeout` (cả hai đều đòi đúng trạng thái đang chờ), tức
# giết một liên kết đặt lịch/sàng lọc vẫn đang sống tốt. Complaint vẫn được gắn cờ + audit (xem
# `_NEGATIVE`) — chỉ không đổi trạng thái.
#
# `FAILED` CÓ mặt: lá thư không hề rời hệ thống, nên với `invite`/`screener` — những loại mà email là
# kênh DUY NHẤT — ứng viên đang ngồi chờ một thứ sẽ KHÔNG BAO GIỜ tới. Chỉ gắn cờ mà để nguyên trạng
# thái thì hồ sơ nằm ở `AWAITING_BOOKING`/`AWAITING_SCREENER` cho tới khi lưới sweep hết hạn, rồi bị
# dán nhãn `booking_no_response` / `no_response` — tức ĐỔ LỖI CHO ỨNG VIÊN vì một lá thư ta chưa từng
# gửi được. Đó đúng là lớp lỗi mà `booking_no_slots` (FR-BOOK-6) đã sinh ra để chặn.
#
# Cạn hạn mức (`reached_daily_quota`, ví dụ DUY NHẤT tài liệu Resend nêu) vẫn hạ, có chủ ý: dù nguyên
# nhân là toàn hệ thống chứ không riêng ứng viên nào, kết quả với TỪNG ứng viên là như nhau — thư
# không tới. Đưa về `PENDING_REVIEW` là đưa cho CON NGƯỜI quyết, không phải một quyết định cuối; và
# như mọi nhánh khác ở đây, TUYỆT ĐỐI không auto-reject.
_DEMOTABLE = frozenset({DeliveryStatus.BOUNCED.value, DeliveryStatus.FAILED.value})

# Tên `action` ghi vào `audit_log`. Mặc định suy từ status (`email_delivered`/`email_bounced`/…) —
# GIỮ NGUYÊN chuỗi cũ để không cắt đứt lịch sử đã ghi. RIÊNG `FAILED` phải đặt tay: công thức sẽ cho
# ra đúng chuỗi `email_failed`, thứ mà `scheduler._dispatch` ĐÃ dùng (cùng `node="scheduler"`!) cho
# một chuyện khác hẳn — lượt gọi Resend ném lỗi tại chỗ, chưa từng sinh hàng `email_delivery` nào.
# Để trùng tên là biến hai sự kiện ngược nhau thành một dòng log không phân biệt được.
_AUDIT_ACTION: dict[str, str] = {DeliveryStatus.FAILED.value: "email_send_failed"}

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


def _is_transient_bounce(data: dict | None) -> bool:
    """`bounce.type` Resend phân "Transient" (hộp thư đầy/tạm thời — địa chỉ VẪN sống) khác
    "Permanent" (địa chỉ chết hẳn). `bounce_reason_of` đã ĐỌC field này từ lâu nhưng KHÔNG ai DÙNG
    nó để quyết định — F2 (final review): Transient CHỈ gắn cờ, KHÔNG hạ trạng thái (xem `_apply_
    bounce`). Cùng kỷ luật với `bounce_reason_of`: `data`/`bounce` sai kiểu hoặc thiếu → False (không
    coi là transient), KHÔNG ném — payload rác là đường bình thường của webhook công khai.
    """
    if not isinstance(data, dict):
        return False
    bounce = data.get("bounce")
    if not isinstance(bounce, dict):
        return False
    bounce_type = bounce.get("type")
    return isinstance(bounce_type, str) and bounce_type.strip().lower() == "transient"


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


def failure_reason_of(data: dict | None) -> str | None:
    """`data.failed.reason` của Resend → câu cho HR. Không có → None.

    Hàm RIÊNG chứ không mở rộng `bounce_reason_of`, vì hai sự kiện mang nguyên nhân ở HAI CHỖ KHÁC
    NHAU trong payload: `email.bounced` để ở `data["bounce"]{type,subType,message}`, còn
    `email.failed` để ở `data["failed"]["reason"]`. Dùng nhầm hàm KHÔNG gây lỗi — nó chỉ trả `None`,
    nghĩa là HR nhận một cảnh báo đỏ không kèm lý do nào, đúng kiểu hỏng-câm khó phát hiện nhất.

    `reason` là chuỗi TỰ DO: tài liệu Resend chỉ nêu đúng một ví dụ (`reached_daily_quota`) và KHÔNG
    có danh sách đóng — đừng `switch` trên nó, chỉ hiển thị.

    Cùng kỷ luật phòng thủ với `bounce_reason_of` (C1): sai kiểu → `None`, KHÔNG ném (payload rác là
    đường bình thường của một webhook công khai, và một exception ở đây từng nuốt mất CẢ sự kiện),
    cắt ở `_MAX_REASON` vì đây là văn bản do bên ngoài gửi tới.
    """
    if not isinstance(data, dict):
        return None
    failed = data.get("failed")
    if not isinstance(failed, dict):
        return None
    reason = failed.get("reason")
    if not reason:
        return None
    return str(reason)[:_MAX_REASON]


def _reason_for(new_status: str, data: dict | None) -> str | None:
    """Chọn ĐÚNG bộ đọc lý do theo loại sự kiện — một chỗ duy nhất biết sự bất đối xứng payload."""
    if new_status == DeliveryStatus.FAILED.value:
        return failure_reason_of(data)
    return bounce_reason_of(data)


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
        reason_text = _reason_for(new_status, event.get("data"))
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
    # F3 (final review): cờ dùng cho audit PHẢI là cờ `_apply_bounce` THẬT SỰ đã chọn/gắn — KHÔNG suy
    # luận lại bằng hằng số cứng ở đây (đó là lý do cũ audit của complaint ghi nhầm "email_bounced").
    audit_flag: str | None = None

    if app_row is not None:
        if new_status in _NEGATIVE:
            final_status, audit_flag = await _apply_bounce(
                session, app_row, kind=kind, new_status=new_status, bounce_data=event.get("data"),
            )
        elif new_status == DeliveryStatus.DELIVERED.value:
            _clear_bounce(app_row, recipient=recipient)

    await audit_service.record(
        session,
        application_id=application_id,
        node="scheduler",
        action=_AUDIT_ACTION.get(new_status, f"email_{new_status.lower()}"),
        escalation_reason=audit_flag,
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
    session: AsyncSession, app_row: Application, *, kind: str, new_status: str,
    bounce_data: dict | None = None,
) -> tuple[str, str]:
    """Gắn cờ + (có điều kiện) hạ về PENDING_REVIEW. Trả `(trạng thái CUỐI, cờ ĐÃ gắn)`.

    **F3 (final review):** trả thêm cờ đã chọn để `_process` dùng ĐÚNG biến này cho dòng audit —
    trước đây `_process` tự đặt `escalation_reason=EMAIL_BOUNCED_FLAG` cho CẢ bounce lẫn complaint
    (hằng số cứng, không hỏi hàm này chọn gì), nên audit của một complaint ghi sai thành
    `"email_bounced"`. Suy luận lại cùng một quyết định ở HAI nơi là nguồn drift — trả ra thay vì
    đoán lại.

    `new_status` quyết cờ nào được gắn (fix vòng 3 — xem định nghĩa `EMAIL_COMPLAINED_FLAG`) VÀ có
    được hạ hay không (I3, adversarial review — xem `_DEMOTABLE`): complaint KHÔNG được hạ, chỉ
    bounce THẬT mới đáng đưa về tay HR.

    **F2 (final review):** trong nhóm BOUNCE, `Transient` (hộp thư đầy/tạm thời) cũng KHÔNG được hạ —
    chỉ `Permanent` (và các loại khác/không rõ, coi như nghiêm trọng) mới hạ. Lý do cụ thể:
    `screener_reminder` chở lại CHÍNH magic-link mà thư `screener` gốc đã giao THÀNH CÔNG — hộp thư
    đầy lúc thư nhắc tới KHÔNG có nghĩa liên kết đã chết, nên hạ về PENDING_REVIEW rồi đóng phiên
    (`_abandon_in_flight_session`) là giết một link đang sống dưới chân ứng viên, mà HR lại không có
    nút "gửi lại link sàng lọc" (chỉ booking mới có). `bounce_data` cho phép `None` (complaint/sự
    kiện không mang `data`) — an toàn vì `_is_transient_bounce` tự canh kiểu.
    """
    # Tra BẢNG, không ternary. `_NEGATIVE` được dẫn xuất từ `_STATUS_FLAG` nên khoá chắc chắn tồn
    # tại ở đây (caller chỉ gọi khi `new_status in _NEGATIVE`) — không còn nhánh `else` nào để một
    # loại sự kiện thứ ba rơi nhầm vào và tự nhận cờ "đã báo cáo spam".
    flag = _STATUS_FLAG[new_status]
    app_row.uncertainty_flags = with_flag(app_row.uncertainty_flags, flag)

    if new_status not in _DEMOTABLE:
        return app_row.status, flag  # complaint: thư ĐÃ TỚI tay ứng viên — chỉ cờ, không hạ

    if new_status == DeliveryStatus.BOUNCED.value and _is_transient_bounce(bounce_data):
        return app_row.status, flag  # Transient: địa chỉ vẫn sống, liên kết vẫn sống — chỉ cờ, không hạ

    # Thư NHẮC sàng lọc không gửi đi được → CHỈ gắn cờ. Nó chở lại CHÍNH magic-link mà thư `screener`
    # gốc đã giao THÀNH CÔNG (`screening_timeout.send_screening_reminder` dùng lại đúng token cũ),
    # nên "thư nhắc không đi được" KHÔNG hề nói rằng liên kết đã chết — nó chỉ nói phía TA đang trục
    # trặc. Hạ trạng thái ở đây sẽ kéo theo `_abandon_in_flight_session` đóng phiên, và
    # `screening._load_valid` từ chối mọi phiên có `timed_out_at` ⇒ ứng viên mở liên kết CÒN HẠN của
    # mình thì nhận "đã quá hạn", `reminded_at` đã tiêu nên không có lời nhắc thứ hai, mà HR lại
    # KHÔNG có nút gửi lại link sàng lọc (chỉ đặt lịch mới có). Bài dự tuyển mất, không đường cứu.
    #
    # Nguy hiểm gấp bội vì `reached_daily_quota` là sự cố TOÀN HỆ THỐNG còn sweep gửi nhắc theo LÔ:
    # một lần cạn hạn mức giết liên kết của mọi ứng viên có thư nhắc rơi vào cửa sổ đó.
    #
    # Đây chính là ngoại lệ F2 đã dựng cho bounce Transient, nay mở rộng đúng phạm vi. KHÔNG áp cho
    # `invite`/`screener`: hai loại đó là lần chạm ĐẦU TIÊN — gửi hỏng nghĩa là ứng viên chưa từng
    # nhận được gì, nên hạ về tay HR mới đúng. Và KHÔNG áp cho bounce Permanent của thư nhắc (vẫn
    # hạ, xem `test_screener_reminder_permanent_bounce_still_demotes`): bounce vĩnh viễn nói địa chỉ
    # ĐÃ CHẾT, nên liên kết còn sống cũng vô nghĩa — khác hẳn "ta chưa gửi được".
    if new_status == DeliveryStatus.FAILED.value and kind == EmailKind.SCREENER_REMINDER.value:
        return app_row.status, flag

    mapping = _SINGLE_CHANNEL.get(kind)
    if mapping is None:
        return app_row.status, flag  # thư biên nhận / thư từ chối → chỉ cờ

    # KHÔNG có vế transient cho `FAILED`, và đó là kết luận từ tài liệu chứ không phải bỏ sót:
    # `email.failed` chỉ mang đúng `failed.reason` (chuỗi TỰ DO, Resend không công bố danh sách đóng)
    # và KHÔNG hề có phân loại Transient/Permanent như `bounce.type`. Tự chế một phép phân loại bằng
    # cách so chuỗi `reason` là dựng chốt chặn trên thứ nhà cung cấp chưa bao giờ hứa giữ nguyên.
    expected_status, bounce_reason, failed_reason = mapping
    reason = failed_reason if new_status == DeliveryStatus.FAILED.value else bounce_reason
    if app_row.status != expected_status:
        # Hồ sơ đã đi tiếp trong lúc webhook đang trên đường. KHÔNG kéo ngược.
        return app_row.status, flag
    if await _already_moved_on(session, app_row.id, kind=kind):
        # Cờ trạng thái nói một đằng, BẢNG nói một nẻo. Tin bảng (bài học SCH-3).
        logger.warning(
            "Webhook Resend: app=%s trạng thái %s nhưng bảng cho thấy đã đi tiếp — chỉ gắn cờ.",
            app_row.id, app_row.status,
        )
        return app_row.status, flag

    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = reason
    await _abandon_in_flight_session(session, app_row.id, kind=kind)
    return app_row.status, flag


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


# Cờ được phép GỠ khi một lá thư sau giao thành công tới cùng địa chỉ. Danh sách TƯỜNG MINH, liệt kê
# từng tên — cố ý KHÔNG lọc theo tiền tố `email_*`: `EMAIL_COMPLAINED_FLAG` phải nằm ngoài VĨNH VIỄN
# (xem định nghĩa của nó), và một vòng lặp "mọi cờ liên quan email" sẽ nuốt nó vào ngay lần đầu ai đó
# thấy ba dòng này trông giống nhau.
#
# `EMAIL_SEND_FAILED_FLAG` CÓ mặt vì một lượt giao hàng thành công về sau thật sự BÁC BỎ nó: thư đi
# được nghĩa là hạn mức/domain/khoá API đều ổn trở lại. Còn complaint thì không — người đã bấm "spam"
# vẫn đã bấm, dù thư sau có tới nơi.
_CLEARABLE_FLAGS = frozenset({EMAIL_BOUNCED_FLAG, EMAIL_SEND_FAILED_FLAG})


def _clear_bounce(app_row: Application, *, recipient: str) -> None:
    """GỠ cờ BOUNCE khi một lá thư sau ĐÃ tới cùng địa chỉ đó (bài học SCH-3: gắn cờ thì phải có
    đường gỡ). Không gỡ thì hồ sơ mang nhãn báo động vĩnh viễn kể cả sau khi địa chỉ đã hoạt động
    trở lại — và cảnh báo không bao giờ tắt là cảnh báo sẽ bị phớt lờ.

    **CHỈ gỡ `EMAIL_BOUNCED_FLAG` — TUYỆT ĐỐI không đụng `EMAIL_COMPLAINED_FLAG`** (fix vòng 3, xem
    định nghĩa cờ đó). Một lượt giao hàng THÀNH CÔNG về sau chứng minh địa chỉ đang hoạt động, nên
    gỡ được cờ bounce; nhưng nó KHÔNG hề phủ nhận việc ứng viên đã từng bấm "đây là spam" — hai sự
    kiện độc lập nhau. Việc chỉ so khớp đúng CHUỖI `EMAIL_BOUNCED_FLAG` (không lặp qua mọi cờ) là
    chốt chặn duy nhất ở đây; đừng "tổng quát hoá" nó thành xoá mọi cờ liên quan tới email.
    """
    if recipient != app_row.applicant_email:
        return
    flags = list(app_row.uncertainty_flags or [])
    if not _CLEARABLE_FLAGS.intersection(flags):
        return
    app_row.uncertainty_flags = [f for f in flags if f not in _CLEARABLE_FLAGS]
    # Chỉ xoá lý do NẾU nó đúng là câu ta đặt — đừng xoá lý do escalation của một chuyện khác.
    if app_row.escalation_reason in _BOUNCE_REASONS:
        app_row.escalation_reason = None
