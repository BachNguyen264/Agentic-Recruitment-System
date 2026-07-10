"""Routes agent — parse-cv (Parser đồng bộ) + rank-cv (Ranker đồng bộ, benchmark)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.agents.nodes.parser import parse_cv
from app.agents.nodes.ranker import rank_cv
from app.api.deps import DBSession
from app.models.application import Application
from app.schemas.agent import ParseCVResponse
from app.schemas.rank import RankCvRequest, RankCvResponse
from app.services import job_service

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/parse-cv", response_model=ParseCVResponse, summary="Parse CV đồng bộ (iterate chất lượng)")
async def parse_cv_endpoint(file: UploadFile = File(...)) -> ParseCVResponse:
    """Chạy NGAY logic Parser trên file upload (KHÔNG qua DB/queue). Công cụ chính để soi chất
    lượng trích xuất + tinh chỉnh prompt. LUÔN parse thật (không phụ thuộc ENABLE_LLM)."""
    content = await file.read()
    suffix = Path(file.filename or "").suffix.lower()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(content)
        tmp.close()
        # parse_cv là sync (đọc file + gọi LLM sync) -> offload khỏi event loop.
        result = await run_in_threadpool(parse_cv, tmp.name)
    finally:
        os.unlink(tmp.name)
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
