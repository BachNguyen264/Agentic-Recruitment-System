"""Routes agent — run-demo chạy pipeline cả 2 nhánh (scaffold, KHÔNG chạm DB)."""

from __future__ import annotations

from fastapi import APIRouter

from app.agents.runner import run_with_trace
from app.schemas.agent import AgentTraceStep, RunDemoRequest, RunDemoResponse

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
