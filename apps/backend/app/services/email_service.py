"""email_service — gửi email qua Resend (PRD §7.4, §12.4 FR-NOTI-1).

Chỉ scheduler gọi (điểm phát email DUY NHẤT). Resend SDK là SYNC → bọc `asyncio.to_thread`
để KHÔNG chặn event loop (CLAUDE.md async-first). Lỗi (thiếu key / mạng / Resend) → raise
`EmailError` RÕ để caller (scheduler) xử lý; KHÔNG nuốt lỗi im lặng ở tầng này.
"""

from __future__ import annotations

import asyncio
import base64
import random
import time
from uuid import uuid4

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.services.email")

# Điểm TIÊM cho test (cùng triết lý `now` của core/hardening.RateLimiter): thời gian và giấc ngủ đi
# qua hai tên module-level, nên test đo được nhịp mà không phải ngủ thật.
_sleep = asyncio.sleep
_monotonic = time.monotonic

# Điểm TIÊM cho test (cùng khuôn `_sleep`/`_monotonic`): sinh khoá idempotency cho MỖI lượt gửi
# LOGIC. Resend dùng khoá này để khử bản trùng khi cùng một request tới hai lần (xem `_paced_send`).
_new_idempotency_key = lambda: uuid4().hex  # noqa: E731 — điểm tiêm module-level, không phải hàm nghiệp vụ

# Nối tiếp hoá MỌI lượt gọi Resend trong tiến trình. Không có nó thì sweep loop (08c + SCH-3) bắn
# cả cụm thư trong một vòng và tự đâm giới hạn 2 req/s của chính mình — rồi vì lá thư đó không có
# đường thử lại, nó mất luôn. Giữ khoá QUA CẢ vòng retry là CÓ CHỦ Ý: 429 nghĩa là "chậm lại", nên
# để lượt gửi khác chen vào giữa lúc đang lùi là làm hỏng đúng thứ ta đang sửa.
_send_lock = asyncio.Lock()
_last_send_at: float = 0.0

# Mã HTTP mà thử lại chắc chắn vô ích: sai định dạng / sai khoá / không tồn tại.
_PERMANENT_CODES = frozenset({"400", "401", "403", "404", "422"})
# Hai loại 429 KHÁC NHAU về bản chất: bùng nổ (chậm lại là qua) vs cạn hạn mức ngày/tháng (chờ tới
# ngày mai mới qua). Gộp chung là biến "hệ thống câm cả ngày" thành một dòng log lẫn vào lỗi mạng.
_QUOTA_TYPES = frozenset({"daily_quota_exceeded", "monthly_quota_exceeded"})

_MAX_BACKOFF_SECONDS = 8.0


class EmailError(Exception):
    """Gửi email thất bại (thiếu cấu hình / lỗi Resend)."""


class EmailQuotaExhausted(EmailError):
    """Cạn hạn mức Resend (ngày/tháng).

    Tách khỏi `EmailError` vì đây KHÔNG phải sự cố của một lá thư mà của **tài nguyên dùng chung**:
    Resend là kênh duy nhất của cả hệ thống, nên cạn quota nghĩa là thư mời, thư từ chối và
    magic-link sàng lọc của MỌI ứng viên khác cũng câm. Nó phải nhìn ra được ngay trong log.
    """


def _classify(exc: Exception) -> str:
    """-> "retry" | "quota" | "permanent". Mặc định "retry" cho lỗi lạ/lỗi mạng (hỏng-mở)."""
    from resend.exceptions import ResendError

    if isinstance(exc, ResendError):
        if getattr(exc, "error_type", "") in _QUOTA_TYPES:
            return "quota"
        if str(getattr(exc, "code", "")) in _PERMANENT_CODES:
            return "permanent"
        return "retry"  # 429 bùng nổ + 5xx + mã chưa biết
    return "retry"  # timeout / lỗi mạng của tầng requests


def _backoff_seconds(attempt: int) -> float:
    """Luỹ thừa + jitter. Jitter để nhiều tiến trình (nếu sau này chạy nhiều instance) không cùng
    thức dậy một lúc rồi lại cùng đâm vào giới hạn."""
    base = min(_MAX_BACKOFF_SECONDS, 0.5 * (2 ** (attempt - 1)))
    return base * (1.0 + random.random() * 0.25)


