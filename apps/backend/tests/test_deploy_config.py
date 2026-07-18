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


@pytest.mark.parametrize(
    "value, match",
    [
        ("*", r"\*"),
        ("https://ok.vercel.app,*", r"\*"),
        # Cách viết "phủ mọi preview" mà rất dễ nghĩ ra — Starlette so khớp CHUỖI CHÍNH XÁC nên nó
        # không bao giờ khớp; phải nổ chứ không được im lặng chấp nhận.
        ("https://*.vercel.app", r"\*"),
        # Vercel hiển thị hostname trần → dễ dán thiếu scheme; Origin của browser luôn có scheme.
        ("ars.vercel.app", "scheme"),
        ("https://x.vercel.app/duong-dan", "đường dẫn"),
    ],
)
def test_cors_origins_rejects_values_that_would_never_match(value: str, match: str) -> None:
    """Mọi giá trị "gần đúng" đều cho CÙNG một triệu chứng khó truy: login 200 nhưng mất phiên.

    Chặn ngay lúc khởi động (RỦI RO #1 của lát 13) thay vì để phát hiện trên bản live.
    """
    with pytest.raises(ValueError, match=match):
        Settings(cors_origins=value).cors_allow_origins  # noqa: B018


def test_cors_origins_normalises_trailing_slash_and_case() -> None:
    # Origin KHÔNG có path và browser gửi chữ thường — giá trị dán từ thanh địa chỉ phải được chuẩn hoá.
    assert Settings(cors_origins="https://X.Vercel.App/").cors_allow_origins == [
        "https://x.vercel.app"
    ]


# ── 2) Middleware CORS thật ───────────────────────────────────────────
def _cors_app(cfg: Settings):
    """Dựng app RIÊNG với CORS cấu hình y hệt main.py.

    KHÔNG dùng `app.main` thật: nó đọc settings lúc import từ môi trường + .env của máy dev, nên
    (a) nhánh PROD (`allow_origins`) không bao giờ được chạy — xoá hẳn dòng đó khỏi main.py mà test
    vẫn xanh, tức rủi ro #1 của lát này KHÔNG có lưới an toàn nào; và (b) chỉ cần lập trình viên đặt
    CORS_ORIGINS trong .env (đúng như runbook hướng dẫn) là test đỏ oan.
    """
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    origins = cfg.cors_allow_origins
    app = FastAPI()

    @app.get("/api/public/jobs")
    async def jobs() -> dict:
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_origin_regex=None if origins else r"http://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    return app


async def _preflight(app, origin: str):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.options(
            "/api/public/jobs",
            headers={"Origin": origin, "Access-Control-Request-Method": "GET"},
        )


async def test_cors_prod_branch_allows_configured_origin_with_credentials() -> None:
    # Nhánh THẬT khi deploy: CORS_ORIGINS = URL Vercel.
    app = _cors_app(Settings(cors_origins="https://ars-demo.vercel.app"))
    r = await _preflight(app, "https://ars-demo.vercel.app")
    assert r.headers.get("access-control-allow-origin") == "https://ars-demo.vercel.app"
    # Credentials BẮT BUỘC: cookie auth HR đi kèm mọi call của frontend.
    assert r.headers.get("access-control-allow-credentials") == "true"


async def test_cors_prod_branch_rejects_localhost_and_foreign_origins() -> None:
    # Đặt CORS_ORIGINS = danh sách CỤ THỂ ⇒ regex dev phải TẮT (không để lọt origin ngoài danh sách).
    app = _cors_app(Settings(cors_origins="https://ars-demo.vercel.app"))
    for origin in ("http://localhost:3000", "https://evil.example.com"):
        r = await _preflight(app, origin)
        assert r.headers.get("access-control-allow-origin") is None, origin


async def test_cors_dev_fallback_allows_localhost_when_unset() -> None:
    # KHÔNG đặt env ⇒ dev giữ nguyên hành vi cũ (dashboard :3000 gọi backend :8000).
    app = _cors_app(Settings(cors_origins=""))
    r = await _preflight(app, "http://localhost:3000")
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert r.headers.get("access-control-allow-credentials") == "true"


async def test_cors_dev_fallback_still_rejects_foreign_origin() -> None:
    app = _cors_app(Settings(cors_origins=""))
    r = await _preflight(app, "https://evil.example.com")
    assert r.headers.get("access-control-allow-origin") is None


def test_main_app_wires_cors_from_settings() -> None:
    """Ghim ĐÚNG cách main.py mắc CORS (các test trên chạy trên app mô phỏng nên không phủ được).

    Không có test này thì xoá hẳn `allow_origins=...` khỏi main.py vẫn xanh toàn bộ — nhánh deploy
    thật (rủi ro #1) mất lưới an toàn. So sánh với `settings` mà chính app đã dùng nên không phụ
    thuộc môi trường máy chạy test.
    """
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.config import settings
    from app.main import app

    cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
    assert len(cors) == 1, "phải có đúng một CORSMiddleware"
    opts = cors[0].kwargs
    assert opts["allow_origins"] == settings.cors_allow_origins
    assert opts["allow_credentials"] is True
    # Có danh sách cụ thể ⇒ TẮT regex dev (không để lọt origin ngoài danh sách khi đã deploy).
    assert (opts["allow_origin_regex"] is None) is bool(settings.cors_allow_origins)
    # Tên file khi HR tải CV gốc (slice 06) chỉ đọc được nếu header này được expose qua CORS.
    assert "Content-Disposition" in opts["expose_headers"]


