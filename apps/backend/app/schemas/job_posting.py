"""Pydantic I/O cho JobPosting (JD) — PRD §16, §8.1, §9 (gate_config), §7.2 (chuẩn đối sánh Ranker).

JD-1: `description`/`requirements`/`benefits` là văn bản ĐỊNH DẠNG (HTML do HR soạn ở editor) — API
nhận/trả THẲNG chuỗi (KHÔNG còn list requirements). Thêm level/salary/employment_type. Cột JSONB nhận
cả dict legacy (row demo scaffold có rubric={}); validator mềm quy về mặc định. Bóc HTML → plain-text
cho embedding/LLM làm ở service (build_jd_text / jd_dict), KHÔNG ở schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

# Tập giá trị cho dropdown (validate ở Create; Read để permissive cho row legacy).
JobLevel = Literal["intern", "fresher", "junior", "mid", "senior", "lead", "manager"]
EmploymentType = Literal["full_time", "part_time", "contract", "internship"]
Currency = Literal["VND", "USD"]


class SalaryInfo(BaseModel):
    """Lương JD (PRD §16). `negotiable` = "Thỏa thuận" → min/max bỏ qua (có thể None)."""

    min: int | None = Field(default=None, ge=0)
    max: int | None = Field(default=None, ge=0)
    currency: Currency = "VND"
    negotiable: bool = False

    @model_validator(mode="after")
    def _check_range(self) -> SalaryInfo:
        # Thỏa thuận → không ràng buộc min/max. Ngược lại min ≤ max (khi có cả hai).
        if not self.negotiable and self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("Lương tối thiểu không được lớn hơn tối đa.")
        return self


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
    description: str = Field(min_length=1, description="Mô tả — văn bản định dạng (HTML).")
    requirements: str = Field(default="", description="Yêu cầu — văn bản định dạng (HTML), dán cả khối.")
    # JD-1 (PRD §16, §8.1): trường hướng-ứng-viên.
    level: JobLevel | None = None
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    benefits: str = Field(default="", description="Quyền lợi — văn bản định dạng (HTML).")
    employment_type: EmploymentType | None = None

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
    requirements: str = ""
    level: str | None = None
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    benefits: str = ""
    employment_type: str | None = None
    rubric: list[RubricCriterion] = Field(default_factory=list)
    screener_questions: list[str] = Field(default_factory=list)
    gate_config: GateConfig = Field(default_factory=GateConfig)
    status: str
    embedding_ref: str | None = None  # null = chưa embed (embedding lỗi / JD legacy)
    # JD-3: số lần AI đã gợi ý rubric cho JD này (cap ở RUBRIC_SUGGEST_MAX_RETRIES). CHỈ HR thấy
    # (KHÔNG khai báo ở PublicJobRead). remaining = phần còn lại (backend là nguồn chân lý của cap).
    rubric_suggestion_count: int = 0
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def rubric_suggestions_remaining(self) -> int:
        """Số lần gợi ý rubric còn lại — dẫn xuất từ count + cap env (frontend hiển thị, KHÔNG tự tính cap)."""
        from app.core.config import settings

        return max(0, settings.rubric_suggest_max_retries - self.rubric_suggestion_count)

    @field_validator("requirements", "benefits", mode="before")
    @classmethod
    def _text_or_empty(cls, v: object) -> object:
        # Cột Text nullable — legacy None → "". Chuỗi HTML (hoặc plain legacy) trả thẳng.
        return "" if v is None else v

    @field_validator("salary", mode="before")
    @classmethod
    def _default_salary(cls, v: object) -> object:
        # JD legacy: salary NULL → mặc định (min/max None, VND, không thỏa thuận).
        return SalaryInfo() if v is None else v

    @field_validator("rubric", mode="before")
    @classmethod
    def _normalize_rubric(cls, v: object) -> object:
        # Row scaffold cũ lưu rubric={} (dict) — quy về list rỗng.
        if isinstance(v, dict):
            return list(v.get("criteria", [])) if "criteria" in v else []
        return v


class PublicJobRead(BaseModel):
    """JD cho trang CÔNG KHAI (ứng viên guest — PRD §8.2, §12.2). PROJECTION AN TOÀN: CHỈ trường
    ứng-viên-thấy. TUYỆT ĐỐI KHÔNG khai báo rubric/gate_config/screener_questions/status/embedding_ref
    (lộ rubric → ứng viên nhồi từ khóa). Các trường không khai báo sẽ KHÔNG được đọc/serialize.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    requirements: str = ""
    level: str | None = None
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    benefits: str = ""
    employment_type: str | None = None
    created_at: datetime

    @field_validator("requirements", "benefits", mode="before")
    @classmethod
    def _text_or_empty(cls, v: object) -> object:
        return "" if v is None else v

    @field_validator("salary", mode="before")
    @classmethod
    def _default_salary(cls, v: object) -> object:
        return SalaryInfo() if v is None else v


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
