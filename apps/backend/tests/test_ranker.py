"""Test Ranker (slice 02b) — MOCK LLM + MOCK embedding (không gọi API, không chạm DB).

Phủ: điểm tổng tính lại từ criteria×weight; cờ near_threshold/weak_match/score_signal_mismatch;
điểm dưới ngưỡng → require_human_review; lỗi LLM → rank_failed không sập; lỗi embedding/Qdrant →
similarity=None nhưng VẪN chấm; build_ranker_chat xử lý đúng reasoning vs non-reasoning; node stub
khi ENABLE_LLM=false. Ref: plan §3.8, PRD §7.2.
"""

from __future__ import annotations

import pytest

from app.agents.nodes import ranker
from app.core.config import settings
from app.schemas.rank import CriterionScore, RankResult

_JD = {
    "job_id": 2,
    "title": "Backend Intern (Node.js)",
    "description": "Xây REST API với Node.js/Express, MongoDB.",
    "requirements": ["Node.js", "Express", "MongoDB"],
    "rubric": [
        {"criterion": "Kinh nghiệm Node.js", "weight": 0.6},
        {"criterion": "Hiểu biết DB", "weight": 0.4},
    ],
}
_PARSED = {
    "full_name": "Nguyen Van A",
    "skills": ["Node.js", "Express", "MongoDB"],
    "experiences": [{"title": "Backend Dev", "company": "X", "summary": "REST API"}],
}


class FakeLLM:
    def __init__(self, result: RankResult) -> None:
        self._result = result

    async def ainvoke(self, _prompt: str) -> RankResult:
        return self._result


def _result(*pairs: tuple[str, float, float], summary: str = "s") -> RankResult:
    return RankResult(
        overall_score=sum(s for _, _, s in pairs) / max(len(pairs), 1),
        criteria=[
            CriterionScore(criterion=c, weight=w, score=s, reasoning="lý do") for c, w, s in pairs
        ],
        summary=summary,
    )


@pytest.fixture(autouse=True)
def _mock_embed(monkeypatch):
    """embed_text mặc định trả vector cùng chiều JD → cosine=1.0 (sim cao)."""
    async def fake_embed(_text: str):
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ranker, "embed_text", fake_embed)


# ── điểm tổng tính lại + ca khớp ─────────────────────────────────────────────


