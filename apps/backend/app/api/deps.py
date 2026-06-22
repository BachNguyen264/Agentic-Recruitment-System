"""Dependencies dùng chung cho API routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session

# Alias gọn cho route handlers: `session: DBSession`.
DBSession = Annotated[AsyncSession, Depends(get_session)]
