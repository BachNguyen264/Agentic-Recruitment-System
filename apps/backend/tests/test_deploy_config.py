"""Test slice 13 — code-prep deploy (CORS từ env · entrypoint bind · hardening public).

Phủ:
  1) CORS: parse `CORS_ORIGINS` (chuỗi CSV) → danh sách origin; rỗng → fallback regex localhost (dev
     giữ nguyên hành vi); `*` bị TỪ CHỐI (browser cấm wildcard khi allow_credentials=True → login
     cross-domain sẽ vỡ IM LẶNG nếu để lọt).
  2) Middleware CORS thực sự trả header cho origin được phép + `Access-Control-Allow-Credentials`,
     và KHÔNG trả cho origin lạ — kiểm trên endpoint CÔNG KHAI (guest gọi từ frontend).
  3) Entrypoint: host/port đọc từ env (Render cấp `$PORT`), reload TẮT khi không phải local.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings


# ── 1) Parse CORS_ORIGINS ─────────────────────────────────────────────
def test_cors_origins_parses_csv_and_strips_whitespace() -> None:
    s = Settings(cors_origins="https://a.vercel.app, https://b.vercel.app ")
    assert s.cors_allow_origins == ["https://a.vercel.app", "https://b.vercel.app"]


def test_cors_origins_empty_means_no_explicit_list_dev_regex_fallback() -> None:
    # Dev (không đặt env): danh sách rỗng → main.py dùng allow_origin_regex localhost như trước.
    assert Settings(cors_origins="").cors_allow_origins == []
    assert Settings(cors_origins="   ").cors_allow_origins == []


def test_cors_origins_rejects_wildcard() -> None:
    # `*` + allow_credentials=True bị browser CẤM → cookie auth không gửi được. Nổ SỚM lúc khởi động
    # còn hơn deploy xong mới phát hiện HR không đăng nhập được (RỦI RO #1 của lát 13).
    with pytest.raises(ValueError, match=r"\*"):
        Settings(cors_origins="*").cors_allow_origins  # noqa: B018
    with pytest.raises(ValueError, match=r"\*"):
        Settings(cors_origins="https://ok.vercel.app,*").cors_allow_origins  # noqa: B018


def test_cors_origins_strips_trailing_slash() -> None:
    # Origin KHÔNG có path — "https://x.vercel.app/" dán từ thanh địa chỉ sẽ không khớp Origin header.
    assert Settings(cors_origins="https://x.vercel.app/").cors_allow_origins == [
        "https://x.vercel.app"
    ]


# ── 2) Middleware CORS thật (endpoint công khai) ──────────────────────
async def test_cors_headers_present_for_allowed_origin_on_public_endpoint() -> None:
    import httpx

    from app.main import app

    origin = "http://localhost:3000"
    transport = httpx.ASGITransport(app=app)  # KHÔNG chạy lifespan.
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.options(
            "/api/public/jobs",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") == origin
    # Credentials BẮT BUỘC: cookie auth HR + cookie đi kèm mọi call của frontend.
    assert r.headers.get("access-control-allow-credentials") == "true"


async def test_cors_headers_absent_for_foreign_origin() -> None:
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.options(
            "/api/public/jobs",
            headers={
                "Origin": "https://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert r.headers.get("access-control-allow-origin") is None


# ── 3) Entrypoint bind (Render cấp $PORT, KHÔNG reload ở prod) ────────
def test_uvicorn_options_default_local_dev() -> None:
    from app.__main__ import uvicorn_options

    opts = uvicorn_options(Settings(app_env="local"))
    assert opts["host"] == "127.0.0.1"
    assert opts["port"] == 8000
    assert opts["reload"] is True


def test_uvicorn_options_production_binds_all_interfaces_no_reload() -> None:
    from app.__main__ import uvicorn_options

    # Render: PORT do nền tảng cấp, HOST=0.0.0.0 để nhận request từ ngoài container.
    opts = uvicorn_options(Settings(app_env="production", host="0.0.0.0", port=10000))
    assert opts["host"] == "0.0.0.0"
    assert opts["port"] == 10000
    assert opts["reload"] is False  # reload = watcher + child process → KHÔNG bao giờ ở prod
