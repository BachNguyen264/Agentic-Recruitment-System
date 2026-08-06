"""IcsProvider — sinh tệp `.ics` (RFC 5545) để đính kèm email xác nhận lịch (PRD §10b.8).

**0 dependency** (như `core/html_text.html_to_text` của JD-1): định dạng iCalendar mà ta cần chỉ là
vài dòng `KEY:VALUE`, còn ba luật dễ sai thì viết một lần ở đây và có test giữ:

1. **Kết thúc dòng CRLF** (RFC 5545 §3.1) — LF trần khiến một số ứng dụng lịch từ chối cả tệp.
2. **Gấp dòng ở 75 octet**, dòng nối bắt đầu bằng MỘT dấu cách — và không được cắt giữa một ký tự
   UTF-8 nhiều byte (tiếng Việt có dấu là 2–3 byte/ký tự, cắt sai thì tệp hỏng ngay).
3. **Thoát ký tự** trong giá trị TEXT: `\\` `;` `,` và xuống dòng (RFC 5545 §3.3.11). Tên vị trí kiểu
   "Tầng 3, toà A" mà không thoát dấu phẩy sẽ bị đọc thành hai giá trị.

**Giờ ghi dạng UTC (`...Z`).** Đây là mốc thời gian TUYỆT ĐỐI nên ứng dụng lịch hiển thị đúng theo
múi giờ của người xem — buổi 08:00 giờ Việt Nam ra `DTSTART:20260810T010000Z`. Cách còn lại
(`TZID=Asia/Ho_Chi_Minh`) đòi kèm nguyên khối `VTIMEZONE` mô tả quy tắc múi giờ; dài hơn, dễ sai
hơn, và không đúng hơn chút nào.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.core.config import settings
from app.core.logging import get_logger
from app.services.calendar import CalendarEvent
from app.models.booking import InterviewBooking

logger = get_logger("app.services.calendar.ics")

__all__ = ["IcsProvider", "build_ics", "event_uid"]

_MAX_OCTETS = 75
_PRODID = "-//Agentic Recruitment System//Interview Booking//VI"


def _escape(value: str) -> str:
    """Thoát ký tự đặc biệt trong giá trị TEXT (RFC 5545 §3.3.11). Thứ tự quan trọng: `\\` TRƯỚC."""
    return (
        (value or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Gấp dòng dài ở 75 octet, dòng nối mở đầu bằng một dấu cách (RFC 5545 §3.1)."""
    raw = line.encode("utf-8")
    if len(raw) <= _MAX_OCTETS:
        return line
    chunks: list[bytes] = []
    limit = _MAX_OCTETS
    while raw:
        if len(raw) <= limit:
            chunks.append(raw)
            break
        cut = limit
        # Lùi ra khỏi giữa một ký tự nhiều byte: 0b10xxxxxx là byte NỐI TIẾP của UTF-8.
        while cut > 0 and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(raw[:cut])
        raw = raw[cut:]
        limit = _MAX_OCTETS - 1  # dòng nối đã tiêu một octet cho dấu cách mở đầu
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def _stamp(value: datetime) -> str:
    """datetime aware → dạng UTC của iCalendar (`20260810T010000Z`)."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"Mốc thời gian trong .ics phải aware, nhận được naive: {value!r}")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _uid_domain() -> str:
    """Phần domain của UID — lấy từ FRONTEND_BASE_URL để UID gắn với hệ thống đang chạy."""
    host = urlsplit(settings.frontend_base_url or "").hostname
    return host or "ars.local"


def event_uid(booking_id: int) -> str:
    """UID TẤT ĐỊNH theo booking.

    Tất định (không random) là có chủ ý: SCH-3 dời lịch sẽ gửi lại cùng UID với `SEQUENCE` cao hơn,
    và ứng dụng lịch CẬP NHẬT sự kiện cũ thay vì tạo thêm một sự kiện trùng.
    """
    return f"booking-{booking_id}@{_uid_domain()}"


def build_ics(
    *,
    uid: str,
    start_at: datetime,
    end_at: datetime,
    summary: str,
    description: str = "",
    location: str = "",
    dtstamp: datetime | None = None,
    sequence: int = 0,
    cancelled: bool = False,
) -> bytes:
    """Dựng một VCALENDAR chứa đúng một VEVENT. Trả bytes UTF-8 (sẵn sàng đính kèm email).

    KHÔNG đặt `METHOD`/`ORGANIZER`/`ATTENDEE`: đó là địa hạt iTIP (RFC 5546) với ràng buộc riêng, và
    một tệp thiếu chúng vẫn là iCalendar HỢP LỆ — ứng dụng lịch hiển thị nút "thêm vào lịch". Khi
    nào cần lời mời hai chiều thật (nhận phản hồi chấp nhận/từ chối) thì thêm, ở SCH-2/SCH-3.
    """
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{_PRODID}",
        "CALSCALE:GREGORIAN",
    ]
    # `METHOD:CANCEL` CHỈ có ở tệp huỷ. Tệp mời vẫn cố ý không có METHOD (xem docstring dưới) —
    # đặt `METHOD:REQUEST` sẽ kéo theo ràng buộc ORGANIZER/ATTENDEE của iTIP mà ta chưa cần.
    if cancelled:
        lines.append("METHOD:CANCEL")
    lines += [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(dtstamp or datetime.now(timezone.utc))}",
        f"DTSTART:{_stamp(start_at)}",
        f"DTEND:{_stamp(end_at)}",
        f"SUMMARY:{_escape(summary)}",
        f"SEQUENCE:{int(sequence)}",
        "STATUS:CANCELLED" if cancelled else "STATUS:CONFIRMED",
    ]
    if description:
        lines.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    # CRLF, kể cả dòng cuối (RFC 5545 §3.1).
    return ("\r\n".join(_fold(line) for line in lines) + "\r\n").encode("utf-8")


class IcsProvider:
    """Provider mặc định: không gọi mạng, không trạng thái phía máy chủ — chỉ sinh tệp đính kèm."""

    async def create_event(
        self,
        booking: InterviewBooking,
        *,
        summary: str,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent:
        uid = event_uid(booking.id)
        return CalendarEvent(
            ref=uid,
            ics=build_ics(
                uid=uid,
                start_at=booking.start_at,
                end_at=booking.end_at,
                summary=summary,
                description=description,
                location=location,
            ),
        )

    async def cancel_event(
        self,
        booking: InterviewBooking,
        *,
        summary: str = "",
    ) -> CalendarEvent:
        """Sinh tệp `.ics` **METHOD:CANCEL** để đính vào thư báo huỷ (SCH-3).

        Không có sự kiện phía máy chủ nào để xoá — tệp cũ đã nằm trong ứng dụng lịch của ứng viên,
        và cách DUY NHẤT gỡ nó ra là gửi một tệp mới cùng `UID`, `SEQUENCE` cao hơn, `STATUS:CANCELLED`.
        Thiếu bước này thì ứng viên vẫn thấy buổi phỏng vấn trên lịch ở một khung giờ đã nhả cho
        người khác — và có thể tới dự một buổi không còn tồn tại.

        `SEQUENCE:1` (> 0 của tệp mời) là thứ khiến ứng dụng lịch chấp nhận bản cập nhật; giữ nguyên
        số cũ thì nhiều ứng dụng lặng lẽ bỏ qua.
        """
        uid = event_uid(booking.id)
        logger.info("calendar(ics): sinh .ics huỷ cho %s", uid)
        return CalendarEvent(
            ref=uid,
            ics=build_ics(
                uid=uid,
                start_at=booking.start_at,
                end_at=booking.end_at,
                summary=summary or "Phỏng vấn (đã huỷ)",
                sequence=1,
                cancelled=True,
            ),
        )
