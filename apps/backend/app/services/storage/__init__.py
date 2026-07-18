"""Seam lưu file CV (slice 06 — PRD §16 `cv_file_ref`, NFR-4).

Nghiệp vụ **CHỈ** đi qua `FileStorage` — KHÔNG đọc/ghi path trực tiếp ở bất kỳ đâu. Đổi nơi file nằm
(đĩa dev ↔ Cloudflare R2) = đổi `STORAGE_BACKEND`, KHÔNG sửa nghiệp vụ.

- `LocalStorage` (dev): thư mục `settings.cv_upload_dir`.
- `R2Storage` (prod): Cloudflare R2 qua S3 API (boto3), **bucket PRIVATE**.

**BẢO MẬT (NFR-4):** CV là dữ liệu cá nhân. Bucket KHÔNG public; HR tải qua endpoint STREAM có
`require_hr` (slice 09). `url()` tồn tại theo hợp đồng interface nhưng KHÔNG dùng để phát CV —
xem ghi chú ở `FileStorage.url`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Protocol
from uuid import uuid4

from app.core.config import settings

__all__ = [
    "FileStorage",
    "StorageError",
    "StorageNotFound",
    "build_cv_key",
    "content_type_for",
    "get_storage",
    "validate_key",
]


class StorageError(Exception):
    """Lỗi tầng storage (I/O, cấu hình, backend từ chối)."""


class StorageNotFound(StorageError):
    """Không có object ứng với key (file đã xóa / key sai / dữ liệu cũ trước slice 06)."""


# Key phải là đường dẫn POSIX "hiền": chữ/số/._-/ và dấu "/". CHẶN traversal (`..`), path tuyệt đối,
# ổ đĩa Windows (`C:`), backslash — key đi từ DB (cv_file_ref) nên vẫn phòng thủ theo chiều sâu:
# một key bẩn sẽ khiến LocalStorage ghi/đọc NGOÀI thư mục uploads.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_DEFAULT_CONTENT_TYPE = "application/octet-stream"


def validate_key(key: str) -> str:
    """Chuẩn hóa + kiểm key. Raise `StorageError` nếu key có thể thoát khỏi gốc lưu trữ."""
    if not key or not isinstance(key, str):
        raise StorageError("Key rỗng.")
    if "\\" in key or key.startswith("/") or ".." in key.split("/"):
        raise StorageError(f"Key không hợp lệ (traversal/tuyệt đối): {key!r}")
    if not _KEY_RE.match(key):
        # Bắt luôn dữ liệu CŨ trước slice 06 (cv_file_ref là path tuyệt đối Windows) → thông báo rõ
        # thay vì đọc bừa ra ngoài thư mục gốc.
        raise StorageError(f"Key không hợp lệ: {key!r}")
    return key


def content_type_for(name: str) -> str:
    """Content-type theo đuôi file (chỉ .pdf/.docx như validate_cv cho phép)."""
    return _CONTENT_TYPES.get(PurePosixPath(name).suffix.lower(), _DEFAULT_CONTENT_TYPE)


def build_cv_key(application_id: int, original_filename: str) -> str:
    """Key CV: ``cv/{application_id}/{uuid}{đuôi}``.

    uuid tránh đè khi cùng application nộp lại; prefix theo application_id để dễ soi/dọn trên bucket.
    """
    suffix = PurePosixPath(original_filename or "").suffix.lower()
    if suffix not in _CONTENT_TYPES:
        suffix = ""
    return f"cv/{int(application_id)}/{uuid4().hex}{suffix}"


class FileStorage(Protocol):
    """Hợp đồng lưu trữ file. Mọi impl phải async (R2 = I/O mạng)."""

    async def save(self, key: str, data: bytes, content_type: str) -> str:
        """Ghi object; trả về key (giá trị lưu vào `cv_file_ref`)."""
        ...

    async def get(self, key: str) -> bytes:
        """Đọc toàn bộ bytes. Không có → `StorageNotFound`."""
        ...

    async def delete(self, key: str) -> None:
        """Xóa object. IDEMPOTENT: key không tồn tại → không lỗi."""
        ...

    async def url(self, key: str) -> str:
        """URL truy cập trực tiếp (R2: presigned hạn NGẮN; local: path nội bộ).

        ⚠️ **KHÔNG dùng để phát CV cho người dùng.** CV = dữ liệu cá nhân (NFR-4) → HR tải qua
        endpoint STREAM có `require_hr` để MỌI lượt tải đều qua kiểm đăng nhập và không rò link.
        Giữ theo hợp đồng interface cho nhu cầu tương lai (file KHÔNG nhạy cảm).
        """
        ...


@lru_cache
def get_storage() -> FileStorage:
    """Factory theo `STORAGE_BACKEND` (singleton — client R2 tái dùng)."""
    backend = (settings.storage_backend or "local").strip().lower()
    if backend == "local":
        from app.services.storage.local import LocalStorage

        return LocalStorage(settings.cv_upload_dir)
    if backend == "r2":
        from app.services.storage.r2 import R2Storage

        return R2Storage()
    raise StorageError(f"STORAGE_BACKEND không hợp lệ: {backend!r} (chỉ 'local' hoặc 'r2').")
