"""Test slice 02a — JD + embedding (MOCK embed/Qdrant; không gọi API thật, không chạm DB/Neon).

Phủ: build_jd_text; gate_config mặc định TẮT; create_job set đúng cột + gọi upsert với vector
đúng chiều; embed lỗi -> JD vẫn tạo + warning (không exception); chuẩn hóa legacy ở Read;
point id ổn định. Integration thật (OpenAI) gate bằng env RUN_EMBED_IT=1.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import settings
from app.schemas.job_posting import GateConfig, JobPostingCreate, JobPostingRead, RubricCriterion
from app.services import job_service
from app.services.embedding_service import EmbeddingError, build_jd_text
from app.services.qdrant_service import jd_point_id


class FakeSession:
    """AsyncSession tối thiểu cho create_job: add/commit/refresh (refresh gán id)."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        pass

    async def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


def _payload(**overrides) -> JobPostingCreate:
    base = dict(
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements=["Node.js", "Express", "MongoDB"],
        rubric=[
            RubricCriterion(criterion="Kinh nghiệm Node.js", weight=0.6),
            RubricCriterion(criterion="Hiểu biết DB", weight=0.4),
        ],
        screener_questions=["Mức lương kỳ vọng?"],
    )
    base.update(overrides)
    return JobPostingCreate(**base)


# ── build_jd_text ────────────────────────────────────────────────────────────


def test_build_jd_text_format() -> None:
    text = build_jd_text(title="T", description="D", requirements=["r1", "  r2  ", ""])
    assert text == "T\nD\nr1\nr2"


# ── schema defaults / validation ────────────────────────────────────────────


def test_gate_config_default_off() -> None:
    jd = JobPostingCreate(title="X", description="Y")
    assert jd.gate_config == GateConfig(auto_reject=False, auto_invite=False)


def test_rubric_weight_bounds() -> None:
    with pytest.raises(ValueError):
        RubricCriterion(criterion="X", weight=1.5)
    # Tổng trọng số KHÔNG ép cứng (validate mềm) — 0.6+0.6 vẫn hợp lệ.
    _payload(rubric=[RubricCriterion(criterion="A", weight=0.6),
                     RubricCriterion(criterion="B", weight=0.6)])


def test_read_normalizes_legacy_row() -> None:
    # Row scaffold cũ: requirements=None (Text), rubric={} (dict JSONB).
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    read = JobPostingRead(
        id=1, title="Cũ", description="", requirements=None, rubric={},
        screener_questions=[], gate_config={"auto_reject": False, "auto_invite": False},
        status="OPEN", embedding_ref=None, created_at=now, updated_at=now,
    )
    assert read.requirements == []
    assert read.rubric == []
    # requirements dạng Text join "\n" tách lại đúng list.
    read2 = read.model_copy(update={"requirements": ["a", "b"]})
    assert JobPostingRead.model_validate(
        {**read2.model_dump(), "requirements": "a\nb"}
    ).requirements == ["a", "b"]


# ── create_job (mock embed + upsert) ─────────────────────────────────────────


async def test_create_job_embeds_and_upserts(monkeypatch) -> None:
    captured: dict = {}

    async def fake_embed(text: str) -> list[float]:
        captured["text"] = text
        return [0.0] * settings.embedding_dim

    async def fake_upsert(job_id: int, vector: list[float], *, title: str) -> str:
        captured["job_id"], captured["dim"], captured["title"] = job_id, len(vector), title
        return "point-ok"

    monkeypatch.setattr(job_service, "embed_text", fake_embed)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)

    job, warning = await job_service.create_job(FakeSession(), _payload())

    assert warning is None
    assert job.embedding_ref == "point-ok"
    assert job.requirements == "Node.js\nExpress\nMongoDB"  # cột Text join "\n"
    assert job.rubric == [
        {"criterion": "Kinh nghiệm Node.js", "weight": 0.6},
        {"criterion": "Hiểu biết DB", "weight": 0.4},
    ]
    assert job.gate_config == {"auto_reject": False, "auto_invite": False}
    assert captured["dim"] == settings.embedding_dim
    assert captured["job_id"] == 1 and captured["title"] == job.title
    assert captured["text"].startswith("Backend Intern (Node.js)\n")


async def test_create_job_survives_embedding_error(monkeypatch) -> None:
    async def boom(text: str) -> list[float]:
        raise EmbeddingError("OpenAI down")

    called = {"upsert": False}

    async def fake_upsert(*a, **kw) -> str:
        called["upsert"] = True
        return "x"

    monkeypatch.setattr(job_service, "embed_text", boom)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)

    job, warning = await job_service.create_job(FakeSession(), _payload())

    assert job.id == 1  # JD vẫn được lưu
    assert job.embedding_ref is None
    assert warning is not None and "CHƯA embed" in warning
    assert called["upsert"] is False  # embed hỏng thì không upsert


# ── point id ổn định ─────────────────────────────────────────────────────────


def test_jd_point_id_stable_and_distinct() -> None:
    assert jd_point_id(1) == jd_point_id(1)
    assert jd_point_id(1) != jd_point_id(2)


# ── integration thật (gate env — không chạy trong make test thường) ─────────


@pytest.mark.skipif(not os.environ.get("RUN_EMBED_IT"), reason="cần RUN_EMBED_IT=1 + OPENAI_API_KEY")
async def test_embed_text_real_dimension() -> None:
    from app.services.embedding_service import embed_text

    vector = await embed_text("Backend Intern Node.js Express REST API")
    assert len(vector) == settings.embedding_dim
