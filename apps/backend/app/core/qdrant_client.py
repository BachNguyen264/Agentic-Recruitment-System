"""Qdrant client (Qdrant Cloud) — async, dùng cho embedding JD–CV (phase sau).

Scaffold: chỉ tạo client + get_collections() ở /api/health. KHÔNG tạo/đẩy embedding thật.
"""

from __future__ import annotations

from qdrant_client import AsyncQdrantClient

from app.core.config import settings

qdrant_client = AsyncQdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key,
    timeout=20,
)
