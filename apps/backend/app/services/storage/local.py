"""LocalStorage — file CV trên đĩa (dev). Bọc đúng hành vi trước slice 06.

Ephemeral: mất khi redeploy → prod dùng `R2Storage`. Thư mục uploads đã gitignore (NFR-4).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services.storage import StorageError, StorageNotFound, validate_key


class LocalStorage:
    """Lưu theo key dưới một thư mục gốc. Key đã qua `validate_key` → không thoát ra ngoài gốc."""

    def __init__(self, root: str) -> None:
        self._root = Path(root)

    def _path(self, key: str) -> Path:
        path = (self._root / validate_key(key)).resolve()
        root = self._root.resolve()
        # Chốt chặn cuối (phòng khi validate_key sót): path PHẢI nằm trong gốc.
        if not path.is_relative_to(root):
            raise StorageError(f"Key thoát khỏi thư mục gốc: {key!r}")
        return path

    def _save_sync(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def save(self, key: str, data: bytes, content_type: str) -> str:
        # content_type không dùng ở đĩa (đuôi file mang thông tin) — giữ theo hợp đồng interface.
        return await asyncio.to_thread(self._save_sync, key, data)

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise StorageNotFound(f"Không tìm thấy file CV: {key}") from exc
        except OSError as exc:
            raise StorageError(f"Lỗi đọc file CV {key}: {exc}") from exc

    async def delete(self, key: str) -> None:
        path = self._path(key)
        # missing_ok=True → idempotent (xóa lại không lỗi), khớp hành vi delete_object của S3/R2.
        await asyncio.to_thread(lambda: path.unlink(missing_ok=True))

    async def url(self, key: str) -> str:
        """Path nội bộ — KHÔNG phát cho người dùng (xem ghi chú `FileStorage.url`)."""
        return str(self._path(key))
