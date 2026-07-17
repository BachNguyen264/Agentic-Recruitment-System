"""Crypto cho auth HR (slice 09) — băm mật khẩu bcrypt + ký/verify JWT.

Dùng THƯ VIỆN cho crypto (KHÔNG tự chế):
  - Mật khẩu: `bcrypt` (pyca, có salt tự sinh). KHÔNG lưu plaintext.
  - Token: `pyjwt` HS256, ký bằng `JWT_SECRET` (env, ≥32 ký tự).

Tách khỏi endpoint/DB — thuần hàm, dễ test. PRD §4 (chỉ HR đăng nhập).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt băm tối đa 72 byte đầu của mật khẩu; byte thừa bị BỎ QUA âm thầm → hai mật khẩu khác nhau
# sau byte 72 trùng hash (rủi ro bảo mật). Ta CHẶN thẳng thay vì cắt ngầm (khớp cảnh báo bcrypt 5.0).
_BCRYPT_MAX_BYTES = 72
_JWT_ALGORITHM = "HS256"


class AuthConfigError(RuntimeError):
    """JWT_SECRET thiếu/yếu — cấu hình sai, phải nổ ngay (KHÔNG im lặng dùng khóa yếu)."""


def _jwt_secret() -> str:
    """Lấy JWT_SECRET; BẮT BUỘC có + tối thiểu 32 ký tự (RFC 7518 §3.2 cho HS256)."""
    secret = settings.jwt_secret
    if not secret or len(secret) < 32:
        raise AuthConfigError(
            "JWT_SECRET thiếu hoặc quá ngắn (cần ≥32 ký tự). Sinh: `openssl rand -hex 32`."
        )
    return secret


# ── Mật khẩu (bcrypt) ────────────────────────────────────────────────
def hash_password(password: str) -> str:
    """Băm bcrypt (salt tự sinh) → chuỗi ~60 ký tự để lưu DB."""
    pw = password.encode("utf-8")
    if len(pw) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"Mật khẩu quá dài (>{_BCRYPT_MAX_BYTES} byte).")
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """So khớp mật khẩu với hash bcrypt. False nếu sai HOẶC hash hỏng (không ném ra ngoài)."""
    try:
        pw = password.encode("utf-8")[:_BCRYPT_MAX_BYTES]  # verify: khớp cách bcrypt xử 72 byte.
        return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT (pyjwt HS256) ────────────────────────────────────────────────
def create_access_token(subject: str) -> str:
    """Ký JWT với `sub` = subject (id HR user, dạng str), hạn `JWT_EXPIRY_MINUTES`."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiry_minutes),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    """Verify chữ ký + hạn → payload. Sai chữ ký / hết hạn / hỏng → None (KHÔNG ném)."""
    try:
        return jwt.decode(token, _jwt_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
