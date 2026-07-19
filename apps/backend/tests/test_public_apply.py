"""Test slice 07 — nộp CV công khai (guest). Tập trung phần BẢO MẬT (không chạm DB/LLM thật).

Phủ:
  1) PublicJobRead PROJECTION AN TOÀN — TUYỆT ĐỐI không lộ rubric/gate_config/screener_questions.
  2) validate_cv — chặn loại/size ở SERVER bằng MAGIC BYTES (không tin đuôi file): .txt đội lốt .pdf
     bị chặn, quá cỡ/rỗng bị chặn, PDF/DOCX hợp lệ được nhận.
  3) get_open_job — CHỈ trả JD OPEN (CLOSED/không tồn tại → None), chống nộp vào JD đã đóng.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.job_posting import JobPosting
from app.services import job_service
from app.tools import cv_storage


class FakeSession:
    def __init__(self, job: JobPosting | None) -> None:
        self._job = job

    async def get(self, _model, pk):  # noqa: ANN001
        return self._job if (self._job is not None and self._job.id == pk) else None


def _job(**overrides) -> JobPosting:
    base = dict(
        id=2,
        title="Backend Intern (Node.js)",
        description="Xây REST API.",
        requirements="Node.js\nExpress",
        rubric=[{"criterion": "Kinh nghiệm Node.js", "weight": 1.0}],
        screener_questions=["Mức lương kỳ vọng?"],
        gate_config={"auto_reject": True, "auto_invite": False},
        status="OPEN",
        embedding_ref="p1",
    )
    base.update(overrides)
    job = JobPosting(**base)
    # created_at do TimestampMixin (server_default) — set tay cho test (không qua DB).
    job.created_at = datetime.now(timezone.utc)
    job.updated_at = job.created_at
    return job


# ── 1) Projection AN TOÀN: KHÔNG lộ rubric/gate/screener ──────────────────────


def test_public_job_read_excludes_internal_fields() -> None:
    from app.schemas.job_posting import PublicJobRead

    dumped = PublicJobRead.model_validate(_job()).model_dump()

    # JD-1: thêm trường hướng-ứng-viên (level/salary/benefits/employment_type) — vẫn KHÔNG nội bộ.
    assert set(dumped) == {
        "id", "title", "description", "requirements",
        "level", "salary", "benefits", "employment_type", "created_at",
    }
    # Chốt chặn rò rỉ tiêu chí chấm/cấu hình nội bộ:
    for leaked in ("rubric", "gate_config", "screener_questions", "embedding_ref", "status"):
        assert leaked not in dumped
    assert dumped["requirements"] == "Node.js\nExpress"  # JD-1: văn bản định dạng, trả THẲNG


# ── 2) validate_cv: magic bytes ở SERVER ─────────────────────────────────────

_PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj"
_DOCX = b"PK\x03\x04\x14\x00\x06\x00" + b"\x00" * 40


def test_validate_cv_accepts_real_pdf() -> None:
    cv_storage.validate_cv("cv.pdf", _PDF)  # không raise


def test_validate_cv_accepts_real_docx() -> None:
    cv_storage.validate_cv("hoso.docx", _DOCX)


def test_validate_cv_rejects_txt_extension() -> None:
    with pytest.raises(cv_storage.InvalidCV):
        cv_storage.validate_cv("cv.txt", b"hello world")


def test_validate_cv_rejects_txt_renamed_to_pdf() -> None:
    # Đuôi .pdf nhưng nội dung KHÔNG phải PDF → magic bytes chặn (không tin đuôi).
    with pytest.raises(cv_storage.InvalidCV):
        cv_storage.validate_cv("fake.pdf", b"this is plain text, not a pdf")


def test_validate_cv_rejects_oversize() -> None:
    big = _PDF + b"0" * (cv_storage.MAX_BYTES + 1)
    with pytest.raises(cv_storage.InvalidCV):
        cv_storage.validate_cv("big.pdf", big)


def test_validate_cv_rejects_empty() -> None:
    with pytest.raises(cv_storage.InvalidCV):
        cv_storage.validate_cv("empty.pdf", b"")


# ── 3) get_open_job: chỉ JD OPEN ─────────────────────────────────────────────


async def test_get_open_job_returns_open() -> None:
    out = await job_service.get_open_job(FakeSession(_job(status="OPEN")), 2)
    assert out is not None and out.id == 2


async def test_get_open_job_rejects_closed() -> None:
    assert await job_service.get_open_job(FakeSession(_job(status="CLOSED")), 2) is None


async def test_get_open_job_missing() -> None:
    assert await job_service.get_open_job(FakeSession(None), 999) is None
