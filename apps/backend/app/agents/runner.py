"""runner — chạy pipeline và thu thập trace (dùng chung cho API run-demo và tests).

Tách khỏi route để test gọi trực tiếp không cần HTTP.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.agents.graph import recruitment_graph
from app.agents.state import RecruitmentState


def initial_state(*, force_review: bool = False, application_id: int | None = None,
                  applicant_email: str | None = None) -> RecruitmentState:
    return {
        "application_id": application_id,
        "input": {"force_review": force_review, "applicant_email": applicant_email},
        "scratchpad": {},
        "messages": [],
        "status": "SUBMITTED",
        "result": None,
        "error": None,
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
    """Chạy đồng bộ (cho tests). Trả về state cuối."""
    return recruitment_graph.invoke(initial_state(force_review=force_review), _thread_config())


async def run_with_trace(*, force_review: bool = False, applicant_email: str | None = None,
                         application_id: int | None = None) -> dict[str, Any]:
    """Chạy bất đồng bộ, thu trace từng node (cho API run-demo)."""
    config = _thread_config()
    state = initial_state(
        force_review=force_review, applicant_email=applicant_email, application_id=application_id
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
    branch = "human_review" if final.get("require_human_review") else "auto"
    return {"branch": branch, "final": final, "trace": trace}
