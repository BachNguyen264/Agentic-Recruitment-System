"""Test slice 08a — Screener suspend/resume (nền bất đồng bộ). PRD §10, §7.3, NFR-2.

Chứng minh CƠ CHẾ (node stub, MemorySaver — KHÔNG chạm Neon/LLM; bài DURABILITY qua restart là
Verify thủ công, xem plan §4):
  1) ca ĐẠT + tự tin → pipeline DỪNG ở screener (interrupt): snapshot.next == ('screener',),
     parser+ranker đã chạy, CHƯA tới human_review.
  2) resume (Command) → screener chạy tiếp → human_review → PENDING_REVIEW; parser/ranker KHÔNG
     chạy lại; screener nhận đúng payload resume.
  3) ca BẤT ĐỊNH (uncertain) KHÔNG đi qua screener — chạy thẳng human_review, KHÔNG suspend.

thread_id ổn định theo lần chạy: dùng cùng config cho chạy đầu + resume (khớp checkpoint).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import Command

from app.agents.graph import compile_graph
from app.agents.runner import initial_state
from app.models.application import ApplicationStatus


async def _drive(graph: Any, graph_input: Any, config: dict) -> None:
    """Chạy hết một lượt astream (bỏ qua sự kiện interrupt) — dừng khi suspend hoặc tới END."""
    async for _update in graph.astream(graph_input, config, stream_mode="updates"):
        pass


def _count(messages: list[str], marker: str) -> int:
    return sum(marker in m for m in messages)


async def test_confident_pass_suspends_at_screener() -> None:
    graph = compile_graph()  # MemorySaver (fresh, cô lập theo test)
    config = {"configurable": {"thread_id": "cp-suspend"}}

    await _drive(graph, initial_state(force_review=False, application_id=1), config)

    snap = await graph.aget_state(config)
    # Đang DỪNG ở screener: còn node chờ chạy.
    assert snap.next == ("screener",)
    # parser + ranker đã chạy, screener CHƯA hoàn tất, CHƯA tới human_review.
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[parser]") == 1
    assert _count(msgs, "[ranker]") == 1
    assert _count(msgs, "[human_review]") == 0
    assert snap.values.get("status") != ApplicationStatus.PENDING_REVIEW.value
    # Payload interrupt (placeholder 08a) mang application_id để 08b gắn form đúng ứng viên.
    interrupts = snap.tasks[0].interrupts
    assert interrupts and interrupts[0].value.get("application_id") == 1


async def test_resume_continues_from_screener_without_rerun() -> None:
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-resume"}}

    await _drive(graph, initial_state(force_review=False, application_id=2), config)
    assert (await graph.aget_state(config)).next == ("screener",)  # đã suspend

    # Resume bằng payload MOCK (08b sẽ là câu trả lời thật).
    await _drive(graph, Command(resume={"q1": "mock answer"}), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # đã tới END
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    # parser/ranker KHÔNG chạy lại (checkpointer nạp state cũ) — mỗi cái đúng 1 lần.
    assert _count(msgs, "[parser]") == 1
    assert _count(msgs, "[ranker]") == 1
    # screener resume rồi human_review.
    assert _count(msgs, "[screener] resume") == 1
    assert _count(msgs, "[human_review]") == 1
    # screener nhận đúng payload resume.
    assert snap.values.get("screener_answers") == {"q1": "mock answer"}


async def test_uncertain_does_not_go_through_screener() -> None:
    graph = compile_graph()
    config = {"configurable": {"thread_id": "cp-uncertain"}}

    await _drive(graph, initial_state(force_review=True, application_id=3), config)

    snap = await graph.aget_state(config)
    assert snap.next == ()  # KHÔNG suspend
    assert snap.values.get("status") == ApplicationStatus.PENDING_REVIEW.value
    msgs = snap.values.get("messages", [])
    assert _count(msgs, "[human_review]") == 1
    assert _count(msgs, "[screener]") == 0  # bất định đi thẳng review, KHÔNG qua screener
