"""screener node — SUSPEND/RESUME (PRD §7.3 + §10). Chạy SAU ranker, trên nhánh ĐẠT.

08a (nền bất đồng bộ): DỪNG pipeline ở đây bằng LangGraph `interrupt()` — state được lưu BỀN xuống
checkpointer Postgres (Neon), không chiếm tài nguyên; resume ĐÚNG điểm dừng khi có câu trả lời, sống
qua restart backend. Đây MỚI là cơ chế; những phần Screener khác xây trên nền này:
  - 08b: gửi BỘ CÂU HỎI CỐ ĐỊNH qua email + magic-link form → resume bằng câu trả lời THẬT.
  - 08c: nhắc +REMINDER_HOURS, deadline +DEADLINE_HOURS. Quá hạn KHÔNG phản hồi → sweep resume node
    với tín hiệu `{"no_response": True}` → node gắn cờ `no_response` + đi tiếp human_review. **Im lặng
    ≠ từ chối:** KHÔNG BAO GIỜ auto-reject (có thể là ứng viên giỏi lỡ email — PRD §10 FR-SCR-4).
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
    # Lần RESUME: interrupt() trả về payload resume → node chạy tiếp, trả dict bên dưới.
    payload = interrupt(
        {"awaiting": "screener_answers", "application_id": state.get("application_id")}
    )

    # 08c — TIMEOUT: sweep resume với `{"no_response": True}` (không phải câu trả lời). Gắn cờ
    # `no_response` + escalation_reason cho HR; đi tiếp human_review. KHÔNG auto-reject (PRD §10 FR-SCR-4).
    if isinstance(payload, dict) and payload.get("no_response"):
        return {
            "status": ApplicationStatus.SCREENING.value,
            "awaiting_screener": False,
            "screener_answers": None,
            "confidence": 1.0,
            "uncertainty_flags": ["no_response"],
            "escalation_reason": "Ứng viên không phản hồi bộ câu hỏi sàng lọc trong thời hạn.",
            "messages": ["[screener] resume: timeout no_response → human_review (KHÔNG auto-reject)"],
        }

    # 08b — câu trả lời THẬT: lưu thô (KHÔNG LLM chuẩn hóa), đi tiếp human_review (HR xem câu trả lời).
    return {
        "status": ApplicationStatus.SCREENING.value,
        "awaiting_screener": False,
        "screener_answers": payload,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "messages": ["[screener] resume: nhận câu trả lời → tiếp human_review"],
    }
