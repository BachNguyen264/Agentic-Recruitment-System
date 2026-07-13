"""runner — chạy pipeline và thu thập trace (dùng chung cho background task và tests).

Tách khỏi route để test/background gọi trực tiếp không cần HTTP.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

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
    """Chạy bất đồng bộ, thu trace từng node (cho background task xử lý mỗi CV)."""
    config = _thread_config()
    state = initial_state(
        force_review=force_review, applicant_email=applicant_email,
        application_id=application_id, cv_path=cv_path, jd=jd,
    )
    trace: list[dict[str, Any]] = []
    async for update in recruitment_graph.astream(state, config, stream_mode="updates"):
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
    final = (await recruitment_graph.aget_state(config)).values
    nodes_run = {step["node"] for step in trace}
    if "gate" in nodes_run:              # gate auto-từ-chối (PRD §9) — điểm phát email ở background.
        branch = "auto_reject"
    elif final.get("require_human_review"):
        branch = "human_review"
    else:
        # Hiện KHÔNG reachable: ca ĐẠT cũng về human_review (BUG A fix). Chừa cho auto-mời (08d);
        # nhãn "screener" (KHÔNG "auto") để audit không hiểu nhầm là đã tự lên lịch.
        branch = "screener"
    return {"branch": branch, "final": final, "trace": trace}
