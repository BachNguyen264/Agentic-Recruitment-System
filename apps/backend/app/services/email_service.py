"""email_service — gửi email qua Resend (PRD §7.4, §12.4 FR-NOTI-1).

Chỉ scheduler gọi (điểm phát email DUY NHẤT). Resend SDK là SYNC → bọc `asyncio.to_thread`
để KHÔNG chặn event loop (CLAUDE.md async-first). Lỗi (thiếu key / mạng / Resend) → raise
`EmailError` RÕ để caller (scheduler) xử lý; KHÔNG nuốt lỗi im lặng ở tầng này.
"""

from __future__ import annotations

import asyncio
import base64

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.services.email")


class EmailError(Exception):
    """Gửi email thất bại (thiếu cấu hình / lỗi Resend)."""


def _send_sync(to: str, subject: str, html: str, attachments: list[dict] | None) -> dict | None:
    """Gọi Resend SDK (đồng bộ) — chạy trong thread riêng qua asyncio.to_thread. Trả phản hồi thô."""
    import resend

    resend.api_key = settings.resend_api_key
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "html": html}
    if attachments:
        payload["attachments"] = attachments
    return resend.Emails.send(payload)


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> str | None:
    """Gửi một email, trả về `resend_email_id` (EMAIL-1 — khoá đối chiếu với webhook bounce/delivered).

    Raise EmailError nếu chưa cấu hình key hoặc Resend lỗi. Trả `None` khi Resend nhận thư nhưng
    KHÔNG trả `id` trong phản hồi — vẫn coi là gửi THÀNH CÔNG (xem log cảnh báo bên dưới), chỉ mất
    khả năng đối soát với webhook; caller (`scheduler._dispatch`) quyết định có ghi vết giao hàng
    hay không dựa vào giá trị này.

    `attachments`: danh sách `(tên tệp, nội dung bytes, content-type)` — SCH-2 dùng để đính `.ics`
    vào thư xác nhận lịch (PRD §12.4 FR-NOTI-1). Resend nhận nội dung dạng **base64**, nên mã hoá ở
    đây; nơi gọi chỉ việc đưa bytes thô.
    """
    if not settings.resend_api_key:
        raise EmailError("RESEND_API_KEY chưa cấu hình — không gửi được email.")
    encoded = [
        {
            "filename": name,
            "content": base64.b64encode(data).decode("ascii"),
            "content_type": content_type,
        }
        for name, data, content_type in (attachments or [])
    ]
    try:
        response = await asyncio.to_thread(_send_sync, to, subject, html, encoded)
    except Exception as exc:  # noqa: BLE001 — gói mọi lỗi Resend/mạng thành EmailError rõ ràng
        raise EmailError(f"Resend gửi email thất bại: {exc}") from exc

    # ID của Resend là KHOÁ ĐỐI CHIẾU duy nhất với webhook (EMAIL-1). Thiếu nó thì lá thư này không
    # theo dõi được nữa — vẫn coi là gửi THÀNH CÔNG (Resend đã nhận), chỉ mất khả năng đối soát;
    # ném ở đây sẽ biến một lá thư đã bay đi thành "gửi hỏng", đúng lớp trạng-thái-nói-dối ngược.
    email_id = (response or {}).get("id") if isinstance(response, dict) else None
    if not email_id:
        logger.warning("email: Resend KHÔNG trả email id (subject=%r) — không theo dõi được bounce", subject)
    logger.info("email: đã gửi tới %s (id=%s)", to, email_id)
    return email_id