def test_cors_middleware_is_outermost() -> None:
    """CORS phải NGOÀI hardening: lỗi 413/429 do middleware sinh ra cũng cần header CORS.

    Nếu không, trình duyệt chỉ báo "CORS error" và frontend KHÔNG đọc được `detail` — ứng viên bị
    chặn vì nộp quá nhanh sẽ thấy lỗi vô nghĩa thay vì câu tiếng Việt giải thích.
    `add_middleware` chèn lên ĐẦU nên user_middleware[0] là lớp NGOÀI CÙNG.
    """
    from fastapi.middleware.cors import CORSMiddleware

    from app.core.hardening import BodySizeLimitMiddleware, RateLimitMiddleware
    from app.main import app

    order = [m.cls for m in app.user_middleware]
    assert order.index(CORSMiddleware) < order.index(BodySizeLimitMiddleware)
    assert order.index(BodySizeLimitMiddleware) < order.index(RateLimitMiddleware)


# ── 3) Liveness cho health check của nền tảng ────────────────────────
async def test_liveness_does_no_io_even_when_all_services_are_down(monkeypatch) -> None:
    """`/api/health/live` phải trả 200 NGAY CẢ KHI Postgres/Redis/Qdrant hỏng — vì nó không gọi gì.

    VÌ SAO cần endpoint riêng: Render gửi health check "vài giây một lần, LIÊN TỤC". `/api/health`
    (kiểm sâu) ping cả 3 dịch vụ ⇒ ~17k lượt/ngày: một mình nó vượt hạn mức Upstash free
    (10k lệnh/ngày) và giữ Neon không bao giờ tự ngủ (đốt compute-hours). Health check của nền tảng
    hỏi "tiến trình còn sống không", KHÔNG phải "cả hệ thống có khỏe không".
    """
    import httpx

    from app.api.routes import health as health_module
    from app.main import app

    async def _boom() -> str:  # nếu liveness lỡ gọi kiểm sâu, test sẽ nổ chứ không im lặng.
        raise AssertionError("liveness KHÔNG được chạm dịch vụ ngoài")

    monkeypatch.setattr(health_module, "_check_postgres", _boom)
    monkeypatch.setattr(health_module, "_check_redis", _boom)
    monkeypatch.setattr(health_module, "_check_qdrant", _boom)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        r = await c.get("/api/health/live")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_liveness_is_public() -> None:
    """Render gọi health check KHÔNG kèm cookie — dính require_hr là service bị coi như chết."""
    from app.api.deps import require_hr
    from app.main import app

    for route in app.routes:
        if getattr(route, "path", "") == "/api/health/live":
            deps = getattr(getattr(route, "dependant", None), "dependencies", [])
            assert not any(getattr(d, "call", None) is require_hr for d in deps)
            return
    raise AssertionError("thiếu route /api/health/live")


# ── 4) Entrypoint bind (Render cấp $PORT, KHÔNG reload ở prod) ────────
def test_uvicorn_options_default_local_dev() -> None:
    from app.__main__ import uvicorn_options

    opts = uvicorn_options(Settings(app_env="local"))
    assert opts["host"] == "127.0.0.1"
    assert opts["port"] == 8000
    assert opts["reload"] is True


def test_env_example_only_lists_real_settings_fields() -> None:
    """Mọi KEY trong .env.example phải khớp một field của Settings.

    Env viết sai tên KHÔNG báo lỗi — pydantic-settings lặng lẽ bỏ qua (extra="ignore"). Trên prod
    điều đó nghĩa là: đặt `CORS_ORIGIN` (thiếu S) trên Render → tưởng đã cấu hình, thực tế backend
    vẫn chạy mặc định dev và HR không đăng nhập được. Test này chặn lỗi chính tả ngay từ file mẫu.

    QUÉT CẢ PHẦN COMMENT: checklist env prod (mục cuối file) nằm trong comment nhưng chính là thứ
    được COPY sang dashboard Render — typo ở đó nguy hiểm hệt như ở dòng thật.
    """
    import re
    from pathlib import Path

    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    keys = {m.lower() for m in re.findall(r"\b([A-Z][A-Z0-9_]{2,})=", env_example.read_text(encoding="utf-8"))}
    exempt = {
        # Thông tin tài khoản Upstash (chưa dùng trong code) — giữ lại để tiện tra cứu.
        "upstash_redis_rest_url",
        "upstash_redis_rest_token",
        # Biến của FRONTEND (đặt ở Vercel, không phải backend Settings).
        "next_public_api_base",
    }
    unknown = keys - set(Settings.model_fields) - exempt
    assert not unknown, f".env.example có key KHÔNG tồn tại trong Settings: {sorted(unknown)}"


def test_uvicorn_options_production_binds_all_interfaces_no_reload() -> None:
    from app.__main__ import uvicorn_options

    # Render: PORT do nền tảng cấp, HOST=0.0.0.0 để nhận request từ ngoài container.
    opts = uvicorn_options(Settings(app_env="production", host="0.0.0.0", port=10000))
    assert opts["host"] == "0.0.0.0"
    assert opts["port"] == 10000
    assert opts["reload"] is False  # reload = watcher + child process → KHÔNG bao giờ ở prod
