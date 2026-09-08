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

__all__ = ["verify_svix_signature"]

_PREFIX = "whsec_"
_VERSION = "v1"


def _key(secret: str) -> bytes | None:
    """`whsec_<base64>` → bytes khoá. Secret hỏng/RỖNG → None (gọi là từ chối, không nổ).

    CHỐT AN NINH: `base64.b64decode("", validate=True)` trả `b''` **HỢP LỆ**, không ném lỗi — nếu
    không chặn `raw` rỗng ở đây, secret rỗng (hoặc đúng chuỗi `"whsec_"` thiếu phần thân — ví dụ
    biến môi trường `RESEND_WEBHOOK_SECRET` chưa set trên Render) sẽ cho ra khoá HMAC RỖNG mà kẻ
    tấn công cũng biết trước, và xác thực vẫn "chạy" bình thường (không phải đường tắt `return True`,
    mà là chạy đúng thuật toán với một khoá công khai) — webhook mở toang trong khi log vẫn báo "đã
    verify". Cùng nguyên tắc `_jwt_secret` trong `core/security.py`: thiếu secret phải bị từ chối,
    KHÔNG âm thầm dùng khoá yếu (khác ở chỗ hàm này KHÔNG được `raise` — verify là hàm biên nhận
    HTTP công khai, exception ở đây sẽ thành 500 thay vì 401).
    """
    raw = secret[len(_PREFIX):] if secret.startswith(_PREFIX) else secret
    if not raw:
        return None
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        return None


def _digest(key: bytes, msg_id: str, timestamp: str, body: bytes) -> str:
    signed = b".".join([msg_id.encode("utf-8"), timestamp.encode("utf-8"), body])
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


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

    Đầu vào tới thẳng từ HTTP header do BÊN NGOÀI kiểm soát hoàn toàn (task sau đọc bằng
    `request.headers.get(...)`, thiếu header ⇒ `None`; header có thể chứa ký tự non-ASCII hoặc một
    chuỗi số khổng lồ) — MỌI kiểu dữ liệu bất ngờ phải hoá thành `False`, không được để
    `AttributeError`/`TypeError`/`OverflowError` thoát ra ngoài thành 500 (mất chặn xác thực, lộ
    stack trace).
    """
    if not isinstance(msg_id, str) or not isinstance(timestamp, str):
        return False
    if not isinstance(body, (bytes, bytearray)):
        return False
    if not isinstance(signature_header, str) or not signature_header:
        return False

    key = _key(secret) if isinstance(secret, str) else None
    if key is None:
        return False

    try:
        sent_at = int(timestamp)
        if abs(now - sent_at) > tolerance_seconds:
            return False
    except (TypeError, ValueError, OverflowError):
        # ValueError: timestamp không phải số (hoặc vượt giới hạn chuyển đổi int() của Python).
        # OverflowError: timestamp là số HỢP LỆ nhưng quá lớn để trừ với `now` (float) — attacker
        # điều khiển hoàn toàn header này, không chặn thì thành DoS/ồn log rẻ tiền (500 mỗi request).
        return False

    expected = _digest(key, msg_id, timestamp, body)
    expected_bytes = expected.encode("ascii")  # tự sinh, luôn ASCII (base64) — encode không bao giờ nổ
    for part in signature_header.split(" "):
        version, _, candidate = part.partition(",")
        if version != _VERSION or not candidate:
            continue
        try:
            # `hmac.compare_digest` trên KIỂU STR bắt buộc ASCII-only, còn trên bytes thì không —
            # Starlette decode header theo latin-1 nên `svix-signature: v1,café` tới được đây; nếu
            # so sánh thẳng bằng str sẽ ném TypeError (thoát ra ngoài thành 500 thay vì 401).
            candidate_bytes = candidate.encode("utf-8")
        except UnicodeEncodeError:
            continue
        if hmac.compare_digest(candidate_bytes, expected_bytes):
            return True
    return False
