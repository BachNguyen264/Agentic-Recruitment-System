"""Test slice 09 — Auth HR (PRD §4).

Phủ:
  1) Crypto (security): bcrypt hash/verify (hash ≠ plaintext, sai mật khẩu False) + JWT roundtrip/
     tampered/expired.
  2) login/logout/me qua HTTP thật (ASGITransport, KHÔNG chạy lifespan → không chạm Neon): login đúng
     → 200 + cookie httpOnly; sai mật khẩu / email lạ → 401 CÙNG message (không lộ email tồn tại);
     me không cookie → 401, có cookie → 200; logout xóa cookie.
  3) Bảo vệ router HR: GET /api/jobs không cookie → 401 (require_hr chặn TRƯỚC handler).
  4) STRUCTURAL — ranh giới: MỌI /api/public/* + auth/login + health giữ MỞ (guest không bị chặn);
     MỌI /api/jobs|applications|agents + auth/me được bảo vệ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

from app.api.deps import require_hr
from app.core.config import settings
from app.core.database import get_session
from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.main import app
from app.models.hr_user import HrUser


# ── 1) Crypto (unit, không DB) ────────────────────────────────────────
def test_hash_is_not_plaintext_and_verifies() -> None:
    h = hash_password("S3cret!pw")
    assert h != "S3cret!pw"
    assert h.startswith("$2b$")  # bcrypt
    assert verify_password("S3cret!pw", h) is True


def test_verify_rejects_wrong_password() -> None:
    h = hash_password("S3cret!pw")
    assert verify_password("wrong", h) is False


def test_verify_rejects_corrupt_hash_without_raising() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_jwt_roundtrip_and_tamper_and_expiry() -> None:
    token = create_access_token("7")
    assert decode_token(token)["sub"] == "7"
    assert decode_token(token[:-3] + "aaa") is None  # chữ ký hỏng
    expired = jwt.encode(
        {"sub": "7", "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm="HS256",
    )
    assert decode_token(expired) is None  # hết hạn


# ── Fakes cho tầng HTTP ───────────────────────────────────────────────
class _Scalars:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows


class _Result:
    def __init__(self, user: HrUser | None) -> None:
        self._user = user

    def scalar_one_or_none(self) -> HrUser | None:
        return self._user

    def scalars(self) -> _Scalars:  # handler HR (vd list_jobs) sau require_hr — trả rỗng (chỉ cần !=401).
        return _Scalars([])


class FakeSession:
    """Thay AsyncSession: login dùng execute()→scalar_one_or_none; require_hr dùng get(HrUser, id)."""

    def __init__(self, user: HrUser | None) -> None:
        self._user = user

    async def execute(self, _stmt):  # noqa: ANN001
        return _Result(self._user)

    async def get(self, _model, pk):  # noqa: ANN001
        return self._user if (self._user and self._user.id == pk) else None


def _client_with(user: HrUser | None) -> httpx.AsyncClient:
    async def _fake_session():
        yield FakeSession(user)

    app.dependency_overrides[get_session] = _fake_session
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan → không setup checkpointer/Neon.
    return httpx.AsyncClient(transport=transport, base_url="http://test")


def _user(pw: str = "Correct1!") -> HrUser:
    u = HrUser(email="admin@ars.local", password_hash=hash_password(pw))
    u.id = 1
    return u


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


# ── 2) login / logout / me ────────────────────────────────────────────
async def test_login_success_sets_httponly_cookie() -> None:
    async with _client_with(_user("Correct1!")) as c:
        r = await c.post("/api/auth/login", json={"email": "admin@ars.local", "password": "Correct1!"})
    assert r.status_code == 200
    assert r.json()["email"] == "admin@ars.local"
    set_cookie = r.headers.get("set-cookie", "")
    assert settings.auth_cookie_name in set_cookie
    assert "httponly" in set_cookie.lower()  # JS không đọc được token


async def test_login_wrong_password_401_generic() -> None:
    async with _client_with(_user("Correct1!")) as c:
        r = await c.post("/api/auth/login", json={"email": "admin@ars.local", "password": "WRONG"})
    assert r.status_code == 401
    assert "set-cookie" not in r.headers
    assert r.json()["detail"] == "Email hoặc mật khẩu không đúng."


async def test_login_unknown_email_same_generic_message() -> None:
    # KHÔNG lộ email tồn tại hay không: message y hệt case sai mật khẩu.
    async with _client_with(None) as c:
        r = await c.post("/api/auth/login", json={"email": "ghost@ars.local", "password": "whatever1"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Email hoặc mật khẩu không đúng."


async def test_me_requires_cookie() -> None:
    async with _client_with(_user()) as c:
        r = await c.get("/api/auth/me")
    assert r.status_code == 401


async def test_me_with_valid_cookie_returns_user() -> None:
    user = _user()
    async with _client_with(user) as c:
        c.cookies.set(settings.auth_cookie_name, create_access_token(str(user.id)))
        r = await c.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json() == {"id": 1, "email": "admin@ars.local"}


async def test_logout_clears_cookie() -> None:
    async with _client_with(_user()) as c:
        r = await c.post("/api/auth/logout")
    assert r.status_code == 200
    # delete_cookie phát Set-Cookie với Max-Age=0 / expires quá khứ.
    set_cookie = r.headers.get("set-cookie", "")
    assert settings.auth_cookie_name in set_cookie
    assert "max-age=0" in set_cookie.lower() or "expires=" in set_cookie.lower()


# ── 3) Bảo vệ router HR ───────────────────────────────────────────────
async def test_hr_router_blocks_without_cookie() -> None:
    # require_hr chặn TRƯỚC handler → 401 mà không chạm job_service/DB.
    async with _client_with(_user()) as c:
        r = await c.get("/api/jobs")
    assert r.status_code == 401


async def test_hr_router_allows_with_cookie() -> None:
    # Có cookie hợp lệ → qua require_hr; handler jobs sẽ gọi FakeSession.execute (trả None user nhưng
    # list_jobs chỉ cần .scalars().all()) — ta CHỈ khẳng định KHÔNG còn 401 (không phải 200 nghiệp vụ).
    user = _user()
    async with _client_with(user) as c:
        c.cookies.set(settings.auth_cookie_name, create_access_token(str(user.id)))
        r = await c.get("/api/jobs")
    assert r.status_code != 401


# ── 4) Structural — ranh giới guest vs HR (không gọi mạng) ────────────
def _protection_map() -> dict[str, bool]:
    """path → có require_hr hay không."""
    out: dict[str, bool] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        if not path.startswith("/api"):
            continue
        deps = getattr(getattr(route, "dependant", None), "dependencies", [])
        out[path] = any(getattr(d, "call", None) is require_hr for d in deps)
    return out


def test_public_and_auth_login_stay_open() -> None:
    m = _protection_map()
    for path in [
        "/api/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/api/public/jobs",
        "/api/public/jobs/{job_id}",
        "/api/public/applications",
        "/api/public/screening/{token}",
    ]:
        assert m.get(path) is False, f"{path} PHẢI mở cho guest (đang bị bảo vệ)"


def test_all_hr_routes_protected() -> None:
    m = _protection_map()
    for path, protected in m.items():
        if path.startswith(("/api/jobs", "/api/applications", "/api/agents")) or path == "/api/auth/me":
            assert protected is True, f"{path} PHẢI được bảo vệ (đang mở)"
