"""gate node — auto-từ-chối (PRD §9 FR-GATE, §8.3). Nhánh khi HR bật gate `auto_reject` cho JD và
ca điểm thấp RÕ RÀNG (tự tin, không cờ — do `route_after_ranker` chọn). Đặt REJECTED, KHÔNG cần HR.

KHÔNG gửi email ở đây: node không có DB session. Điểm phát email DUY NHẤT là
`scheduler.notify_decision("reject", …)`, gọi ở background task SAU khi graph chạy (CLAUDE.md).
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def gate_auto_reject_node(state: RecruitmentState) -> dict:
    score = state.get("score")
    return {
        "status": ApplicationStatus.REJECTED.value,
        "result": {"action": "auto_reject", "score": score},
        "messages": [
            f"[gate] auto-từ-chối: điểm {score} dưới ngưỡng đạt, gate JD BẬT (PRD §9). "
            "Thư từ chối gửi qua scheduler."
        ],
    }
