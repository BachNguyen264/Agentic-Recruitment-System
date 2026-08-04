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


def _send_sync(to: str, subject: str, html: str, attachments: list[dict] | None) -> None:
    """Gọi Resend SDK (đồng bộ) — chạy trong thread riêng qua asyncio.to_thread."""
    import resend

    resend.api_key = settings.resend_api_key
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "html": html}
    if attachments:
        payload["attachments"] = attachments
    resend.Emails.send(payload)


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> None:
    """Gửi một email. Raise EmailError nếu chưa cấu hình key hoặc Resend lỗi.

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
        await asyncio.to_thread(_send_sync, to, subject, html, encoded)
    except Exception as exc:  # noqa: BLE001 — gói mọi lỗi Resend/mạng thành EmailError rõ ràng
        raise EmailError(f"Resend gửi email thất bại: {exc}") from exc
    logger.info("email: đã gửi tới %s (subject=%r)", to, subject)
