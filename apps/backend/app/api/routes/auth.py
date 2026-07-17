"""Routes auth HR (slice 09, PRD §4) — login / logout / me.

CHỈ HR Admin đăng nhập; ứng viên là GUEST (không tài khoản). JWT trong cookie **httpOnly** (JS không
đọc được → chống XSS lấy token). Cookie Secure/SameSite/domain đọc từ ENV để deploy cross-domain
(Vercel + Render) KHÔNG phải sửa code. Lỗi đăng nhập THÔNG BÁO CHUNG (không lộ email có tồn tại).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select

from app.api.deps import CurrentHr, DBSession
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.hr_user import HrUser
from app.schemas.auth import HrUserRead, LoginRequest

router = APIRouter(prefix="/auth", tags=["auth"])

# Hash bcrypt THẬT (tính một lần lúc import) để verify khi email không tồn tại → thời gian phản hồi
# bằng lúc email có thật, không rò rỉ "email nào tồn tại" qua timing. Hash giả (chuỗi không hợp lệ)
# sẽ khiến checkpw ném + trả về ngay → hỏng biện pháp; phải là hash hợp lệ để chạy đủ cost bcrypt.
_DUMMY_HASH = hash_password("timing-attack-guard-not-a-real-password")


def _samesite() -> str:
    """SameSite hợp lệ cho Starlette ('lax'|'strict'|'none'). None BẮT BUỘC kèm Secure (nếu không
    browser hiện đại bỏ cookie) — ép an toàn ở set_cookie qua _cookie_secure()."""
    value = (settings.cookie_samesite or "lax").lower()
    return value if value in {"lax", "strict", "none"} else "lax"


def _cookie_secure() -> bool:
    """Secure theo env; nhưng SameSite=None thì BUỘC Secure=True (bất kể env) — chuẩn browser."""
    return bool(settings.cookie_secure) or _samesite() == "none"


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=settings.jwt_expiry_minutes * 60,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_samesite(),
        domain=settings.cookie_domain or None,
        path="/",
    )


def _clear_auth_cookie(response: Response) -> None:
    # Xóa phải KHỚP attrs lúc set (path/domain/samesite/secure) để browser thật sự bỏ cookie.
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        domain=settings.cookie_domain or None,
        httponly=True,
        secure=_cookie_secure(),
        samesite=_samesite(),
    )


@router.post("/login", response_model=HrUserRead, summary="HR đăng nhập → set cookie JWT httpOnly")
async def login(payload: LoginRequest, response: Response, session: DBSession) -> HrUserRead:
    email = payload.email.strip().lower()
    user = (
        await session.execute(select(HrUser).where(HrUser.email == email))
    ).scalar_one_or_none()
    # THÔNG BÁO CHUNG cho cả "email không tồn tại" lẫn "sai mật khẩu" — không lộ email nào có thật.
    # Vẫn verify khi user=None (dùng hash THẬT _DUMMY_HASH) để thời gian phản hồi không rò rỉ (timing).
    hashed = user.password_hash if user else _DUMMY_HASH
    if user is None or not verify_password(payload.password, hashed):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Email hoặc mật khẩu không đúng."
        )
    _set_auth_cookie(response, create_access_token(str(user.id)))
    return HrUserRead.model_validate(user)


@router.post("/logout", summary="Đăng xuất — xóa cookie")
async def logout(response: Response) -> dict:
    _clear_auth_cookie(response)
    return {"status": "logged_out"}


@router.get("/me", response_model=HrUserRead, summary="HR hiện tại (frontend kiểm đã đăng nhập chưa)")
async def me(current: CurrentHr) -> HrUserRead:
    return HrUserRead.model_validate(current)
