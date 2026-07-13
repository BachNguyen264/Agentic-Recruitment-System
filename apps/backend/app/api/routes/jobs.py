"""Routes JobPosting (JD) — tạo (kèm embed→Qdrant), đọc, và search-test verify (slice 02a)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import DBSession
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
from app.services import job_service, qdrant_service
from app.services.embedding_service import EmbeddingError, embed_text

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobPostingCreateResult, status_code=status.HTTP_201_CREATED)
async def create_job(payload: JobPostingCreate, session: DBSession) -> JobPostingCreateResult:
    job, warning = await job_service.create_job(session, payload)
    return JobPostingCreateResult(
        job=JobPostingRead.model_validate(job), embedding_warning=warning
    )


@router.get("", response_model=list[JobPostingRead])
async def list_jobs(session: DBSession) -> list[JobPostingRead]:
    rows = await job_service.list_jobs(session)
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
    summary="Đóng/mở JD (OPEN/CLOSED) — KHÔNG xóa (PRD §12.1)",
)
async def update_status(
    job_id: int, payload: JobStatusUpdate, session: DBSession
) -> JobPostingRead:
    job = await job_service.set_job_status(session, job_id, payload.status)
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
