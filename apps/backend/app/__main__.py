"""Dev entrypoint: `python -m app` → uvicorn (--reload).

VÌ SAO tồn tại (không chạy uvicorn CLI trực tiếp nữa): checkpointer Screener dùng **psycopg async**
(AsyncPostgresSaver — PRD §10). Trên **Windows**, event loop mặc định của asyncio là ProactorEventLoop,
mà **psycopg async KHÔNG chạy được trên Proactor** (yêu cầu SelectorEventLoop — theo docs psycopg).
Phải set policy TRƯỚC khi uvicorn tạo loop; đặt ở cấp module (ngoài __main__) nên tiến trình worker của
`--reload` (Windows spawn re-import __main__) cũng set được. Linux/production: no-op (đã dùng epoll/Selector).
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # Windows dev only: psycopg async cần SelectorEventLoop (mặc định Proactor không tương thích).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402 — import SAU khi set policy (đúng chủ đích)


def main() -> None:
    # Giữ hành vi cũ của `make dev-backend`: :8000, hot-reload. Truyền import-string để reload hoạt động.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
