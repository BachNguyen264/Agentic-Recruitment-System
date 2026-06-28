"""cv_storage — lưu file CV upload (dev: local). PRD §16 (cv_file_ref).

# TODO (production): chuyển sang object storage (S3/Cloudinary). Lát này lưu local trong
# ``settings.cv_upload_dir`` (đã gitignore — CV là dữ liệu cá nhân, NFR-4).
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import settings

ALLOWED_SUFFIXES = {".pdf", ".docx"}


def save_cv(application_id: int, original_filename: str, content: bytes) -> str:
    """Ghi file CV ra đĩa, tên theo application_id + đuôi gốc. Trả về đường dẫn (cv_file_ref)."""
    suffix = Path(original_filename or "").suffix.lower()
    dest_dir = Path(settings.cv_upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{application_id}{suffix}"
    dest.write_bytes(content)
    return str(dest)
