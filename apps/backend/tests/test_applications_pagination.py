"""B1 — phân trang + lọc trạng thái + thu hẹp payload cho `GET /api/applications`.

Vì sao slice này tồn tại (đo thật trên prod 29/08/2026): bảng có 206 hồ sơ, `list_applications`
cắt cứng 100 dòng mới nhất và KHÔNG có offset/lọc. Cửa sổ đó rơi trọn vào mẻ probe (id 130–229,
toàn `parse_failed`), nên HR mở `/applications` thấy 100 dòng hỏng còn 86 hồ sơ ĐÃ CHẤM ĐIỂM SẠCH
(id 24–109) thì không một nút/bộ lọc/trang nào chạm tới được. Ba con số trên ba màn hình lệch nhau
(206 / 100 / 0) đều quy về đúng dòng `limit=100` đó.

Phủ:
  1) Service: `offset` phân trang KHÔNG lặp/nuốt dòng (khoá phụ `id`), `statuses` lọc ở SERVER.
  2) Route: `?limit`/`?offset`/`?status` được chuyển xuống service đúng như nhận.
  3) Trần `le=200` chặn `?limit=100000` (router HR không có rate-limit nào đỡ).
  4) **`parsed_data`/`score_breakdown` VẮNG MẶT khỏi JSON danh sách** — không có test này thì dạng
     `response_model_exclude` sai (set phẳng) là NO-OP IM LẶNG và không ai phát hiện.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.core.config import settings
from app.core.database import get_session
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models.application import Application
from app.models.email_delivery import DeliveryStatus
from app.models.hr_user import HrUser
from app.services import application_service

_NOW = datetime.now(timezone.utc)


# ── Fakes ────────────────────────────────────────────────────────────────────


def _app_row(app_id: int, *, status: str = "PENDING_REVIEW", created: datetime | None = None) -> Application:
    row = Application(
        job_id=8,
        applicant_email=f"ung-vien-{app_id}@example.com",
        status=status,
        # parsed_data CỐ Ý to: đây là thứ phải BIẾN MẤT khỏi payload danh sách.
        parsed_data={"full_name": f"Ứng viên {app_id}", "skills": ["Python"] * 20},
        score=88.0,
        score_breakdown={"criteria": [{"criterion": "Python", "score": 9}]},
        uncertainty_flags=[],
    )
    row.id = app_id
    row.created_at = created or (_NOW - timedelta(seconds=app_id))
    row.updated_at = row.created_at
    return row


class RecordingSession:
    """Ghi lại tham số mà route truyền xuống service + phục vụ `require_hr`."""

    def __init__(self, rows: list[Application], user: HrUser) -> None:
        self.rows = rows
        self._user = user

    async def get(self, model, pk):  # noqa: ANN001
        return self._user if (model is HrUser and self._user.id == pk) else None


def _user() -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password("Correct1!"))
    u.id = 1
    return u


def _client(session: RecordingSession) -> httpx.AsyncClient:
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


@pytest.fixture()
def _patched(monkeypatch: pytest.MonkeyPatch):
    """Chặn hai truy vấn DB thật của route, giữ lại tham số đã truyền để assert."""
    seen: dict = {}

    async def fake_list(_session, *, statuses=None, q=None, limit=100, offset=0):  # noqa: ANN001
        seen.update(statuses=statuses, q=q, limit=limit, offset=offset)
        return [_app_row(1), _app_row(2)]

    async def fake_no_slots(_session):  # noqa: ANN001
        return set()

    monkeypatch.setattr(application_service, "list_applications", fake_list)
    from app.api.routes import applications as routes_mod

    monkeypatch.setattr(routes_mod.application_service, "list_applications", fake_list)
    monkeypatch.setattr(routes_mod.booking_service, "no_slot_application_ids", fake_no_slots)
    return seen


# ── 1) Payload danh sách KHÔNG chở trường nặng ───────────────────────────────


async def test_list_omits_heavy_fields(_patched) -> None:
    """BẪY ĐÃ VẤP: `response_model_exclude` viết dạng set PHẲNG trên `response_model=list[...]` là
    no-op IM LẶNG (Pydantic v2 hiểu set phẳng trên sequence là chỉ số phần tử). Không có assert này
    thì bản vá "giảm 80% payload" trôi qua review mà không giảm một byte nào."""
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications")
    assert r.status_code == 200
    body = r.json()
    assert body, "cần ít nhất một dòng để phép kiểm có nghĩa"
    for row in body:
        assert "parsed_data" not in row, "parsed_data vẫn còn — exclude đang là no-op"
        assert "score_breakdown" not in row, "score_breakdown vẫn còn — exclude đang là no-op"
        # Những trường danh sách THẬT SỰ vẽ thì phải còn nguyên.
        assert row["applicant_email"] and row["status"] and row["score"] is not None


async def test_detail_still_has_heavy_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thu hẹp CHỈ ở danh sách — endpoint chi tiết vẫn là chỗ đọc parsed_data/score_breakdown."""
    from app.api.routes import applications as routes_mod

    async def fake_get(_session, _id):  # noqa: ANN001
        return _app_row(7)

    async def _none(*_a, **_k):
        return None

    async def _false(*_a, **_k):
        return False

    async def _list(*_a, **_k):
        return []

    monkeypatch.setattr(routes_mod.application_service, "get_application", fake_get)
    monkeypatch.setattr(routes_mod.screening, "latest_answers", _list)
    monkeypatch.setattr(routes_mod.booking_service, "latest_booking", _none)
    # C1: endpoint chi tiết nay hỏi MỘT hồ sơ (`has_no_slot_flag`), không quét cả bảng.
    monkeypatch.setattr(routes_mod.booking_service, "has_no_slot_flag", _false)
    monkeypatch.setattr(routes_mod.booking_service, "has_any_session", _none)
    monkeypatch.setattr(routes_mod, "_latest_reason", _none)

    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications/7")
    assert r.status_code == 200
    assert r.json()["parsed_data"]["full_name"] == "Ứng viên 7"


