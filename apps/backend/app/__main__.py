"""Entrypoint: `python -m app` → uvicorn. Dùng CHUNG cho dev (reload) và prod (Render).

VÌ SAO tồn tại (không chạy uvicorn CLI trực tiếp): checkpointer Screener dùng **psycopg async**
(AsyncPostgresSaver — PRD §10). Trên **Windows**, event loop mặc định của asyncio là ProactorEventLoop,
mà **psycopg async KHÔNG chạy được trên Proactor** (yêu cầu SelectorEventLoop — theo docs psycopg).
Phải set policy TRƯỚC khi uvicorn tạo loop; đặt ở cấp module (ngoài __main__) nên tiến trình worker của
`--reload` (Windows spawn re-import __main__) cũng set được. **Linux/Render: no-op** (đã dùng
epoll/SelectorEventLoop mặc định) — nhánh này bị bỏ qua hoàn toàn, uvicorn khởi động bình thường.

Slice 13 (deploy): host/port đọc từ env — Render cấp `$PORT` và yêu cầu bind `0.0.0.0`. Backend là
TIẾN TRÌNH BỀN (một process, không serverless): sweep timeout 08c, pool checkpointer 08a và
BackgroundTasks đều sống trong process này.
"""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    # Windows dev only: psycopg async cần SelectorEventLoop (mặc định Proactor không tương thích).
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402 — import SAU khi set policy (đúng chủ đích)

from app.core.config import Settings, settings  # noqa: E402


def uvicorn_options(cfg: Settings) -> dict[str, object]:
    """Tham số uvicorn theo môi trường. Tách hàm để test được (không thật sự chạy server).

    reload CHỈ ở local: nó dựng watcher + tiến trình con, gấp đôi bộ nhớ và làm sweep/checkpointer
    khởi động hai lần — không bao giờ dùng trên Render.
    """
    return {
        "host": cfg.host,
        "port": cfg.port,
        "reload": cfg.app_env == "local",
    }


def main() -> None:
    # Truyền import-string (không phải object app) để reload hoạt động ở dev.
    uvicorn.run("app.main:app", **uvicorn_options(settings))


if __name__ == "__main__":
    main()
