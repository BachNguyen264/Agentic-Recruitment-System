"""cv_reader — trích văn bản thô từ CV (PDF/DOCX). PRD §7.1 (tool đọc theo định dạng).

Chọn bộ đọc theo đuôi file: PDF -> PyMuPDF (fitz), DOCX -> python-docx. Đuôi khác -> lỗi rõ ràng.
Text quá ngắn (CV ảnh scan / rỗng) -> EmptyCVTextError để node set `parse_failed` (OCR ngoài phạm vi).
"""

from __future__ import annotations

from pathlib import Path

# Dưới ngưỡng này coi như không trích được văn bản (CV ảnh scan / file rỗng).
MIN_TEXT_CHARS = 50


class CVReadError(Exception):
    """Không đọc được CV: định dạng không hỗ trợ hoặc file lỗi/hỏng."""


class EmptyCVTextError(CVReadError):
    """Trích được quá ít text — CV có thể là ảnh scan (OCR ngoài phạm vi slice này)."""


def _extract_pdf(path: Path) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    with fitz.open(path) as doc:
        for page in doc:
            parts.append(page.get_text())
    return "\n".join(parts)


def _extract_docx(path: Path) -> str:
    from docx import Document

    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(path: str | Path) -> str:
    """Trích text thô từ CV. Raise ``CVReadError``/``EmptyCVTextError`` cho ca không đọc được.

    KHÔNG bắt lỗi tại đây — để node parser quyết định set `parse_failed`.
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        reader = _extract_pdf
    elif suffix == ".docx":
        reader = _extract_docx
    else:
        raise CVReadError(f"Định dạng không hỗ trợ: {suffix or '(không có đuôi)'} — chỉ nhận .pdf/.docx.")

    try:
        text = reader(path)
    except CVReadError:
        raise
    except Exception as exc:  # noqa: BLE001 — gói lỗi đọc file thành tín hiệu parse_failed
        raise CVReadError(f"Lỗi khi đọc {path.name}: {exc}") from exc

    if len(text.strip()) < MIN_TEXT_CHARS:
        raise EmptyCVTextError(
            "CV có thể là ảnh scan hoặc rỗng — không trích được văn bản (OCR ngoài phạm vi)."
        )
    return text
