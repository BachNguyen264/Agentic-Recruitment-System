"""Pydantic I/O cho JobPosting (JD) — PRD §16, §9 (gate_config), §7.2 (chuẩn đối sánh Ranker).

DB giữ nguyên schema scaffold (không migration): cột `requirements` là Text nên API nhận
list[str] và join "\n" khi lưu; Read chuẩn hóa ngược lại. Cột JSONB nhận cả dict legacy
(row demo scaffold có rubric={}) — validator mềm quy về list rỗng.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RubricCriterion(BaseModel):
    criterion: str = Field(min_length=1, description="Tên tiêu chí, vd 'Kinh nghiệm Node.js'.")
    weight: float = Field(ge=0, le=1, description="Trọng số 0..1 (tổng NÊN ~1 — không ép cứng).")


class GateConfig(BaseModel):
    # PRD §9 FR-GATE-3: mặc định cả hai gate TẮT (an toàn nhất).
    auto_reject: bool = False
    auto_invite: bool = False


class GateConfigUpdate(BaseModel):
    """Body PATCH /jobs/{id}/gate — cập nhật partial (field None giữ nguyên). PRD §9 FR-GATE-1."""

    auto_reject: bool | None = None
    auto_invite: bool | None = None


class JobStatusUpdate(BaseModel):
    """Body PATCH /jobs/{id}/status — đóng/mở JD (KHÔNG xóa). PRD §12.1 FR-HR-JD-1."""

    status: Literal["OPEN", "CLOSED"]


class JobPostingCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)
    requirements: list[str] = Field(default_factory=list, description="Các yêu cầu chính.")

    @field_validator("requirements")
    @classmethod
    def _normalize_requirement_items(cls, v: list[str]) -> list[str]:
        # Cột DB là Text join "\n": item chứa newline sẽ bị tách đôi khi đọc lại —
        # chuẩn hóa mọi whitespace nội bộ thành 1 space, bỏ item rỗng.
        return [" ".join(item.split()) for item in v if item.strip()]
    rubric: list[RubricCriterion] = Field(default_factory=list)
    screener_questions: list[str] = Field(
        default_factory=list, description="Bộ câu hỏi cố định cho Screener (PRD §10 FR-SCR-6)."
    )
    gate_config: GateConfig = Field(default_factory=GateConfig)


class JobPostingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    requirements: list[str] = Field(default_factory=list)
    rubric: list[RubricCriterion] = Field(default_factory=list)
    screener_questions: list[str] = Field(default_factory=list)
    gate_config: GateConfig = Field(default_factory=GateConfig)
    status: str
    embedding_ref: str | None = None  # null = chưa embed (embedding lỗi / JD legacy)
    created_at: datetime
    updated_at: datetime

    @field_validator("requirements", mode="before")
    @classmethod
    def _split_requirements(cls, v: object) -> object:
        # Cột DB là Text (join "\n"); legacy có thể None.
        if v is None:
            return []
        if isinstance(v, str):
            return [line for line in v.splitlines() if line.strip()]
        return v

    @field_validator("rubric", mode="before")
    @classmethod
    def _normalize_rubric(cls, v: object) -> object:
        # Row scaffold cũ lưu rubric={} (dict) — quy về list rỗng.
        if isinstance(v, dict):
            return list(v.get("criteria", [])) if "criteria" in v else []
        return v


class JobPostingCreateResult(BaseModel):
    """POST /api/jobs: JD đã lưu + cảnh báo nếu embedding lỗi (JD vẫn tạo được)."""

    job: JobPostingRead
    embedding_warning: str | None = None


class SearchTestRequest(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class SearchTestHit(BaseModel):
    job_id: int
    title: str
    score: float


class SearchTestResponse(BaseModel):
    query: str
    hits: list[SearchTestHit]
