"""Test Parser (slice-01) — LLM MOCK (không gọi API thật, giữ make test nhanh + không tốn credit).

Phủ: parse CV mẫu (PDF+DOCX) với LLM mock -> lưu đúng + confidence cao; file rỗng/đuôi lạ -> parse_failed;
LLM ném exception -> parse_failed (không sập); trích text THẬT trên fixture (kiểm extractor, không mock).
Ref: plan slice-01 §3.7, PRD §7.1.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from docx import Document

from app.agents.nodes import parser as parser_mod
from app.agents.nodes.parser import _confidence, parse_cv, parser_node
from app.core.config import settings
from app.schemas.parsed_cv import (
    Certificate,
    Education,
    Experience,
    Language,
    OtherItem,
    ParsedCV,
)
from app.tools.cv_reader import EmptyCVTextError, extract_text

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _full_parsed() -> ParsedCV:
    return ParsedCV(
        full_name="Nguyễn Văn A",
        email="nguyenvana@example.com",
        phone="+84901234567",
        skills=["Python", "FastAPI", "PostgreSQL"],
        experiences=[Experience(company="Acme Corp", title="Senior Backend Engineer")],
        education=[Education(school="ĐH Bách khoa Hà Nội", degree="Cử nhân")],
        total_years_experience=5.0,
        professional_summary="Backend engineer.",
    )


class _FakeLLM:
    """Giả ChatOpenAI.with_structured_output: .invoke(prompt) -> ParsedCV cố định."""

    def __init__(self, parsed: ParsedCV) -> None:
        self._parsed = parsed

    def invoke(self, _prompt: str) -> ParsedCV:
        return self._parsed


class _BoomLLM:
    def invoke(self, _prompt: str):
        raise RuntimeError("OpenAI API down")


# ── parse_cv với LLM mock trên CV mẫu thật (extract_text chạy thật) ──────────────


def test_parse_good_docx_mocked() -> None:
    result = parse_cv(str(FIXTURES / "good_cv.docx"), llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == []
    assert result["confidence"] == 1.0  # đủ 5 trường lõi
    assert result["escalation_reason"] is None
    assert result["parsed_data"]["full_name"] == "Nguyễn Văn A"
    assert "Python" in result["parsed_data"]["skills"]


def test_parse_good_pdf_mocked() -> None:
    result = parse_cv(str(FIXTURES / "good_cv.pdf"), llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == []
    assert result["confidence"] == 1.0
    assert result["parsed_data"]["email"] == "nguyenvana@example.com"


def test_confidence_reflects_completeness() -> None:
    # Chỉ có tên + email -> 2/5 trường lõi = 0.4.
    sparse = ParsedCV(full_name="Tran Van B", email="b@example.com")
    result = parse_cv(str(FIXTURES / "sparse_cv.pdf"), llm=_FakeLLM(sparse))
    assert result["confidence"] == 0.4
    assert result["uncertainty_flags"] == []


# ── parse_failed: đuôi lạ / text rỗng / lỗi LLM ─────────────────────────────────


def test_unsupported_extension_parse_failed(tmp_path: Path) -> None:
    bad = tmp_path / "resume.txt"
    bad.write_text("noi dung khong phai pdf docx " * 5, encoding="utf-8")
    result = parse_cv(str(bad))  # không truyền llm: extract_text raise TRƯỚC khi build LLM
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0
    assert result["escalation_reason"]
    assert result["parsed_data"] is None


def test_empty_text_parse_failed(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.docx"
    doc = Document()
    doc.add_paragraph("Hi")  # < 50 ký tự -> EmptyCVTextError
    doc.save(str(tiny))
    result = parse_cv(str(tiny))
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0


def test_llm_error_parse_failed_no_crash() -> None:
    result = parse_cv(str(FIXTURES / "good_cv.pdf"), llm=_BoomLLM())
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0
    assert "LLM" in result["escalation_reason"]


# ── extract_text THẬT (không mock) — kiểm extractor PDF/DOCX ─────────────────────


def test_extract_text_real_docx() -> None:
    text = extract_text(str(FIXTURES / "good_cv.docx"))
    assert len(text.strip()) >= 50
    assert "Python" in text


def test_extract_text_real_pdf() -> None:
    text = extract_text(str(FIXTURES / "good_cv.pdf"))
    assert len(text.strip()) >= 50
    assert "Backend" in text


def test_extract_text_short_raises(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.docx"
    doc = Document()
    doc.add_paragraph("xyz")
    doc.save(str(tiny))
    try:
        extract_text(str(tiny))
        raise AssertionError("phải ném EmptyCVTextError")
    except EmptyCVTextError:
        pass


# ── parser_node: stub khi ENABLE_LLM=false; thật khi bật + có cv_path ───────────


def test_parser_node_stub_when_llm_disabled(monkeypatch) -> None:
    # Ép enable_llm=False (độc lập .env) -> giữ stub (không phá flow cũ).
    monkeypatch.setattr(settings, "enable_llm", False)
    out = parser_node({"input": {"cv_path": str(FIXTURES / "good_cv.docx")}, "scratchpad": {}})
    assert out["confidence"] == 1.0
    assert "[parser] stub" in out["messages"][0]
    assert "parsed_data" not in out


def test_parser_node_real_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_llm", True)
    monkeypatch.setattr(parser_mod, "_build_parser_llm", lambda: _FakeLLM(_full_parsed()))
    out = parser_node({"input": {"cv_path": str(FIXTURES / "good_cv.docx")}, "scratchpad": {}})
    assert out["confidence"] == 1.0
    assert out["uncertainty_flags"] == []
    assert out["parsed_data"]["full_name"] == "Nguyễn Văn A"
    assert "[parser] OK" in out["messages"][0]


# ── slice 01c: certificates / languages / awards / other ────────────────────────


def _parsed_with_extras() -> ParsedCV:
    return ParsedCV(
        full_name="Nguyen Van C",
        email="c@example.com",
        skills=["Node.js"],
        certificates=[Certificate(name="TOEIC", detail="945/990", year="2025")],
        languages=[Language(name="English", proficiency="Professional working")],
        awards=["First prize, University Hackathon 2022"],
        other=[OtherItem(label="Hobbies", content="Chess, reading tech blogs, hiking")],
    )


def test_new_blocks_passthrough() -> None:
    pd = parse_cv(str(FIXTURES / "cert_cv.pdf"), llm=_FakeLLM(_parsed_with_extras()))["parsed_data"]
    assert pd["certificates"][0] == {"name": "TOEIC", "detail": "945/990", "year": "2025"}
    assert pd["languages"][0]["name"] == "English"
    assert pd["awards"] == ["First prize, University Hackathon 2022"]
    assert pd["other"][0]["label"] == "Hobbies"


def test_certificate_not_in_other_shape() -> None:
    # Đúng SHAPE ưu tiên: chứng chỉ ở certificates, khối lạ ở other, chứng chỉ KHÔNG lẫn other.
    pd = parse_cv(str(FIXTURES / "cert_cv.pdf"), llm=_FakeLLM(_parsed_with_extras()))["parsed_data"]
    assert any(c["name"] == "TOEIC" for c in pd["certificates"])
    other_blob = " ".join(f"{o['label']} {o['content']}" for o in pd["other"]).lower()
    assert "toeic" not in other_blob
    assert "chess" in other_blob  # khối 'Hobbies' nằm ở other


def test_backward_compat_empty_new_blocks() -> None:
    # CV cũ (mock không set trường mới) -> [] mặc định; confidence GIỮ NGUYÊN (5 khối lõi).
    result = parse_cv(str(FIXTURES / "good_cv.docx"), llm=_FakeLLM(_full_parsed()))
    pd = result["parsed_data"]
    assert pd["certificates"] == [] and pd["languages"] == [] and pd["awards"] == [] and pd["other"] == []
    assert result["confidence"] == 1.0


def test_confidence_ignores_new_blocks() -> None:
    # name + email = 2/5; certificates/languages/awards/other KHÔNG cộng vào confidence.
    p = ParsedCV(
        full_name="X", email="x@y.com",
        certificates=[Certificate(name="TOEIC", detail="990")],
        languages=[Language(name="English")], awards=["a"],
        other=[OtherItem(label="l", content="c")],
    )
    assert _confidence(p) == 0.4


@pytest.mark.skipif(not os.environ.get("RUN_PARSE_IT"), reason="cần RUN_PARSE_IT=1 + OPENAI_API_KEY")
def test_certificates_extracted_real() -> None:
    # LLM THẬT trên cert_cv.pdf: TOEIC vào certificates, KHÔNG lọt other (kiểm ưu tiên thật).
    pd = parse_cv(str(FIXTURES / "cert_cv.pdf"))["parsed_data"]
    assert "toeic" in " ".join(c["name"] for c in pd["certificates"]).lower()
    other_blob = " ".join(f"{o['label']} {o['content']}" for o in pd["other"]).lower()
    assert "toeic" not in other_blob
