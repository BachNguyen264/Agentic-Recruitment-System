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


@router.get("/health/live", summary="Liveness THUẦN (health check của nền tảng)")
async def liveness() -> dict:
    """Chỉ trả lời "tiến trình còn sống" — KHÔNG chạm Postgres/Redis/Qdrant. Đây là path để trỏ
    Health Check của Render (slice 13).

    VÌ SAO tách khỏi `/health`: Render gửi health check VÀI GIÂY MỘT LẦN, liên tục suốt thời gian
    service chạy. Nếu trỏ vào `/health` (ping cả 3 dịch vụ) thì riêng health check đã ~17k lượt/ngày:
    vượt hạn mức Upstash free (10k lệnh/ngày) và giữ Neon luôn thức (đốt compute-hours) — hệ thống tự
    làm hỏng mình khi KHÔNG có ai dùng. Ngoài ra health check phải hỏi "tiến trình còn sống không";
    một dịch vụ phụ chập chờn KHÔNG phải lý do để Render restart cả backend.
    """
    return {"status": "ok"}


@router.get("/health", summary="Kiểm SÂU — ping 3 dịch vụ (dành cho người/chẩn đoán)")
async def health() -> dict:
    services = {
        "postgres": await _check_postgres(),
        "redis": await _check_redis(),
        "qdrant": await _check_qdrant(),
    }
    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "api": "ok", "services": services}
