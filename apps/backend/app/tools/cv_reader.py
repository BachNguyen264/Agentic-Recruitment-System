"""cv_reader — trích văn bản thô từ CV (PDF/DOCX). PRD §7.1 (tool đọc theo định dạng).

Làm việc trên **BYTES** (slice 06): file CV có thể nằm trên đĩa (dev) hoặc Cloudflare R2 (prod) —
nguồn bytes do seam `services/storage` cung cấp, cv_reader KHÔNG mở path. Chọn bộ đọc theo ĐUÔI của
tên/key (key luôn giữ đuôi — xem `storage.build_cv_key`): PDF -> PyMuPDF (fitz), DOCX -> python-docx.
Text quá ngắn (CV ảnh scan / rỗng) -> EmptyCVTextError để node set `parse_failed` (OCR ngoài phạm vi).
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath

# Dưới ngưỡng này coi như không trích được văn bản (CV ảnh scan / file rỗng).
MIN_TEXT_CHARS = 50


class CVReadError(Exception):
    """Không đọc được CV: định dạng không hỗ trợ hoặc file lỗi/hỏng."""


class EmptyCVTextError(CVReadError):
    """Trích được quá ít text — CV có thể là ảnh scan (OCR ngoài phạm vi slice này)."""


def _extract_pdf(data: bytes) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    # stream= đọc thẳng từ bytes (không cần file tạm) — bắt buộc khi CV nằm trên object storage.
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
    return "\n".join(parts)


def _extract_docx(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def extract_text(data: bytes, name: str) -> str:
    """Trích text thô từ BYTES CV; `name` (tên file/key) chỉ dùng để chọn bộ đọc theo đuôi.

    Raise ``CVReadError``/``EmptyCVTextError`` cho ca không đọc được. KHÔNG bắt lỗi tại đây —
    node parser quyết định set `parse_failed`.
    """
    suffix = PurePosixPath(name or "").suffix.lower()

    if suffix == ".pdf":
        reader = _extract_pdf
    elif suffix == ".docx":
        reader = _extract_docx
    else:
        raise CVReadError(f"Định dạng không hỗ trợ: {suffix or '(không có đuôi)'} — chỉ nhận .pdf/.docx.")

    if not data:
        raise EmptyCVTextError("File CV rỗng — không trích được văn bản.")

    try:
        text = reader(data)
    except CVReadError:
        raise
    except Exception as exc:  # noqa: BLE001 — gói lỗi đọc file thành tín hiệu parse_failed
        raise CVReadError(f"Lỗi khi đọc {name}: {exc}") from exc

    if len(text.strip()) < MIN_TEXT_CHARS:
        raise EmptyCVTextError(
            "CV có thể là ảnh scan hoặc rỗng — không trích được văn bản (OCR ngoài phạm vi)."
        )
    return text
