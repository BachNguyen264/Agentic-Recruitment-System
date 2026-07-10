"""Pydantic I/O cho endpoint /agents/parse-cv (công cụ iterate chất lượng Parser)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ParseCVResponse(BaseModel):
    """Kết quả /agents/parse-cv (đồng bộ) — công cụ iterate chất lượng Parser (PRD §7.1)."""

    parsed_data: dict | None = None
    confidence: float
    uncertainty_flags: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
