"""Phân trang JD + endpoint đếm JD (`GET /api/jobs`, `/api/jobs/counts`, `/api/public/jobs`).

Vì sao slice này tồn tại: `GET /api/jobs` ghim CỨNG `limit=100` và không nhận tham số nào — đúng
lớp lỗi AUDIT-1 đã vấp ở danh sách hồ sơ (`list_applications(limit=100)`): vượt 100 JD thì HR mất
JD, và chip đếm trên giao diện (vốn đếm độ dài mảng nhận được) khẳng định SAI. Cổng công khai
`/api/public/jobs` cũng cắt cứng 100 JD, tức vị trí thứ 101 không có đường nào để ứng viên thấy.

Phủ:
  1) `/api/jobs/counts` trả đúng số VÀ **không bị `/{job_id}` nuốt** (gọi THẬT, khẳng định ≠ 422).
  2) Phân trang JD: hai trang liên tiếp KHÔNG lặp và KHÔNG nuốt dòng **khi created_at TRÙNG NHAU**
     — dữ liệu created_at khác nhau thì test xanh cả khi thiếu khoá phụ, tức không chứng minh gì.
  3) Trần `limit` ở CẢ HAI cổng (HR le=200, công khai le=100) + tham số đi xuống service đúng.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.hr_user import HrUser
from app.models.job_posting import JobPosting
from app.services import job_service

# KHÔNG đặt `pytestmark = pytest.mark.asyncio`: pyproject bật `asyncio_mode = "auto"`, nên test
# async tự chạy còn mark dán lên test ĐỒNG BỘ trong file này chỉ sinh cảnh báo.

# MỌI JD trong bộ dữ liệu phân trang dùng CHUNG một mốc thời gian — đó là toàn bộ mục đích của
# nhóm test 2. Trên prod, JD nhập hàng loạt / seed demo trùng nhau tới mili-giây là chuyện thường,
# và `created_at` vừa không unique vừa không có index.
_SAME = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)


def _job(job_id: int, *, created: datetime | None = None, status: str = "OPEN") -> JobPosting:
    job = JobPosting(
        id=job_id,
        title=f"Vị trí {job_id}",
        description="Mô tả",
        requirements="Yêu cầu",
        rubric=[{"criterion": "Kinh nghiệm", "weight": 1.0}],
        screener_questions=[],
        gate_config={"auto_reject": False, "auto_invite": False},
        status=status,
        embedding_ref=None,
        rubric_suggestion_count=0,  # server_default chỉ chạy khi qua DB thật
    )
    job.created_at = created or _SAME
    job.updated_at = job.created_at
    return job


def _user() -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password("Correct1!"))
    u.id = 1
    return u


def _client(session) -> httpx.AsyncClient:  # noqa: ANN001
    async def _fake_session():
        yield session

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không chạm Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _authed(c: httpx.AsyncClient) -> None:
    c.cookies.set(settings.auth_cookie_name, create_access_token("1"))


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── Giả lập Postgres vừa đủ để kiểm ORDER BY + LIMIT + OFFSET ────────────────


def _order_keys(stmt) -> list[tuple[str, bool]]:  # noqa: ANN001
    """Đọc ORDER BY từ câu SQL đã dựng → [(tên cột, giảm dần?)]. Chỉ dùng `str(stmt)`."""
    sql = str(stmt)
    assert "ORDER BY" in sql, "câu lệnh không có ORDER BY — phân trang không thể ổn định"
    order_sql = sql.split("ORDER BY", 1)[1].split("LIMIT", 1)[0]
    keys: list[tuple[str, bool]] = []
    for token in order_sql.split(","):
        token = token.strip()
        if token:
            keys.append((token.split()[0].split(".")[-1], token.upper().endswith("DESC")))
    return keys


class _Result:
    def __init__(self, rows: list[JobPosting]) -> None:
        self._rows = rows

    def scalars(self):  # noqa: ANN202
        return self

    def all(self) -> list[JobPosting]:
        return list(self._rows)


class _PagingSession:
    """Giả lập Postgres ĐÚNG phần đang được kiểm: ORDER BY → OFFSET/LIMIT.

    Mấu chốt: với các hàng BẰNG NHAU trên MỌI khoá sắp xếp, Postgres KHÔNG hứa hẹn thứ tự nào cả —
    hai lần chạy có thể ra hai thứ tự khác nhau (đổi plan, seq scan song song, hàng vừa bị cập
    nhật…). Fake này mô phỏng đúng sự tự do đó bằng cách ĐẢO danh sách nguồn ở lượt gọi CHẴN. Nhờ
    vậy test chỉ xanh khi ORDER BY là một thứ tự TOÀN PHẦN (có khoá phụ `id`), và ĐỎ ngay khi bỏ
    khoá phụ — chứ không xanh nhờ may mắn.

    Mệnh đề WHERE cố ý bị bỏ qua (bộ dữ liệu ở đây không có JD ARCHIVED); phần lọc ARCHIVED đã có
    `tests/test_jd_archive.py` canh trên câu lệnh biên dịch.
    """

    def __init__(self, rows: list[JobPosting]) -> None:
        self._rows = rows
        self.calls = 0

    async def execute(self, stmt):  # noqa: ANN001
        self.calls += 1
        pool = list(self._rows)
        if self.calls % 2 == 0:
            pool.reverse()  # "tự do" của Postgres giữa các hàng bằng nhau
        for column, descending in reversed(_order_keys(stmt)):
            pool.sort(key=lambda r: getattr(r, column), reverse=descending)
        offset = stmt._offset_clause.value if stmt._offset_clause is not None else 0
        limit = stmt._limit_clause.value if stmt._limit_clause is not None else None
        page = pool[offset:] if limit is None else pool[offset : offset + limit]
        return _Result(page)


class _CountSession:
    """`execute` trả các cặp (status, count) như Result của GROUP BY; `get` phục vụ `require_hr`."""

    def __init__(self, grouped: list[tuple[str, int]], user: HrUser | None = None) -> None:
        self.grouped = grouped
        self._user = user
        self.stmts: list = []

    async def get(self, model, pk):  # noqa: ANN001
        if model is HrUser and self._user is not None and self._user.id == pk:
            return self._user
        return None

    async def execute(self, stmt):  # noqa: ANN001
        self.stmts.append(stmt)
        return list(self.grouped)


# ── 1) /api/jobs/counts ──────────────────────────────────────────────────────


async def test_counts_endpoint_is_not_swallowed_by_job_id_route() -> None:
    """BẪY THẬT: `/{job_id}` khai TRƯỚC thì FastAPI khớp "counts" vào `get_job` và trả **422**
    ("counts" không parse ra int). Chỉ gọi THẬT mới bắt được — đọc code thì hai route trông đều
    hợp lệ. Cùng cái bẫy đã vấp ở `GET /api/applications/pipeline`."""
    session = _CountSession([("OPEN", 3), ("DRAFT", 1), ("CLOSED", 1), ("ARCHIVED", 2)], _user())
    async with _client(session) as c:
        _authed(c)
        r = await c.get("/api/jobs/counts")

    assert r.status_code != 422, "'/jobs/counts' đang rơi vào tay handler '/jobs/{job_id}'"
    assert r.status_code == 200
    assert r.json() == {"active": 5, "archived": 2}


def test_counts_route_declared_before_job_id() -> None:
    """Chốt chặn thứ hai cho cùng bất biến, ở tầng khai báo: đảo hai dòng là hỏng ngay."""
    paths = [r.path for r in app.routes if getattr(r, "path", "").startswith("/api/jobs")]
    assert paths.index("/api/jobs/counts") < paths.index("/api/jobs/{job_id}")


def test_counts_route_is_hr_gated() -> None:
    """Số lượng JD là dữ liệu nội bộ — endpoint đếm phải nằm sau `require_hr` như mọi route HR."""
    from app.api.deps import require_hr

    route = next(r for r in app.routes if getattr(r, "path", "") == "/api/jobs/counts")
    assert require_hr in [d.call for d in route.dependant.dependencies]


async def test_count_jobs_uses_a_single_group_by_query() -> None:
    """MỘT câu SQL cho cả hai con số — không phải hai lượt `SELECT count(*)`."""
    session = _CountSession([("OPEN", 2), ("ARCHIVED", 1)])
    counts = await job_service.count_jobs(session)

    assert len(session.stmts) == 1, f"đếm bằng {len(session.stmts)} câu SQL"
    assert "group by" in str(session.stmts[0]).lower()
    assert counts == {"active": 2, "archived": 1}


async def test_count_jobs_groups_every_non_archived_status_as_active() -> None:
    """Phân nhóm phải KHỚP `list_jobs` (`status != 'ARCHIVED'`), kể cả status lạ của dữ liệu cũ —
    hai phép phân nhóm lệch nhau thì chip đếm và danh sách nói hai chuyện khác nhau."""
    counts = await job_service.count_jobs(_CountSession([("WEIRD_LEGACY", 4), ("ARCHIVED", 1)]))
    assert counts == {"active": 4, "archived": 1}


async def test_count_jobs_returns_both_keys_even_at_zero() -> None:
    """Bảng rỗng: client không phải đoán khoá nào tồn tại (thiếu khoá ≠ giá trị 0)."""
    assert await job_service.count_jobs(_CountSession([])) == {"active": 0, "archived": 0}


# ── 2) Phân trang JD khi created_at TRÙNG NHAU ───────────────────────────────


async def test_pages_do_not_repeat_or_swallow_rows_when_created_at_ties() -> None:
    """10 JD CÙNG `created_at` → ba trang 4/4/2 phải phủ đúng 10 JD: không lặp, không nuốt.

    Nếu `order_by` chỉ có `created_at DESC` thì thứ tự giữa 10 hàng bằng nhau là tuỳ Postgres:
    trang 2 có thể trả lại một JD của trang 1 và giấu mất một JD khác. Lỗi IM LẶNG — HR không thấy
    gì bất thường, chỉ là một vị trí tuyển dụng không bao giờ xuất hiện. `id DESC` là thứ duy nhất
    chặn nó. (Bỏ khoá phụ đi → test này ĐỎ; nếu dựng dữ liệu created_at KHÁC nhau thì nó xanh dù
    thiếu khoá phụ, tức không chứng minh được gì.)
    """
    session = _PagingSession([_job(i) for i in range(1, 11)])

    page1 = [j.id for j in await job_service.list_jobs(session, limit=4, offset=0)]
    page2 = [j.id for j in await job_service.list_jobs(session, limit=4, offset=4)]
    page3 = [j.id for j in await job_service.list_jobs(session, limit=4, offset=8)]

    assert not set(page1) & set(page2), f"trang 2 LẶP JD của trang 1: {set(page1) & set(page2)}"
    assert not set(page2) & set(page3), f"trang 3 LẶP JD của trang 2: {set(page2) & set(page3)}"
    assert sorted(page1 + page2 + page3) == list(range(1, 11)), "có JD bị NUỐT giữa các trang"
    # Thứ tự cũng phải ỔN ĐỊNH, không chỉ "không trùng": mới nhất trước, ties theo id giảm dần.
    assert page1 + page2 + page3 == [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]


async def test_open_jobs_pages_do_not_repeat_or_swallow_rows() -> None:
    """Cùng bất biến cho cổng CÔNG KHAI — ứng viên không thấy vị trí là mất một ứng viên."""
    session = _PagingSession([_job(i) for i in range(1, 8)])

    page1 = [j.id for j in await job_service.list_open_jobs(session, limit=3, offset=0)]
    page2 = [j.id for j in await job_service.list_open_jobs(session, limit=3, offset=3)]

    assert not set(page1) & set(page2)
    assert page1 + page2 == [7, 6, 5, 4, 3, 2]


async def test_sql_carries_id_tiebreaker_limit_and_offset() -> None:
    """Chốt ở tầng SQL cho CẢ HAI hàm: xoá `.offset(offset)` mà không có dòng này thì rất dễ trôi."""
    captured: list[str] = []

    class _Capture(_PagingSession):
        async def execute(self, stmt):  # noqa: ANN001
            captured.append(str(stmt).lower())
            return await super().execute(stmt)

    session = _Capture([_job(1)])
    await job_service.list_jobs(session, limit=5, offset=15)
    await job_service.list_open_jobs(session, limit=5, offset=15)

    assert len(captured) == 2
    for sql in captured:
        assert "created_at desc" in sql
        assert "job_posting.id desc" in sql, "thiếu khoá phụ id → phân trang lặp/nuốt dòng"
        assert "limit" in sql and "offset" in sql


# ── 3) Tham số của route: pass-through + trần limit ──────────────────────────


@pytest.fixture()
def _patched_jobs(monkeypatch: pytest.MonkeyPatch):
    """Chặn truy vấn DB của route HR, giữ lại tham số đã truyền để assert."""
    seen: dict = {}

    async def fake_list(_session, *, archived=False, limit=100, offset=0):  # noqa: ANN001
        seen.update(archived=archived, limit=limit, offset=offset)
        return [_job(1)]

    from app.api.routes import jobs as routes_mod

    monkeypatch.setattr(routes_mod.job_service, "list_jobs", fake_list)
    return seen


@pytest.fixture()
def _patched_public_jobs(monkeypatch: pytest.MonkeyPatch):
    seen: dict = {}

    async def fake_list(_session, *, limit=100, offset=0):  # noqa: ANN001
        seen.update(limit=limit, offset=offset)
        return [_job(1)]

    from app.api.routes import public as routes_mod

    monkeypatch.setattr(routes_mod.job_service, "list_open_jobs", fake_list)
    return seen


async def test_jobs_defaults_match_previous_behaviour(_patched_jobs) -> None:
    """Không truyền gì = hành vi CŨ (100 JD hoạt động, mới nhất trước) — client cũ không vỡ."""
    async with _client(_CountSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list), "hợp đồng: MẢNG THUẦN, không bọc envelope"
    assert _patched_jobs == {"archived": False, "limit": 100, "offset": 0}


async def test_jobs_limit_offset_passed_through(_patched_jobs) -> None:
    async with _client(_CountSession([], _user())) as c:
        _authed(c)
        await c.get("/api/jobs?archived=true&limit=25&offset=50")
    assert _patched_jobs == {"archived": True, "limit": 25, "offset": 50}


@pytest.mark.parametrize("qs", ["limit=201", "limit=0", "offset=-1"])
async def test_jobs_rejects_out_of_range_paging(_patched_jobs, qs: str) -> None:
    """Router HR KHÔNG nằm trong xô rate-limit nào — thiếu trần thì `?limit=100000` tuần tự hoá cả bảng."""
    async with _client(_CountSession([], _user())) as c:
        _authed(c)
        r = await c.get(f"/api/jobs?{qs}")
    assert r.status_code == 422


async def test_jobs_accepts_ceiling_value(_patched_jobs) -> None:
    async with _client(_CountSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/jobs?limit=200")
    assert r.status_code == 200
    assert _patched_jobs["limit"] == 200


async def test_public_jobs_limit_offset_passed_through(_patched_public_jobs) -> None:
    async with _client(_CountSession([])) as c:  # công khai: KHÔNG cookie
        r = await c.get("/api/public/jobs?limit=10&offset=20")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert _patched_public_jobs == {"limit": 10, "offset": 20}


@pytest.mark.parametrize("qs", ["limit=101", "limit=0", "offset=-1"])
async def test_public_jobs_has_a_tighter_ceiling(_patched_public_jobs, qs: str) -> None:
    """Trần công khai CHẶT HƠN đường HR (100 vs 200): endpoint này không cần đăng nhập, và
    rate-limit công khai CỐ Ý không siết GET (siết GET từng làm ứng viên mất bài dự tuyển)."""
    async with _client(_CountSession([])) as c:
        r = await c.get(f"/api/public/jobs?{qs}")
    assert r.status_code == 422


async def test_public_jobs_accepts_ceiling_value(_patched_public_jobs) -> None:
    async with _client(_CountSession([])) as c:
        r = await c.get("/api/public/jobs?limit=100")
    assert r.status_code == 200
    assert _patched_public_jobs["limit"] == 100
