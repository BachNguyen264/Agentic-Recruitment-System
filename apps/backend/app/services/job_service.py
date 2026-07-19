"""job_service — tạo/đọc JD; khi tạo thì embed + upsert Qdrant (PRD §8.1, FR-HR-JD-1).

BẤT BIẾN slice 02a: embedding/Qdrant lỗi KHÔNG làm sập tạo JD — JD vẫn nằm DB,
`embedding_ref=None` (cờ "chưa embed") + trả cảnh báo cho caller.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.html_text import html_to_lines, html_to_text
from app.core.logging import get_logger
from app.models.job_posting import JobPosting
from app.schemas.job_posting import JobPostingCreate
from app.services import qdrant_service
from app.services.embedding_service import build_jd_text, embed_text

logger = get_logger("app.services.job_service")


class RubricRequiredError(Exception):
    """JD chưa có rubric hợp lệ → KHÔNG mở được (PRD §8.1, §12.1 FR-HR-JD-2). Route → 400."""


def is_valid_rubric(rubric: list | None) -> bool:
    """Rubric đủ để MỞ JD (PRD §8.1: "MỞ JD yêu cầu JD đã có rubric → ranker luôn có tiêu chí"):
    ≥1 tiêu chí + tổng trọng số > 0 (ranker cần trọng số dương để chuẩn hóa điểm — `_weighted_overall`
    trả None khi tổng ≤ 0). KHÔNG ép tổng ≈ 1 (validate mềm của 05 chỉ là gợi ý UI; ranker tự chuẩn hóa)."""
    items = [c for c in (rubric or []) if isinstance(c, dict)]
    if not items:
        return False
    return sum(float(c.get("weight", 0) or 0) for c in items) > 0


async def create_job(
    session: AsyncSession, data: JobPostingCreate
) -> tuple[JobPosting, str | None]:
    """Lưu JD → embed → upsert Qdrant. Trả (row, warning|None). Embed lỗi → JD vẫn tạo."""
    job = JobPosting(
        status="DRAFT",  # JD-2a: JD mới = nháp; MỞ (→OPEN) cần rubric (set_job_status kiểm)
        title=data.title,
        description=data.description,   # HTML định dạng — lưu thẳng; bóc HTML chỉ khi embed/LLM
        requirements=data.requirements,  # HTML định dạng (JD-1: không còn list "\n".join)
        level=data.level,
        salary=data.salary.model_dump(),
        benefits=data.benefits,
        employment_type=data.employment_type,
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
    """JD dict cho ranker (state.input.jd / rank-cv). BÓC HTML → plain-text: mô tả/yêu cầu là văn bản
    định dạng (JD-1) — tag KHÔNG được lọt vào prompt LLM (nhiễu điểm). requirements → list dòng (bullet)."""
    return {
        "job_id": job.id,
        "title": job.title,
        "description": html_to_text(job.description or ""),
        "requirements": html_to_lines(job.requirements or ""),
        "rubric": list(job.rubric or []),
        # PRD §9: gate auto-từ-chối cấu hình theo JD — policy đọc SAU ranker (ranker bỏ qua key này).
        "gate_config": dict(job.gate_config or {}),
        # JD-2b (PRD §7.3 FR-SCR-0): screener CHỈ chạy khi JD có câu hỏi. Đưa vào SNAPSHOT (config-as-of-
        # entry, như gate_config) để screener_node quyết interrupt/bỏ-qua từ state, KHÔNG đọc DB trong node.
        "screener_questions": list(job.screener_questions or []),
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

    old_text = build_jd_text(
        title=job.title, description=job.description or "", requirements=job.requirements or ""
    )
    new_text = build_jd_text(
        title=data.title, description=data.description, requirements=data.requirements
    )

    job.title = data.title
    job.description = data.description       # HTML định dạng — lưu thẳng
    job.requirements = data.requirements     # HTML định dạng (JD-1)
    job.level = data.level
    job.salary = data.salary.model_dump()
    job.benefits = data.benefits
    job.employment_type = data.employment_type
    job.rubric = [c.model_dump() for c in data.rubric]
    job.screener_questions = list(data.screener_questions)
    job.gate_config = data.gate_config.model_dump()
    await session.commit()
    await session.refresh(job)

    if new_text == old_text:
        logger.info("update JD id=%s: văn bản embed KHÔNG đổi → BỎ QUA re-embed", job.id)
        return job, None  # chỉ rubric/gate/screener đổi → không tốn API embedding

    warning: str | None = None
    try:
        logger.info("update JD id=%s: title/description/requirements đổi → re-embed", job.id)
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
    """Đổi status JD (DRAFT→OPEN / OPEN↔CLOSED — KHÔNG xóa). None nếu JD không tồn tại.

    MỞ (→OPEN) CHẶN nếu chưa có rubric hợp lệ (PRD §8.1, §12.1 FR-HR-JD-2) → RubricRequiredError
    (route trả 400). Đóng/tạm dừng (→CLOSED) luôn cho phép.
    """
    job = await session.get(JobPosting, job_id)
    if job is None:
        return None
    if status == "OPEN" and not is_valid_rubric(job.rubric):
        raise RubricRequiredError(
            "JD cần có rubric (≥1 tiêu chí, tổng trọng số > 0) mới mở được — "
            "hãy cấu hình rubric ở màn 'Cấu hình sàng lọc' trước."
        )
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


async def list_open_jobs(session: AsyncSession, *, limit: int = 100) -> list[JobPosting]:
    """JD đang MỞ cho trang công khai (PRD §8.2, FR-AP-1). Chỉ status=OPEN."""
    result = await session.execute(
        select(JobPosting)
        .where(JobPosting.status == "OPEN")
        .order_by(JobPosting.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_open_job(session: AsyncSession, job_id: int) -> JobPosting | None:
    """JD công khai theo id — CHỈ khi OPEN (chống nộp vào JD đã đóng). None nếu không OPEN/không có."""
    job = await session.get(JobPosting, job_id)
    return job if (job is not None and job.status == "OPEN") else None
