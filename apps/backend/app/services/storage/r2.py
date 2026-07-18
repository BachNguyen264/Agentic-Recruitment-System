"""R2Storage — file CV trên Cloudflare R2 (S3 API, boto3). Prod: BỀN qua restart/redeploy.

**Bucket PRIVATE** (NFR-4 — CV là dữ liệu cá nhân): không public-read; HR tải qua endpoint STREAM
có `require_hr`. Credentials CHỈ từ env (`R2_*`).

boto3 là ĐỒNG BỘ → mọi lời gọi bọc `asyncio.to_thread` (nhất quán với `email_service`) để không
chặn event loop. Client tạo LƯỜI (một lần) — client boto3 an toàn dùng lại cho nhiều lời gọi.
"""

from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.services.storage import StorageError, StorageNotFound, validate_key

logger = get_logger("app.storage.r2")

# Mã lỗi S3/R2 nghĩa là "không có object" → ánh xạ sang StorageNotFound.
_NOT_FOUND_CODES = {"404", "NoSuchKey", "NotFound"}
# Hạn presigned URL nếu ai đó dùng `url()` — RẤT ngắn (CV nhạy cảm). Đường phát CV chính vẫn là stream.
_PRESIGN_TTL_SECONDS = 120


class R2Storage:
    def __init__(self) -> None:
        endpoint = settings.r2_endpoint_url
        missing = [
            name
            for name, value in (
                ("R2_ACCESS_KEY_ID", settings.r2_access_key_id),
                ("R2_SECRET_ACCESS_KEY", settings.r2_secret_access_key),
                ("R2_BUCKET", settings.r2_bucket),
                ("R2_ENDPOINT/R2_ACCOUNT_ID", endpoint),
            )
            if not value
        ]
        if missing:
            raise StorageError(
                "STORAGE_BACKEND=r2 nhưng thiếu cấu hình: " + ", ".join(missing)
            )
        self._bucket: str = settings.r2_bucket  # type: ignore[assignment]
        self._endpoint: str = endpoint  # type: ignore[assignment]
        self._client: Any | None = None
        self._lock = Lock()

    def _get_client(self) -> Any:
        """Tạo client boto3 một lần (lười). Lock: hai request đầu tiên có thể vào cùng lúc."""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    import boto3
                    from botocore.config import Config

                    self._client = boto3.client(
                        "s3",
                        endpoint_url=self._endpoint,
                        aws_access_key_id=settings.r2_access_key_id,
                        aws_secret_access_key=settings.r2_secret_access_key,
                        # R2 bỏ qua region nhưng SDK cần một giá trị; "auto" là chuẩn của R2.
                        region_name="auto",
                        config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
                    )
        return self._client

    @staticmethod
    def _error_code(exc: Exception) -> str:
        return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))

    # ── sync core (chạy trong thread) ────────────────────────────────
    def _save_sync(self, key: str, data: bytes, content_type: str) -> str:
        self._get_client().put_object(
            Bucket=self._bucket, Key=key, Body=data, ContentType=content_type
        )
        return key

    def _get_sync(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            resp = self._get_client().get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._error_code(exc) in _NOT_FOUND_CODES:
                raise StorageNotFound(f"Không tìm thấy CV trên R2: {key}") from exc
            raise StorageError(f"Lỗi đọc CV trên R2 ({key}): {exc}") from exc
        return resp["Body"].read()

    def _delete_sync(self, key: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._get_client().delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            # delete_object của S3 vốn idempotent; chỉ lỗi thật (quyền/mạng) mới nổi lên.
            raise StorageError(f"Lỗi xóa CV trên R2 ({key}): {exc}") from exc

    def _url_sync(self, key: str) -> str:
        return self._get_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=_PRESIGN_TTL_SECONDS,
        )

    # ── async API (hợp đồng FileStorage) ─────────────────────────────
    async def save(self, key: str, data: bytes, content_type: str) -> str:
        validate_key(key)
        try:
            return await asyncio.to_thread(self._save_sync, key, data, content_type)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001 — gói lỗi mạng/SDK thành lỗi storage rõ ràng
            raise StorageError(f"Lỗi ghi CV lên R2 ({key}): {exc}") from exc

    async def get(self, key: str) -> bytes:
        validate_key(key)
        try:
            return await asyncio.to_thread(self._get_sync, key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Lỗi đọc CV trên R2 ({key}): {exc}") from exc

    async def delete(self, key: str) -> None:
        validate_key(key)
        try:
            await asyncio.to_thread(self._delete_sync, key)
        except StorageError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Lỗi xóa CV trên R2 ({key}): {exc}") from exc

    async def url(self, key: str) -> str:
        """Presigned hạn NGẮN. ⚠️ KHÔNG dùng phát CV — xem ghi chú `FileStorage.url` (NFR-4)."""
        validate_key(key)
        try:
            return await asyncio.to_thread(self._url_sync, key)
        except Exception as exc:  # noqa: BLE001
            raise StorageError(f"Lỗi tạo presigned URL ({key}): {exc}") from exc
