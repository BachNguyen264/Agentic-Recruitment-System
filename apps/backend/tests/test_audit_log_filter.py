"""Lọc nhật ký kiểm toán theo khoảng thời gian (`GET /api/admin/audit-log` + `/audit-log/nodes`).

Phần THUẦN (luôn chạy): kiểm đầu vào trước khi chạm DB.
  - Thời điểm KHÔNG múi giờ bị từ chối (422): server chạy UTC, giao diện nghĩ theo giờ Việt Nam — một
    `2026-10-06T00:00:00` trần bị hiểu thành 07:00 sáng giờ VN và bảng lệch 7 tiếng mà không ai kêu.
  - "Từ" sau "Đến" → 422 với câu nói rõ, thay vì một bảng rỗng trông như "không có dữ liệu".

Phần DB (**gated `RUN_AUDIT_IT=1`**, cần Postgres thật):

    RUN_AUDIT_IT=1 uv run --directory apps/backend pytest tests/test_audit_log_filter.py -q

  Bản ghi được đặt ở NĂM 2001 — không bản ghi thật nào nằm ở đó, nên tổng số và số đếm theo bước là
  con số tuyệt đối, chạy được trên một DB dev đang có dữ liệu khác.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routes import admin as admin_routes
from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.audit_log import AuditLog
from app.models.hr_user import HrUser

_ICT = timezone(timedelta(hours=7))


# ── Phần thuần: kiểm đầu vào ─────────────────────────────────────────────────


def _user() -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password("Correct1!"))
    u.id = 1
    return u


class _AuthOnlySession:
    """Chỉ phục vụ `require_hr`. KHÔNG có `execute`: handler mà chạm DB trước khi kiểm đầu vào là nổ
    (500) — đúng thứ test này muốn bắt."""

    async def get(self, model, pk):  # noqa: ANN001
        return _user() if (model is HrUser and pk == 1) else None


@pytest.fixture
def client():
    async def _fake_session():
        yield _AuthOnlySession()

    app.dependency_overrides[get_session] = _fake_session
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    c.cookies.set(settings.auth_cookie_name, create_access_token("1"))
    yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/api/admin/audit-log", "/api/admin/audit-log/nodes"])
@pytest.mark.parametrize("param", ["created_from", "created_to"])
async def test_naive_timestamp_is_rejected(client: httpx.AsyncClient, path: str, param: str) -> None:
    async with client as c:
        r = await c.get(path, params={param: "2026-10-06T00:00:00"})
    assert r.status_code == 422
    assert "múi giờ" in r.json()["detail"]


@pytest.mark.parametrize("path", ["/api/admin/audit-log", "/api/admin/audit-log/nodes"])
async def test_year_out_of_range_is_rejected_not_a_500(client: httpx.AsyncClient, path: str) -> None:
    """Năm 0001 parse được thành datetime, nhưng đổi sang UTC thì asyncpg tràn (OverflowError) →
    HTTP 500. Ô date của trình duyệt cho gõ năm tuỳ ý nên đây không phải ca lý thuyết."""
    async with client as c:
        r = await c.get(path, params={"created_from": "0001-01-01T00:00:00+07:00"})
    assert r.status_code == 422


@pytest.mark.parametrize("path", ["/api/admin/audit-log", "/api/admin/audit-log/nodes"])
async def test_reversed_range_is_rejected(client: httpx.AsyncClient, path: str) -> None:
    async with client as c:
        r = await c.get(path, params={
            "created_from": "2026-10-07T00:00:00+07:00",
            "created_to": "2026-10-06T00:00:00+07:00",
        })
    assert r.status_code == 422


# ── Phần DB: lọc thật ────────────────────────────────────────────────────────

_db = pytest.mark.skipif(
    not os.environ.get("RUN_AUDIT_IT"), reason="cần RUN_AUDIT_IT=1 + Postgres thật"
)
_MARK = "audit-filter-it"


@pytest.fixture
async def Session():  # noqa: N802
    """Engine RIÊNG + NullPool mỗi test (gotcha SCH-1: pool toàn cục giữ connection của loop cũ)."""
    engine = create_async_engine(
        settings.database_url, connect_args=settings.db_connect_args, poolclass=NullPool
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture
async def rows_2001(Session):  # noqa: N803
    """Bốn bản ghi giờ VN quanh hai ngày 01–02/01/2001, xoá ở cuối."""
    stamps = [
        ("parser", datetime(2000, 12, 31, 23, 59, tzinfo=_ICT)),  # ngày TRƯỚC — ngoài khoảng
        ("parser", datetime(2001, 1, 1, 0, 0, tzinfo=_ICT)),  # mép đầu — TRONG (bao gồm)
        ("ranker", datetime(2001, 1, 1, 23, 59, tzinfo=_ICT)),  # cuối ngày 01 — TRONG
        ("ranker", datetime(2001, 1, 2, 0, 0, tzinfo=_ICT)),  # mép cuối — NGOÀI (không bao gồm)
    ]
    async with Session() as s:
        rows = [
            AuditLog(node=node, action=_MARK, detail={}, created_at=at) for node, at in stamps
        ]
        s.add_all(rows)
        await s.commit()
        ids = [r.id for r in rows]
    try:
        yield ids
    finally:
        async with Session() as s:
            await s.execute(delete(AuditLog).where(AuditLog.id.in_(ids)))
            await s.commit()


_DAY_FROM = datetime(2001, 1, 1, 0, 0, tzinfo=_ICT)
_DAY_TO = datetime(2001, 1, 2, 0, 0, tzinfo=_ICT)


@_db
async def test_date_range_is_half_open_in_the_given_timezone(Session, rows_2001) -> None:  # noqa: N803
    async with Session() as s:
        page = await admin_routes.list_audit_log(
            s, limit=50, offset=0, node=None, application_id=None,
            created_from=_DAY_FROM, created_to=_DAY_TO,
        )
    assert page.total == 2
    assert [i.id for i in page.items] == [rows_2001[2], rows_2001[1]]  # mới nhất trước


@_db
async def test_node_counts_follow_the_same_range(Session, rows_2001) -> None:  # noqa: N803
    """Chip "Tất cả (n)" + từng bước phải đếm ĐÚNG tập đang lọc — đếm cả bảng trong khi bảng chỉ
    hiện 2 dòng là hai con số nói hai chuyện khác nhau trên cùng một màn."""
    async with Session() as s:
        counts = await admin_routes.audit_log_node_counts(
            s, created_from=_DAY_FROM, created_to=_DAY_TO
        )
    assert counts == {"parser": 1, "ranker": 1}
