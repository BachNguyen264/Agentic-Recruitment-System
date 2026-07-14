"""screener node — SUSPEND/RESUME (PRD §7.3 + §10). Chạy SAU ranker, trên nhánh ĐẠT.

08a (nền bất đồng bộ): DỪNG pipeline ở đây bằng LangGraph `interrupt()` — state được lưu BỀN xuống
checkpointer Postgres (Neon), không chiếm tài nguyên; resume ĐÚNG điểm dừng khi có câu trả lời, sống
qua restart backend. Đây MỚI là cơ chế; những phần Screener khác xây trên nền này:
  - 08b: gửi BỘ CÂU HỎI CỐ ĐỊNH qua email + magic-link form → resume bằng câu trả lời THẬT.
  - 08c: nhắc +24h, deadline +72h (timeout/trả lời trễ).
  - 08d: cổng auto-mời sau screener.
KHÔNG phải chatbot. Payload interrupt ở 08a chỉ PLACEHOLDER (câu hỏi thật = 08b).

LƯU Ý (ngữ nghĩa interrupt): khi resume, node CHẠY LẠI TỪ ĐẦU — code TRƯỚC `interrupt()` chạy 2 lần.
Giữ node tối giản, KHÔNG side-effect trước `interrupt()`.
"""

from __future__ import annotations

from langgraph.types import interrupt

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def screener_node(state: RecruitmentState) -> dict:
    # Lần chạy ĐẦU: interrupt() raise → pipeline DỪNG (suspend), KHÔNG trả dict, state lưu ở checkpointer.
    # Lần RESUME: interrupt() trả về payload resume (mock ở 08a) → node chạy tiếp, trả dict bên dưới.
    answers = interrupt(
        {"awaiting": "screener_answers", "application_id": state.get("application_id")}
    )
    # 08a chưa xử lý câu trả lời (chuẩn hóa/chấm = 08b) — chỉ đi tiếp sang human_review.
    return {
        "status": ApplicationStatus.SCREENING.value,
        "awaiting_screener": False,
        "screener_answers": answers,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "messages": ["[screener] resume: nhận câu trả lời (placeholder 08a) → tiếp human_review"],
    }
