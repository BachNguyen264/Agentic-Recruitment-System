"""Đặt lịch phỏng vấn — ứng viên tự chọn giờ (SCH-1 · PRD §10b, §16).

Hai bảng, hai vai trò KHÁC nhau — đừng gộp:

- `InterviewBooking`: một **khung giờ** của hệ thống. `HELD` = giữ tạm trong lúc ứng viên đang chọn
  (`BOOKING_HOLD_MINUTES`), `BOOKED` = đã chốt, `CANCELLED` = đã nhả. **HELD chỉ là khuyến nghị, BOOKED mới là
  thẩm quyền** (PRD §10b.5) — nên chốt chặn cuối cùng nằm ở DB: **partial unique index trên
  `start_at` CHỈ áp cho hàng `BOOKED`**. Hai hàng cùng `start_at` được phép cùng `HELD` (hai người
  đang cân nhắc), nhưng chỉ MỘT được thành `BOOKED`; kẻ thua nhận `IntegrityError` → 409 (SCH-2).
- `BookingSession`: **liên kết** gửi cho ứng viên. Khác token screener ở chỗ **KHÔNG one-time**
  (PRD §10b.3): mở lại bao nhiêu lần cũng được tới khi đặt xong hoặc hết TTL 72h, vì mỗi lần mở là
  sinh danh sách slot TƯƠI (sinh lười) nên link không bao giờ ôi.

Thời gian: cột `timestamptz` (UTC trong DB); sinh/so sánh/hiển thị theo `Asia/Ho_Chi_Minh` ở tầng
service. **KHÔNG bao giờ dùng datetime naive** (xem `booking_config`).

⚠️ Không có quan hệ ORM tới `Application`: bảng này chỉ được truy vấn tường minh qua
`booking_service`. Xoá application vẫn dọn sạch nhờ FK `ondelete="CASCADE"` (đường xoá thật của
`scripts/reset_demo_data.py` là `DELETE` mức SQL nên cascade do DB lo, không cần ORM).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class BookingStatus(str, enum.Enum):
    """Trạng thái một khung giờ (PRD §16). Lưu dạng String như `ApplicationStatus`."""

    HELD = "HELD"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


# Tên index dùng lại ở migration hand-written — giữ MỘT nguồn để hai nơi không lệch nhau.
BOOKED_START_AT_INDEX = "uq_interview_booking_booked_start_at"

# Điều kiện của partial unique index. `text()` chứ KHÔNG phải so sánh Python: nó phải đi thẳng
# xuống SQL (`WHERE status = 'BOOKED'`).
_BOOKED_ONLY = text("status = 'BOOKED'")


class InterviewBooking(Base, TimestampMixin):
    __tablename__ = "interview_booking"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )

    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    status: Mapped[str] = mapped_column(
        String(16), default=BookingStatus.HELD.value, nullable=False, index=True
    )

    # Hạn giữ chỗ — CHỈ có nghĩa khi status=HELD. Xoá (NULL) khi lật BOOKED/CANCELLED.
    # Hold hết hạn KHÔNG cần cron dọn: mọi truy vấn "slot đang bị chiếm" đều lọc `> now()`
    # (PRD §10b.5), nên hàng HELD quá hạn tự động thôi chiếm chỗ.
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SCH-3: mốc đã gửi thư NHẮC TRƯỚC BUỔI PHỎNG VẤN. Cột mốc thời gian chứ không phải bộ đếm —
    # "đã nhắc chưa" là câu hỏi nhị phân, và mốc còn cho biết nhắc lúc nào khi truy vết sự cố.
    reminder_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        # Chống đặt trùng ở tầng DB (PRD §10b.5, FR-BOOK-2). PHẢI là partial: nếu unique toàn bảng
        # thì hai người cùng HELD một giờ đã nổ ngay từ khâu giữ chỗ, phá luôn ý "HELD = khuyến nghị".
        # Khai báo ở đây để `alembic check`/autogenerate KHÔNG đòi tạo lại index migration đã tạo.
        Index(
            BOOKED_START_AT_INDEX,
            "start_at",
            unique=True,
            postgresql_where=_BOOKED_ONLY,
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<InterviewBooking id={self.id} app={self.application_id} "
            f"start={self.start_at.isoformat() if self.start_at else None} status={self.status}>"
        )


class BookingSession(Base, TimestampMixin):
    __tablename__ = "booking_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )
    # secrets.token_urlsafe(32) → ~43 ký tự (như ScreeningSession).
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Hạn của LIÊN KẾT (BOOKING_LINK_TTL_HOURS, mặc định 72h) — KHÁC hạn giữ chỗ vài phút của
    # `InterviewBooking.hold_expires_at`. Hai đồng hồ này rất dễ nhầm: xem bảng PRD §10b.3.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Nhắc một lần trước khi link hết hạn → PENDING_REVIEW[booking_no_response] (SCH-3).
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # SCH-3: lần ĐẦU ứng viên mở link mà kho khung giờ đã cạn. Đây là lỗi của HỆ THỐNG (lịch chưa mở
    # đủ), không phải ứng viên chậm — nên nó phải hiện thành nhãn RIÊNG trên dashboard. Xoá về NULL
    # ngay khi có slot trở lại, nếu không nhãn báo động sẽ ở lại vĩnh viễn sau khi HR đã mở thêm lịch.
    no_slots_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Mốc ứng viên chốt được giờ. KHÔNG dùng làm cờ one-time (link mở lại được — PRD §10b.3);
    # nó chỉ nói "phiên này đã xong việc" để SCH-3 khỏi nhắc.
    booked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<BookingSession id={self.id} app={self.application_id} booked={self.booked_at is not None}>"
