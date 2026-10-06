"""resend_policy — lá thư hỏng nào HR gửi lại được (PRD FR-SCR-7, FR-NOTI-3). Module LÁ, thuần.

Tách khỏi `email_resend` vì `schemas.application` cần đúng một hàm này cho computed field
`resendable_email`, mà `email_resend` kéo theo `screening` → `tasks.background` → cả graph LangGraph.
Một schema không có lý do gì để import cả pipeline chỉ vì một phép so cờ.
"""

from __future__ import annotations

from typing import Literal

from app.models.application import ApplicationStatus
from app.services.email_delivery import EMAIL_COMPLAINED_FLAG, EMAIL_SEND_FAILED_FLAG

__all__ = ["ResendableEmail", "resendable_email"]

ResendableEmail = Literal["screener", "reject"]

# Trạng thái → loại thư gửi lại được ở trạng thái đó. Chỉ hai ca KHÔNG còn đường cứu nào khác.
_RESENDABLE_BY_STATUS: dict[str, ResendableEmail] = {
    ApplicationStatus.AWAITING_SCREENER.value: "screener",
    ApplicationStatus.REJECTED.value: "reject",
}


def resendable_email(status: str, flags: list | None) -> ResendableEmail | None:
    """Loại thư HR gửi lại được cho hồ sơ này, hoặc `None`. Nguồn DUY NHẤT cho cả nút trên UI
    (`ApplicationRead.resendable_email`) lẫn chốt chặn của `email_resend.resend_failed_email` — hai
    nơi tự suy riêng thì HR thấy nút rồi bấm ra 409.

    - Phải có `email_send_failed`: đây là đường CỨU một lá thư hỏng, không phải kênh nhắc tuỳ ý.
      Bounce KHÔNG tính — địa chỉ chết thì gửi lại vào đúng địa chỉ đó là vô ích.
    - Ứng viên đã báo spam (`email_complained`) → không bao giờ gửi thêm: complaint hại danh tiếng
      gửi email của CẢ hệ thống.
    """
    current = set(flags or [])
    if EMAIL_SEND_FAILED_FLAG not in current or EMAIL_COMPLAINED_FLAG in current:
        return None
    return _RESENDABLE_BY_STATUS.get(status)