async def test_overall_recomputed_from_weighted_criteria() -> None:
    llm = FakeLLM(_result(("Kinh nghiệm Node.js", 0.6, 90), ("Hiểu biết DB", 0.4, 70)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[1.0, 0.0, 0.0])
    assert res["score"] == 82.0  # 90*0.6 + 70*0.4 (trọng số JD, Σ=1)
    assert res["semantic_similarity"] == 1.0
    assert res["uncertainty_flags"] == []
    assert res["require_human_review"] is False
    assert res["confidence"] == 1.0
    # breakdown dùng TÊN tiêu chí authoritative từ rubric JD (không phải LLM tự echo).
    assert [c["criterion"] for c in res["score_breakdown"]] == [
        "Kinh nghiệm Node.js", "Hiểu biết DB",
    ]


def test_weighted_overall_normalizes_when_weights_not_sum_to_one() -> None:
    # Σweight = 0.5 → chuẩn hóa: (80*0.3 + 60*0.2)/0.5 = 72.0
    assert ranker._weighted_overall([
        {"score": 80, "weight": 0.3}, {"score": 60, "weight": 0.2},
    ]) == 72.0
    assert ranker._weighted_overall([]) is None  # không có tiêu chí → None


async def test_overall_uses_jd_weights_not_llm_echoed() -> None:
    # LLM echo trọng số SAI (0.1/0.9) nhưng code phải dùng trọng số JD (0.6/0.4).
    llm = FakeLLM(_result(("x", 0.1, 90), ("y", 0.9, 40)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[1.0, 0.0, 0.0])
    assert res["score"] == 70.0  # 90*0.6 + 40*0.4 (JD), KHÔNG phải 90*0.1+40*0.9=45


# ── cờ heuristic ─────────────────────────────────────────────────────────────


async def test_low_score_requires_human_review() -> None:
    llm = FakeLLM(_result(("A", 0.6, 15), ("B", 0.4, 25)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[1.0, 0.0, 0.0])
    assert res["score"] == 19.0  # < 60
    assert res["require_human_review"] is True
    assert res["escalation_reason"]


async def test_near_threshold_flag() -> None:
    # overall = 58 → |58-60| = 2 < band 10 → near_threshold. Cũng < 60 → require review.
    llm = FakeLLM(_result(("A", 0.6, 58), ("B", 0.4, 58)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[1.0, 0.0, 0.0])
    assert res["score"] == 58.0
    assert "near_threshold" in res["uncertainty_flags"]
    assert res["confidence"] <= 0.5


async def test_weak_match_when_similarity_low() -> None:
    # jd_vector trực giao với embed CV [1,0,0] → cosine=0 < 0.2 → weak_match.
    llm = FakeLLM(_result(("A", 0.6, 90), ("B", 0.4, 90)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[0.0, 1.0, 0.0])
    assert res["semantic_similarity"] == 0.0
    assert "weak_match" in res["uncertainty_flags"]


async def test_score_signal_mismatch_high_score_low_sim() -> None:
    # điểm 90 (đạt) nhưng cosine 0.0 (rất thấp) → score_signal_mismatch.
    llm = FakeLLM(_result(("A", 0.6, 90), ("B", 0.4, 90)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[0.0, 1.0, 0.0])
    assert "score_signal_mismatch" in res["uncertainty_flags"]
    assert res["require_human_review"] is False  # điểm vẫn đạt; review vì cờ (qua should_review)


# ── không sập ────────────────────────────────────────────────────────────────


async def test_llm_error_rank_failed_no_crash() -> None:
    class BoomLLM:
        async def ainvoke(self, _prompt):
            raise RuntimeError("OpenAI down")

    res = await ranker.rank_cv(_PARSED, _JD, llm=BoomLLM(), jd_vector=[1.0, 0.0, 0.0])
    assert res["uncertainty_flags"] == ["rank_failed"]
    assert res["score"] is None
    assert res["require_human_review"] is True
    assert "LLM" in res["escalation_reason"]


async def test_embedding_error_similarity_none_still_scores(monkeypatch) -> None:
    async def boom_embed(_text):
        raise RuntimeError("embedding API down")

    monkeypatch.setattr(ranker, "embed_text", boom_embed)
    llm = FakeLLM(_result(("A", 0.6, 90), ("B", 0.4, 80)))
    res = await ranker.rank_cv(_PARSED, _JD, llm=llm, jd_vector=[1.0, 0.0, 0.0])
    assert res["semantic_similarity"] is None  # tín hiệu phụ lỗi
    assert res["score"] == 86.0  # nhưng VẪN chấm được
    assert "weak_match" not in res["uncertainty_flags"]  # sim None → không suy ra cờ sim


# ── build_ranker_chat: reasoning vs non-reasoning ───────────────────────────


def test_build_ranker_chat_non_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ranker_reasoning_effort", None)
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    chat = ranker.build_ranker_chat()
    assert chat.temperature == 0


def test_build_ranker_chat_reasoning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ranker_reasoning_effort", "low")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    chat = ranker.build_ranker_chat()
    assert chat.reasoning_effort == "low"
    assert chat.temperature != 0  # KHÔNG truyền temperature cho reasoning model


# ── node stub khi ENABLE_LLM=false ──────────────────────────────────────────


async def test_ranker_node_stub_when_llm_disabled() -> None:
    # Mặc định enable_llm=False → giữ stub cũ (test_graph không vỡ).
    out = await ranker.ranker_node({"input": {"jd": _JD}, "parsed_data": _PARSED, "scratchpad": {}})
    assert out["confidence"] == 1.0
    assert "[ranker] stub" in out["messages"][0]
    assert "score" not in out


async def test_ranker_node_real_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_llm", True)
    llm = FakeLLM(_result(("A", 0.6, 90), ("B", 0.4, 80)))
    monkeypatch.setattr(ranker, "build_ranker_llm", lambda: llm)

    async def fake_vec(_job_id):
        return [1.0, 0.0, 0.0]

    monkeypatch.setattr(ranker.qdrant_service, "get_jd_vector", fake_vec)
    out = await ranker.ranker_node({"input": {"jd": _JD}, "parsed_data": _PARSED, "scratchpad": {}})
    assert out["score"] == 86.0
    assert out["semantic_similarity"] == 1.0
    assert "[ranker] score=" in out["messages"][0]