def _send_sync(
    to: str, subject: str, html: str, attachments: list[dict] | None, idempotency_key: str
) -> dict | None:
    """Gọi Resend SDK (đồng bộ) — chạy trong thread riêng qua asyncio.to_thread. Trả phản hồi thô.

    `idempotency_key` đi vào header `Idempotency-Key` (resend/request.py) — BẮT BUỘC, không có
    mặc định: gọi hàm này mà quên truyền khoá là lỗi lập trình, phải nổ ngay chứ không âm thầm gửi
    thư không chống-trùng được.
    """
    import resend

    resend.api_key = settings.resend_api_key
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "html": html}
    if attachments:
        payload["attachments"] = attachments
    return resend.Emails.send(payload, options={"idempotency_key": idempotency_key})


async def _paced_send(
    to: str, subject: str, html: str, attachments: list[dict] | None
) -> dict | None:
    """Gọi Resend đúng nhịp + thử lại lỗi tạm thời. Đây là chỗ DUY NHẤT chạm `_send_sync`."""
    global _last_send_at

    # Sinh MỘT khoá cho cả lượt gửi LOGIC — TRƯỚC vòng retry, dùng lại NGUYÊN VẸN qua mọi lần thử.
    # Đây là điều Resend cần để khử được bản trùng: SDK gói MỌI lỗi transport (timeout đọc, mất kết
    # nối — resend/request.py) thành lỗi được `_classify` xếp loại "retry được". Nếu timeout xảy ra
    # SAU KHI Resend đã nhận thư, thử lại mà KHÔNG cùng khoá sẽ tạo ra một lá thư THỨ HAI — ứng viên
    # nhận hai thư mời/từ chối, và mỗi bản trùng còn đốt thêm quota của kênh email DUY NHẤT của cả
    # hệ thống. Sinh khoá TRONG vòng lặp (mỗi lần thử một khoá riêng) sẽ vô hiệu hoá toàn bộ ý nghĩa.
    idempotency_key = _new_idempotency_key()

    async with _send_lock:
        attempt = 0
        while True:
            wait = (settings.email_min_interval_ms / 1000.0) - (_monotonic() - _last_send_at)
            if wait > 0:
                await _sleep(wait)
            try:
                response = await asyncio.to_thread(
                    _send_sync, to, subject, html, attachments, idempotency_key
                )
            except Exception as exc:  # noqa: BLE001 — phân loại rồi mới quyết thử lại hay không
                # Lượt HỎNG vẫn tính là đã chạm Resend: nó vẫn tiêu một lượt của hạn mức 2 req/s.
                _last_send_at = _monotonic()
                kind = _classify(exc)
                if kind == "quota":
                    logger.error(
                        "email: CẠN HẠN MỨC RESEND — mọi thư của MỌI ứng viên sẽ câm cho tới khi "
                        "hạn mức đặt lại. Chi tiết: %s", exc,
                    )
                    raise EmailQuotaExhausted(f"Cạn hạn mức Resend: {exc}") from exc
                if kind == "permanent" or attempt >= settings.email_max_retries:
                    raise EmailError(f"Resend gửi email thất bại: {exc}") from exc
                attempt += 1
                delay = _backoff_seconds(attempt)
                logger.warning(
                    "email: lỗi tạm thời (%s) — thử lại lần %s/%s sau %.2fs",
                    exc, attempt, settings.email_max_retries, delay,
                )
                await _sleep(delay)
                continue
            _last_send_at = _monotonic()
            return response


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
    response = await _paced_send(to, subject, html, encoded)

    # ID của Resend là KHOÁ ĐỐI CHIẾU duy nhất với webhook (EMAIL-1). Thiếu nó thì lá thư này không
    # theo dõi được nữa — vẫn coi là gửi THÀNH CÔNG (Resend đã nhận), chỉ mất khả năng đối soát;
    # ném ở đây sẽ biến một lá thư đã bay đi thành "gửi hỏng", đúng lớp trạng-thái-nói-dối ngược.
    email_id = (response or {}).get("id") if isinstance(response, dict) else None
    if not email_id:
        logger.warning("email: Resend KHÔNG trả email id (subject=%r) — không theo dõi được bounce", subject)
    logger.info("email: đã gửi tới %s (id=%s)", to, email_id)
    return email_id
