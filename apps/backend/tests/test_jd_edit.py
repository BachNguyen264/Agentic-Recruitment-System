"""Test slice 05 — sửa JD (re-embed CÓ ĐIỀU KIỆN) + đóng/mở JD. MOCK embed/Qdrant, không chạm DB.

Bất biến (plan §3.1): re-embed CHỈ khi title/description/requirements đổi; sửa CHỈ rubric/gate/
screener → KHÔNG gọi embedding (tránh tốn API). Lỗi embedding không làm sập cập nhật (JD vẫn lưu +
cảnh báo). Đóng/mở = đổi status, KHÔNG xóa.
"""

from __future__ import annotations

import pytest

from app.models.job_posting import JobPosting
from app.schemas.job_posting import GateConfig, JobPostingCreate, RubricCriterion
from app.services import job_service
from app.services.embedding_service import EmbeddingError


class FakeSession:
    """AsyncSession tối thiểu cho update_job/set_job_status: get/commit/refresh/rollback."""

    def __init__(self, job: JobPosting | None) -> None:
        self._job = job
        self.commits = 0
        self.rollbacks = 0

    async def get(self, _model, pk):  # noqa: ANN001
        return self._job if (self._job is not None and self._job.id == pk) else None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, _obj) -> None:
        pass


def _job(**overrides) -> JobPosting:
    base = dict(
        id=1,
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements="Node.js\nExpress\nMongoDB",  # cột Text (join "\n")
        rubric=[{"criterion": "Kinh nghiệm Node.js", "weight": 0.6},
                {"criterion": "Hiểu biết DB", "weight": 0.4}],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config={"auto_reject": False, "auto_invite": False},
        status="OPEN",
        embedding_ref="point-old",
    )
    base.update(overrides)
    return JobPosting(**base)


def _payload(**overrides) -> JobPostingCreate:
    """Payload sửa — mặc định GIỐNG HỆT _job (title/description/requirements không đổi)."""
    base = dict(
        title="Backend Intern (Node.js)",
        description="Xây REST API cho hệ thống đặt vé.",
        requirements="Node.js\nExpress\nMongoDB",  # GIỐNG _job → build_jd_text khớp → skip re-embed
        rubric=[RubricCriterion(criterion="Kinh nghiệm Node.js", weight=0.6),
                RubricCriterion(criterion="Hiểu biết DB", weight=0.4)],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config=GateConfig(auto_reject=False, auto_invite=False),
    )
    base.update(overrides)
    return JobPostingCreate(**base)


def _mock_embed(monkeypatch, called: dict) -> None:
    async def fake_embed(text: str) -> list[float]:
        called["embed"] = text
        return [0.0] * 1536

    async def fake_upsert(job_id: int, vector: list[float], *, title: str) -> str:
        called["upsert"] = job_id
        return "point-new"

    monkeypatch.setattr(job_service, "embed_text", fake_embed)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)


# ── update_job: re-embed CÓ ĐIỀU KIỆN ────────────────────────────────────────


async def test_update_reembeds_when_description_changes(monkeypatch) -> None:
    called: dict = {}
    _mock_embed(monkeypatch, called)
    session = FakeSession(_job())

    job, warning = await job_service.update_job(
        session, 1, _payload(description="Mô tả MỚI hoàn toàn khác.")
    )

    assert warning is None
    assert "embed" in called and called["upsert"] == 1  # ĐÃ re-embed
    assert job.embedding_ref == "point-new"
    assert job.description == "Mô tả MỚI hoàn toàn khác."


async def test_update_reembeds_when_requirements_change(monkeypatch) -> None:
    called: dict = {}
    _mock_embed(monkeypatch, called)
    session = FakeSession(_job())

    await job_service.update_job(
        session, 1, _payload(requirements="Node.js\nPostgreSQL\nDocker")
    )

    assert "embed" in called  # requirements đổi → re-embed


async def test_update_skips_reembed_when_only_rubric_and_gate_change(monkeypatch) -> None:
    called: dict = {}
    _mock_embed(monkeypatch, called)
    session = FakeSession(_job())

    job, warning = await job_service.update_job(
        session, 1,
        _payload(
            rubric=[RubricCriterion(criterion="Kinh nghiệm Node.js", weight=1.0)],
            gate_config=GateConfig(auto_reject=True, auto_invite=False),
        ),
    )

    assert warning is None
    assert "embed" not in called and "upsert" not in called  # KHÔNG re-embed
    assert job.rubric == [{"criterion": "Kinh nghiệm Node.js", "weight": 1.0}]
    assert job.gate_config == {"auto_reject": True, "auto_invite": False}
    assert job.embedding_ref == "point-old"  # vector cũ giữ nguyên


async def test_update_missing_job_returns_none(monkeypatch) -> None:
    called: dict = {}
    _mock_embed(monkeypatch, called)
    job, warning = await job_service.update_job(FakeSession(None), 999, _payload())
    assert job is None and warning is None


async def test_update_survives_reembed_error(monkeypatch) -> None:
    async def boom(text: str) -> list[float]:
        raise EmbeddingError("OpenAI down")

    monkeypatch.setattr(job_service, "embed_text", boom)
    session = FakeSession(_job())

    job, warning = await job_service.update_job(
        session, 1, _payload(title="Tiêu đề MỚI khác hẳn")
    )

    assert job is not None
    assert job.title == "Tiêu đề MỚI khác hẳn"  # cập nhật DB VẪN xong
    assert warning is not None and "re-embed" in warning.lower()


# ── set_job_status: đóng/mở (KHÔNG xóa) ──────────────────────────────────────


async def test_set_job_status_closes_and_reopens() -> None:
    job = _job(status="OPEN")
    session = FakeSession(job)

    out = await job_service.set_job_status(session, 1, "CLOSED")
    assert out.status == "CLOSED"

    out2 = await job_service.set_job_status(session, 1, "OPEN")
    assert out2.status == "OPEN"


async def test_set_job_status_missing_returns_none() -> None:
    assert await job_service.set_job_status(FakeSession(None), 999, "CLOSED") is None
