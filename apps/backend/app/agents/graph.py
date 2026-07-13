"""graph.py — pipeline LangGraph CỐ ĐỊNH (PRD §5 trụ cột 1: KHÔNG Supervisor).

    START -> parser -> ranker --[route_after_ranker]--> human_review -> END
                                  ├--------------------> screener -> scheduler -> END
                                  └--------------------> gate (auto-reject) -> END

GATE RANK (PRD §8.3, §9): conditional sau ranker route 3 nhánh — human_review (bất định), screener
(đạt ngưỡng, nhánh tự động), gate (điểm thấp SẠCH + JD bật auto_reject). Checkpointer = MemorySaver.

TODO (PRD §9/§10): GATE MỜI sau screener + Screener suspend/resume (Postgres checkpointer, NFR-2).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.nodes.gate import gate_auto_reject_node
from app.agents.nodes.human_review import human_review_node
from app.agents.nodes.parser import parser_node
from app.agents.nodes.ranker import ranker_node
from app.agents.nodes.scheduler import scheduler_node
from app.agents.nodes.screener import screener_node
from app.agents.policy import route_after_ranker
from app.agents.state import RecruitmentState


def build_graph() -> StateGraph:
    graph = StateGraph(RecruitmentState)

    graph.add_node("parser", parser_node)
    graph.add_node("ranker", ranker_node)
    graph.add_node("screener", screener_node)
    graph.add_node("scheduler", scheduler_node)
    graph.add_node("human_review", human_review_node)
    graph.add_node("gate", gate_auto_reject_node)

    graph.add_edge(START, "parser")
    graph.add_edge("parser", "ranker")

    # GATE RANK (PRD §8.3, §9): điểm rẽ nhánh sau ranker — 3 nhánh.
    graph.add_conditional_edges(
        "ranker",
        route_after_ranker,
        {"screener": "screener", "human_review": "human_review", "auto_reject": "gate"},
    )

    # Nhánh tự động (đạt ngưỡng).
    graph.add_edge("screener", "scheduler")
    graph.add_edge("scheduler", END)
    # Nhánh review (bất định).
    graph.add_edge("human_review", END)
    # Nhánh auto-reject (điểm thấp SẠCH + gate JD bật). Email từ chối gửi ở background task.
    graph.add_edge("gate", END)

    return graph


def compile_graph(checkpointer=None):
    # TODO (PRD §10/NFR-2): thay MemorySaver bằng Postgres checkpointer cho Screener suspend.
    return build_graph().compile(checkpointer=checkpointer or MemorySaver())


# Singleton dùng cho API run-demo (thread_id phân biệt mỗi lần chạy).
recruitment_graph = compile_graph()
