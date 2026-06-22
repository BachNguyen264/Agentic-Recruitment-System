"""Pydantic I/O cho Application (scaffold: POST tạo, GET đọc)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class ApplicationCreate(BaseModel):
    """Ứng viên nộp CV: chỉ cần email + JD (PRD §8.2). cv_file_ref = placeholder ở scaffold."""

    job_id: int | None = None
    applicant_email: EmailStr
    cv_file_ref: str | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None
    applicant_email: str
    cv_file_ref: str | None
    parsed_data: dict
    score: float | None
    score_breakdown: dict
    status: str
    # 4 trụ cột (PRD §5)
    confidence: float | None
    uncertainty_flags: list = Field(default_factory=list)
    escalation_reason: str | None
    # Screener async (PRD §10)
    screener_sent_at: datetime | None
    screener_deadline: datetime | None
    created_at: datetime
    updated_at: datetime
