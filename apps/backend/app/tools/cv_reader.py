"""cv_reader — trích văn bản thô từ CV (PDF/DOCX). PRD §7.1 (tool đọc theo định dạng).

Làm việc trên **BYTES** (slice 06): file CV có thể nằm trên đĩa (dev) hoặc Cloudflare R2 (prod) —
nguồn bytes do seam `services/storage` cung cấp, cv_reader KHÔNG mở path. Chọn bộ đọc theo ĐUÔI của
tên/key (key luôn giữ đuôi — xem `storage.build_cv_key`): PDF -> PyMuPDF (fitz), DOCX -> python-docx.
Text quá ngắn (CV ảnh scan / rỗng) -> EmptyCVTextError để node set `parse_failed` (OCR ngoài phạm vi).
"""

from __future__ import annotations

import io
from pathlib import PurePosixPath

from app.core.config import settings

# Dưới ngưỡng này coi như không trích được văn bản (CV ảnh scan / file rỗng).
MIN_TEXT_CHARS = 50


class CVReadError(Exception):
    """Không đọc được CV: định dạng không hỗ trợ hoặc file lỗi/hỏng."""


class EmptyCVTextError(CVReadError):
    """Trích được quá ít text — CV có thể là ảnh scan (OCR ngoài phạm vi slice này)."""


def _extract_pdf(data: bytes, budget: int) -> str:
    import fitz  # PyMuPDF

    parts: list[str] = []
    taken = 0
    # stream= đọc thẳng từ bytes (không cần file tạm) — bắt buộc khi CV nằm trên object storage.
    with fitz.open(stream=data, filetype="pdf") as doc:
        for page in doc:
            parts.append(page.get_text())
            taken += len(parts[-1]) + 1  # +1 cho "\n" sẽ nối vào
            if taken >= budget:
                # DỪNG ĐỌC hẳn, không chỉ cắt kết quả cuối: mỗi `get_text()` tiếp theo vừa tốn CPU
                # vừa cấp phát thêm RAM cho phần chắc chắn bị vứt. Đây là TOÀN BỘ lý do trần nằm
                # TRONG bộ đọc chứ không phải ở `extract_text` — cắt sau khi trích xong thì 130 MB
                # đã nằm trong RAM và 18s CPU đã tiêu (xem `settings.parser_max_cv_chars`).
                break
    return "\n".join(parts)[:budget]


def _extract_docx(data: bytes, budget: int) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    taken = 0
    for para in doc.paragraphs:
        parts.append(para.text)
        taken += len(parts[-1]) + 1
        if taken >= budget:
            break
    return "\n".join(parts)[:budget]


def extract_text(data: bytes, name: str, *, max_chars: int | None = None) -> str:
    """Trích text thô từ BYTES CV; `name` (tên file/key) chỉ dùng để chọn bộ đọc theo đuôi.

    Raise ``CVReadError``/``EmptyCVTextError`` cho ca không đọc được. KHÔNG bắt lỗi tại đây —
    node parser quyết định set `parse_failed`.

    `max_chars` = TRẦN ký tự, áp BÊN TRONG bộ đọc (mặc định `settings.parser_max_cv_chars`). Chạm
    trần thì chuỗi trả về dài ĐÚNG BẰNG trần; người gọi nhận ra bằng `len(text) >= max_chars` rồi tự
    quyết gắn cờ (xem `parser.parse_cv` → `cv_truncated`). Ở đây KHÔNG raise: CV dài bất thường vẫn
    là hồ sơ ĐỌC ĐƯỢC — nó phải vào human_review, không phải bị vứt như file hỏng.
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

    budget = settings.parser_max_cv_chars if max_chars is None else max_chars
    try:
        text = reader(data, budget)
    except CVReadError:
        raise
    except Exception as exc:  # noqa: BLE001 — gói lỗi đọc file thành tín hiệu parse_failed
        raise CVReadError(f"Lỗi khi đọc {name}: {exc}") from exc

    if len(text.strip()) < MIN_TEXT_CHARS:
        raise EmptyCVTextError(
            "CV có thể là ảnh scan hoặc rỗng — không trích được văn bản (OCR ngoài phạm vi)."
        )
    return text
