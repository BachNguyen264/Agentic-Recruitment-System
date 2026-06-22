"""ranker node — STUB (PRD §7.2). Node RA QUYẾT ĐỊNH (sau nó là GATE RANK, PRD §8.3).

Thật: đối sánh ngữ nghĩa CV–JD (RAG/Qdrant) + chấm điểm rubric -> điểm + phân rã + tóm tắt;
set `weak_match` khi khớp yếu, confidence thấp khi điểm sát ngưỡng.

Scaffold: đọc cờ demo `input.force_review` để ép một ca BẤT ĐỊNH (đại diện weak_match) nhằm
chạy được nhánh human_review; còn lại trả ca tự tin (confidence=1.0).
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def ranker_node(state: RecruitmentState) -> dict:
    force_review = bool(state.get("input", {}).get("force_review"))

    # TODO (PRD §7.2): truy vấn vector Qdrant + công cụ chấm điểm rubric.
    if force_review:
        # Ca bất định: FR-GATE-2 — gate auto no-op, LUÔN vào human_review.
        return {
            "status": ApplicationStatus.RANKING.value,
            "confidence": 0.5,
            "uncertainty_flags": ["weak_match"],
            "escalation_reason": "Điểm sát ngưỡng / khớp yếu (demo ép nhánh review).",
            "scratchpad": {**state.get("scratchpad", {}), "score": 0.5},
            "messages": ["[ranker] stub: confidence=0.5, flags=[weak_match] -> BẤT ĐỊNH"],
        }

    return {
        "status": ApplicationStatus.RANKING.value,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "scratchpad": {**state.get("scratchpad", {}), "score": 0.9},
        "messages": ["[ranker] stub: confidence=1.0 -> đủ tự tin (nhánh tự động)"],
    }
