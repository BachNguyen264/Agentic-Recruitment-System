"""Health endpoint — ping THẬT cả 3 dịch vụ managed (Postgres · Redis · Qdrant)."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.database import engine
from app.core.qdrant_client import qdrant_client
from app.core.redis_client import redis_client

router = APIRouter(tags=["health"])


async def _check_postgres() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — báo cáo trạng thái, không raise
        return f"error: {type(exc).__name__}"


async def _check_redis() -> str:
    try:
        return "ok" if await redis_client.ping() else "error: no pong"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


async def _check_qdrant() -> str:
    try:
        await qdrant_client.get_collections()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


@router.get("/health", summary="Liveness + ping 3 dịch vụ")
async def health() -> dict:
    services = {
        "postgres": await _check_postgres(),
        "redis": await _check_redis(),
        "qdrant": await _check_qdrant(),
    }
    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "api": "ok", "services": services}
