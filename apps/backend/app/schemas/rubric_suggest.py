"""Schema AI gợi ý rubric (JD-3 — PRD §12.1 FR-HR-RUBRIC-1, trụ cột 4).

LLM đọc JD (tiêu đề + mô tả + yêu cầu plain-text + cấp bậc) → structured output đề xuất TIÊU CHÍ +
TRỌNG SỐ → HR chỉnh/lưu (KHÔNG tự áp). `SuggestedCriterion` dùng chung cho structured-output của LLM
lẫn payload trả về (reasoning là gợi ý-để-HR-tham-khảo, tùy chọn).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SuggestedCriterion(BaseModel):
    criterion: str = Field(min_length=1, description="Tên tiêu chí chấm điểm, vd 'Kinh nghiệm Node.js'.")
    weight: float = Field(
        ge=0, le=1,
        description="Trọng số 0..1 phản ánh MỨC QUAN TRỌNG của tiêu chí với vị trí (tổng ~1).",
    )
    reasoning: str = Field(
        default="",
        description="1 câu vì sao tiêu chí này + mức trọng số này hợp với JD (để HR tham khảo).",
    )


class RubricSuggestion(BaseModel):
    """Structured output LLM — list tiêu chí đề xuất (bắt nguồn từ JD, cân trọng số theo cấp bậc)."""

    criteria: list[SuggestedCriterion] = Field(
        description="3-6 tiêu chí cốt lõi suy ra từ JD; KHÔNG bịa tiêu chí không có căn cứ trong JD.",
    )


class RubricSuggestResponse(BaseModel):
    """Trả về POST /api/jobs/{id}/suggest-rubric — đề xuất + hạn mức còn lại (hiện cho HR)."""

    criteria: list[SuggestedCriterion]
    used: int = Field(description="Số lần đã gợi ý cho JD này (sau lần gọi này).")
    remaining: int = Field(description="Số lần gợi ý còn lại (cap - used).")
    model_used: str  # RUBRIC_SUGGEST_MODEL + (reasoning_effort | temperature=0) — tư liệu benchmark
