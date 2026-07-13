"""job_service — tạo/đọc JD; khi tạo thì embed + upsert Qdrant (PRD §8.1, FR-HR-JD-1).

BẤT BIẾN slice 02a: embedding/Qdrant lỗi KHÔNG làm sập tạo JD — JD vẫn nằm DB,
`embedding_ref=None` (cờ "chưa embed") + trả cảnh báo cho caller.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.job_posting import JobPosting
from app.schemas.job_posting import JobPostingCreate
from app.services import qdrant_service
from app.services.embedding_service import build_jd_text, embed_text

logger = get_logger("app.services.job_service")


async def create_job(
    session: AsyncSession, data: JobPostingCreate
) -> tuple[JobPosting, str | None]:
    """Lưu JD → embed → upsert Qdrant. Trả (row, warning|None). Embed lỗi → JD vẫn tạo."""
    job = JobPosting(
        title=data.title,
        description=data.description,
        requirements="\n".join(data.requirements),  # cột Text — Read tách lại thành list
        rubric=[c.model_dump() for c in data.rubric],
        screener_questions=list(data.screener_questions),
        gate_config=data.gate_config.model_dump(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    warning: str | None = None
    try:
        text = build_jd_text(
            title=data.title, description=data.description, requirements=data.requirements
        )
        vector = await embed_text(text)
        job.embedding_ref = await qdrant_service.upsert_jd(job.id, vector, title=job.title)
        await session.commit()
        await session.refresh(job)
    except Exception as exc:  # noqa: BLE001 — embed/Qdrant lỗi KHÔNG sập tạo JD (plan 02a)
        # Rollback + reset ref in-memory: commit thứ hai fail mà không rollback thì response
        # sẽ mang embedding_ref đã gán (expire_on_commit=False) trong khi DB là NULL.
        await session.rollback()
        job.embedding_ref = None
        logger.warning("Embed/upsert JD id=%s thất bại (JD vẫn lưu DB): %s", job.id, exc)
        warning = f"JD đã lưu nhưng CHƯA embed được (embedding_ref=None): {exc}"
    return job, warning


def jd_dict(job: JobPosting) -> dict:
    """JD dict cho ranker (state.input.jd / rank-cv). requirements cột Text → tách lại list."""
    reqs = [line for line in (job.requirements or "").splitlines() if line.strip()]
    return {
        "job_id": job.id,
        "title": job.title,
        "description": job.description or "",
        "requirements": reqs,
        "rubric": list(job.rubric or []),
        # PRD §9: gate auto-từ-chối cấu hình theo JD — policy đọc SAU ranker (ranker bỏ qua key này).
        "gate_config": dict(job.gate_config or {}),
    }


async def update_job(
    session: AsyncSession, job_id: int, data: JobPostingCreate
) -> tuple[JobPosting | None, str | None]:
    """Sửa JD → cập nhật DB → RE-EMBED CHỈ KHI title/description/requirements đổi (plan §3.1).

    Trả (row, warning|None); None nếu JD không tồn tại. So sánh văn bản embed cũ/mới (build_jd_text
    chuẩn hóa) để quyết re-embed — chỉ rubric/gate/screener đổi thì KHÔNG gọi embedding (tốn API).
    Re-embed lỗi KHÔNG làm sập cập nhật (JD vẫn lưu, vector cũ giữ nguyên + cảnh báo) — pattern 02a.
    """
    job = await session.get(JobPosting, job_id)
    if job is None:
        return None, None

    old_reqs = [line for line in (job.requirements or "").splitlines() if line.strip()]
    old_text = build_jd_text(
        title=job.title, description=job.description or "", requirements=old_reqs
    )
    new_text = build_jd_text(
        title=data.title, description=data.description, requirements=data.requirements
    )

    job.title = data.title
    job.description = data.description
    job.requirements = "\n".join(data.requirements)  # cột Text — Read tách lại thành list
    job.rubric = [c.model_dump() for c in data.rubric]
    job.screener_questions = list(data.screener_questions)
    job.gate_config = data.gate_config.model_dump()
    await session.commit()
    await session.refresh(job)

    if new_text == old_text:
        return job, None  # văn bản embed KHÔNG đổi → bỏ qua re-embed

    warning: str | None = None
    try:
        vector = await embed_text(new_text)
        job.embedding_ref = await qdrant_service.upsert_jd(job.id, vector, title=job.title)
        await session.commit()
        await session.refresh(job)
    except Exception as exc:  # noqa: BLE001 — re-embed lỗi KHÔNG sập cập nhật (JD đã lưu, vector cũ giữ)
        await session.rollback()
        logger.warning("Re-embed JD id=%s thất bại (JD vẫn cập nhật): %s", job.id, exc)
        warning = f"JD đã cập nhật nhưng CHƯA re-embed được: {exc}"
    return job, warning


async def set_job_status(
    session: AsyncSession, job_id: int, status: str
) -> JobPosting | None:
    """Đóng/mở JD = đổi cột status (KHÔNG xóa). None nếu JD không tồn tại."""
    job = await session.get(JobPosting, job_id)
    if job is None:
        return None
    job.status = status
    await session.commit()
    await session.refresh(job)
    return job


async def set_gate_config(
    session: AsyncSession, job_id: int, *,
    auto_reject: bool | None = None, auto_invite: bool | None = None,
) -> JobPosting | None:
    """Bật/tắt gate của JD (PRD §9 FR-GATE-1, cấu hình theo từng JD). None nếu JD không tồn tại.

    Chỉ cập nhật field được truyền (partial) — field None giữ nguyên. Gán lại dict để SQLAlchemy
    nhận thay đổi JSONB (mutate in-place không đánh dấu dirty).
    """
    job = await session.get(JobPosting, job_id)
    if job is None:
        return None
    gate = dict(job.gate_config or {})
    if auto_reject is not None:
        gate["auto_reject"] = auto_reject
    if auto_invite is not None:
        gate["auto_invite"] = auto_invite
    job.gate_config = gate
    await session.commit()
    await session.refresh(job)
    return job


async def get_job(session: AsyncSession, job_id: int) -> JobPosting | None:
    return await session.get(JobPosting, job_id)


async def list_jobs(session: AsyncSession, *, limit: int = 100) -> list[JobPosting]:
    result = await session.execute(
        select(JobPosting).order_by(JobPosting.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