# ── 2) Tham số phân trang / lọc đi xuống service đúng ────────────────────────


async def test_defaults_match_previous_behaviour(_patched) -> None:
    """Không truyền gì = hành vi CŨ (100 dòng mới nhất) — `loadtest_apply.py` ghim WINDOW_LIMIT=100.

    So khớp TOÀN BỘ dict chứ không phải từng khoá: thêm một tham số lọc mới mà quên cho nó mặc định
    "không lọc" thì test này phải ĐỎ. Đó chính là điều đã xảy ra khi `q` được thêm vào.
    """
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        await c.get("/api/applications")
    assert _patched == {"statuses": None, "q": None, "limit": 100, "offset": 0}


async def test_offset_and_limit_passed_through(_patched) -> None:
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        await c.get("/api/applications?limit=20&offset=40")
    assert _patched["limit"] == 20
    assert _patched["offset"] == 40


async def test_status_filter_passed_through(_patched) -> None:
    """`/review` phải hỏi ĐÚNG ca chờ duyệt ở SERVER, không tải 100 dòng rồi lọc phía client."""
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        await c.get("/api/applications?status=PENDING_REVIEW")
    assert _patched["statuses"] == ["PENDING_REVIEW"]


async def test_multiple_statuses(_patched) -> None:
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        await c.get("/api/applications?status=PENDING_REVIEW&status=REJECTED")
    assert _patched["statuses"] == ["PENDING_REVIEW", "REJECTED"]


# ── 3) Trần limit ────────────────────────────────────────────────────────────


async def test_limit_ceiling_rejects_huge_page(_patched) -> None:
    """Router HR KHÔNG nằm trong xô rate-limit nào (`core/hardening.py` chỉ bọc login/ghi công
    khai/health sâu) — thiếu trần thì `?limit=100000` tuần tự hoá cả bảng trong một request."""
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications?limit=100000")
    assert r.status_code == 422


async def test_limit_zero_rejected(_patched) -> None:
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications?limit=0")
    assert r.status_code == 422


async def test_negative_offset_rejected(_patched) -> None:
    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications?offset=-1")
    assert r.status_code == 422


# ── 4) Khoá phụ trong ORDER BY (chống lặp/nuốt dòng giữa các trang) ──────────


class _CapturingExec:
    """Bắt câu SQL mà service dựng, không cần Postgres."""

    def __init__(self) -> None:
        self.stmt = None

    async def execute(self, stmt):  # noqa: ANN001
        self.stmt = stmt

        class _R:
            def scalars(self):  # noqa: ANN202
                class _S:
                    def all(self):  # noqa: ANN202
                        return []

                return _S()

        return _R()


async def test_order_by_has_id_tiebreaker() -> None:
    """BẤT BIẾN: `created_at` KHÔNG unique và KHÔNG có index (đo prod: 40 hồ sơ trong cùng một phút).

    `OFFSET` trên khoá không unique để Postgres tự chọn thứ tự giữa các hàng bằng nhau ⇒ trang 2 có
    thể LẶP một hàng của trang 1 và NUỐT một hàng khác. Lỗi im lặng: HR chỉ đơn giản không bao giờ
    thấy một ứng viên. Khoá phụ `id DESC` là thứ duy nhất chặn nó.
    """
    cap = _CapturingExec()
    await application_service.list_applications(cap, limit=10, offset=10)
    sql = str(cap.stmt).lower()
    assert "order by" in sql
    assert "created_at desc" in sql
    assert "application.id desc" in sql, "thiếu khoá phụ id → phân trang có thể lặp/nuốt dòng"
    # Xoá `.offset(offset)` khỏi service mà KHÔNG có hai dòng này thì toàn bộ suite vẫn xanh —
    # tức bản vá phân trang không được test nào quan sát.
    assert "limit" in sql, "LIMIT không tới SQL"
    assert "offset" in sql, "OFFSET không tới SQL"


