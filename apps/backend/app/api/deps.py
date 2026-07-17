"""Dependencies dùng chung cho API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_session
from app.core.security import decode_token
from app.models.hr_user import HrUser

# Alias gọn cho route handlers: `session: DBSession`.
DBSession = Annotated[AsyncSession, Depends(get_session)]


async def require_hr(request: Request, session: DBSession) -> HrUser:
    """Bảo vệ endpoint HR (slice 09, PRD §4): đọc JWT từ cookie httpOnly → verify → nạp HrUser.

    Thiếu cookie / token sai / hết hạn / user đã bị xóa → 401. Áp lên MỌI router HR
    (jobs/applications/agents). Endpoint CÔNG KHAI (public/*, auth/login...) KHÔNG dùng dependency này.
    """
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chưa đăng nhập.")
    payload = decode_token(token)
    if payload is None or "sub" not in payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên không hợp lệ.")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên không hợp lệ.") from None
    user = await session.get(HrUser, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản không tồn tại.")
    return user


CurrentHr = Annotated[HrUser, Depends(require_hr)]
