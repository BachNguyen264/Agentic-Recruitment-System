"""policy — quyết định rẽ nhánh (PRD §5 trụ cột 3, §8.3 GATE RANK, §9 FR-GATE-2).

`should_review`: dưới ngưỡng confidence / có cờ bất định / lỗi -> human_review. "Không chắc thì hỏi
HR" là hành vi ĐÚNG. Gate auto chỉ can thiệp ca tự tin; ca bất định LUÔN vào human_review (bất biến).
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.core.config import settings


def should_review(state: RecruitmentState) -> bool:
    if state.get("error"):
        return True
    if state.get("require_human_review"):
        return True
    if state.get("uncertainty_flags"):
        return True
    confidence = state.get("confidence", 1.0)
    return confidence < settings.confidence_threshold


def route_after_ranker(state: RecruitmentState) -> str:
    """Tên nhánh trả về phải khớp key trong add_conditional_edges (graph.py)."""
    return "human_review" if should_review(state) else "screener"
