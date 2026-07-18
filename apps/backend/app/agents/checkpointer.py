"""Postgres checkpointer (AsyncPostgresSaver) cho Screener suspend/resume — PRD §10, NFR-2.

Lưu state pipeline BỀN xuống Neon (bảng checkpoint riêng, tách bảng app) để dừng ở screener rồi
resume ĐÚNG điểm dừng, sống qua restart backend (khác MemorySaver — mất khi tắt tiến trình).

Kết nối RIÊNG bằng **psycopg** (KHÔNG phải asyncpg của SQLAlchemy) tới endpoint Neon TRỰC TIẾP
(xem settings.checkpointer_conninfo). Pool + saver tạo MỘT LẦN ở lifespan (cùng event loop uvicorn);
`.setup()` idempotent (tạo bảng checkpoint nếu chưa có). Windows dev cần SelectorEventLoop —
đã set ở app/__main__.py (xem CLAUDE.md gotchas).
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.agents.graph import compile_graph
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("app.agents.checkpointer")

# AsyncPostgresSaver yêu cầu connection autocommit; dict_row + prepare_threshold=0 theo docs LangGraph.
_CONN_KWARGS: dict[str, Any] = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,
}

_pool: AsyncConnectionPool | None = None
_saver: AsyncPostgresSaver | None = None
_graph: Any = None  # graph compile với AsyncPostgresSaver (dùng ở prod/background/resume)


def _build_pool() -> AsyncConnectionPool:
    """Dựng pool psycopg BỀN với autosuspend của Neon (KHÔNG mở — caller mở trong event loop).

    Neon (serverless) tự NGỦ sau ~5 phút nhàn rỗi và GIẾT các kết nối đang mở. Pool mặc định không
    biết điều đó → lần dùng kế tiếp mượn phải kết nối chết → `psycopg.errors.AdminShutdown` (cả
    pipeline hỏng). Hai lớp chống (tương đương pre-ping/recycle của SQLAlchemy engine — vốn đã sống
    qua autosuspend):
      - `check=AsyncConnectionPool.check_connection`: PING nhẹ (`execute("")`) mỗi lần MƯỢN; kết nối
        chết bị loại + thay bằng kết nối mới (đánh thức Neon ~1s) thay vì ném lỗi lên nghiệp vụ.
      - `max_idle` < ngưỡng autosuspend Neon: pool tự đóng kết nối nhàn rỗi TRƯỚC khi Neon giết,
        nên hiếm khi còn kết nối chết để mà loại.
    """
    return AsyncConnectionPool(
        conninfo=settings.checkpointer_conninfo,
        max_size=settings.checkpointer_pool_max_size,
        max_idle=settings.checkpointer_pool_max_idle_seconds,
        check=AsyncConnectionPool.check_connection,
        kwargs=_CONN_KWARGS,
        open=False,  # async: mở tường minh trong loop hiện tại (KHÔNG mở ở __init__)
    )


async def setup_checkpointer() -> None:
    """Lifespan startup: mở pool Neon (direct) + `.setup()` (idempotent) + compile graph với saver.

    Fail-fast: lỗi ở đây (Neon down / loop sai) NÉM ra ngoài → app KHÔNG boot câm với suspend
    không bền. Chạy trong event loop uvicorn (Windows: SelectorEventLoop từ app/__main__.py).
    """
    global _pool, _saver, _graph
    if _graph is not None:
        return
    _pool = _build_pool()
    await _pool.open(wait=True, timeout=15)
    _saver = AsyncPostgresSaver(_pool)
    await _saver.setup()  # tạo bảng checkpoint trong Neon — idempotent, an toàn chạy lại mỗi lần boot
    _graph = compile_graph(_saver)
    logger.info(
        "Checkpointer Postgres sẵn sàng (pool max=%s; bảng checkpoint đã ensure).",
        settings.checkpointer_pool_max_size,
    )


async def teardown_checkpointer() -> None:
    """Lifespan shutdown: đóng pool sạch."""
    global _pool, _saver, _graph
    if _pool is not None:
        await _pool.close()
        logger.info("Checkpointer Postgres: đã đóng pool.")
    _pool = _saver = _graph = None


def get_graph() -> Any:
    """Graph đang hoạt động. Prod: bản compile với AsyncPostgresSaver (đã setup ở lifespan).
    Fallback: singleton MemorySaver (test/an toàn khi checkpointer chưa lên) — suspend KHÔNG bền."""
    if _graph is not None:
        return _graph
    # setup_checkpointer là fail-fast ở lifespan nên nhánh này KHÔNG xảy ra ở tiến trình boot đúng.
    # Nếu tới đây (vd checkpointer bị bỏ qua tương lai) → suspend KHÔNG bền qua restart: cảnh báo rõ.
    from app.agents.graph import recruitment_graph

    logger.warning(
        "get_graph(): checkpointer Postgres CHƯA setup → dùng MemorySaver (suspend KHÔNG bền qua restart)."
    )
    return recruitment_graph
