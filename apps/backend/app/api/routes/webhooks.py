"""Webhook từ nhà cung cấp email (EMAIL-1 · PRD §7.4, §12.4 FR-NOTI-1).

Đây là chiều NGƯỢC LẠI của tầng email: `Emails.send()` trả OK chỉ nghĩa là Resend đã nhận; bounce
tới vài giây–vài phút sau qua endpoint này. Không có nó thì dashboard nói "Đã hẹn phỏng vấn" trong
khi ứng viên chưa từng nhận được thư nào.

**Endpoint CÔNG KHAI CÓ MUTATION** — router này KHÔNG áp `require_hr` (không có cookie phiên nào để
kiểm, Resend gọi server-to-server). Chốt chặn DUY NHẤT là CHỮ KÝ, ba lớp mỗi lớp vá một đường tấn
công khác nhau:

1. **Verify chữ ký BẮT BUỘC** (Svix, xem `core/webhook_signature`). Sai/thiếu → 401, KHÔNG chạm
   nghiệp vụ. Thiếu nó thì bất kỳ ai cũng POST được một sự kiện "bounced" để đẩy hồ sơ của ứng viên
   thật về hàng chờ HR.
2. **Chưa cấu hình secret → 503**, không phải "cho qua". Một webhook nhận mọi thứ không ký còn tệ
   hơn không có webhook. (Lớp chắn THỨ HAI — `verify_svix_signature` cũng tự từ chối secret rỗng,
   nhưng route kiểm trước để tránh gọi verify với secret không tồn tại và để trả đúng mã 503.)
3. **Miễn trừ rate-limit** — Resend gọi từ vài IP cố định, siết theo IP là gom hết vào một xô rồi
   429 và MẤT sự kiện bounce. Hôm nay `RateLimitMiddleware._bucket()` không khớp `/api/webhooks/*`
   nên đã miễn trừ sẵn; `tests/test_webhook_resend.py` khoá lại để lần sửa `_bucket()` sau không
   âm thầm nuốt mất. Cùng lý do với `OriginCheckMiddleware`: request không có header `Origin`
   (server-to-server) được cho qua — đó là hành vi hiện có, nay có test giữ.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import DBSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.webhook_signature import verify_svix_signature
from app.services import email_delivery

logger = get_logger("app.api.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Điểm tiêm cho test (cùng triết lý `now` của RateLimiter) — cửa sổ replay đo được mà không phải ngủ.
_now = time.time
# Gián tiếp qua một tên module-level để test khẳng định được "chữ ký sai ⇒ nghiệp vụ KHÔNG chạy".
_handle = email_delivery.handle_event


@router.post(
    "/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sự kiện giao hàng từ Resend — verify chữ ký rồi cập nhật trạng thái (EMAIL-1)",
)
async def resend_webhook(request: Request, session: DBSession) -> Response:
    if not settings.resend_webhook_secret:
        logger.error("Webhook Resend: RESEND_WEBHOOK_SECRET chưa cấu hình — từ chối mọi sự kiện.")
        raise HTTPException(status_code=503, detail="Webhook chưa được cấu hình.")

    # BYTES THÔ. Parse JSON rồi serialize lại sẽ đổi khoảng trắng/thứ tự khoá ⇒ chữ ký không bao giờ
    # khớp — lỗi #1 khi tự cài verify webhook.
    body = await request.body()
    headers = request.headers
    # Svix đổi tên header sang chuẩn `webhook-*`; chấp nhận cả hai để không vỡ khi Resend nâng cấp.
    msg_id = headers.get("svix-id") or headers.get("webhook-id") or ""
    timestamp = headers.get("svix-timestamp") or headers.get("webhook-timestamp") or ""
    signature = headers.get("svix-signature") or headers.get("webhook-signature") or ""

    if not verify_svix_signature(
        secret=settings.resend_webhook_secret,
        msg_id=msg_id,
        timestamp=timestamp,
        signature_header=signature,
        body=body,
        now=_now(),
        tolerance_seconds=settings.resend_webhook_tolerance_seconds,
    ):
        # KHÔNG nói rõ sai ở đâu (chữ ký / thời gian) — đó là thông tin miễn phí cho người đang dò.
        logger.warning("Webhook Resend: chữ ký KHÔNG hợp lệ (id=%r) — bỏ qua.", msg_id)
        raise HTTPException(status_code=401, detail="Chữ ký không hợp lệ.")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload không phải JSON hợp lệ.") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Payload không đúng định dạng.")

    await _handle(session, event)
    # 204 kể cả khi không tra được hàng nào: Resend thử lại khi nhận mã lỗi, và thử lại một sự kiện
    # ta cố ý bỏ qua là vô ích cho cả hai bên.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
