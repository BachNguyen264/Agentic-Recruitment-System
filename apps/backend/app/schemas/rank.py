"""Schema Ranker (PRD §7.2) — chấm rubric có suy luận + I/O cho endpoint rank-cv.

RankResult là structured-output của LLM: chấm TỪNG tiêu chí rubric (do HR nhập ở JD) kèm lý do.
Code tính lại `overall` từ criteria×weight để đối chiếu (không tin mù điểm tổng của LLM).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CriterionScore(BaseModel):
    criterion: str = Field(description="Tên tiêu chí rubric — đúng như JD cung cấp, không tự thêm.")
    weight: float = Field(description="Trọng số tiêu chí (echo lại từ rubric JD).")
    score: float = Field(ge=0, le=100, description="Điểm 0..100 cho tiêu chí này dựa BẰNG CHỨNG trong CV.")
    reasoning: str = Field(description="Lý do chấm: dẫn bằng chứng cụ thể trong CV; thiếu bằng chứng → nói rõ; KHÔNG bịa.")


class RankResult(BaseModel):
    """Structured output LLM. `overall_score` để đối chiếu — code tính lại từ criteria×weight."""

    overall_score: float = Field(ge=0, le=100, description="Điểm tổng 0..100 (tổng hợp của bạn).")
    criteria: list[CriterionScore] = Field(
        description="Chấm TỪNG tiêu chí rubric, đúng thứ tự JD đưa, không thêm/bớt tiêu chí."
    )
    summary: str = Field(description="Tóm tắt ngắn mức phù hợp của ứng viên với JD (2-3 câu).")


# ── I/O endpoint rank-cv ─────────────────────────────────────────────────────


class RankCvRequest(BaseModel):
    """Chấm một CV cho một JD. Truyền `application_id` HOẶC (`parsed_data` + `job_id`)."""

    application_id: int | None = None
    parsed_data: dict | None = None
    job_id: int | None = None


class RankCvResponse(BaseModel):
    score: float | None = None
    score_breakdown: list[CriterionScore] = Field(default_factory=list)
    summary: str | None = None
    semantic_similarity: float | None = None
    confidence: float
    uncertainty_flags: list[str] = Field(default_factory=list)
    escalation_reason: str | None = None
    model_used: str  # RANKER_MODEL + (reasoning_effort | temperature=0) — phân biệt khi benchmark
