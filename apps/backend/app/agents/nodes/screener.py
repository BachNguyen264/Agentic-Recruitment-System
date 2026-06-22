"""screener node — STUB (PRD §7.3 + §10). Chạy SAU ranker, trên nhánh tự động.

Thật: gửi BỘ CÂU HỎI CỐ ĐỊNH qua email + magic-link form rồi **SUSPEND** pipeline (lưu state bền,
không chiếm tài nguyên); resume theo sự kiện/timeout; nhắc +24h; deadline +72h. KHÔNG phải chatbot.

Scaffold: pass-through, KHÔNG suspend thật.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def screener_node(state: RecruitmentState) -> dict:
    # TODO (PRD §10): LangGraph interrupt + Postgres checkpointer (suspend/resume, reminder, timeout).
    # TODO (PRD §9): GATE MỜI sau screener (auto-mời ON -> scheduler; OFF/có cờ -> human_review).
    return {
        "status": ApplicationStatus.SCREENING.value,
        "awaiting_screener": False,  # scaffold: chưa suspend
        "screener_answers": None,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "messages": ["[screener] stub pass-through (chưa gửi email/suspend — PRD §10)"],
    }
