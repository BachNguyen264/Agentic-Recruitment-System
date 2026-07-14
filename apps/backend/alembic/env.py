"""Alembic env (async). Đọc URL + connect_args (Neon SSL) từ app.core.config."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models import Base  # noqa: F401 — import để đăng ký toàn bộ model vào metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _include_object(object_, name, type_, reflected, compare_to) -> bool:  # noqa: ANN001
    """Chỉ autogenerate cho bảng THUỘC model app (Base.metadata). Bỏ qua bảng ngoài — nhất là các
    bảng checkpoint của LangGraph (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/
    `checkpoint_migrations`) do AsyncPostgresSaver tự quản (PRD §10). Nếu không, autogenerate sẽ đề
    xuất DROP chúng → mất suspend/resume 08a. Giữ nguyên bảng app không có trong DB (reflected=False)."""
    if type_ == "table" and reflected and name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_object=_include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(
        settings.database_url,
        connect_args=settings.db_connect_args,  # Neon SSL + statement_cache_size=0
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
