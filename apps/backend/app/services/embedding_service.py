"""embedding_service — text → vector (OpenAI, PRD §7.2: JD embedding làm chuẩn đối sánh).

Model + số chiều đọc từ env (EMBEDDING_MODEL/EMBEDDING_DIM — phải khớp nhau).
Lỗi API ném EmbeddingError rõ ràng — caller quyết định (tạo JD KHÔNG được sập vì embed lỗi).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import settings


class EmbeddingError(Exception):
    """Gọi API embedding thất bại (key sai, mạng, quota...)."""


@lru_cache
def _embeddings():
    # Khởi tạo lười + cache: import langchain_openai chỉ khi thật sự cần embed.
    from langchain_openai import OpenAIEmbeddings

    return OpenAIEmbeddings(model=settings.embedding_model, api_key=settings.openai_api_key)


async def embed_text(text: str) -> list[float]:
    """Embed một đoạn text → vector EMBEDDING_DIM chiều."""
    try:
        vector = await _embeddings().aembed_query(text)
    except Exception as exc:  # noqa: BLE001 — gói mọi lỗi provider thành tín hiệu rõ ràng
        raise EmbeddingError(f"Lỗi gọi API embedding ({settings.embedding_model}): {exc}") from exc
    if len(vector) != settings.embedding_dim:
        raise EmbeddingError(
            f"Vector {len(vector)} chiều, kỳ vọng {settings.embedding_dim} — "
            "EMBEDDING_MODEL và EMBEDDING_DIM không khớp nhau."
        )
    return vector


def build_jd_text(*, title: str, description: str, requirements: list[str]) -> str:
    """Ghép JD thành một đoạn text để embed (một vector/JD — không chunk, plan 02a)."""
    parts = [title, description, *requirements]
    return "\n".join(p.strip() for p in parts if p and p.strip())


def build_cv_text(parsed_data: dict) -> str:
    """Ghép nội dung CV để embed (tín hiệu tương đồng CV↔JD — plan 02b, KHÔNG vào điểm)."""
    parts: list[str] = []
    if parsed_data.get("professional_summary"):
        parts.append(str(parsed_data["professional_summary"]))
    skills = parsed_data.get("skills") or []
    if skills:
        parts.append("Kỹ năng: " + ", ".join(str(s) for s in skills))
    for exp in parsed_data.get("experiences") or []:
        seg = " ".join(str(exp.get(k) or "") for k in ("title", "company", "summary")).strip()
        if seg:
            parts.append(seg)
    return "\n".join(p for p in parts if p and p.strip())
