"""RecruitmentState — state dùng chung của pipeline LangGraph.

Chừa SẴN chỗ kiến trúc cho 4 trụ cột (PRD §5) và Screener async (PRD §10). Ở scaffold các node
chỉ set giá trị stub. KHÔNG có logic agent thật.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class RecruitmentState(TypedDict, total=False):
    # ── Lõi ──────────────────────────────────────────────────────────
    application_id: int | None
    input: dict[str, Any]
    scratchpad: dict[str, Any]
    messages: Annotated[list[str], operator.add]  # append-only (reducer cộng dồn)
    status: str
    result: dict[str, Any] | None
    error: str | None

    # ── Parser (PRD §7.1): CV -> JSON có cấu trúc (ParsedCV.model_dump) ──
    parsed_data: dict[str, Any] | None

    # ── 4 trụ cột (PRD §5 trụ cột 3: an toàn trước case lạ) ──────────
    confidence: float
    uncertainty_flags: list[str]      # vd: parse_failed, weak_match, no_response
    escalation_reason: str | None
    require_human_review: bool

    # ── Screener bất đồng bộ (PRD §10 suspend/resume) ────────────────
    awaiting_screener: bool
    screener_answers: dict[str, Any] | None
