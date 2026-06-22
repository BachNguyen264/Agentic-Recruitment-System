"""graph.py — pipeline LangGraph CỐ ĐỊNH (PRD §5 trụ cột 1: KHÔNG Supervisor).

    START -> parser -> ranker --[should_review]--> human_review -> END
                                  └----------------> screener -> scheduler -> END

Trong scaffold giữ tuyến tính đơn giản: conditional sau ranker route nhánh tự động
(screener -> scheduler) vs human_review. Checkpointer = MemorySaver.

TODO (PRD §9/§10): GATE MỜI sau screener + Screener suspend/resume (Postgres checkpointer, NFR-2).
"""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

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

    graph.add_edge(START, "parser")
    graph.add_edge("parser", "ranker")

    # GATE RANK (PRD §8.3): điểm rẽ nhánh DUY NHẤT trong scaffold.
    graph.add_conditional_edges(
        "ranker",
        route_after_ranker,
        {"screener": "screener", "human_review": "human_review"},
    )

    # Nhánh tự động.
    graph.add_edge("screener", "scheduler")
    graph.add_edge("scheduler", END)
    # Nhánh review.
    graph.add_edge("human_review", END)

    return graph


def compile_graph(checkpointer=None):
    # TODO (PRD §10/NFR-2): thay MemorySaver bằng Postgres checkpointer cho Screener suspend.
    return build_graph().compile(checkpointer=checkpointer or MemorySaver())


# Singleton dùng cho API run-demo (thread_id phân biệt mỗi lần chạy).
recruitment_graph = compile_graph()
