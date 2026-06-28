"""Routes agent — run-demo (pipeline 2 nhánh) + parse-cv (Parser đồng bộ, iterate chất lượng)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.agents.nodes.parser import parse_cv
from app.agents.runner import run_with_trace
from app.schemas.agent import AgentTraceStep, ParseCVResponse, RunDemoRequest, RunDemoResponse

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("/run-demo", response_model=RunDemoResponse, summary="Chạy pipeline demo (ép nhánh được)")
async def run_demo(payload: RunDemoRequest) -> RunDemoResponse:
    out = await run_with_trace(
        force_review=payload.force_review, applicant_email=payload.applicant_email
    )
    final = out["final"]
    return RunDemoResponse(
        branch=out["branch"],
        final_status=final.get("status", "UNKNOWN"),
        confidence=final.get("confidence"),
        require_human_review=bool(final.get("require_human_review", False)),
        escalation_reason=final.get("escalation_reason"),
        trace=[AgentTraceStep(**step) for step in out["trace"]],
        messages=final.get("messages", []),
    )


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
