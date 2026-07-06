"""ranker node — THẬT (PRD §7.2). Node RA QUYẾT ĐỊNH (sau nó là routing should_review).

LLM chấm **rubric** (do HR nhập ở JD) có suy luận → điểm từng tiêu chí + lý do + điểm tổng (điểm CHÍNH).
Embedding/Qdrant chỉ là **tín hiệu phụ**: cosine CV↔JD để hiển thị + cờ mismatch — KHÔNG vào điểm.
confidence/uncertainty_flags = heuristic XÁC ĐỊNH (không hỏi LLM tự chấm). Điểm dưới ngưỡng đạt →
`require_human_review` (mặc định PRD §8.3 khi gate auto-từ-chối TẮT — KHÔNG phải gate). Lỗi LLM/Qdrant
KHÔNG làm sập pipeline.

`ENABLE_LLM=false` / thiếu JD|parsed_data → giữ hành vi stub cũ (không phá run-demo/test_graph).
"""

from __future__ import annotations

import math
from typing import Any

from app.agents.state import RecruitmentState
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import ApplicationStatus
from app.schemas.rank import RankResult
from app.services import qdrant_service
from app.services.embedding_service import build_cv_text, embed_text

logger = get_logger("app.agents.ranker")

# Ngưỡng cho tín hiệu phụ (cosine). Chỉ để sinh cờ — KHÔNG ảnh hưởng điểm.
_WEAK_SIM = 0.2           # cosine < mức này → weak_match
_MISMATCH_SIM_LOW = 0.2   # điểm đạt nhưng cosine rất thấp → nghi ngờ
_MISMATCH_SIM_HIGH = 0.5  # điểm trượt nhưng cosine cao → nghi ngờ
_OVERALL_DIVERGE = 20.0   # |điểm tính lại − điểm LLM| lớn → log (không tin mù)

_SENTINEL_FETCH: Any = object()  # jd_vector chưa truyền → tự fetch từ Qdrant

_PROMPT_TEMPLATE = """Bạn là chuyên viên tuyển dụng chấm mức phù hợp của một CV với một tin tuyển dụng (JD).

NGUYÊN TẮC:
- Chấm ĐÚNG từng tiêu chí trong RUBRIC dưới đây, theo THỨ TỰ, KHÔNG thêm/bớt tiêu chí.
- Mỗi tiêu chí: điểm 0..100 dựa trên BẰNG CHỨNG cụ thể trong CV. Thiếu bằng chứng → điểm thấp và nói rõ "CV không nêu…".
- KHÔNG bịa thông tin không có trong CV. KHÔNG suy diễn quá mức.
- `summary`: 2-3 câu tóm tắt mức phù hợp.

===== JD =====
Vị trí: {title}
Mô tả: {description}
Yêu cầu:
{requirements}

===== RUBRIC (chấm từng tiêu chí này) =====
{rubric}

===== CV ỨNG VIÊN (JSON đã bóc tách) =====
{cv}
"""


def model_label() -> str:
    """Nhãn model + chế độ — để phân biệt cấu hình khi benchmark (plan §6)."""
    effort = (settings.ranker_reasoning_effort or "").strip()
    mode = f"reasoning_effort={effort}" if effort else "temperature=0"
    return f"{settings.ranker_model} ({mode})"


def build_ranker_chat():
    """ChatOpenAI cấu hình được: reasoning (reasoning_effort) vs non-reasoning (temperature=0).

    Đổi qua lại CHỈ bằng .env (RANKER_REASONING_EFFORT) — không sửa code (plan §3.3, §6).
    """
    from langchain_openai import ChatOpenAI

    effort = (settings.ranker_reasoning_effort or "").strip()
    if effort:
        # Reasoning model (vd gpt-5-mini): dùng reasoning_effort, KHÔNG truyền temperature.
        return ChatOpenAI(
            model=settings.ranker_model,
            reasoning_effort=effort,
            api_key=settings.openai_api_key,
        )
    # Non-reasoning (vd gpt-4.1): temperature=0 cho ổn định.
    return ChatOpenAI(
        model=settings.ranker_model,
        temperature=0,
        api_key=settings.openai_api_key,
    )


def build_ranker_llm():
    """ChatOpenAI (theo env) + structured output RankResult — client chấm rubric."""
    return build_ranker_chat().with_structured_output(RankResult)


def _cosine(a: list[float] | None, b: list[float] | None) -> float | None:
    if not a or not b or len(a) != len(b):
        return None
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return None
    return round(dot / (na * nb), 4)


