"""EmailDelivery — lưu vết GIAO HÀNG của từng lá thư (EMAIL-1 · PRD §7.4, §12.4 FR-NOTI-1).

`Emails.send()` trả OK chỉ nghĩa là **Resend đã nhận**. Bounce xảy ra bất đồng bộ vài giây tới
vài phút sau, qua webhook — nên phải có một hàng để webhook đó tra vào. Khoá đối chiếu là
`resend_email_id`: đây là thứ DUY NHẤT hai bên cùng biết.

Bảng riêng chứ không phải một cột trên `application`: một hồ sơ nhận NHIỀU thư (mời, nhắc, xác
nhận, huỷ) và mỗi lá có số phận giao hàng riêng — thư mời bounce là chuyện khác hẳn thư nhắc
bounce (xem bảng quyết định ở `services/email_delivery`).
"""

from __future__ import annotations

import enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class EmailKind(str, enum.Enum):
    """Loại thư. Giá trị PHẢI TRÙNG chuỗi `mode` của `scheduler._dispatch`.

    Lý do là một bất biến chứ không phải sở thích: audit_log đã ghi `email_sent:{mode}` từ lát 04,
    nên đặt tên thứ hai ở đây là tạo hai từ vựng cho cùng một thứ — và lúc truy vết sự cố thì
    không nối được dòng audit với hàng giao hàng nữa.
    """

    INVITE = "invite"
    REJECT = "reject"
    SCREENER = "screener"
    SCREENER_REMINDER = "screener_reminder"
    BOOKING_CONFIRMED = "booking_confirmed"
    INTERVIEW_REMINDER = "interview_reminder"
    BOOKING_REMINDER = "booking_reminder"
    BOOKING_CANCELLED = "booking_cancelled"
    # ĐỂ DÀNH: hệ thống hiện KHÔNG gửi thư xác nhận nộp CV (thêm nó là feature mới — xem spec §2
    # quyết định #3). Giữ giá trị + phân loại bounce sẵn để sau này bật lên không phải đụng enum.
    SUBMISSION_ACK = "submission_ack"


class DeliveryStatus(str, enum.Enum):
    """Số phận một lá thư. Lưu dạng String như `ApplicationStatus`/`BookingStatus`."""

    SENT = "SENT"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    COMPLAINED = "COMPLAINED"


# Thứ bậc — MỘT quy tắc lo cả hai chuyện: thứ tự sự kiện lẫn idempotency.
#
# Resend KHÔNG bảo đảm thứ tự và có gửi lại sự kiện trùng. Nếu cứ tới đâu ghi đè đó thì một
# `delivered` tới muộn sẽ XOÁ dấu bounce — hồ sơ vừa được gắn cờ lại sạch sẽ trở lại, và HR không
# bao giờ biết. Chỉ áp khi hạng CAO HƠN: `delivered` (1) không đè được `bounced` (2), sự kiện
# trùng cùng hạng là no-op, và bounce tới SAU delivered (chuyện thật — máy chủ nhận báo lại) vẫn áp
# được vì 2 > 1.
_RANK: dict[str, int] = {
    DeliveryStatus.SENT.value: 0,
    DeliveryStatus.DELIVERED.value: 1,
    DeliveryStatus.BOUNCED.value: 2,
    DeliveryStatus.COMPLAINED.value: 3,
}


def outranks(new: str, current: str) -> bool:
    """`new` có được phép ghi đè `current` không. Mã lạ → False (không bao giờ lọt vào cột)."""
    return _RANK.get(new, -1) > _RANK.get(current, -1)


class EmailDelivery(Base, TimestampMixin):
    __tablename__ = "email_delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    # KHOÁ ĐỐI CHIẾU với webhook. unique để sự kiện trùng tra ra đúng một hàng; NOT NULL vì hàng
    # không có id thì webhook chẳng bao giờ tìm thấy — vô dụng, xem `_dispatch` (bỏ qua, chỉ log).
    resend_email_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # nullable: chừa đường cho thư KHÔNG thuộc hồ sơ nào (chưa có, nhưng cột này rẻ hơn migration
    # sau). CASCADE giống `audit_log` — xoá hồ sơ thì vết giao hàng đi theo.
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    recipient: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(
        String(16), default=DeliveryStatus.SENT.value, index=True
    )
    # Lý do bounce rút gọn từ Resend — hiện cho HR ở trang chi tiết. CẮT NGẮN ở tầng service
    # (`_MAX_REASON`), không tin độ dài do bên ngoài gửi tới.
    bounce_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EmailDelivery id={self.id} app={self.application_id} "
            f"kind={self.kind} status={self.status}>"
        )
