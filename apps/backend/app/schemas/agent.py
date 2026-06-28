"""Pydantic I/O cho demo pipeline (run-demo)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RunDemoRequest(BaseModel):
    # Cờ ép nhánh: True -> ranker tạo ca bất định -> human_review; False -> nhánh tự động.
    force_review: bool = False
    applicant_email: str | None = None


class AgentTraceStep(BaseModel):
    node: str
    status: str | None = None
    confidence: float | None = None
    uncertainty_flags: list[str] = Field(default_factory=list)
    require_human_review: bool = False


class RunDemoResponse(BaseModel):
    branch: str  # "auto" | "human_review"
    final_status: str
    confidence: float | None = None
    require_human_review: bool = False
    escalation_reason: str | None = None
    trace: list[AgentTraceStep] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)


class ParseCVResponse(BaseModel):
    """Kết quả /agents/parse-cv (đồng bộ) — công cụ iterate chất lượng Parser (PRD §7.1)."""

    parsed_data: dict | None = None
    confidence: float
    uncertainty_flags: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
