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
        # GHI ĐÈ lý do của ranker. Ranker chạy trước gate nên nó chỉ biết "điểm dưới ngưỡng → cần HR
        # xem xét"; tới đây thì KHÔNG cần HR nữa — chính gate vừa quyết. Không ghi đè thì hồ sơ
        # REJECTED mang lý do "cần HR xem xét" vào cả `application` lẫn `audit_log`, tức bản ghi pháp
        # y (PRD §16, NFR-3) mô tả sai người ra quyết định. Đây là lỗi thật bắt được khi verify prod
        # 18/08/2026 — nay cả hai node đều chỉ phát biểu điều mình thực sự biết.
        "escalation_reason": (
            f"Tự động từ chối: điểm {score}/100 dưới ngưỡng đạt và gate auto-từ-chối của JD đang BẬT "
            "(PRD §9). Không cần HR xử lý."
        ),
        "messages": [
            f"[gate] auto-từ-chối: điểm {score} dưới ngưỡng đạt, gate JD BẬT (PRD §9). "
            "Thư từ chối gửi qua scheduler."
        ],
    }
