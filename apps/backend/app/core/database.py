"""Async SQLAlchemy engine + session (Neon Postgres).

Neon yêu cầu SSL: bật qua ``connect_args={"ssl": True}`` (xem Settings.db_connect_args).
KHÔNG dùng ``?sslmode=`` trong URL — asyncpg không hiểu (CLAUDE.md).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    """Base khai báo cho mọi ORM model."""


engine = create_async_engine(
    settings.database_url,
    connect_args=settings.db_connect_args,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: cấp một AsyncSession theo request."""
    async with AsyncSessionLocal() as session:
        yield session
