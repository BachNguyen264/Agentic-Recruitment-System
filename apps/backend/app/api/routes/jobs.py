"""Routes JobPosting (JD) — tạo (kèm embed→Qdrant), đọc, và search-test verify (slice 02a)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DBSession
from app.core.config import settings
from app.schemas.job_posting import (
    GateConfigUpdate,
    JobPostingCreate,
    JobPostingCreateResult,
    JobPostingRead,
    JobStatusUpdate,
    SearchTestHit,
    SearchTestRequest,
    SearchTestResponse,
)
from app.schemas.rubric_suggest import RubricSuggestResponse, SuggestedCriterion
from app.services import job_service, qdrant_service, rubric_suggester
from app.services.embedding_service import EmbeddingError, embed_text

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobPostingCreateResult, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobPostingCreate, session: DBSession) -> JobPostingCreateResult:
    job, warning = await job_service.create_job(session, payload)
    return JobPostingCreateResult(
        job=JobPostingRead.model_validate(job), embedding_warning=warning
    )


@router.get("", response_model=list[JobPostingRead])
async def list_jobs(session: DBSession, archived: bool = False) -> list[JobPostingRead]:
    """`?archived=false` (mặc định) → JD hoạt động (ẨN đã-lưu-trữ); `?archived=true` → chỉ JD ARCHIVED (JD-4)."""
    rows = await job_service.list_jobs(session, archived=archived)
    return [JobPostingRead.model_validate(r) for r in rows]


@router.get("/{job_id}", response_model=JobPostingRead)
async def get_job(job_id: int, session: DBSession) -> JobPostingRead:
    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingRead.model_validate(job)


@router.put(
    "/{job_id}",
    response_model=JobPostingCreateResult,
    summary="Sửa JD — re-embed CHỈ khi title/description/requirements đổi (PRD §12.1)",
)
async def update_job(
    job_id: int, payload: JobPostingCreate, session: DBSession
) -> JobPostingCreateResult:
    """Cập nhật JD (form tạo+sửa dùng chung). Re-embed có điều kiện; lỗi embed → JD vẫn cập nhật + cảnh báo."""
    job, warning = await job_service.update_job(session, job_id, payload)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingCreateResult(
        job=JobPostingRead.model_validate(job), embedding_warning=warning
    )


@router.patch(
    "/{job_id}/status",
    response_model=JobPostingRead,
    summary="Đổi status JD (OPEN/CLOSED) — MỞ cần rubric (PRD §8.1, §12.1)",
)
async def update_status(
    job_id: int, payload: JobStatusUpdate, session: DBSession
) -> JobPostingRead:
    try:
        job = await job_service.set_job_status(session, job_id, payload.status)
    except job_service.RubricRequiredError as exc:
        # MỞ JD khi chưa có rubric hợp lệ → 400 rõ (PRD §12.1 FR-HR-JD-2).
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingRead.model_validate(job)


@router.post(
    "/{job_id}/archive",
    response_model=JobPostingRead,
    summary="Lưu trữ JD (soft-delete → ARCHIVED; giữ hồ sơ+kiểm toán, PRD §12.1 FR-HR-JD-3)",
)
async def archive_job(job_id: int, session: DBSession) -> JobPostingRead:
    """Ẩn JD khỏi list + /apply, KHÔNG xóa dữ liệu. KHÔNG hard-delete."""
    job = await job_service.archive_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingRead.model_validate(job)


@router.post(
    "/{job_id}/restore",
    response_model=JobPostingRead,
    summary="Khôi phục JD đã lưu trữ (→ CLOSED, không tự OPEN; PRD §12.1 FR-HR-JD-3)",
)
async def restore_job(job_id: int, session: DBSession) -> JobPostingRead:
    job = await job_service.restore_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingRead.model_validate(job)


@router.patch(
    "/{job_id}/gate",
    response_model=JobPostingRead,
    summary="Bật/tắt gate auto (auto_reject/auto_invite) theo JD (PRD §9)",
)
async def update_gate(
    job_id: int, payload: GateConfigUpdate, session: DBSession
) -> JobPostingRead:
    """Cập nhật gate_config của JD (partial). UI đầy đủ ở lát 05; endpoint này để bật/tắt nhanh."""
    job = await job_service.set_gate_config(
        session, job_id, auto_reject=payload.auto_reject, auto_invite=payload.auto_invite
    )
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")
    return JobPostingRead.model_validate(job)


@router.post(
    "/{job_id}/suggest-rubric",
    response_model=RubricSuggestResponse,
    summary="AI gợi ý rubric từ JD (PRD §12.1 FR-HR-RUBRIC-1) — HR duyệt/chỉnh, KHÔNG tự áp",
)
async def suggest_rubric(job_id: int, session: DBSession) -> RubricSuggestResponse:
    """Đọc JD đã lưu (plain-text + cấp bậc) → LLM đề xuất tiêu chí+trọng số. Cap RUBRIC_SUGGEST_MAX_RETRIES
    lần/JD (reset khi nội dung JD đổi). Auth-gated (router HR-only). Đề xuất TRẢ VỀ cho HR chỉnh trước
    khi lưu — endpoint KHÔNG ghi rubric vào JD (trụ cột 4: HR duyệt mới áp).
    """
    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")

    max_retries = settings.rubric_suggest_max_retries
    if (job.rubric_suggestion_count or 0) >= max_retries:
        # Hết lượt → 429 rõ ràng (PRD §12.1: cap 3 lần/JD). Sửa nội dung JD → reset (update_job).
        raise HTTPException(
            status_code=429,
            detail=f"Đã hết lượt AI gợi ý rubric ({max_retries} lần/JD). "
            "Sửa nội dung JD (tiêu đề/mô tả/yêu cầu) rồi lưu để đặt lại lượt gợi ý.",
        )

    try:
        criteria = await rubric_suggester.suggest_rubric(
            title=job.title,
            description=job.description or "",
            requirements=job.requirements or "",
            level=job.level,
        )
    except rubric_suggester.RubricSuggestError as exc:
        # Lỗi LLM → 502 (KHÔNG tiêu lượt: count chỉ tăng SAU khi có đề xuất). HR thử lại được.
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    job = await job_service.bump_rubric_suggestion_count(session, job_id)
    used = job.rubric_suggestion_count if job else max_retries
    return RubricSuggestResponse(
        criteria=[SuggestedCriterion(**c) for c in criteria],
        used=used,
        remaining=max(0, max_retries - used),
        model_used=rubric_suggester.model_label(),
    )


@router.post("/search-test", response_model=SearchTestResponse, summary="Verify tra cứu tương đồng")
async def search_test(payload: SearchTestRequest) -> SearchTestResponse:
    """Embed query → search Qdrant (type='jd') → JD khớp + score. Công cụ verify slice 02a."""
    try:
        vector = await embed_text(payload.query)
    except EmbeddingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    try:
        points = await qdrant_service.search(vector, top_k=payload.top_k)
    except Exception as exc:  # noqa: BLE001 — Qdrant down/timeout → 502 message rõ (không 500 chung)
        raise HTTPException(status_code=502, detail=f"Lỗi truy vấn Qdrant: {exc}") from exc
    hits = [
        SearchTestHit(
            job_id=int(p.payload["job_id"]),
            title=str(p.payload.get("title", "")),
            score=float(p.score),
        )
        for p in points
        if p.payload and "job_id" in p.payload
    ]
    return SearchTestResponse(query=payload.query, hits=hits)
