"""parser node — STUB (PRD §7.1).

Thật: CV (PDF/DOCX) -> JSON có cấu trúc; set `parse_failed` nếu không đọc được.
Scaffold: pass-through, confidence=1.0.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def parser_node(state: RecruitmentState) -> dict:
    # TODO (PRD §7.1): chọn bộ đọc theo định dạng (PyMuPDF/python-docx) -> parsed_data JSON.
    return {
        "status": ApplicationStatus.PARSING.value,
        "scratchpad": {**state.get("scratchpad", {}), "parsed": True},
        "confidence": 1.0,
        "uncertainty_flags": [],
        "messages": ["[parser] stub pass-through (chưa parse CV thật — PRD §7.1)"],
    }
