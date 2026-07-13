"""Test skeleton LangGraph (Phase 4): graph compile + chạy ĐÚNG cả 2 nhánh + policy.

KHÔNG chạm DB/LLM — node là stub thuần.
"""

from __future__ import annotations

from app.agents.graph import compile_graph
from app.agents.policy import should_review
from app.agents.runner import run_sync


def test_graph_compiles() -> None:
    assert compile_graph() is not None


def test_confident_pass_reaches_human_review() -> None:
    # BUG A fix: ca ĐẠT/tự tin KHÔNG còn tự đặt INTERVIEW_SCHEDULED câm — về human_review để HR duyệt
    # rồi scheduler mới gửi thư mời THẬT (auto-mời chưa xây, mặc định TẮT). Không qua screener/scheduler.
    final = run_sync(force_review=False)
    assert final["status"] == "PENDING_REVIEW"
    assert final["require_human_review"] is True
    joined = " ".join(final["messages"])
    assert "[parser]" in joined and "[ranker]" in joined
    assert "[human_review]" in joined
    assert "[scheduler]" not in joined  # KHÔNG auto-schedule câm


def test_review_branch_reaches_human_review() -> None:
    final = run_sync(force_review=True)
    assert final["status"] == "PENDING_REVIEW"
    assert final["require_human_review"] is True
    assert final["escalation_reason"]
    joined = " ".join(final["messages"])
    assert "[human_review]" in joined
    assert "[scheduler]" not in joined  # nhánh review KHÔNG đi qua scheduler


def test_should_review_policy() -> None:
    # Có cờ bất định -> review (FR-GATE-2).
    assert should_review({"uncertainty_flags": ["weak_match"]}) is True
    # Dưới ngưỡng confidence (mặc định 0.6) -> review.
    assert should_review({"confidence": 0.5, "uncertainty_flags": []}) is True
    # Tự tin, không cờ -> không review.
    assert should_review({"confidence": 1.0, "uncertainty_flags": []}) is False
