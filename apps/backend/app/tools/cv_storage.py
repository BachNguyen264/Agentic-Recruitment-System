"""cv_storage — KIỂM TRA file CV upload (server-side). PRD §8.2, §16, NFR-4.

Slice 06: việc LƯU đã chuyển sang seam `app/services/storage` (LocalStorage/R2Storage) — module này
giờ CHỈ còn phần validate (đuôi + size + magic bytes), dùng chung cho MỌI đường nhận CV.
"""

from __future__ import annotations

from pathlib import Path

ALLOWED_SUFFIXES = {".pdf", ".docx"}
MAX_BYTES = 10 * 1024 * 1024  # 10MB

# Magic bytes: KHÔNG tin đuôi file (nộp công khai, guest). PDF bắt đầu "%PDF"; DOCX là container
# ZIP nên bắt đầu "PK\x03\x04". Chặn .txt đội lốt .pdf ngay ở server (PRD §8.2 nộp công khai).
_PDF_MAGIC = b"%PDF"
_ZIP_MAGIC = b"PK\x03\x04"


class InvalidCV(Exception):
    """CV không hợp lệ (sai loại/nội dung/size) — route → 400."""


def validate_cv(filename: str, content: bytes) -> None:
    """Kiểm CV ở SERVER: đuôi ∈ {.pdf,.docx} + size ≤ MAX_BYTES + MAGIC BYTES khớp loại. Raise InvalidCV."""
    suffix = Path(filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise InvalidCV("Chỉ nhận CV định dạng .pdf hoặc .docx.")
    if not content:
        raise InvalidCV("File rỗng.")
    if len(content) > MAX_BYTES:
        raise InvalidCV("File quá lớn (tối đa 10MB).")
    if suffix == ".pdf" and not content.startswith(_PDF_MAGIC):
        raise InvalidCV("Nội dung không phải PDF hợp lệ.")
    if suffix == ".docx" and not content.startswith(_ZIP_MAGIC):
        raise InvalidCV("Nội dung không phải DOCX hợp lệ.")
