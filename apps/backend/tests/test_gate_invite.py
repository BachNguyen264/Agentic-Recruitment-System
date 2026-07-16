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


# ── graph end-to-end: cạnh conditional sau screener + node auto-mời + nhãn nhánh ──────────

from typing import Any  # noqa: E402

from langgraph.types import Command  # noqa: E402

from app.agents.graph import compile_graph  # noqa: E402
from app.agents.runner import _branch, initial_state  # noqa: E402
from app.models.application import ApplicationStatus  # noqa: E402

_JD_INVITE_ON = {"title": "Backend", "gate_config": {"auto_reject": False, "auto_invite": True}}
_JD_INVITE_OFF = {"title": "Backend", "gate_config": {"auto_reject": False, "auto_invite": False}}


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    async for _ in graph.astream(graph_input, config, stream_mode="updates"):
        pass


async def test_graph_clean_resume_auto_invite_routes_scheduler() -> None:
    """Ca sạch + JD auto_invite ON: resume → screener → scheduler (SCHEDULING), KHÔNG human_review."""
    graph = compile_graph()  # MemorySaver
    config = {"configurable": {"thread_id": "gi-on"}}
    await _drive(graph, initial_state(force_review=False, application_id=1, jd=_JD_INVITE_ON), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()
    # scheduler node đặt SCHEDULING (marker mời — chưa INTERVIEW_SCHEDULED); KHÔNG qua human_review.
    assert snap.values.get("status") == ApplicationStatus.SCHEDULING.value
    msgs = snap.values.get("messages", [])
    assert sum("[scheduler] auto-mời" in m for m in msgs) == 1
    assert sum("[human_review]" in m for m in msgs) == 0
    assert sum("[parser]" in m for m in msgs) == 1  # KHÔNG rerun parser/ranker
    # nhãn nhánh (_branch) = auto_invite (background sẽ gửi thư mời).
    nodes_run = {"parser", "ranker", "screener", "scheduler"}
    assert _branch(suspended=False, nodes_run=nodes_run) == "auto_invite"


async def test_graph_clean_resume_gate_off_human_review() -> None:
    """Ca sạch + JD auto_invite OFF: resume → human_review (mặc định, KHÔNG auto-mời)."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "gi-off"}}
    await _drive(graph, initial_state(force_review=False, application_id=2, jd=_JD_INVITE_OFF), config)
    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    assert sum("[human_review]" in m for m in msgs) == 1
    assert sum("[scheduler]" in m for m in msgs) == 0
