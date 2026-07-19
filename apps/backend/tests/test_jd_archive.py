"""Test JD-4 — soft-delete (ARCHIVED) + dọn vector Qdrant + guard submit (PRD §12.1 FR-HR-JD-3).

Phủ:
  1) Service: archive_job (BẤT KỲ status → ARCHIVED) · restore_job (→ CLOSED, KHÔNG tự OPEN) · missing → None.
  2) list_jobs: mặc định ẨN ARCHIVED (status != ARCHIVED); archived=True → CHỈ ARCHIVED.
  3) delete_jd_vector: gọi Qdrant delete đúng point_id (idempotent — cho true-delete, KHÔNG cho archive).
  4) Guard submit: get_open_job REJECT ARCHIVED (nộp CV vào JD lưu-trữ → 404, KHÔNG tạo rác) end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.core.database import get_session
from app.main import app
from app.models.job_posting import JobPosting
from app.services import application_service, job_service, qdrant_service


class FakeSession:
    """AsyncSession tối thiểu: get/commit/refresh."""

    def __init__(self, job: JobPosting | None) -> None:
        self._job = job
        self.commits = 0

    async def get(self, _model, pk):  # noqa: ANN001
        return self._job if (self._job is not None and self._job.id == pk) else None

    async def commit(self) -> None:
        self.commits += 1

    async def refresh(self, _obj) -> None:
        pass


def _job(**overrides) -> JobPosting:
    base = dict(
        id=2,
        title="Backend Intern",
        description="Xây REST API.",
        requirements="Node.js",
        rubric=[{"criterion": "Kinh nghiệm Node.js", "weight": 1.0}],
        screener_questions=[],
        gate_config={"auto_reject": False, "auto_invite": False},
        status="OPEN",
        embedding_ref="p1",
    )
    base.update(overrides)
    job = JobPosting(**base)
    job.created_at = datetime.now(timezone.utc)
    job.updated_at = job.created_at
    return job


# ── 1) archive_job / restore_job ─────────────────────────────────────────────


async def test_archive_from_open_sets_archived() -> None:
    job = _job(status="OPEN")
    out = await job_service.archive_job(FakeSession(job), 2)
    assert out.status == "ARCHIVED"  # ẩn khỏi list + /apply, dữ liệu giữ nguyên


async def test_archive_from_any_status() -> None:
    for st in ("DRAFT", "CLOSED"):
        job = _job(status=st)
        out = await job_service.archive_job(FakeSession(job), 2)
        assert out.status == "ARCHIVED"


async def test_restore_sets_closed_not_open() -> None:
    # Khôi phục → CLOSED (KHÔNG tự OPEN — mở lại là hành động chủ đích theo rubric-bắt-buộc JD-2a).
    job = _job(status="ARCHIVED")
    out = await job_service.restore_job(FakeSession(job), 2)
    assert out.status == "CLOSED"


async def test_archive_restore_missing_returns_none() -> None:
    assert await job_service.archive_job(FakeSession(None), 999) is None
    assert await job_service.restore_job(FakeSession(None), 999) is None


async def test_restore_noop_on_non_archived_does_not_close_live_jd() -> None:
    # An toàn (adversarial review JD-4): restore CHỈ gỡ-lưu-trữ; gọi nhầm trên JD OPEN (stale-UI/replay)
    # KHÔNG được âm thầm đóng JD đang nhận CV.
    for st in ("OPEN", "DRAFT", "CLOSED"):
        job = _job(status=st)
        out = await job_service.restore_job(FakeSession(job), 2)
        assert out.status == st  # nguyên trạng — KHÔNG bị đổi thành CLOSED


# ── 2) list_jobs: ẩn/hiện ARCHIVED (kiểm WHERE trên câu lệnh biên dịch) ───────


class CapturingSession:
    def __init__(self) -> None:
        self.stmt = None

    async def execute(self, stmt):  # noqa: ANN001
        self.stmt = stmt
        return _EmptyResult()


class _EmptyResult:
    def scalars(self):
        return _EmptyScalars()


class _EmptyScalars:
    def all(self):
        return []


def _sql(stmt) -> str:  # noqa: ANN001
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


async def test_list_jobs_hides_archived_by_default() -> None:
    s = CapturingSession()
    await job_service.list_jobs(s)
    sql = _sql(s.stmt)
    assert "status != 'ARCHIVED'" in sql  # ẩn JD đã lưu trữ khỏi list HR mặc định


async def test_list_jobs_archived_only_when_flag() -> None:
    s = CapturingSession()
    await job_service.list_jobs(s, archived=True)
    sql = _sql(s.stmt)
    assert "status = 'ARCHIVED'" in sql  # màn "Đã lưu trữ" chỉ JD ARCHIVED


# ── 3) delete_jd_vector: seam dọn vector (true-delete) ────────────────────────


async def test_delete_jd_vector_calls_qdrant_with_point_id(monkeypatch) -> None:
    calls: dict = {}

    async def fake_delete(*, collection_name, points_selector):  # noqa: ANN001
        calls["collection"] = collection_name
        calls["points"] = list(points_selector.points)

    monkeypatch.setattr(qdrant_service.qdrant_client, "delete", fake_delete)
    await qdrant_service.delete_jd_vector(42)
    assert calls["points"] == [qdrant_service.jd_point_id(42)]  # đúng point JD 42


# ── 4) Guard submit: ARCHIVED → get_open_job None → 404, KHÔNG tạo rác ────────


async def test_get_open_job_rejects_archived() -> None:
    # JD-4: archive JD → get_open_job loại (chỉ OPEN) → /apply + nộp CV tự chặn.
    assert await job_service.get_open_job(FakeSession(_job(status="ARCHIVED")), 2) is None


def _public_client(job: JobPosting | None) -> httpx.AsyncClient:
    async def _fake_session():
        yield FakeSession(job)

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không chạm Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


_PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj" + b"0" * 100


async def test_submit_to_archived_jd_404_no_application(monkeypatch) -> None:
    created = {"n": 0}

    async def spy_create(*_a, **_k):  # phải KHÔNG được gọi (404 trước khi tạo hồ sơ)
        created["n"] += 1

    monkeypatch.setattr(application_service, "create_application", spy_create)
    async with _public_client(_job(status="ARCHIVED")) as c:
        r = await c.post(
            "/api/public/applications",
            data={"job_id": "2", "applicant_email": "guest@example.com"},
            files={"file": ("cv.pdf", _PDF, "application/pdf")},
        )
    assert r.status_code == 404  # JD lưu-trữ không nhận CV
    assert created["n"] == 0  # KHÔNG tạo Application rác


async def test_submit_missing_job_id_422_no_application(monkeypatch) -> None:
    created = {"n": 0}

    async def spy_create(*_a, **_k):
        created["n"] += 1

    monkeypatch.setattr(application_service, "create_application", spy_create)
    async with _public_client(_job()) as c:
        r = await c.post(
            "/api/public/applications",
            data={"applicant_email": "guest@example.com"},  # THIẾU job_id
            files={"file": ("cv.pdf", _PDF, "application/pdf")},
        )
    assert r.status_code == 422  # Form(...) bắt buộc → validation, KHÔNG tạo rác
    assert created["n"] == 0
