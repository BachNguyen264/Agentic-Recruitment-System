"""human_review node — STUB (PRD §11). Điểm dừng để HR quyết, kích hoạt có điều kiện.

Thật: đính kèm **ReviewCard** (tóm tắt + điểm + lý do + đề xuất); HR duyệt -> delegate scheduler,
HR từ chối -> scheduler gửi thư từ chối; ghi audit_log.

Scaffold: set require_human_review=True + escalation_reason, dừng ở PENDING_REVIEW.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.core.config import settings
from app.models.application import ApplicationStatus


def _fallback_reason(state: RecruitmentState) -> str:
    """Lý do khi các node TRƯỚC không đặt `escalation_reason`.

    Ca PHỔ BIẾN NHẤT rơi vào đây: hồ sơ SẠCH (đạt ngưỡng, không cờ bất định) nhưng gate auto-mời TẮT
    (mặc định) → `route_after_screener` đưa về human_review mà ranker chẳng có gì để "leo thang".
    Trước đây trả "Cần HR xem xét (lý do chưa xác định)" — HR mở ReviewCard đọc câu đó tưởng hệ thống
    lỗi, trong khi lý do thật rất rõ ràng. Nêu ĐÚNG lý do, suy từ chính state (PRD §11).
    """
    flags = [f for f in (state.get("uncertainty_flags") or []) if f]
    if flags:
        return f"Có dấu hiệu bất định ({', '.join(flags)}) — cần HR xem xét."

    score = state.get("score")
    if score is not None and score >= settings.score_pass_threshold:
        gate = ((state.get("input") or {}).get("jd") or {}).get("gate_config") or {}
        if not gate.get("auto_invite"):
            return (
                f"Hồ sơ đạt {score}/100 (ngưỡng {settings.score_pass_threshold:g}), không có cờ bất "
                "định. Gate auto-mời đang TẮT cho JD này nên mọi ca đạt đều chờ HR xác nhận."
            )
        return f"Hồ sơ đạt {score}/100 — chờ HR xác nhận trước khi mời."

    return "Cần HR xem xét."


def human_review_node(state: RecruitmentState) -> dict:
    reason = state.get("escalation_reason") or _fallback_reason(state)
    # TODO (PRD §11): dựng ReviewCard (FR-HR-1) + chờ quyết định HR rồi delegate scheduler (FR-HR-4).
    return {
        "status": ApplicationStatus.PENDING_REVIEW.value,
        "require_human_review": True,
        "escalation_reason": reason,
        "result": {"action": "queued_for_human_review"},
        "messages": [f"[human_review] -> PENDING_REVIEW (kèm ReviewCard — PRD §11). Lý do: {reason}"],
    }
