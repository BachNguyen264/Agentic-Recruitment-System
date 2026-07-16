"""runner — chạy pipeline và thu thập trace (dùng chung cho background task và tests).

Tách khỏi route để test/background gọi trực tiếp không cần HTTP.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langgraph.types import Command

from app.agents.checkpointer import get_graph
from app.agents.graph import recruitment_graph
from app.agents.state import RecruitmentState


def initial_state(*, force_review: bool = False, application_id: int | None = None,
                  applicant_email: str | None = None,
                  cv_path: str | None = None,
                  jd: dict[str, Any] | None = None) -> RecruitmentState:
    return {
        "application_id": application_id,
        "input": {
            "force_review": force_review,
            "applicant_email": applicant_email,
            "cv_path": cv_path,  # parser đọc CV từ đây (None -> parser stub)
            "jd": jd,            # ranker đọc JD từ đây (None -> ranker stub)
        },
        "scratchpad": {},
        "messages": [],
        "status": "SUBMITTED",
        "result": None,
        "error": None,
        "parsed_data": None,
        "score": None,
        "score_breakdown": None,
        "semantic_similarity": None,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "escalation_reason": None,
        "require_human_review": False,
        "awaiting_screener": False,
        "screener_answers": None,
    }


def _thread_config() -> dict[str, Any]:
    return {"configurable": {"thread_id": f"demo-{uuid.uuid4()}"}}


def _app_thread_config(application_id: int | None) -> dict[str, Any]:
    """thread_id ỔN ĐỊNH theo application_id — BẮT BUỘC khớp giữa lần chạy đầu và lúc resume để
    checkpointer tìm đúng điểm dừng (PRD §10). Không có id (demo) → thread ngẫu nhiên (không resume)."""
    tid = f"app-{application_id}" if application_id is not None else f"demo-{uuid.uuid4()}"
    return {"configurable": {"thread_id": tid}}


def _branch(*, suspended: bool, nodes_run: set[str]) -> str:
    """Nhãn nhánh cho audit/persist. suspended = đang chờ screener (AWAITING_SCREENER, chưa quyết)."""
    if suspended:
        return "screener"
    if "gate" in nodes_run:  # gate auto-từ-chối (PRD §9) — điểm phát email ở background.
        return "auto_reject"
    if "scheduler" in nodes_run:  # gate auto-MỜI (PRD §9, 08d) — thư mời THẬT gửi ở background (resume).
        return "auto_invite"
    return "human_review"  # terminal cho ca bất định VÀ ca đạt (gate mời TẮT) sau khi resume screener.


async def _stream_collect(graph: Any, graph_input: Any, config: dict[str, Any]) -> tuple[Any, list[dict[str, Any]]]:
    """astream (updates) + thu trace, BỎ QUA sự kiện `__interrupt__` (điểm suspend, không phải node
    hoàn tất — payload là tuple Interrupt, không .get được). Trả (snapshot cuối, trace)."""
    trace: list[dict[str, Any]] = []
    async for update in graph.astream(graph_input, config, stream_mode="updates"):
        if "__interrupt__" in update:  # DỪNG ở screener — xác định qua snapshot.next bên dưới.
            continue
        for node_name, partial in update.items():
            partial = partial or {}
            trace.append(
                {
                    "node": node_name,
                    "status": partial.get("status"),
                    "confidence": partial.get("confidence"),
                    "uncertainty_flags": partial.get("uncertainty_flags", []) or [],
                    "require_human_review": bool(partial.get("require_human_review", False)),
                }
            )
    snapshot = await graph.aget_state(config)
    return snapshot, trace


def run_sync(*, force_review: bool = False) -> dict[str, Any]:
    """Chạy đồng bộ (cho tests). Dùng ainvoke qua asyncio.run vì có node async (ranker).

    An toàn: chỉ được gọi từ ngữ cảnh KHÔNG có event loop (test đồng bộ) — không dùng trong route.
    """
    return asyncio.run(
        recruitment_graph.ainvoke(initial_state(force_review=force_review), _thread_config())
    )


async def run_with_trace(*, force_review: bool = False, applicant_email: str | None = None,
                         application_id: int | None = None,
                         cv_path: str | None = None,
                         jd: dict[str, Any] | None = None) -> dict[str, Any]:
    """Chạy bất đồng bộ, thu trace từng node (cho background task xử lý mỗi CV).

    Dùng `get_graph()` (prod: bản compile với AsyncPostgresSaver — suspend bền; PRD §10) + thread_id
    ỔN ĐỊNH theo application_id (để resume). Ca ĐẠT dừng ở screener → `suspended=True` (AWAITING_SCREENER).
    """
    graph = get_graph()
    config = _app_thread_config(application_id)
    state = initial_state(
        force_review=force_review, applicant_email=applicant_email,
        application_id=application_id, cv_path=cv_path, jd=jd,
    )
    snapshot, trace = await _stream_collect(graph, state, config)
    suspended = bool(snapshot.next)  # còn node chờ chạy (screener) → đang suspend, CHƯA quyết.
    branch = _branch(suspended=suspended, nodes_run={step["node"] for step in trace})
    return {"branch": branch, "final": snapshot.values, "trace": trace, "suspended": suspended}


async def resume_with_trace(*, application_id: int, resume_payload: Any) -> dict[str, Any]:
    """Resume pipeline TỪ screener (KHÔNG chạy lại parser/ranker — checkpointer nạp state cũ, PRD §10).

    Dùng cùng thread_id = application_id với lần chạy đầu. `Command(resume=...)` cấp payload cho
    `interrupt()` trong screener → node chạy tiếp → human_review → END. Trả trace + state cuối.
    """
    graph = get_graph()
    config = _app_thread_config(application_id)
    snapshot, trace = await _stream_collect(graph, Command(resume=resume_payload), config)
    suspended = bool(snapshot.next)  # bình thường False (đã tới human_review → END).
    branch = _branch(suspended=suspended, nodes_run={step["node"] for step in trace})
    return {"branch": branch, "final": snapshot.values, "trace": trace, "suspended": suspended}
