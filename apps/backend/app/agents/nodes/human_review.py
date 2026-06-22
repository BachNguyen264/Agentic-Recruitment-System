"""human_review node — STUB (PRD §11). Điểm dừng để HR quyết, kích hoạt có điều kiện.

Thật: đính kèm **ReviewCard** (tóm tắt + điểm + lý do + đề xuất); HR duyệt -> delegate scheduler,
HR từ chối -> scheduler gửi thư từ chối; ghi audit_log.

Scaffold: set require_human_review=True + escalation_reason, dừng ở PENDING_REVIEW.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def human_review_node(state: RecruitmentState) -> dict:
    reason = state.get("escalation_reason") or "Cần HR xem xét (lý do chưa xác định)."
    # TODO (PRD §11): dựng ReviewCard (FR-HR-1) + chờ quyết định HR rồi delegate scheduler (FR-HR-4).
    return {
        "status": ApplicationStatus.PENDING_REVIEW.value,
        "require_human_review": True,
        "escalation_reason": reason,
        "result": {"action": "queued_for_human_review"},
        "messages": [f"[human_review] -> PENDING_REVIEW (kèm ReviewCard — PRD §11). Lý do: {reason}"],
    }
