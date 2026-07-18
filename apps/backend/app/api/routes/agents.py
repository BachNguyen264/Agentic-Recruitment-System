"""Routes agent — parse-cv (Parser đồng bộ) + rank-cv (Ranker đồng bộ, benchmark)."""

from __future__ import annotations

from fastapi import APIRouter, Body, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.agents.nodes.parser import parse_cv
from app.agents.nodes.ranker import rank_cv
from app.api.deps import DBSession
from app.core.config import settings
from app.models.application import Application, ApplicationStatus
from app.schemas.agent import ParseCVResponse
from app.schemas.rank import RankCvRequest, RankCvResponse
from app.services import job_service
from app.tasks import background
from app.tools import cv_storage

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post(
    "/resume-screener/{application_id}",
    summary="[DEV] Resume screener bằng payload mock — gated ENABLE_DEV_ENDPOINTS (PRD §10)",
)
async def resume_screener_endpoint(
    application_id: int,
    session: DBSession,
    payload: dict | None = Body(default=None),
) -> dict:
    """Endpoint DEV (08a): resume thủ công bằng payload mock. Đường THẬT của Screener là magic-link
    form (08b: `POST /api/public/screening/{token}`, có token + row-lock). Endpoint này BỎ QUA
    token/one-time nên chỉ để test nội bộ → GATE sau `ENABLE_DEV_ENDPOINTS` (mặc định TẮT → 404).

    Chỉ resume ca đang `AWAITING_SCREENER` (else 409). KHÔNG chạy lại parser/ranker."""
    if not settings.enable_dev_endpoints:
        raise HTTPException(status_code=404, detail="Not found")
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    if app_row.status != ApplicationStatus.AWAITING_SCREENER.value:
        raise HTTPException(
            status_code=409,
            detail=f"Application {application_id} không ở AWAITING_SCREENER (hiện: {app_row.status}).",
        )
    return await background.resume_screener(
        session, application_id, payload or {"awaiting": "screener_answers", "mock": True}
    )


@router.post("/parse-cv", response_model=ParseCVResponse, summary="Parse CV đồng bộ (iterate chất lượng)")
async def parse_cv_endpoint(file: UploadFile = File(...)) -> ParseCVResponse:
    """Chạy NGAY logic Parser trên file upload (KHÔNG qua DB/queue). Công cụ chính để soi chất
    lượng trích xuất + tinh chỉnh prompt. LUÔN parse thật (không phụ thuộc ENABLE_LLM).

    Slice 06: parse THẲNG TỪ BYTES — KHÔNG còn ghi file tạm ra đĩa (CV là dữ liệu cá nhân, NFR-4:
    không rải bản sao ngoài kho lưu trữ). File này KHÔNG được lưu (công cụ soi tức thời)."""
    content = await file.read()
    # Trước đây đường này KHÔNG kiểm gì (chỉ lấy đuôi cho file tạm) — dùng chung validate_cv.
    try:
        cv_storage.validate_cv(file.filename or "", content)
    except cv_storage.InvalidCV as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    # parse_cv là sync (đọc bytes + gọi LLM sync) -> offload khỏi event loop.
    result = await run_in_threadpool(parse_cv, content, file.filename or "")
    return ParseCVResponse(**result)


@router.post("/rank-cv", response_model=RankCvResponse, summary="Chấm CV theo rubric JD (đồng bộ)")
async def rank_cv_endpoint(payload: RankCvRequest, session: DBSession) -> RankCvResponse:
    """Chạy NGAY Ranker: parsed CV + JD(rubric) → điểm/breakdown/similarity/flags + `model_used`.

    Truyền `application_id` (lấy parsed_data + job_id từ DB) HOẶC (`parsed_data` + `job_id`).
    Công cụ chính để tinh chỉnh + BENCHMARK model (plan §6). LUÔN chấm thật (không phụ thuộc ENABLE_LLM)."""
    if payload.application_id is not None:
        app_row = await session.get(Application, payload.application_id)
        if app_row is None:
            raise HTTPException(status_code=404, detail="Application không tồn tại")
        parsed_data = app_row.parsed_data
        job_id = app_row.job_id
    else:
        parsed_data = payload.parsed_data
        job_id = payload.job_id

    if not parsed_data:
        raise HTTPException(status_code=400, detail="Thiếu parsed_data (hoặc application chưa parse).")
    if job_id is None:
        raise HTTPException(status_code=400, detail="Thiếu job_id.")

    job = await job_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="JobPosting không tồn tại")

    result = await rank_cv(parsed_data, job_service.jd_dict(job))
    return RankCvResponse(
        score=result["score"],
        score_breakdown=result["score_breakdown"] or [],
        summary=result["summary"],
        semantic_similarity=result["semantic_similarity"],
        confidence=result["confidence"],
        uncertainty_flags=result["uncertainty_flags"],
        escalation_reason=result["escalation_reason"],
        model_used=result["model_used"],
    )
