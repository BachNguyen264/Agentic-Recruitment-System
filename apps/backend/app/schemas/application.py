"""Pydantic I/O cho Application (scaffold: POST tạo, GET đọc)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.services.review import recommendation as _recommendation


class ApplicationCreate(BaseModel):
    """Ứng viên nộp CV: chỉ cần email + JD (PRD §8.2). cv_file_ref = placeholder ở scaffold."""

    job_id: int | None = None
    applicant_email: EmailStr
    cv_file_ref: str | None = None


class ReviewRequest(BaseModel):
    """HR quyết định một ca PENDING_REVIEW (PRD §11 FR-HR-4)."""

    decision: Literal["approve", "reject"]
    note: str | None = None


class PublicSubmitResponse(BaseModel):
    """Xác nhận nộp CV công khai (PRD §8.2). KHÔNG lộ điểm/parsed_data/trạng thái cho ứng viên."""

    application_id: int
    message: str = "Đã nhận hồ sơ. Chúng tôi sẽ liên hệ với bạn qua email."


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

    @computed_field  # gợi ý hiển thị cho ReviewCard (PRD §11) — dẫn xuất, KHÔNG tự quyết.
    @property
    def recommendation(self) -> str:
        return _recommendation(self.score, self.uncertainty_flags)
