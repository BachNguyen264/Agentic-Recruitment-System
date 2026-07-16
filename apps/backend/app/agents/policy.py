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


def _auto_invite_enabled(state: RecruitmentState) -> bool:
    """Gate auto-mời của JD (PRD §9 FR-GATE-1, 08d). Đọc từ `input.jd.gate_config` (ảnh chụp lúc CV vào
    pipeline — đối xứng auto_reject; cấu hình theo từng JD). Mặc định TẮT."""
    jd = (state.get("input") or {}).get("jd") or {}
    gate = jd.get("gate_config") or {}
    return bool(gate.get("auto_invite"))


def route_after_ranker(state: RecruitmentState) -> str:
    """Định tuyến sau ranker (PRD §8.3, §9) — THỨ TỰ ƯU TIÊN AN TOÀN TRƯỚC. Tên nhánh khớp key trong
    add_conditional_edges (graph.py). Chỉ ca điểm thấp SẠCH + gate BẬT rời human_review (→ auto_reject);
    mọi ca còn lại về human_review.

    1) BẤT ĐỊNH → `human_review` (gate KHÔNG xét — ca không chắc luôn về người).
    2) tự tin + ĐẠT ngưỡng (require_human_review falsy) → `screener` (08a, PRD §10): pipeline DỪNG hỏi
       ứng viên (bộ câu hỏi cố định — async, suspend/resume). Xong screener → human_review (HR duyệt →
       scheduler gửi thư MỜI THẬT, đường 03b+04). Auto-mời chưa xây (mặc định TẮT) → KHÔNG auto-set
       INTERVIEW_SCHEDULED câm. (Trước 08a: đi thẳng human_review — BUG A fix.)
    3) tự tin + điểm thấp SẠCH (ranker đặt require_human_review = điểm < ngưỡng) → gate JD:
       auto_reject BẬT → `auto_reject`; TẮT → `human_review`. (KHÔNG qua screener.)
    """
    if should_review(state):
        return "human_review"
    if not state.get("require_human_review"):
        return "screener"  # ĐẠT ngưỡng → Screener async (08a): dừng hỏi ứng viên rồi mới → human_review
    return "auto_reject" if _auto_reject_enabled(state) else "human_review"


def route_after_screener(state: RecruitmentState) -> str:
    """Định tuyến SAU khi screener resume (PRD §9 §10, 08d) — GATE AUTO-MỜI, đối xứng auto_reject.
    THỨ TỰ ƯU TIÊN AN TOÀN TRƯỚC. Tên nhánh khớp key add_conditional_edges (graph.py).

    1) Ca KHÔNG sạch (no_response timeout / cờ bất định / low-confidence / lỗi) → `human_review` LUÔN —
       gate KHÔNG xét (§9 FR-GATE-2 "cờ thắng gate"). Đây là chốt an toàn: im lặng/bất định ≠ mời.
    2) Ca SẠCH (đã trả lời, tự tin, không cờ) → gate JD: auto_invite BẬT → `auto_invite` (thư mời THẬT
       qua scheduler, KHÔNG cần HR); TẮT → `human_review` (HR đọc câu trả lời rồi mới duyệt — mặc định).

    KHÔNG chấm NỘI DUNG câu trả lời: đủ điều kiện = qua rank (đã tới screener) + đã trả lời + không cờ.
    Answers vẫn lưu cho HR/phỏng vấn (08b). Mặc định auto_invite TẮT → hành vi sau-screener KHÔNG đổi."""
    if should_review(state):
        return "human_review"
    return "auto_invite" if _auto_invite_enabled(state) else "human_review"