def _weighted_overall(criteria: list[dict]) -> float | None:
    """Điểm tổng = Σ(score×weight)/Σweight (chuẩn hóa). None nếu tổng trọng số ≤ 0."""
    total_w = sum(max(float(c.get("weight", 0)), 0.0) for c in criteria)
    if total_w <= 0:
        return None
    acc = sum(float(c.get("score", 0)) * max(float(c.get("weight", 0)), 0.0) for c in criteria)
    return round(acc / total_w, 1)


def _reconcile_criteria(
    llm_criteria: list[dict], jd_rubric: list[dict]
) -> tuple[list[dict], float | None]:
    """Ghép điểm LLM với TÊN + TRỌNG SỐ authoritative từ rubric JD — điểm auditable, KHÔNG tin
    trọng số/tên do LLM tự echo. Ghép theo thứ tự (prompt yêu cầu LLM trả đúng thứ tự rubric);
    lệch số tiêu chí → log + ghép theo min. Trả (criteria đã hợp nhất, điểm tổng có trọng số JD).
    """
    if not jd_rubric:
        return llm_criteria, _weighted_overall(llm_criteria)
    if len(llm_criteria) != len(jd_rubric):
        logger.info(
            "ranker: số tiêu chí LLM (%d) != rubric JD (%d) — ghép theo min",
            len(llm_criteria), len(jd_rubric),
        )
    merged = [
        {
            "criterion": jd_rubric[i].get("criterion"),
            "weight": float(jd_rubric[i].get("weight", 0) or 0),
            "score": float(llm_criteria[i].get("score", 0) or 0),
            "reasoning": llm_criteria[i].get("reasoning", ""),
        }
        for i in range(min(len(llm_criteria), len(jd_rubric)))
    ]
    return merged, _weighted_overall(merged)


def _flags_and_confidence(
    overall: float, similarity: float | None
) -> tuple[list[str], float, str | None]:
    """Cờ + confidence XÁC ĐỊNH từ điểm & tín hiệu phụ (plan §3.4.4)."""
    flags: list[str] = []
    caps: list[float] = []
    reasons: list[str] = []

    pass_t = settings.score_pass_threshold
    if abs(overall - pass_t) < settings.score_near_band:
        flags.append("near_threshold")
        caps.append(0.5)
        reasons.append(f"Điểm {overall}/100 sát ngưỡng {pass_t:g}")
    if similarity is not None and similarity < _WEAK_SIM:
        flags.append("weak_match")
        caps.append(0.4)
        reasons.append(f"Tương đồng ngữ nghĩa thấp (cosine={similarity})")
    if similarity is not None and (
        (overall >= pass_t and similarity < _MISMATCH_SIM_LOW)
        or (overall < pass_t and similarity > _MISMATCH_SIM_HIGH)
    ):
        flags.append("score_signal_mismatch")
        caps.append(0.45)
        reasons.append(f"Điểm rubric ({overall}) lệch tín hiệu tương đồng ({similarity})")

    confidence = round(min(caps), 2) if caps else 1.0
    escalation = "; ".join(reasons) if reasons else None
    return flags, confidence, escalation


def _failed(reason: str, similarity: float | None) -> dict:
    """Lỗi LLM chấm điểm → cờ rank_failed + require_human_review, KHÔNG sập (plan §3.4.6)."""
    return {
        "score": None,
        "score_breakdown": None,
        "summary": None,
        "semantic_similarity": similarity,
        "confidence": 0.0,
        "uncertainty_flags": ["rank_failed"],
        "escalation_reason": reason,
        "require_human_review": True,
        "model_used": model_label(),
    }


def _format_rubric(rubric: list[dict]) -> str:
    if not rubric:
        return "(JD chưa có rubric — chấm tổng thể mức phù hợp)"
    return "\n".join(
        f"- {c.get('criterion', '?')} (trọng số {c.get('weight', 0)})" for c in rubric
    )


def _build_prompt(parsed_data: dict, jd: dict) -> str:
    import json

    reqs = jd.get("requirements") or []
    return _PROMPT_TEMPLATE.format(
        title=jd.get("title", ""),
        description=jd.get("description", ""),
        requirements="\n".join(f"- {r}" for r in reqs) or "(không nêu)",
        rubric=_format_rubric(jd.get("rubric") or []),
        cv=json.dumps(parsed_data, ensure_ascii=False, indent=2),
    )


