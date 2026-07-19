"""Test JD-1 — trường JD mới + văn bản định dạng + BÓC HTML cho embedding/LLM (PRD §12.1, §16, §8.1).

Trọng tâm (plan §3.5):
  1) html_to_text/html_to_lines — bóc tag, giữ ranh giới đoạn/mục; plain-text đi thẳng.
  2) jd_dict — mô tả/yêu cầu HTML → PLAIN-TEXT cho ranker (tag KHÔNG lọt vào prompt LLM).
  3) SalaryInfo — min ≤ max; "thỏa thuận" bỏ qua min/max; currency mặc định VND.
  4) level/employment_type — validate tập cho phép ở Create.
  5) Trường mới lưu/đọc round-trip.
Không chạm DB/LLM/embedding thật.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.html_text import html_to_lines, html_to_text
from app.models.job_posting import JobPosting
from app.schemas.job_posting import JobPostingCreate, SalaryInfo
from app.services import job_service


# ── 1) html_to_text / html_to_lines ──────────────────────────────────────────


def test_html_to_text_strips_tags_and_keeps_lines() -> None:
    html = "<p>Xây <strong>REST API</strong></p><ul><li>Node.js</li><li>Express</li></ul>"
    assert html_to_text(html) == "Xây REST API\nNode.js\nExpress"


def test_html_to_text_plain_passthrough_and_entities() -> None:
    assert html_to_text("Node.js &amp; SQL") == "Node.js & SQL"  # giải mã entity
    assert html_to_text("  chỉ một dòng  ") == "chỉ một dòng"    # strip


def test_html_to_text_empty_and_none() -> None:
    assert html_to_text(None) == ""
    assert html_to_text("") == ""
    assert html_to_text("<p></p>") == ""  # editor rỗng


def test_html_to_lines_from_bullets() -> None:
    assert html_to_lines("<ul><li>Git</li><li>Docker</li></ul>") == ["Git", "Docker"]
    assert html_to_lines(None) == []


# ── 2) jd_dict: PLAIN-TEXT cho ranker ────────────────────────────────────────


def test_jd_dict_strips_html_for_ranker() -> None:
    job = JobPosting(
        id=7,
        title="Backend Intern",
        description="<p>Xây <em>REST API</em></p>",
        requirements="<ul><li>Node.js</li><li>MongoDB</li></ul>",
        rubric=[{"criterion": "Node.js", "weight": 1.0}],
        gate_config={"auto_reject": False, "auto_invite": False},
    )
    jd = job_service.jd_dict(job)

    # KHÔNG còn tag HTML trong đầu vào LLM.
    assert jd["description"] == "Xây REST API"
    assert "<" not in jd["description"]
    assert jd["requirements"] == ["Node.js", "MongoDB"]  # list dòng plain-text (ranker join bullet)
    assert all("<" not in r for r in jd["requirements"])


# ── 3) SalaryInfo validate ───────────────────────────────────────────────────


def test_salary_default_currency_vnd() -> None:
    s = SalaryInfo()
    assert s.currency == "VND" and s.negotiable is False and s.min is None and s.max is None


def test_salary_min_gt_max_rejected() -> None:
    with pytest.raises(ValidationError):
        SalaryInfo(min=30_000_000, max=20_000_000)


def test_salary_negotiable_bypasses_range() -> None:
    # Thỏa thuận → không ràng buộc min/max (thường bỏ trống).
    s = SalaryInfo(negotiable=True)
    assert s.negotiable is True
    # min>max nhưng negotiable → không raise (thỏa thuận thắng).
    SalaryInfo(min=30_000_000, max=20_000_000, negotiable=True)


def test_salary_valid_range_ok() -> None:
    s = SalaryInfo(min=15_000_000, max=25_000_000, currency="USD")
    assert s.min == 15_000_000 and s.max == 25_000_000 and s.currency == "USD"


# ── 4) level / employment_type: tập cho phép ─────────────────────────────────


def _create(**overrides) -> JobPostingCreate:
    base = dict(title="Backend", description="Mô tả")
    base.update(overrides)
    return JobPostingCreate(**base)


def test_level_and_employment_type_accept_allowed() -> None:
    jd = _create(level="senior", employment_type="full_time")
    assert jd.level == "senior" and jd.employment_type == "full_time"


def test_level_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _create(level="god_tier")


def test_employment_type_rejects_unknown() -> None:
    with pytest.raises(ValidationError):
        _create(employment_type="freelance_maybe")


# ── 5) Trường mới round-trip qua create_job ──────────────────────────────────


class _FakeSession:
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    def add(self, obj) -> None: ...
    async def refresh(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = 1


async def test_create_job_persists_new_fields(monkeypatch) -> None:
    async def fake_embed(text: str) -> list[float]:
        return [0.0] * 1536

    async def fake_upsert(job_id: int, vector, *, title: str) -> str:
        return "p"

    monkeypatch.setattr(job_service, "embed_text", fake_embed)
    monkeypatch.setattr(job_service.qdrant_service, "upsert_jd", fake_upsert)

    payload = _create(
        level="junior",
        salary=SalaryInfo(min=12_000_000, max=18_000_000, currency="VND"),
        benefits="<p>Bảo hiểm + thưởng</p>",
        employment_type="full_time",
        requirements="<ul><li>Python</li></ul>",
    )
    job, warning = await job_service.create_job(_FakeSession(), payload)

    assert warning is None
    assert job.level == "junior" and job.employment_type == "full_time"
    assert job.salary == {"min": 12_000_000, "max": 18_000_000, "currency": "VND", "negotiable": False}
    assert job.benefits == "<p>Bảo hiểm + thưởng</p>"   # lưu HTML thẳng (bóc tag chỉ khi embed/LLM)
    assert job.requirements == "<ul><li>Python</li></ul>"
