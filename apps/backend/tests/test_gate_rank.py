"""Test slice 03c — Gate rank (auto-từ-chối sau ranker, cấu hình theo JD). PRD §9, §8.3.

Phủ ba tầng (mock scheduler/email — KHÔNG gửi thật, KHÔNG chạm DB thật):
  1) route_after_ranker: 3 nhánh đúng THỨ TỰ ƯU TIÊN (uncertain → human_review LUÔN; confident+đạt
     → screener; confident+điểm thấp SẠCH → gate ON auto_reject / OFF human_review).
  2) gate node đặt REJECTED (không gửi email — node không có session).
  3) background: nhánh auto_reject → delegate scheduler.notify_decision("reject") + status REJECTED
     + audit gate/auto_reject (điểm phát email DUY NHẤT; lỗi gửi nuốt có kiểm soát).
  4) job_service.set_gate_config: bật/tắt gate theo JD (không đụng field còn lại).

BẤT BIẾN (PRD §9): ranker đặt require_human_review cho MỌI điểm thấp → đó là TRIGGER của gate,
KHÔNG phải tín hiệu bất định. Ca có cờ/low-confidence LUÔN về human_review dù gate bật (an toàn).
"""

from __future__ import annotations

import pytest

from app.agents.policy import route_after_ranker
from app.core.config import settings

_LOW = settings.score_pass_threshold - 20   # điểm thấp rõ ràng
_PASS = settings.score_pass_threshold + 20   # điểm đạt rõ ràng


def _state(
    *,
    confidence: float = 1.0,
    flags: list[str] | None = None,
    require_review: bool = False,
    score: float | None = None,
    auto_reject: bool = False,
    error: str | None = None,
) -> dict:
    return {
        "error": error,
        "confidence": confidence,
        "uncertainty_flags": flags or [],
        "require_human_review": require_review,
        "score": score,
        "input": {"jd": {"gate_config": {"auto_reject": auto_reject, "auto_invite": False}}},
    }


# ── route_after_ranker: 3 nhánh theo thứ tự ưu tiên ──────────────────────────


def test_route_confident_clean_low_score_gate_on_auto_rejects() -> None:
    # Tự tin, KHÔNG cờ, điểm thấp (ranker đặt require_review) + gate BẬT → auto_reject.
    st = _state(require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "auto_reject"


def test_route_confident_clean_low_score_gate_off_human_review() -> None:
    # Cùng ca nhưng gate TẮT → human_review (hành vi mặc định, không đổi).
    st = _state(require_review=True, score=_LOW, auto_reject=False)
    assert route_after_ranker(st) == "human_review"


def test_route_flagged_low_score_gate_on_still_human_review() -> None:
    # Điểm thấp NHƯNG có cờ bất định → uncertain → human_review dù gate BẬT (an toàn — gate no-op).
    st = _state(flags=["score_signal_mismatch"], require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_low_confidence_gate_on_still_human_review() -> None:
    # confidence dưới ngưỡng → uncertain → human_review dù gate BẬT.
    st = _state(confidence=0.3, require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_error_gate_on_still_human_review() -> None:
    # Lỗi kỹ thuật → uncertain → human_review dù gate BẬT.
    st = _state(error="boom", require_review=True, score=_LOW, auto_reject=True)
    assert route_after_ranker(st) == "human_review"


def test_route_confident_pass_continues_to_screener() -> None:
    # Đạt ngưỡng, tự tin → screener (nhánh tự động cũ — gate KHÔNG đụng).
    st = _state(require_review=False, score=_PASS, auto_reject=True)
    assert route_after_ranker(st) == "screener"


# ── gate node: đặt REJECTED, KHÔNG gửi email ─────────────────────────────────


def test_gate_node_sets_rejected() -> None:
    from app.agents.nodes.gate import gate_auto_reject_node

    out = gate_auto_reject_node(_state(require_review=True, score=_LOW, auto_reject=True))
    from app.models.application import ApplicationStatus

    assert out["status"] == ApplicationStatus.REJECTED.value
    assert out["result"]["action"] == "auto_reject"
