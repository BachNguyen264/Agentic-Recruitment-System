"""policy — quyết định rẽ nhánh (PRD §5 trụ cột 3, §8.3 GATE RANK, §9 FR-GATE-2).

`should_review`: BẤT ĐỊNH (lỗi / có cờ bất định / confidence thấp) -> human_review. "Không chắc thì
hỏi HR" là hành vi ĐÚNG; ca bất định LUÔN vào human_review, gate KHÔNG được can thiệp (bất biến §9).

CHÚ Ý (bất biến ranker): ranker đặt `require_human_review=True` cho MỌI điểm dưới ngưỡng đạt — đó là
"mặc định khi gate auto-từ-chối TẮT", KHÔNG phải tín hiệu bất định. Vì vậy cờ này KHÔNG nằm trong
`should_review` mà là TRIGGER của gate ở `route_after_ranker` (nếu để trong should_review thì nhánh
auto_reject thành dead code — mọi điểm thấp về human_review). Xem PRD §8.3.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.core.config import settings


def should_review(state: RecruitmentState) -> bool:
    """Ca BẤT ĐỊNH → human_review LUÔN (gate no-op). KHÔNG tính require_human_review (xem docstring)."""
    if state.get("error"):
        return True
    if state.get("uncertainty_flags"):
        return True
    confidence = state.get("confidence", 1.0)
    return confidence < settings.confidence_threshold


def _auto_reject_enabled(state: RecruitmentState) -> bool:
    """Gate auto-từ-chối của JD (PRD §9 FR-GATE-1: cấu hình theo từng JD). Mặc định TẮT."""
    jd = (state.get("input") or {}).get("jd") or {}
    gate = jd.get("gate_config") or {}
    return bool(gate.get("auto_reject"))


def route_after_ranker(state: RecruitmentState) -> str:
    """3 nhánh sau ranker (PRD §8.3, §9) — THỨ TỰ ƯU TIÊN AN TOÀN TRƯỚC. Tên nhánh khớp key trong
    add_conditional_edges (graph.py):

    1) BẤT ĐỊNH → `human_review` (gate KHÔNG xét — ca không chắc luôn về người).
    2) tự tin + đạt ngưỡng (require_human_review falsy) → `screener` (nhánh tự động — giữ nguyên).
    3) tự tin + điểm thấp SẠCH (ranker đặt require_human_review = điểm < ngưỡng) → gate JD:
       auto_reject BẬT → `auto_reject`; TẮT → `human_review` (mặc định — hành vi không đổi).
    """
    if should_review(state):
        return "human_review"
    if not state.get("require_human_review"):
        return "screener"
    return "auto_reject" if _auto_reject_enabled(state) else "human_review"
