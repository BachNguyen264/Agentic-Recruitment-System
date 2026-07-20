"""Test endpoint nhật ký kiểm toán — GET /api/applications/{id}/audit (PRD §16, NFR-3).

Nguồn cho "Agent trace" THẬT ở màn chi tiết: trước đây frontend phải SUY ĐOÁN trạng thái từng node
từ dữ liệu hồ sơ (parsed_data/score/status) vì audit_log nằm trong DB mà không có đường đọc.

Phủ:
  1) Thứ tự: sắp theo (created_at, id) — nhiều bước CÙNG transaction có created_at TRÙNG NHAU
     (Postgres now() cố định trong transaction) nên thiếu `id` thì trace đọc ra sai trình tự pipeline.
  2) Lọc đúng hồ sơ + có limit (không kéo cả bảng).
  3) Route: 404 khi hồ sơ không tồn tại; [] khi hồ sơ CÓ THẬT nhưng chưa có bước nào; trả đủ trường.
  4) RANH GIỚI AUTH: endpoint nằm trong router HR → không cookie = 401 (không rò trace cho khách).
"""

from __future__ import annotations

import httpx
import pytest

from app.api.deps import require_hr
from app.core.database import get_session
from app.main import app
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.hr_user import HrUser
from app.services import audit_service


class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _Result:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _Scalars:
        return _Scalars(self._rows)


class FakeSession:
    """AsyncSession tối thiểu: get(Application) cho guard 404, execute() trả các dòng audit."""

    def __init__(self, app_row: Application | None, rows: list | None = None) -> None:
        self._app = app_row
        self._rows = rows or []
        self.stmt = None

    async def get(self, model, pk):  # noqa: ANN001
        if model is HrUser:  # require_hr khi test đường có cookie thật (không dùng ở đây)
            return None
        return self._app if (self._app is not None and self._app.id == pk) else None

    async def execute(self, stmt):  # noqa: ANN001
        self.stmt = stmt
        return _Result(self._rows)


def _entry(entry_id: int, node: str, action: str) -> AuditLog:
    row = AuditLog(
        application_id=1, node=node, action=action, confidence=0.9,
        uncertainty_flags=[], escalation_reason=None, detail={"status": "OK"},
    )
    row.id = entry_id
    from datetime import datetime, timezone

    row.created_at = datetime(2026, 7, 20, 10, 0, 0, tzinfo=timezone.utc)
    return row


# ── 1) + 2) service: thứ tự + lọc ────────────────────────────────────────────


async def test_orders_by_created_at_then_id() -> None:
    # Bước cùng transaction có created_at TRÙNG → phải có `id` làm khoá phụ, nếu không thứ tự
    # pipeline (parser → ranker → …) đọc ra lung tung.
    session = FakeSession(Application(id=1))
    await audit_service.list_for_application(session, 1)
    sql = str(session.stmt)
    assert "ORDER BY audit_log.created_at, audit_log.id" in sql


async def test_filters_by_application_and_limits() -> None:
    session = FakeSession(Application(id=1))
    await audit_service.list_for_application(session, 7, limit=50)
    sql = str(session.stmt)
    assert "audit_log.application_id" in sql  # lọc đúng hồ sơ
    assert "LIMIT" in sql  # không kéo cả bảng


async def test_returns_rows_in_given_order() -> None:
    rows = [_entry(1, "system", "received"), _entry(2, "parser", "parsed")]
    out = await audit_service.list_for_application(FakeSession(Application(id=1), rows), 1)
    assert [r.action for r in out] == ["received", "parsed"]


# ── 3) + 4) route ────────────────────────────────────────────────────────────


def _client(app_row: Application | None, rows: list | None = None) -> httpx.AsyncClient:
    async def _fake_session():
        yield FakeSession(app_row, rows)

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[require_hr] = lambda: HrUser(email="hr@ars.local", password_hash="x")
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không chạm Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


async def test_audit_endpoint_returns_trace() -> None:
    rows = [_entry(1, "system", "received"), _entry(2, "ranker", "ranked")]
    async with _client(Application(id=1), rows) as c:
        r = await c.get("/api/applications/1/audit")

    assert r.status_code == 200
    body = r.json()
    assert [e["node"] for e in body] == ["system", "ranker"]
    first = body[0]
    # Đủ trường cho trace: mốc thời gian + hành động + tín hiệu 4 trụ cột.
    for key in ("id", "node", "action", "confidence", "uncertainty_flags", "detail", "created_at"):
        assert key in first
    assert "application_id" not in first  # client đã biết (nằm trên URL) — không lặp


async def test_audit_endpoint_404_when_application_missing() -> None:
    async with _client(None) as c:
        r = await c.get("/api/applications/99/audit")
    assert r.status_code == 404


async def test_audit_endpoint_empty_list_when_no_entries() -> None:
    # Hồ sơ CÓ THẬT nhưng chưa ghi bước nào → [] (KHÁC 404 "không tồn tại").
    async with _client(Application(id=1), []) as c:
        r = await c.get("/api/applications/1/audit")
    assert r.status_code == 200
    assert r.json() == []


async def test_audit_endpoint_requires_hr_login() -> None:
    # Ranh giới 09: KHÔNG override require_hr → không cookie = 401 (khách không đọc được trace).
    async def _fake_session():
        yield FakeSession(Application(id=1), [])

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/applications/1/audit")
    assert r.status_code == 401