async def test_status_filter_reaches_sql() -> None:
    """Lọc phải nằm trong WHERE (server), KHÔNG phải lọc sau khi đã cắt trang ở client."""
    cap = _CapturingExec()
    await application_service.list_applications(cap, statuses=["PENDING_REVIEW"])
    sql = str(cap.stmt).lower()
    # `"status" in sql` là VÔ NGHĨA: `application.status` có mặt trong SELECT của mọi câu. Phải kiểm
    # đúng mệnh đề IN của WHERE thì mới chứng minh được lọc chạy ở SERVER.
    assert "where" in sql
    assert "application.status in" in sql, "lọc trạng thái không nằm trong WHERE"


async def test_no_status_filter_means_no_where() -> None:
    cap = _CapturingExec()
    await application_service.list_applications(cap)
    assert "where" not in str(cap.stmt).lower()


# ── 5) C1: endpoint chi tiết không bắn truy vấn thừa ─────────────────────────


async def test_detail_skips_email_reason_queries_when_flags_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ba truy vấn `_latest_reason` chỉ chạy khi cờ email tương ứng đã bật.

    Cờ suy ra từ `uncertainty_flags` sẵn có trên hàng (0 truy vấn) và UI chỉ render lý do BÊN TRONG
    guard của cờ — nên với hồ sơ bình thường đây là 3 truy vấn thuần lãng phí, NHÂN LÊN theo số ca
    trong hàng đợi `/review`.
    """
    from app.api.routes import applications as routes_mod

    calls: list[str] = []

    async def counting_reason(_session, _app_id, delivery_status):  # noqa: ANN001
        calls.append(delivery_status)
        return "lý do nào đó"

    async def _none(*_a, **_k):
        return None

    async def _false(*_a, **_k):
        return False

    async def _list(*_a, **_k):
        return []

    async def fake_get(_session, _id):  # noqa: ANN001
        return _app_row(3)  # uncertainty_flags=[] → cả ba cờ đều tắt

    monkeypatch.setattr(routes_mod.application_service, "get_application", fake_get)
    monkeypatch.setattr(routes_mod.screening, "latest_answers", _list)
    monkeypatch.setattr(routes_mod.booking_service, "latest_booking", _none)
    monkeypatch.setattr(routes_mod.booking_service, "has_no_slot_flag", _false)
    monkeypatch.setattr(routes_mod.booking_service, "has_any_session", _none)
    monkeypatch.setattr(routes_mod, "_latest_reason", counting_reason)

    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications/3")
    assert r.status_code == 200
    assert calls == [], f"vẫn bắn {len(calls)} truy vấn lý do email dù không có cờ nào bật"


async def test_detail_still_queries_reason_when_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ngược lại: cờ BẬT thì lý do vẫn phải tới được HR — tối ưu không được nuốt thông tin thật."""
    from app.api.routes import applications as routes_mod

    calls: list[str] = []

    async def counting_reason(_session, _app_id, delivery_status):  # noqa: ANN001
        calls.append(delivery_status)
        return "hộp thư không tồn tại"

    async def _none(*_a, **_k):
        return None

    async def _false(*_a, **_k):
        return False

    async def _list(*_a, **_k):
        return []

    async def fake_get(_session, _id):  # noqa: ANN001
        row = _app_row(4)
        row.uncertainty_flags = ["email_bounced"]
        return row

    monkeypatch.setattr(routes_mod.application_service, "get_application", fake_get)
    monkeypatch.setattr(routes_mod.screening, "latest_answers", _list)
    monkeypatch.setattr(routes_mod.booking_service, "latest_booking", _none)
    monkeypatch.setattr(routes_mod.booking_service, "has_no_slot_flag", _false)
    monkeypatch.setattr(routes_mod.booking_service, "has_any_session", _none)
    monkeypatch.setattr(routes_mod, "_latest_reason", counting_reason)

    async with _client(RecordingSession([], _user())) as c:
        _authed(c)
        r = await c.get("/api/applications/4")
    body = r.json()
    assert body["email_bounce_reason"] == "hộp thư không tồn tại"
    assert calls == [DeliveryStatus.BOUNCED.value], "chỉ hỏi ĐÚNG loại sự kiện đang có cờ"
    assert body["email_complaint_reason"] is None
