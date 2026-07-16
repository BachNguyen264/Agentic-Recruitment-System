"""graph.py — pipeline LangGraph CỐ ĐỊNH (PRD §5 trụ cột 1: KHÔNG Supervisor).

    START -> parser -> ranker --[route_after_ranker]--> human_review -> END
                                  ├--(đạt)-> screener ==(resume)==[route_after_screener]--> human_review -> END
                                  │                                    └--(sạch+auto_invite)-> scheduler -> END
                                  └--(điểm thấp sạch)-> gate (auto-reject) -> END

GATE RANK (PRD §8.3, §9) + SCREENER ASYNC (PRD §10) + GATE MỜI (§9, 08d): conditional sau ranker route 3
nhánh — human_review (bất định), screener (ĐẠT → suspend/resume), gate (điểm thấp SẠCH + auto_reject).
Sau screener resume, conditional route_after_screener: ca sạch + JD auto_invite → scheduler (auto-mời
thư mời THẬT ở background), else → human_review. Checkpointer = AsyncPostgresSaver ở prod (compile_graph
nhận saver; xem app/agents/checkpointer.py) — MemorySaver chỉ khi chưa setup (test/fallback).
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
from app.agents.policy import route_after_ranker, route_after_screener
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

    # Nhánh ĐẠT: screener DỪNG (suspend/resume, PRD §10). Khi RESUME xong → GATE AUTO-MỜI (PRD §9, 08d):
    # ca sạch + JD auto_invite BẬT → scheduler (auto-mời); else → human_review. route_after_screener CHỈ
    # chạy lúc resume (lần đầu interrupt() suspend TRƯỚC cạnh ra). Mặc định auto_invite TẮT → human_review.
    graph.add_conditional_edges(
        "screener",
        route_after_screener,
        {"auto_invite": "scheduler", "human_review": "human_review"},
    )
    # scheduler = node AUTO-MỜI (08d): marker SCHEDULING → background gửi thư mời thật → INTERVIEW_SCHEDULED.
    graph.add_edge("scheduler", END)
    # Nhánh review (bất định) + sau screener.
    graph.add_edge("human_review", END)
    # Nhánh auto-reject (điểm thấp SẠCH + gate JD bật). Email từ chối gửi ở background task.
    graph.add_edge("gate", END)

    return graph


def compile_graph(checkpointer=None):
    # Prod truyền AsyncPostgresSaver (Screener suspend/resume bền — PRD §10, xem checkpointer.py).
    # Không truyền → MemorySaver (test/fallback, KHÔNG bền qua restart).
    return build_graph().compile(checkpointer=checkpointer or MemorySaver())


# Singleton MemorySaver — fallback cho test/khi checkpointer Postgres chưa setup (get_graph()).
recruitment_graph = compile_graph()
