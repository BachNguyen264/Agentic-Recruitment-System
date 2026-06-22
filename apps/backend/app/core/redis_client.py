"""Redis client (Upstash) — async, dùng cho cache/short-term memory (phase sau).

Scaffold: chỉ tạo client + ping ở /api/health. KHÔNG worker polling Redis (phá free-tier Upstash).
"""

from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings

# Upstash dùng rediss:// (TLS). decode_responses=True để nhận str thay vì bytes.
redis_client: redis.Redis = redis.from_url(settings.redis_url, decode_responses=True)
