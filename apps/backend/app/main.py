"""FastAPI entrypoint (scaffold).

Khởi tạo app, CORS cho web dashboard (PWA), lifespan đóng kết nối sạch khi tắt.
Nguồn chân lý nghiệp vụ: PRD.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import checkpointer
from app.api.deps import require_hr
from app.api.routes import agents, applications, auth, health, jobs, public
from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger, setup_logging
from app.core.qdrant_client import qdrant_client
from app.core.redis_client import redis_client
from app.services import screening_scheduler

logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(
        "Backend khởi động (env=%s, enable_llm=%s, confidence_threshold=%s)",
        settings.app_env,
        settings.enable_llm,
        settings.confidence_threshold,
    )
    # Checkpointer Postgres (PRD §10): pool + bảng checkpoint Neon, compile graph — MỘT LẦN ở đây.
    await checkpointer.setup_checkpointer()
    # Sweep timeout Screener (08c, PRD §10 FR-SCR-3/4): SAU checkpointer (sweep resume graph cần
    # graph đã compile với saver). Task ở event loop chính. Đổi InProcess↔QStash không đụng nghiệp vụ.
    scheduler = screening_scheduler.get_scheduler()
    await scheduler.start()
    app.state.screening_scheduler = scheduler
    yield
    # Đóng kết nối sạch — dừng sweep TRƯỚC khi đóng checkpointer (sweep dùng graph/pool).
    await scheduler.stop()
    await checkpointer.teardown_checkpointer()
    await redis_client.aclose()
    await qdrant_client.close()
    await engine.dispose()
    logger.info("Backend tắt — đã đóng sweep + Redis/Qdrant/DB.")


app = FastAPI(
    title="Autonomous Recruitment System — Backend",
    version="0.1.0",
    description="Pipeline tuyển dụng đa tác tử (scaffold). Nguồn chân lý: PRD.md.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    # Dev: cho phép localhost/127.0.0.1 mọi cổng (dashboard :3000).
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Slice 09 — Auth HR (PRD §4): require_hr bảo vệ MỌI router HR ở cấp router (áp cho mọi endpoint
# bên trong). CÔNG KHAI giữ MỞ tuyệt đối: health, auth (login/logout), public (JD/nộp CV/screening)
# — ứng viên GUEST không bị chặn. `me` tự bảo vệ trong auth router (dependency ở handler).
_HR_ONLY = [Depends(require_hr)]

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(public.router, prefix="/api")
app.include_router(applications.router, prefix="/api", dependencies=_HR_ONLY)
app.include_router(agents.router, prefix="/api", dependencies=_HR_ONLY)
app.include_router(jobs.router, prefix="/api", dependencies=_HR_ONLY)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "autonomous-recruitment-system",
        "stage": "scaffold",
        "docs": "/docs",
        "health": "/api/health",
    }
