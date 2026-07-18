"""Test slice 06 — seam object storage (PRD §16 cv_file_ref, NFR-4).

Phủ:
  1) `validate_key` — CHẶN traversal/path tuyệt đối/backslash/key kiểu CŨ (path Windows). Đây là lá
     chắn để một `cv_file_ref` bẩn không đọc/ghi ra ngoài thư mục gốc.
  2) `build_cv_key` / `content_type_for` — key GIỮ ĐUÔI (cv_reader chọn bộ đọc theo đuôi) + duy nhất.
  3) LocalStorage — save→get roundtrip, delete (idempotent), get thiếu → StorageNotFound, không
     thoát khỏi thư mục gốc.
  4) R2Storage — boto3 MOCK (KHÔNG gọi R2 thật): save/get/delete gọi đúng API + đúng bucket/key/
     content-type; lỗi 404/NoSuchKey → StorageNotFound; thiếu config → StorageError.
  5) Factory `get_storage` theo STORAGE_BACKEND.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.storage import (
    StorageError,
    StorageNotFound,
    build_cv_key,
    content_type_for,
    get_storage,
    validate_key,
)
from app.services.storage.local import LocalStorage
from app.services.storage.r2 import R2Storage

_PDF = b"%PDF-1.4 noi dung gia lap"


# ── 1) validate_key: chặn thoát thư mục ───────────────────────────────
@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "cv/../../secret.pdf",
        "/etc/passwd",
        "..",
        r"D:\Web\Project\DATN\apps\backend\data\uploads\23.pdf",  # cv_file_ref ĐỊNH DẠNG CŨ
        "cv/1/x.pdf; rm -rf /",
        "",
    ],
)
def test_validate_key_rejects_dangerous(bad: str) -> None:
    with pytest.raises(StorageError):
        validate_key(bad)


def test_validate_key_accepts_normal_key() -> None:
    assert validate_key("cv/12/9af3b1c2.pdf") == "cv/12/9af3b1c2.pdf"


# ── 2) key + content-type ─────────────────────────────────────────────
def test_build_cv_key_keeps_extension_and_is_unique() -> None:
    k1 = build_cv_key(12, "Nguyen Van A - CV.pdf")
    k2 = build_cv_key(12, "Nguyen Van A - CV.pdf")
    assert k1.startswith("cv/12/") and k1.endswith(".pdf")
    assert k1 != k2  # uuid → nộp lại không đè file cũ
    validate_key(k1)  # key sinh ra luôn hợp lệ
    # ĐUÔI LÀ BẮT BUỘC: cv_reader chọn bộ đọc theo đuôi của key.
    assert build_cv_key(3, "ho so.docx").endswith(".docx")


def test_build_cv_key_drops_unknown_extension() -> None:
    # Đuôi lạ KHÔNG được nhét vào key (validate_cv đã chặn ở tầng route; đây là lớp thứ hai).
    key = build_cv_key(1, "evil.exe")
    assert not key.endswith(".exe")
    assert key.startswith("cv/1/")
    validate_key(key)


def test_content_type_for() -> None:
    assert content_type_for("cv/1/a.pdf") == "application/pdf"
    assert "wordprocessingml" in content_type_for("cv/1/a.docx")
    assert content_type_for("cv/1/a") == "application/octet-stream"


# ── 3) LocalStorage ───────────────────────────────────────────────────
async def test_local_save_get_roundtrip(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    key = build_cv_key(5, "cv.pdf")

    returned = await storage.save(key, _PDF, "application/pdf")

    assert returned == key  # trả KEY (giá trị vào cv_file_ref), không phải path
    assert await storage.get(key) == _PDF
    assert (tmp_path / key).exists()  # nằm đúng dưới thư mục gốc


async def test_local_get_missing_raises_not_found(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(StorageNotFound):
        await storage.get("cv/1/khong-ton-tai.pdf")


async def test_local_delete_removes_and_is_idempotent(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    key = build_cv_key(6, "cv.pdf")
    await storage.save(key, _PDF, "application/pdf")

    await storage.delete(key)
    assert not (tmp_path / key).exists()
    await storage.delete(key)  # xóa lại KHÔNG lỗi (khớp hành vi S3)

    with pytest.raises(StorageNotFound):
        await storage.get(key)


async def test_local_rejects_escaping_key(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(StorageError):
        await storage.get("../outside.pdf")


# ── 4) R2Storage với boto3 MOCK (KHÔNG gọi mạng) ──────────────────────
class _FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _FakeS3:
    """Ghi lại lời gọi để khẳng định đúng API/tham số."""

    def __init__(self, *, get_error: Exception | None = None) -> None:
        self.calls: list[tuple] = []
        self._get_error = get_error
        self.objects: dict[str, bytes] = {}

    def put_object(self, **kw):
        self.calls.append(("put_object", kw))
        self.objects[kw["Key"]] = kw["Body"]
        return {}

    def get_object(self, **kw):
        self.calls.append(("get_object", kw))
        if self._get_error:
            raise self._get_error
        return {"Body": _FakeBody(self.objects.get(kw["Key"], _PDF))}

    def delete_object(self, **kw):
        self.calls.append(("delete_object", kw))
        self.objects.pop(kw["Key"], None)
        return {}

    def generate_presigned_url(self, *a, **kw):
        self.calls.append(("generate_presigned_url", kw))
        return "https://example.invalid/presigned"


@pytest.fixture
def r2_settings(monkeypatch):
    monkeypatch.setattr(settings, "r2_access_key_id", "AKIA_TEST")
    monkeypatch.setattr(settings, "r2_secret_access_key", "SECRET_TEST")
    monkeypatch.setattr(settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(settings, "r2_endpoint", "https://acct.r2.cloudflarestorage.com")
    return settings


def _r2_with(fake: _FakeS3) -> R2Storage:
    storage = R2Storage()
    storage._client = fake  # tiêm client giả — KHÔNG tạo client boto3 thật, KHÔNG gọi mạng
    return storage


async def test_r2_save_calls_put_object(r2_settings) -> None:
    fake = _FakeS3()
    storage = _r2_with(fake)
    key = build_cv_key(9, "cv.pdf")

    returned = await storage.save(key, _PDF, "application/pdf")

    assert returned == key
    name, kw = fake.calls[0]
    assert name == "put_object"
    assert kw["Bucket"] == "test-bucket"
    assert kw["Key"] == key
    assert kw["Body"] == _PDF
    assert kw["ContentType"] == "application/pdf"


async def test_r2_get_calls_get_object(r2_settings) -> None:
    fake = _FakeS3()
    storage = _r2_with(fake)
    assert await storage.get("cv/9/a.pdf") == _PDF
    name, kw = fake.calls[0]
    assert name == "get_object" and kw == {"Bucket": "test-bucket", "Key": "cv/9/a.pdf"}


async def test_r2_delete_calls_delete_object(r2_settings) -> None:
    fake = _FakeS3()
    storage = _r2_with(fake)
    await storage.delete("cv/9/a.pdf")
    name, kw = fake.calls[0]
    assert name == "delete_object" and kw == {"Bucket": "test-bucket", "Key": "cv/9/a.pdf"}


async def test_r2_missing_object_raises_not_found(r2_settings) -> None:
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "NoSuchKey", "Message": "not found"}}, "GetObject")
    storage = _r2_with(_FakeS3(get_error=err))
    with pytest.raises(StorageNotFound):
        await storage.get("cv/9/missing.pdf")


async def test_r2_other_error_raises_storage_error(r2_settings) -> None:
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "AccessDenied", "Message": "nope"}}, "GetObject")
    storage = _r2_with(_FakeS3(get_error=err))
    with pytest.raises(StorageError) as exc:
        await storage.get("cv/9/a.pdf")
    assert not isinstance(exc.value, StorageNotFound)  # 403 KHÁC 404 — không nuốt thành "mất file"


async def test_r2_rejects_dangerous_key(r2_settings) -> None:
    storage = _r2_with(_FakeS3())
    with pytest.raises(StorageError):
        await storage.get("../../etc/passwd")


def test_r2_missing_config_raises(monkeypatch) -> None:
    monkeypatch.setattr(settings, "r2_access_key_id", None)
    monkeypatch.setattr(settings, "r2_secret_access_key", None)
    monkeypatch.setattr(settings, "r2_bucket", None)
    monkeypatch.setattr(settings, "r2_endpoint", None)
    monkeypatch.setattr(settings, "r2_account_id", None)
    with pytest.raises(StorageError) as exc:
        R2Storage()
    assert "R2_ACCESS_KEY_ID" in str(exc.value)  # báo RÕ thiếu biến nào


# ── 4b) Lưu HỎNG không được để lại hồ sơ "parse thành công" giả ───────
async def test_upload_deletes_row_when_storage_save_fails(monkeypatch) -> None:
    """R2 sập lúc nộp → phải XÓA hồ sơ vừa tạo + 503, KHÔNG để cv_file_ref rỗng.

    Vì sao quan trọng: parser coi `cv_file_ref` rỗng là "không có CV" → chạy nhánh STUB và trả
    confidence 1.0 ⇒ hồ sơ KHÔNG có CV lại trôi qua pipeline như đã parse THÀNH CÔNG.
    """
    import httpx

    from app.api.routes import public as public_mod
    from app.core.database import get_session
    from app.main import app
    from app.models.application import Application

    deleted: list = []

    class _Session:
        async def delete(self, obj):  # noqa: ANN001
            deleted.append(obj)

        async def commit(self):
            return None

        async def refresh(self, _obj):  # noqa: ANN001
            return None

    session = _Session()

    async def _fake_session():
        yield session

    class _BoomStorage:
        async def save(self, *_a, **_kw):
            raise StorageError("R2 down")

    async def _fake_create(_session, _data):
        row = Application(job_id=2, applicant_email="x@e.com", status="SUBMITTED")
        row.id = 999
        return row

    job = type("J", (), {"id": 2})()
    monkeypatch.setattr(public_mod.job_service, "get_open_job", lambda *a, **k: _async(job))
    monkeypatch.setattr(public_mod.application_service, "create_application", _fake_create)
    monkeypatch.setattr(public_mod, "get_storage", lambda: _BoomStorage())
    app.dependency_overrides[get_session] = _fake_session
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/public/applications",
                data={"job_id": "2", "applicant_email": "x@e.com"},
                files={"file": ("cv.pdf", _PDF, "application/pdf")},
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503  # ứng viên được báo lỗi rõ, không "im lặng thành công"
    assert deleted and deleted[0].id == 999  # hồ sơ mồ côi đã bị xóa


async def _async(value):
    return value


# ── 5) Factory ────────────────────────────────────────────────────────
def test_factory_picks_backend(monkeypatch) -> None:
    get_storage.cache_clear()
    monkeypatch.setattr(settings, "storage_backend", "local")
    assert isinstance(get_storage(), LocalStorage)

    get_storage.cache_clear()
    monkeypatch.setattr(settings, "storage_backend", "r2")
    monkeypatch.setattr(settings, "r2_access_key_id", "AKIA_TEST")
    monkeypatch.setattr(settings, "r2_secret_access_key", "SECRET_TEST")
    monkeypatch.setattr(settings, "r2_bucket", "test-bucket")
    monkeypatch.setattr(settings, "r2_endpoint", "https://acct.r2.cloudflarestorage.com")
    assert isinstance(get_storage(), R2Storage)

    get_storage.cache_clear()
    monkeypatch.setattr(settings, "storage_backend", "s3-gcs-azure")
    with pytest.raises(StorageError):
        get_storage()
    get_storage.cache_clear()
