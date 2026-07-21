"""Test lý do vào human_review (PRD §11) — chuỗi HR đọc trên ReviewCard.

Bối cảnh: ca PHỔ BIẾN NHẤT là hồ sơ SẠCH (đạt ngưỡng, không cờ) + gate auto-mời TẮT → về
human_review mà không node nào đặt `escalation_reason`. Trước đây rơi vào chuỗi dự phòng
"lý do chưa xác định" → HR tưởng hệ thống lỗi. Giờ phải nêu ĐÚNG lý do.
"""

from __future__ import annotations

from app.agents.nodes.human_review import human_review_node
from app.core.config import settings


def _state(**over) -> dict:
    base: dict = {"input": {"jd": {"gate_config": {"auto_reject": False, "auto_invite": False}}}}
    base.update(over)
    return base


def test_giu_nguyen_ly_do_da_co() -> None:
    # Node trước đã nêu lý do (vd ranker: điểm dưới ngưỡng) → KHÔNG ghi đè.
    out = human_review_node(_state(escalation_reason="Điểm 40/100 dưới ngưỡng đạt 60."))
    assert out["escalation_reason"] == "Điểm 40/100 dưới ngưỡng đạt 60."
    assert out["status"] == "PENDING_REVIEW"
    assert out["require_human_review"] is True


def test_co_bat_dinh_thi_neu_ten_co() -> None:
    out = human_review_node(_state(uncertainty_flags=["no_response", "weak_match"]))
    assert "no_response" in out["escalation_reason"]
    assert "weak_match" in out["escalation_reason"]


def test_ho_so_sach_gate_moi_tat_neu_dung_ly_do() -> None:
    # KHÔNG còn "lý do chưa xác định" — phải nói rõ vì gate auto-mời tắt.
    score = settings.score_pass_threshold + 26.8
    out = human_review_node(_state(score=score, uncertainty_flags=[]))
    reason = out["escalation_reason"]
    assert "chưa xác định" not in reason
    assert "auto-mời" in reason and "TẮT" in reason
    assert str(score) in reason


def test_ho_so_sach_gate_moi_bat_van_co_ly_do_ro() -> None:
    # Gate bật nhưng vẫn vào review (vd đường có câu hỏi sàng lọc) → nêu điểm, không "chưa xác định".
    out = human_review_node(
        _state(
            score=88.0,
            uncertainty_flags=[],
            input={"jd": {"gate_config": {"auto_reject": False, "auto_invite": True}}},
        )
    )
    assert "chưa xác định" not in out["escalation_reason"]
    assert "88.0/100" in out["escalation_reason"]


def test_khong_co_gi_de_suy_thi_van_co_cau_gon() -> None:
    out = human_review_node(_state())
    assert out["escalation_reason"] == "Cần HR xem xét."
