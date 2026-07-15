"""Test slice 08c — Screener timeout (nhắc + hết hạn + trả lời trễ). PRD §10 FR-SCR-3/4/5.

Ba mảng:
  A) screener node phân biệt resume câu-trả-lời (08b) vs tín hiệu `no_response` (timeout) — qua graph
     + MemorySaver (KHÔNG chạm Neon/LLM).
  B) handlers nghiệp vụ (send_screening_reminder / handle_screening_timeout) + sweep_once — mock DB
     + mock resume/scheduler (đơn vị hóa; row-lock/concurrency kiểm ở Verify live).
  C) trả lời trễ: session hết hạn / đã timeout → _load_valid từ chối êm (không resume lại).

Ranh giới: im lặng ≠ từ chối — timeout LUÔN → human_review + cờ no_response, KHÔNG auto-reject.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from langgraph.types import Command

from app.agents.graph import compile_graph
from app.agents.runner import initial_state
from app.models.application import ApplicationStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    async for _update in graph.astream(graph_input, config, stream_mode="updates"):
        pass


def _count(messages: list[str], marker: str) -> int:
    return sum(marker in m for m in messages)


# ── A) screener node: resume no_response → human_review + cờ, KHÔNG auto-reject ──────────


async def test_resume_no_response_routes_human_review_with_flag() -> None:
    """Timeout resume (`{"no_response": True}`) → screener đi tiếp human_review với cờ no_response +
    escalation_reason; parser/ranker KHÔNG chạy lại; status PENDING_REVIEW (KHÔNG REJECTED)."""
    graph = compile_graph()  # MemorySaver, cô lập
    config = {"configurable": {"thread_id": "cp-timeout"}}

    await _drive(graph, initial_state(force_review=False, application_id=9), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    await _drive(graph, Command(resume={"no_response": True}), config)  # tín hiệu timeout

    snap = await graph.aget_state(config)
    assert snap.next == ()  # tới END
    # KHÔNG auto-reject: đi human_review → PENDING_REVIEW.
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    assert "no_response" in (snap.values.get("uncertainty_flags") or [])
    assert snap.values.get("escalation_reason")  # có lý do "không phản hồi" cho HR
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[parser]") == 1 and _count(msgs, "[ranker]") == 1  # KHÔNG rerun
    assert _count(msgs, "[human_review]") == 1


async def test_resume_real_answers_still_works_no_flag() -> None:
    """Không hồi quy 08b: resume câu-trả-lời-thật (payload có `answers`) KHÔNG gắn cờ no_response."""
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-answers"}}

    await _drive(graph, initial_state(force_review=False, application_id=10), config)
    await _drive(graph, Command(resume={"answers": [{"question": "Q", "answer": "A"}]}), config)

    snap = await graph.aget_state(config)
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    assert "no_response" not in (snap.values.get("uncertainty_flags") or [])
    assert snap.values.get("screener_answers") == {"answers": [{"question": "Q", "answer": "A"}]}
