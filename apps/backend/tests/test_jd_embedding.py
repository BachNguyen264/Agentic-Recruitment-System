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
    """AsyncSession tối thiểu cho create_job: add/commit/refresh/rollback (refresh gán id).

    ``fail_commit_at``: commit thứ N ném lỗi (mô phỏng Neon rớt kết nối lúc lưu embedding_ref).
    """

    def __init__(self, *, fail_commit_at: int | None = None) -> None:
        self.added: list = []
        self.commits = 0
        self.rollbacks = 0
        self._fail_commit_at = fail_commit_at

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1
        if self._fail_commit_at is not None and self.commits == self._fail_commit_at:
            raise ConnectionError("mất kết nối DB (giả lập)")

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


def _payload(**overrides) -> JobPostingCreate:
    base = dict(
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements="Node.js\nExpress\nMongoDB",  # JD-1: văn bản định dạng (không còn list)
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
    text = build_jd_text(title="T", description="D", requirements="r1\n  r2  \n")
    assert text == "T\nD\nr1\nr2"


def test_build_jd_text_strips_html() -> None:
    # JD-1 GOTCHA: tag định dạng TUYỆT ĐỐI không lọt vào embedding (nhiễu vector).
    text = build_jd_text(
        title="Backend",
        description="<p>Xây <strong>REST API</strong></p>",
        requirements="<ul><li>Node.js</li><li>Express</li></ul>",
    )
    assert "<" not in text and ">" not in text
    assert "strong" not in text and "<li" not in text
    assert text == "Backend\nXây REST API\nNode.js\nExpress"


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
    # Row scaffold cũ (trước JD-1): requirements/benefits=None (Text), salary=None (JSONB),
    # rubric={} (dict JSONB). Read chuẩn hóa mềm để không vỡ khi đọc JD legacy.
    from datetime import datetime, timezone

    from app.schemas.job_posting import SalaryInfo

    now = datetime.now(timezone.utc)
    read = JobPostingRead(
        id=1, title="Cũ", description="", requirements=None, benefits=None, salary=None, rubric={},
        screener_questions=[], gate_config={"auto_reject": False, "auto_invite": False},
        status="OPEN", embedding_ref=None, created_at=now, updated_at=now,
    )
    assert read.requirements == "" and read.benefits == ""  # None → ""
    assert read.salary == SalaryInfo()  # None → mặc định (VND, không thỏa thuận)
    assert read.level is None and read.employment_type is None
    assert read.rubric == []
    # JD-1: requirements là văn bản định dạng — lưu/đọc THẲNG (không còn tách list).
    assert JobPostingRead.model_validate(
        {**read.model_dump(), "requirements": "<p>a</p><p>b</p>"}
    ).requirements == "<p>a</p><p>b</p>"


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
    assert job.status == "DRAFT"  # JD-2a: JD mới = nháp (MỞ cần rubric riêng)
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


async def test_create_job_second_commit_failure_consistent(monkeypatch) -> None:
    """Commit lưu embedding_ref fail → rollback + ref reset None (response khớp DB)."""

    async def fake_embed(text: str) -> list[float]:
        return [0.0] * settings.embedding_dim

    async def fake_upsert(job_id: int, vector: list[float], *, title: str) -> str:
        return "point-ok"

    monkeypatch.setattr(job_service, "embed_text", fake_embed)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)

    session = FakeSession(fail_commit_at=2)  # commit 1 = lưu JD OK; commit 2 = lưu ref FAIL
    job, warning = await job_service.create_job(session, _payload())

    assert job.embedding_ref is None  # KHÔNG trả point id khi DB chưa ghi được
    assert warning is not None
    assert session.rollbacks == 1


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
