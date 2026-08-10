"""Verify chữ ký webhook chuẩn Svix — Resend dùng chuẩn này (EMAIL-1).

Thuần stdlib (`hmac`/`hashlib`/`base64`), KHÔNG thêm dependency — cùng nếp `IcsProvider` (SCH-1) và
`html_text` (JD-1). Thuật toán đủ nhỏ để đọc hết trong một màn hình, và test tự dựng được chữ ký
hợp lệ nên không phải gọi mạng để kiểm.

    signed_content = f"{svix-id}.{svix-timestamp}.{raw body}"
    expected       = base64( HMAC-SHA256( base64decode(secret sau 'whsec_'), signed_content ) )

Hai chốt chặn, KHÔNG được bỏ cái nào:
  1) So sánh bằng `hmac.compare_digest` — so bằng `==` rò rỉ thời gian, và đây là thứ duy nhất
     ngăn người lạ giả sự kiện bounce để phá hồ sơ ứng viên thật.
  2) Cửa sổ thời gian theo `svix-timestamp` — chữ ký ĐÚNG mà không có hạn thì một request hợp lệ bị
     chặn lại sẽ phát lại được mãi mãi.

**Body phải là BYTES THÔ.** Parse JSON rồi serialize lại sẽ đổi khoảng trắng/thứ tự khoá và chữ ký
không bao giờ khớp — đây là lỗi #1 khi tự cài verify webhook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

__all__ = ["sign_svix_payload", "verify_svix_signature"]

_PREFIX = "whsec_"
_VERSION = "v1"


def _key(secret: str) -> bytes | None:
    """`whsec_<base64>` → bytes khoá. Secret hỏng → None (gọi là từ chối, không nổ)."""
    raw = secret[len(_PREFIX):] if secret.startswith(_PREFIX) else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        return None


def _digest(key: bytes, msg_id: str, timestamp: str, body: bytes) -> str:
    signed = b".".join([msg_id.encode("utf-8"), timestamp.encode("utf-8"), body])
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


def sign_svix_payload(*, secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    """Dựng header `svix-signature` hợp lệ. Dùng cho TEST và để đặc tả thuật toán bằng code chạy được."""
    key = _key(secret)
    if key is None:
        raise ValueError("Secret webhook không hợp lệ (phải là whsec_<base64>).")
    return f"{_VERSION},{_digest(key, msg_id, timestamp, body)}"


def verify_svix_signature(
    *,
    secret: str,
    msg_id: str,
    timestamp: str,
    signature_header: str,
    body: bytes,
    now: float,
    tolerance_seconds: float,
) -> bool:
    """True chỉ khi chữ ký khớp VÀ mốc thời gian nằm trong cửa sổ. Mọi ca bất thường → False.

    `now` được TIÊM VÀO (không gọi `time` bên trong) để test đo được cửa sổ replay mà không phải
    ngủ — cùng triết lý `RateLimiter.allow(..., now)` của `core/hardening`.
    """
    key = _key(secret)
    if key is None or not signature_header:
        return False

    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now - sent_at) > tolerance_seconds:
        return False

    expected = _digest(key, msg_id, timestamp, body)
    for part in signature_header.split(" "):
        version, _, candidate = part.partition(",")
        if version != _VERSION or not candidate:
            continue
        if hmac.compare_digest(candidate, expected):
            return True
    return False
