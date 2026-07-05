"""qdrant_service — collection + upsert/search vector JD (PRD §7.2, §16 embedding_ref).

Một collection dùng chung JD + CV (payload "type" phân biệt — plan 02a; CV embed ở lát 2b).
Point ID = UUID5 xác định từ "jd:{job_id}" — ổn định (upsert idempotent) và không đụng độ
với point CV sau này trong cùng collection.
"""

from __future__ import annotations

import asyncio
import uuid

from qdrant_client import models
from qdrant_client.http.exceptions import UnexpectedResponse

from app.core.config import settings
from app.core.qdrant_client import qdrant_client

_NAMESPACE = uuid.NAMESPACE_URL
# ensure_collection chỉ cần chạy thật một lần mỗi process; lock chặn race 2 request đầu tiên
# cùng check-then-create (create_collection KHÔNG idempotent — Qdrant trả 409).
_collection_ready = False
_ensure_lock = asyncio.Lock()


def jd_point_id(job_id: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"jd:{job_id}"))


async def ensure_collection() -> None:
    """Tạo collection nếu chưa có (size=EMBEDDING_DIM, Cosine) + payload index. Idempotent."""
    global _collection_ready
    if _collection_ready:
        return
    async with _ensure_lock:
        if _collection_ready:  # request khác vừa hoàn thành trong lúc đợi lock
            return
        if not await qdrant_client.collection_exists(settings.qdrant_collection):
            try:
                await qdrant_client.create_collection(
                    collection_name=settings.qdrant_collection,
                    vectors_config=models.VectorParams(
                        size=settings.embedding_dim, distance=models.Distance.COSINE
                    ),
                )
            except UnexpectedResponse as exc:
                # 409 = process/replica khác vừa tạo xong (lock chỉ chặn trong 1 process) — coi là OK.
                if exc.status_code != 409:
                    raise
        # Qdrant Cloud BẮT BUỘC payload index cho field dùng trong filter ("type").
        # Gọi cả khi collection đã tồn tại (idempotent — tạo lại index sẵn có trả OK).
        await qdrant_client.create_payload_index(
            collection_name=settings.qdrant_collection,
            field_name="type",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        _collection_ready = True


async def upsert_jd(job_id: int, vector: list[float], *, title: str) -> str:
    """Upsert vector JD kèm payload {job_id, title, type:"jd"}. Trả point id (embedding_ref)."""
    await ensure_collection()
    point_id = jd_point_id(job_id)
    await qdrant_client.upsert(
        collection_name=settings.qdrant_collection,
        points=[
            models.PointStruct(
                id=point_id,
                vector=vector,
                payload={"job_id": job_id, "title": title, "type": "jd"},
            )
        ],
    )
    return point_id


async def search(
    vector: list[float], *, top_k: int = 5, filter_type: str = "jd"
) -> list[models.ScoredPoint]:
    """Tra cứu tương đồng (Cosine), lọc theo payload type. Trả điểm + score."""
    await ensure_collection()
    result = await qdrant_client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=top_k,
        query_filter=models.Filter(
            must=[models.FieldCondition(key="type", match=models.MatchValue(value=filter_type))]
        ),
        with_payload=True,
    )
    return list(result.points)
