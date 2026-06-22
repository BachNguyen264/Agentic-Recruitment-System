"""FastAPI entrypoint (scaffold).

Khởi tạo app, CORS cho dashboard/mobile, lifespan đóng kết nối sạch khi tắt.
Nguồn chân lý nghiệp vụ: PRD.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import agents, applications, health
from app.core.config import settings
from app.core.database import engine
from app.core.logging import get_logger, setup_logging
from app.core.qdrant_client import qdrant_client
from app.core.redis_client import redis_client

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
    yield
    # Đóng kết nối sạch.
    await redis_client.aclose()
    await qdrant_client.close()
    await engine.dispose()
    logger.info("Backend tắt — đã đóng kết nối Redis/Qdrant/DB.")


app = FastAPI(
    title="Autonomous Recruitment System — Backend",
    version="0.1.0",
    description="Pipeline tuyển dụng đa tác tử (scaffold). Nguồn chân lý: PRD.md.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # Next.js dashboard
        "http://localhost:19006",  # Expo web
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(applications.router, prefix="/api")
app.include_router(agents.router, prefix="/api")


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "autonomous-recruitment-system",
        "stage": "scaffold",
        "docs": "/docs",
        "health": "/api/health",
    }
