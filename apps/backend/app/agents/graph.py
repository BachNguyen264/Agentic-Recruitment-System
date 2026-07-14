"""graph.py — pipeline LangGraph CỐ ĐỊNH (PRD §5 trụ cột 1: KHÔNG Supervisor).

    START -> parser -> ranker --[route_after_ranker]--> human_review -> END
                                  ├--(đạt)------------> screener ==(suspend/resume)==> human_review -> END
                                  └--(điểm thấp sạch)-> gate (auto-reject) -> END

GATE RANK (PRD §8.3, §9) + SCREENER ASYNC (PRD §10): conditional sau ranker route 3 nhánh —
human_review (bất định), screener (ĐẠT ngưỡng → DỪNG hỏi ứng viên, suspend/resume, rồi human_review),
gate (điểm thấp SẠCH + JD bật auto_reject). Checkpointer = AsyncPostgresSaver ở prod (compile_graph
nhận saver; xem app/agents/checkpointer.py) — MemorySaver chỉ khi chưa setup (test/fallback).

TODO (PRD §9, 08d): GATE MỜI sau screener (auto-mời) — hiện screener → human_review (auto-mời TẮT).
`scheduler_node` giữ làm STUB dự trữ (KHÔNG reachable — mời thật đi qua human_review→notify_decision).
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

    # Nhánh ĐẠT: screener DỪNG (suspend/resume, PRD §10) → xong thì về human_review (auto-mời 08d chưa
    # xây → mặc định TẮT: HR duyệt rồi scheduler mới gửi thư MỜI thật, đường 03b+04).
    graph.add_edge("screener", "human_review")
    # scheduler_node: STUB dự trữ, KHÔNG reachable (giữ node cho slot 08d auto-mời). Không có cạnh vào.
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