async def rank_cv(
    parsed_data: dict,
    jd: dict,
    *,
    llm: Any | None = None,
    jd_vector: Any = _SENTINEL_FETCH,
) -> dict:
    """Lõi ranker (KHÔNG chạm DB): CV + JD → điểm rubric + tín hiệu similarity + cờ.

    `jd`: {job_id, title, description, requirements: list[str], rubric: list[{criterion, weight}]}.
    `llm`/`jd_vector` cho phép inject mock trong test. Dùng chung bởi node + endpoint rank-cv.
    """
    # 1) Tín hiệu embedding (PHỤ) — lỗi Qdrant/embedding → similarity=None, KHÔNG sập.
    similarity: float | None = None
    try:
        cv_text = build_cv_text(parsed_data)
        if cv_text:
            cv_vec = await embed_text(cv_text)
            jd_vec = (
                jd_vector
                if jd_vector is not _SENTINEL_FETCH
                else await qdrant_service.get_jd_vector(int(jd["job_id"]))
            )
            similarity = _cosine(cv_vec, jd_vec)
    except Exception as exc:  # noqa: BLE001 — tín hiệu phụ, không được làm hỏng chấm điểm
        logger.warning("ranker: tín hiệu similarity lỗi (bỏ qua): %s", exc)
        similarity = None

    # 2-3) Chấm rubric (điểm CHÍNH) + tính lại điểm tổng bằng trọng số JD — lỗi LLM/parse →
    #      rank_failed, KHÔNG sập.
    try:
        client = llm or build_ranker_llm()
        result: RankResult = await client.ainvoke(_build_prompt(parsed_data, jd))
        criteria, computed = _reconcile_criteria(
            [c.model_dump() for c in result.criteria], jd.get("rubric") or []
        )
        llm_overall = float(result.overall_score)
        summary = result.summary
    except Exception as exc:  # noqa: BLE001
        logger.warning("ranker: lỗi LLM/parse khi chấm điểm: %s", exc)
        return _failed(f"Lỗi gọi LLM khi chấm điểm: {exc}", similarity)

    overall = computed if computed is not None else round(llm_overall, 1)
    if computed is not None and abs(computed - llm_overall) > _OVERALL_DIVERGE:
        logger.info("ranker: điểm tính lại lệch LLM (computed=%s, llm=%s)", computed, llm_overall)

    # 4) Cờ + confidence + quyết định escalate.
    flags, confidence, escalation = _flags_and_confidence(overall, similarity)
    require_review = overall < settings.score_pass_threshold
    if require_review and not escalation:
        escalation = (
            f"Điểm {overall}/100 dưới ngưỡng đạt {settings.score_pass_threshold:g} — "
            "cần HR xem xét (auto-từ-chối chưa bật)."
        )

    return {
        "score": overall,
        "score_breakdown": criteria,
        "summary": summary,
        "semantic_similarity": similarity,
        "confidence": confidence,
        "uncertainty_flags": flags,
        "escalation_reason": escalation,
        "require_human_review": require_review,
        "model_used": model_label(),
    }


def _stub(state: RecruitmentState) -> dict:
    """Hành vi stub cũ (giữ nguyên để không phá run-demo/test_graph khi ENABLE_LLM=false)."""
    force_review = bool((state.get("input") or {}).get("force_review"))
    if force_review:
        return {
            "status": ApplicationStatus.RANKING.value,
            "confidence": 0.5,
            "uncertainty_flags": ["weak_match"],
            "escalation_reason": "Điểm sát ngưỡng / khớp yếu (demo ép nhánh review).",
            "scratchpad": {**state.get("scratchpad", {}), "score": 0.5},
            "messages": ["[ranker] stub: confidence=0.5, flags=[weak_match] -> BẤT ĐỊNH"],
        }
    return {
        "status": ApplicationStatus.RANKING.value,
        "confidence": 1.0,
        "uncertainty_flags": [],
        "scratchpad": {**state.get("scratchpad", {}), "score": 0.9},
        "messages": ["[ranker] stub: confidence=1.0 -> đủ tự tin (nhánh tự động)"],
    }


async def ranker_node(state: RecruitmentState) -> dict:
    """Node pipeline. Lấy parsed_data (state) + jd (state.input.jd, do caller nạp từ DB)."""
    parsed_data = state.get("parsed_data")
    jd = (state.get("input") or {}).get("jd")

    if not settings.enable_llm or not parsed_data or not jd:
        return _stub(state)

    result = await rank_cv(parsed_data, jd)
    if "rank_failed" in result["uncertainty_flags"]:
        msg = f"[ranker] rank_failed — {result['escalation_reason']}"
    else:
        msg = (
            f"[ranker] score={result['score']} sim={result['semantic_similarity']} "
            f"conf={result['confidence']} flags={result['uncertainty_flags']}"
        )

    return {
        "status": ApplicationStatus.RANKING.value,
        "score": result["score"],
        "score_breakdown": result["score_breakdown"],
        "semantic_similarity": result["semantic_similarity"],
        "confidence": result["confidence"],
        "uncertainty_flags": result["uncertainty_flags"],
        "escalation_reason": result["escalation_reason"],
        "require_human_review": result["require_human_review"],
        "scratchpad": {
            **state.get("scratchpad", {}),
            "score": result["score"],
            "rank_summary": result["summary"],
        },
        "messages": [msg],
    }
