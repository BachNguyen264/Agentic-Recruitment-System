"""Test Parser (slice-01) — LLM MOCK (không gọi API thật, giữ make test nhanh + không tốn credit).

Phủ: parse CV mẫu (PDF+DOCX) với LLM mock -> lưu đúng + confidence cao; file rỗng/đuôi lạ -> parse_failed;
LLM ném exception -> parse_failed (không sập); trích text THẬT trên fixture (kiểm extractor, không mock).
Ref: plan slice-01 §3.7, PRD §7.1.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from docx import Document

from app.agents.nodes import parser as parser_mod
from app.agents.nodes.parser import _confidence, parse_cv, parser_node
from app.core.config import settings
from app.services.storage import StorageNotFound
from app.schemas.parsed_cv import (
    Certificate,
    Education,
    Experience,
    Language,
    OtherItem,
    ParsedCV,
)
from app.tools.cv_reader import MIN_TEXT_CHARS, CVReadError, EmptyCVTextError, extract_text

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
# Slice 06: parse_cv nhận BYTES + tên (chọn bộ đọc theo đuôi) — không còn mở path.


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_good_docx_mocked() -> None:
    result = parse_cv(_fixture("good_cv.docx"), "good_cv.docx", llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == []
    assert result["confidence"] == 1.0  # đủ 5 trường lõi
    assert result["escalation_reason"] is None
    assert result["parsed_data"]["full_name"] == "Nguyễn Văn A"
    assert "Python" in result["parsed_data"]["skills"]


def test_parse_good_pdf_mocked() -> None:
    result = parse_cv(_fixture("good_cv.pdf"), "good_cv.pdf", llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == []
    assert result["confidence"] == 1.0
    assert result["parsed_data"]["email"] == "nguyenvana@example.com"


def test_parse_works_with_storage_key_name() -> None:
    """Tên truyền vào có thể là KEY storage (cv/1/<uuid>.pdf) — vẫn chọn đúng bộ đọc theo đuôi."""
    result = parse_cv(_fixture("good_cv.pdf"), "cv/1/abc123.pdf", llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == []
    assert result["parsed_data"]["full_name"] == "Nguyễn Văn A"


def test_confidence_reflects_completeness() -> None:
    # Chỉ có tên + email -> 2/5 trường lõi = 0.4.
    sparse = ParsedCV(full_name="Tran Van B", email="b@example.com")
    result = parse_cv(_fixture("sparse_cv.pdf"), "sparse_cv.pdf", llm=_FakeLLM(sparse))
    assert result["confidence"] == 0.4
    assert result["uncertainty_flags"] == []


# ── parse_failed: đuôi lạ / text rỗng / lỗi LLM ─────────────────────────────────


def test_unsupported_extension_parse_failed() -> None:
    # không truyền llm: extract_text raise TRƯỚC khi build LLM
    result = parse_cv(b"noi dung khong phai pdf docx " * 5, "resume.txt")
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0
    assert result["escalation_reason"]
    assert result["parsed_data"] is None


def test_empty_text_parse_failed(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.docx"
    doc = Document()
    doc.add_paragraph("Hi")  # < 50 ký tự -> EmptyCVTextError
    doc.save(str(tiny))
    result = parse_cv(tiny.read_bytes(), "tiny.docx")
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0


def test_llm_error_parse_failed_no_crash() -> None:
    result = parse_cv(_fixture("good_cv.pdf"), "good_cv.pdf", llm=_BoomLLM())
    assert result["uncertainty_flags"] == ["parse_failed"]
    assert result["confidence"] == 0.0
    assert "LLM" in result["escalation_reason"]


# ── extract_text THẬT (không mock) — kiểm extractor PDF/DOCX từ BYTES ────────────


def test_extract_text_real_docx() -> None:
    text = extract_text(_fixture("good_cv.docx"), "good_cv.docx")
    assert len(text.strip()) >= 50
    assert "Python" in text


def test_extract_text_real_pdf() -> None:
    text = extract_text(_fixture("good_cv.pdf"), "good_cv.pdf")
    assert len(text.strip()) >= 50
    assert "Backend" in text


def test_extract_text_short_raises(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.docx"
    doc = Document()
    doc.add_paragraph("xyz")
    doc.save(str(tiny))
    try:
        extract_text(tiny.read_bytes(), "tiny.docx")
        raise AssertionError("phải ném EmptyCVTextError")
    except EmptyCVTextError:
        pass


# ── parser_node: stub khi ENABLE_LLM=false; thật khi bật + có key CV ────────────
# Slice 06: node là ASYNC và lấy bytes qua seam storage (mock ở đây — không chạm đĩa/R2).


class _FakeStorage:
    """Storage giả: trả bytes cố định cho mọi key (hoặc ném lỗi để test nhánh hỏng)."""

    def __init__(self, data: bytes | None = None, error: Exception | None = None) -> None:
        self._data = data
        self._error = error
        self.asked: list[str] = []

    async def get(self, key: str) -> bytes:
        self.asked.append(key)
        if self._error:
            raise self._error
        return self._data or b""


async def test_parser_node_stub_when_llm_disabled(monkeypatch) -> None:
    # Ép enable_llm=False (độc lập .env) -> giữ stub (không phá flow cũ).
    monkeypatch.setattr(settings, "enable_llm", False)
    out = await parser_node({"input": {"cv_path": "cv/1/x.docx"}, "scratchpad": {}})
    assert out["confidence"] == 1.0
    assert "[parser] stub" in out["messages"][0]
    assert "parsed_data" not in out


async def test_parser_node_real_reads_via_storage(monkeypatch) -> None:
    monkeypatch.setattr(settings, "enable_llm", True)
    monkeypatch.setattr(parser_mod, "_build_parser_llm", lambda: _FakeLLM(_full_parsed()))
    storage = _FakeStorage(_fixture("good_cv.docx"))
    monkeypatch.setattr(parser_mod, "get_storage", lambda: storage)

    out = await parser_node({"input": {"cv_path": "cv/7/abc.docx"}, "scratchpad": {}})

    assert storage.asked == ["cv/7/abc.docx"]  # ĐỌC QUA SEAM, không mở path
    assert out["confidence"] == 1.0
    assert out["uncertainty_flags"] == []
    assert out["parsed_data"]["full_name"] == "Nguyễn Văn A"
    assert "[parser] OK" in out["messages"][0]


async def test_parser_node_does_not_block_event_loop(monkeypatch) -> None:
    """parse_cv là ĐỒNG BỘ (PyMuPDF + gọi LLM sync). Node async PHẢI offload nó sang thread.

    Trước slice 06 node là `def` nên LangGraph tự chạy trong thread executor; đổi sang `async def`
    làm mất cơ chế đó → nếu gọi thẳng, một CV sẽ CHẶN toàn bộ event loop (mọi request khác đứng
    hình vài giây). Test này canh nhịp một task nền: bị chặn thì nó gần như không chạy được vòng nào.
    """
    import asyncio
    import time

    monkeypatch.setattr(settings, "enable_llm", True)
    monkeypatch.setattr(parser_mod, "get_storage", lambda: _FakeStorage(b"x"))

    def _slow_blocking_parse(_data, _name, **_kw):
        time.sleep(0.30)  # mô phỏng trích PDF + gọi LLM (đồng bộ, chặn)
        return {"parsed_data": None, "confidence": 0.0, "uncertainty_flags": [], "escalation_reason": None}

    monkeypatch.setattr(parser_mod, "parse_cv", _slow_blocking_parse)

    ticks = 0

    async def _heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(_heartbeat())
    await parser_node({"input": {"cv_path": "cv/1/a.pdf"}, "scratchpad": {}})
    beat.cancel()

    # Không chặn → heartbeat chạy được nhiều vòng trong 0.3s. Chặn → gần như 0.
    assert ticks >= 5, f"event loop bị CHẶN trong lúc parse (chỉ {ticks} nhịp) — phải offload sang thread"


async def test_parser_node_storage_error_parse_failed_no_crash(monkeypatch) -> None:
    """Mất file / R2 lỗi / key cũ → parse_failed + escalation, KHÔNG sập pipeline (PRD §7.1)."""
    monkeypatch.setattr(settings, "enable_llm", True)
    storage = _FakeStorage(error=StorageNotFound("không tìm thấy"))
    monkeypatch.setattr(parser_mod, "get_storage", lambda: storage)

    out = await parser_node({"input": {"cv_path": "cv/9/missing.pdf"}, "scratchpad": {}})

    assert out["uncertainty_flags"] == ["parse_failed"]
    assert out["confidence"] == 0.0
    assert "storage" in out["escalation_reason"].lower()


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
    pd = parse_cv(_fixture("cert_cv.pdf"), "cert_cv.pdf", llm=_FakeLLM(_parsed_with_extras()))["parsed_data"]
    assert pd["certificates"][0] == {"name": "TOEIC", "detail": "945/990", "year": "2025"}
    assert pd["languages"][0]["name"] == "English"
    assert pd["awards"] == ["First prize, University Hackathon 2022"]
    assert pd["other"][0]["label"] == "Hobbies"


def test_certificate_not_in_other_shape() -> None:
    # Đúng SHAPE ưu tiên: chứng chỉ ở certificates, khối lạ ở other, chứng chỉ KHÔNG lẫn other.
    pd = parse_cv(_fixture("cert_cv.pdf"), "cert_cv.pdf", llm=_FakeLLM(_parsed_with_extras()))["parsed_data"]
    assert any(c["name"] == "TOEIC" for c in pd["certificates"])
    other_blob = " ".join(f"{o['label']} {o['content']}" for o in pd["other"]).lower()
    assert "toeic" not in other_blob
    assert "chess" in other_blob  # khối 'Hobbies' nằm ở other


def test_backward_compat_empty_new_blocks() -> None:
    # CV cũ (mock không set trường mới) -> [] mặc định; confidence GIỮ NGUYÊN (5 khối lõi).
    result = parse_cv(_fixture("good_cv.docx"), "good_cv.docx", llm=_FakeLLM(_full_parsed()))
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
    pd = parse_cv(_fixture("cert_cv.pdf"), "cert_cv.pdf")["parsed_data"]
    assert "toeic" in " ".join(c["name"] for c in pd["certificates"]).lower()
    other_blob = " ".join(f"{o['label']} {o['content']}" for o in pd["other"]).lower()
    assert "toeic" not in other_blob


# ── A1: trần ký tự khi trích (settings.parser_max_cv_chars) ─────────────────────
# Vì sao có nhóm test này: một PDF 0.918 MB HỢP LỆ trích ra 12.46 TRIỆU ký tự (~3.1M token, ~260 MB
# RAM) qua endpoint nộp CV CÔNG KHAI. Trần phải áp BÊN TRONG bộ đọc, và cờ `cv_truncated` phải SỐNG
# SÓT qua ranker — nếu không, hồ sơ CV-bị-cắt lọt gate auto-mời với điểm cao.


def _fat_docx(paragraphs: int, chars_each: int) -> bytes:
    import io as _io

    doc = Document()
    for _ in range(paragraphs):
        doc.add_paragraph("x" * chars_each)
    buf = _io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_extract_text_caps_at_budget() -> None:
    """Trần áp trong bộ đọc: 200 đoạn × 1000 ký tự = ~200k, xin 5k thì nhận đúng 5k."""
    data = _fat_docx(paragraphs=200, chars_each=1000)
    text = extract_text(data, "fat.docx", max_chars=5_000)
    assert len(text) == 5_000


def test_extract_text_below_budget_untouched() -> None:
    """CV bình thường KHÔNG bị đụng tới — trần chỉ được cắt file bất thường."""
    full = extract_text(_fixture("good_cv.docx"), "good_cv.docx", max_chars=1_000_000)
    assert len(full) < 1_000_000
    assert full == extract_text(_fixture("good_cv.docx"), "good_cv.docx")


def test_parse_cv_flags_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chạm trần → cờ cv_truncated + escalation_reason, nhưng VẪN parse (không phải parse_failed)."""
    monkeypatch.setattr(settings, "parser_max_cv_chars", 3_000)
    data = _fat_docx(paragraphs=100, chars_each=1000)
    result = parse_cv(data, "fat.docx", llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == ["cv_truncated"]
    assert "parse_failed" not in result["uncertainty_flags"]
    assert result["parsed_data"] is not None  # vẫn chấm được, chỉ là trên phần đầu
    assert result["escalation_reason"]


def test_parse_cv_normal_has_no_truncated_flag() -> None:
    result = parse_cv(_fixture("good_cv.docx"), "good_cv.docx", llm=_FakeLLM(_full_parsed()))
    assert "cv_truncated" not in result["uncertainty_flags"]


@pytest.mark.asyncio
async def test_ranker_carries_cv_truncated_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """BẤT BIẾN: ranker thay mới toàn bộ uncertainty_flags — cờ cv_truncated phải được CHỞ QUA.

    Không có test này thì cờ biến mất im lặng và `policy.should_review` không còn kéo hồ sơ về
    human_review ⇒ CV bị cắt mất phần cuối lọt thẳng gate auto-mời với điểm cao.
    """
    from app.agents.nodes import ranker as ranker_mod

    async def _fake_rank(parsed_data, jd):  # noqa: ANN001, ARG001
        return {
            "score": 92.0,
            "score_breakdown": [],
            "summary": "ok",
            "semantic_similarity": 0.9,
            "confidence": 1.0,
            "uncertainty_flags": [],          # ranker tự thấy SẠCH
            "escalation_reason": None,
            "require_human_review": False,    # điểm cao → sẽ đi gate nếu không có cờ
            "model_used": "test",
        }

    monkeypatch.setattr(settings, "enable_llm", True)
    monkeypatch.setattr(ranker_mod, "rank_cv", _fake_rank)
    state = {
        "parsed_data": {"full_name": "A"},
        "input": {"jd": {"title": "BE"}},
        "uncertainty_flags": ["cv_truncated"],
        "escalation_reason": "CV dài bất thường — chỉ đọc phần đầu.",
    }
    out = await ranker_mod.ranker_node(state)
    assert "cv_truncated" in out["uncertainty_flags"], "ranker đã NUỐT cờ của parser"
    assert out["escalation_reason"], "human_review sẽ nhận thẻ không có lý do"

    from app.agents.policy import should_review

    assert should_review({**state, **out}) is True  # cờ thắng gate (PRD §9)


# ── Chốt trên: file dựng để PHÁ (review sau AUDIT-1 — cả hai lỗ đều ĐO ĐƯỢC, không phải suy đoán) ──


def _zip_bomb_docx(xml_mb: int = 60) -> bytes:
    """.docx hợp lệ mà `word/document.xml` phình ra `xml_mb` MB sau giải nén (tỉ lệ ~700:1)."""
    import zipfile as _z

    body = "<w:p><w:r><w:t>" + "A" * 4000 + "</w:t></w:r></w:p>"
    n = (xml_mb * 1024 * 1024) // len(body) + 1
    xml = (
        '<?xml version="1.0"?><w:document '
        'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
        + body * n
        + "</w:body></w:document>"
    )
    buf = io.BytesIO()
    with _z.ZipFile(buf, "w", _z.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return buf.getvalue()


def test_docx_zip_bomb_rejected_before_parsing() -> None:
    """.docx nén cao bị chặn ở TIỀN KIỂM, trước khi python-docx dựng lxml.

    Đo được trên bản chưa vá: .docx 442 KB chứa XML 116.5 MB làm RSS tăng **+639 MB** — đủ OOM một
    instance Render 512 MB bằng MỘT lượt upload qua endpoint CÔNG KHAI. Trần ký tự KHÔNG cản được vì
    `Document()` giải nén toàn bộ TRƯỚC khi vòng `break` chạy.
    """
    bomb = _zip_bomb_docx(xml_mb=60)
    assert len(bomb) < 1_000_000, "file mồi phải nhỏ — đó là toàn bộ vấn đề"
    with pytest.raises(CVReadError) as exc:
        extract_text(bomb, "bomb.docx")
    assert "giải nén quá lớn" in str(exc.value)


def test_docx_under_uncompressed_cap_still_parses() -> None:
    """Trần giải nén KHÔNG được chặn nhầm .docx thật."""
    text = extract_text(_fixture("good_cv.docx"), "good_cv.docx")
    assert len(text) > MIN_TEXT_CHARS


def test_corrupt_zip_becomes_cv_read_error() -> None:
    """ZIP hỏng → CVReadError (đi chung đường parse_failed), KHÔNG phải traceback lạ."""
    with pytest.raises(CVReadError):
        extract_text(b"PK\x03\x04" + b"rac" * 50, "hong.docx")


def test_extract_text_bounded_kills_runaway_extraction() -> None:
    """Hạn giờ CỨNG: chi phí bố cục PyMuPDF là BẬC HAI theo glyph (đo: PDF 1 trang 6.6 KB → 90s),
    và PyMuPDF không nhả GIL nên `asyncio.to_thread` KHÔNG cô lập được — event loop đứng theo, kể cả
    `/api/health/live`, và Render giết cả service. Chỉ tiến trình GIẾT ĐƯỢC mới chặn nổi.

    Dùng hạn giờ cực nhỏ trên CV THẬT để phép kiểm XÁC ĐỊNH (không phụ thuộc tốc độ máy chạy CI).
    """
    import time as _t

    from app.tools.cv_reader import extract_text_bounded

    original = settings.parser_extract_timeout_seconds
    settings.parser_extract_timeout_seconds = 0.01
    try:
        started = _t.perf_counter()
        with pytest.raises(CVReadError) as exc:
            extract_text_bounded(_fixture("good_cv.pdf"), "good_cv.pdf")
        assert "quá hạn" in str(exc.value)
        assert _t.perf_counter() - started < 30, "hạn giờ không cắt được — đã treo"
    finally:
        settings.parser_extract_timeout_seconds = original


def test_extract_text_bounded_returns_normally_for_real_cv() -> None:
    """Đường bình thường phải y hệt `extract_text` — bọc tiến trình không được đổi kết quả."""
    from app.tools.cv_reader import extract_text_bounded

    got = extract_text_bounded(_fixture("good_cv.docx"), "good_cv.docx")
    assert got.text == extract_text(_fixture("good_cv.docx"), "good_cv.docx")
    assert got.hidden_chars == 0


# ── Chốt việc DỪNG SỚM + biên chính xác (bắt lỗi off-by-one) ────────────────────────────────────


def test_reader_stops_early_instead_of_reading_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    """BẤT BIẾN: bộ đọc phải DỪNG khi đủ trần, không đọc hết rồi mới cắt.

    Không có test này thì viết lại thành `"\n".join(mọi trang)[:budget]` vẫn XANH toàn bộ suite —
    và bản "gọn hơn" đó tốn 421s + 382 MB trên PDF 2.000 trang mà trả về chuỗi GIỐNG HỆT từng byte.
    Test khẳng định CÔNG VIỆC ĐÃ TRÁNH, không phải kết quả.
    """
    import docx as _docx

    import app.tools.cv_reader as mod

    read = {"n": 0}

    class _Para:
        text = "x" * 500

        def iter_inner_content(self):  # noqa: ANN202 — không run nào ⇒ không chữ ẩn
            return []

    class _Element:
        def find(self, _tag):  # noqa: ANN001, ANN202 — không có nền trang
            return None

    class _Doc:
        element = _Element()

        @property
        def paragraphs(self):  # noqa: ANN202
            def gen():
                for _ in range(10_000):
                    read["n"] += 1  # đếm khi CONSUMER thật sự kéo đoạn tiếp theo
                    yield _Para()

            return gen()

    monkeypatch.setattr(_docx, "Document", lambda _f: _Doc())
    # Trần 1.000 ⇒ 2 đoạn × 500 ký tự là đủ. Kéo tới đoạn thứ 4 nghĩa là `break` không chạy.
    mod._extract_docx(_minimal_docx_zip(), 1_000)
    assert read["n"] <= 3, f"đọc {read['n']}/10.000 đoạn cho trần 1.000 — KHÔNG dừng sớm"


def _minimal_docx_zip() -> bytes:
    """.docx tối thiểu qua được tiền kiểm ZIP (nội dung không quan trọng — `Document` đã bị thay)."""
    import zipfile as _z

    buf = io.BytesIO()
    with _z.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def test_truncation_flag_fires_exactly_at_budget_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    """BIÊN: cộng `+1` cho MỌI phần làm `taken` lệch 1 ⇒ trả về `budget-1` ký tự ⇒
    `len(text) >= budget` là False ⇒ CV BỊ CẮT mà KHÔNG có cờ `cv_truncated`, tức vô hiệu hoá đúng
    cái chốt "CV mất phần cuối không được lọt gate auto". Test này ĐỎ trên bản chưa sửa."""
    doc = Document()
    for _ in range(50):
        doc.add_paragraph("y" * 999)  # 999 + 1 dấu xuống dòng = bội số tròn của 1.000
    buf = io.BytesIO()
    doc.save(buf)
    data = buf.getvalue()

    text = extract_text(data, "bien.docx", max_chars=5_000)
    assert len(text) == 5_000, f"trả về {len(text)} ký tự thay vì đúng 5.000"

    # `parse_cv` đọc trần từ settings — phải hạ trần thì mới chạm được đúng cái biên đang kiểm.
    monkeypatch.setattr(settings, "parser_max_cv_chars", 5_000)
    result = parse_cv(data, "bien.docx", llm=_FakeLLM(_full_parsed()))
    assert result["uncertainty_flags"] == ["cv_truncated"], (
        "CV bị cắt ở đúng biên mà KHÔNG có cờ — gate auto sẽ xử lý một hồ sơ thiếu phần cuối"
    )
