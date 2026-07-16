"""Test slice 08d — Gate auto-mời SAU screener (đối xứng auto-reject 03c). PRD §9, §8.3.

Phủ (mock scheduler/email — KHÔNG gửi thật, KHÔNG chạm DB thật):
  1) route_after_screener: ca SẠCH + auto_invite ON → auto_invite; OFF → human_review;
     ca KHÔNG sạch (no_response / cờ / low-conf / error) + gate ON → human_review LUÔN ("cờ thắng gate").
  2) scheduler_node = marker SCHEDULING (quyết định mời, chưa gửi — pure, không email).
  3) background.resume_screener nhánh auto_invite → notify_decision("invite"); email OK → INTERVIEW_SCHEDULED,
     email FAIL → PENDING_REVIEW (KHÔNG "trạng thái nói dối").

BẤT BIẾN (PRD §9 FR-GATE-2): gate CHỈ áp ca tự tin/sạch; ca bất định/no_response LUÔN → human_review.
"""

from __future__ import annotations

from app.agents.policy import route_after_screener


def _state(
    *,
    confidence: float = 1.0,
    flags: list[str] | None = None,
    error: str | None = None,
    auto_invite: bool = False,
) -> dict:
    return {
        "error": error,
        "confidence": confidence,
        "uncertainty_flags": flags or [],
        "input": {"jd": {"gate_config": {"auto_reject": False, "auto_invite": auto_invite}}},
    }


# ── route_after_screener: ca sạch để gate quyết; ca không sạch LUÔN về người ──────────────


def test_route_clean_gate_on_auto_invites() -> None:
    # Đã trả lời (confident, không cờ) + auto_invite BẬT → auto_invite.
    assert route_after_screener(_state(auto_invite=True)) == "auto_invite"


def test_route_clean_gate_off_human_review() -> None:
    # Cùng ca nhưng auto_invite TẮT → human_review (mặc định, hành vi trước 08d KHÔNG đổi).
    assert route_after_screener(_state(auto_invite=False)) == "human_review"


def test_route_no_response_gate_on_still_human_review() -> None:
    # Timeout (no_response) + gate BẬT → human_review LUÔN (an toàn — im lặng ≠ mời).
    assert route_after_screener(_state(flags=["no_response"], auto_invite=True)) == "human_review"


def test_route_flagged_gate_on_still_human_review() -> None:
    # Cờ bất định + gate BẬT → human_review (gate no-op).
    assert route_after_screener(_state(flags=["weak_match"], auto_invite=True)) == "human_review"


def test_route_low_confidence_gate_on_still_human_review() -> None:
    assert route_after_screener(_state(confidence=0.3, auto_invite=True)) == "human_review"


def test_route_error_gate_on_still_human_review() -> None:
    assert route_after_screener(_state(error="boom", auto_invite=True)) == "human_review"


def test_route_no_jd_defaults_human_review() -> None:
    # Không JD/không gate_config → auto_invite mặc định TẮT → human_review.
    assert route_after_screener({"confidence": 1.0, "uncertainty_flags": [], "input": {}}) == "human_review"
