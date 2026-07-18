"""Test slice 13 — hardening endpoint CÔNG KHAI (giờ chúng ra internet).

Bối cảnh: ứng viên là GUEST (không đăng nhập) nên `/api/public/*` mở cho cả thế giới, và
`/api/auth/login` là cửa duy nhất vào khu HR. Hai lớp phòng thủ đơn giản:

  1) Body-size limit — chặn upload khổng lồ TRƯỚC khi đọc vào RAM (Render free chỉ 512MB; handler
     `await file.read()` đọc trọn file → một request 2GB là đủ giết tiến trình).
  2) Rate-limit theo IP — chống brute-force mật khẩu HR + spam nộp CV/dò token screener.

KHÔNG áp cho route HR khác (đã có require_hr) và health (Render ping liên tục để giữ service sống).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from app.core.hardening import BodySizeLimitMiddleware, RateLimiter, RateLimitMiddleware

MAX_BYTES = 1024


def _app(*, rate_limited: bool = False, **kw) -> FastAPI:
    """App tối giản để test middleware CÔ LẬP (không kéo theo settings/DB của app thật)."""
    app = FastAPI()

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    async def login() -> dict:
        return {"ok": True}

    @app.post("/api/public/applications")
    async def submit() -> dict:
        return {"ok": True}

    @app.get("/api/public/jobs")
    async def jobs() -> dict:
        return {"ok": True}

    if rate_limited:
        app.add_middleware(RateLimitMiddleware, **kw)
    else:
        app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BYTES)
    return app


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# ── 1) Body-size limit ────────────────────────────────────────────────
async def test_body_over_limit_rejected_413() -> None:
    async with _client(_app()) as c:
        r = await c.post("/api/public/applications", content=b"x" * (MAX_BYTES + 1))
    assert r.status_code == 413


async def test_body_under_limit_passes() -> None:
    async with _client(_app()) as c:
        r = await c.post("/api/public/applications", content=b"x" * 10)
    assert r.status_code == 200


async def test_get_without_body_unaffected() -> None:
    async with _client(_app()) as c:
        r = await c.get("/api/public/jobs")
    assert r.status_code == 200


async def test_body_without_content_length_rejected_411() -> None:
    # Không có Content-Length (vd Transfer-Encoding: chunked) thì KHÔNG kiểm trước được kích thước
    # → buộc client khai báo độ dài. Browser luôn gửi Content-Length cho FormData/JSON nên không
    # ảnh hưởng ứng viên thật; chỉ chặn đường lách limit bằng chunked.
    async def _chunks():
        yield b"x" * 10

    async with _client(_app()) as c:
        r = await c.post("/api/public/applications", content=_chunks())
    assert r.status_code == 411


# ── 2) RateLimiter (unit — cửa sổ trượt, đồng hồ tiêm vào) ───────────
def test_rate_limiter_allows_up_to_max_then_blocks() -> None:
    rl = RateLimiter(max_events=3, window_seconds=60)
    assert [rl.allow("ip1", now=t)[0] for t in (0.0, 1.0, 2.0)] == [True, True, True]
    allowed, retry_after = rl.allow("ip1", now=3.0)
    assert allowed is False
    assert 0 < retry_after <= 60


def test_rate_limiter_isolates_keys() -> None:
    rl = RateLimiter(max_events=1, window_seconds=60)
    assert rl.allow("ip1", now=0.0)[0] is True
    assert rl.allow("ip1", now=1.0)[0] is False
    assert rl.allow("ip2", now=1.0)[0] is True  # IP khác KHÔNG bị vạ lây


def test_rate_limiter_window_slides() -> None:
    rl = RateLimiter(max_events=2, window_seconds=10)
    rl.allow("ip1", now=0.0)
    rl.allow("ip1", now=1.0)
    assert rl.allow("ip1", now=5.0)[0] is False
    assert rl.allow("ip1", now=11.0)[0] is True  # 2 lượt cũ đã rơi khỏi cửa sổ


def test_rate_limiter_evicts_stale_keys_to_bound_memory() -> None:
    # Kẻ tấn công đổi IP liên tục KHÔNG được làm phình bộ nhớ vô hạn (chính nó thành DoS).
    rl = RateLimiter(max_events=5, window_seconds=10, max_keys=50)
    for i in range(500):
        rl.allow(f"ip{i}", now=float(i))
    assert len(rl._hits) <= 50


# ── 3) RateLimitMiddleware (HTTP thật) ───────────────────────────────
async def test_login_blocked_after_max_attempts() -> None:
    app = _app(rate_limited=True, login_max=3, login_window_seconds=900,
               public_max=100, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        codes = [(await c.post("/api/auth/login")).status_code for _ in range(4)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3] == 429  # brute-force mật khẩu HR bị chặn


async def test_rate_limited_response_has_retry_after() -> None:
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=100, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        await c.post("/api/auth/login")
        r = await c.post("/api/auth/login")
    assert r.status_code == 429
    assert int(r.headers["retry-after"]) > 0
    assert "detail" in r.json()


async def test_public_submit_has_its_own_bucket() -> None:
    # Nộp CV cạn quota KHÔNG được khóa luôn đường đăng nhập của HR (và ngược lại).
    app = _app(rate_limited=True, login_max=5, login_window_seconds=900,
               public_max=1, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        assert (await c.post("/api/public/applications")).status_code == 200
        assert (await c.post("/api/public/applications")).status_code == 429
        assert (await c.post("/api/auth/login")).status_code == 200  # bucket riêng


async def test_health_and_read_only_public_not_rate_limited() -> None:
    # Render ping /api/health liên tục để giữ service sống — chặn nó là tự cắt health check.
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=1, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        codes = [(await c.get("/api/health")).status_code for _ in range(5)]
    assert codes == [200] * 5


async def test_trust_proxy_uses_rightmost_forwarded_ip() -> None:
    # Sau proxy Render, X-Forwarded-For phần TRÁI do client tự gửi (giả mạo được) — phần PHẢI NHẤT
    # do proxy ghi. Lấy nhầm phần trái = kẻ tấn công đổi header là thoát rate-limit.
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True)
    async with _client(app) as c:
        h1 = {"X-Forwarded-For": "9.9.9.9, 1.2.3.4"}
        assert (await c.post("/api/auth/login", headers=h1)).status_code == 200
        # Đổi phần TRÁI (tự khai) nhưng IP thật (phải nhất) vẫn thế → PHẢI vẫn bị chặn.
        h2 = {"X-Forwarded-For": "8.8.8.8, 1.2.3.4"}
        assert (await c.post("/api/auth/login", headers=h2)).status_code == 429
        # IP thật khác → được đi tiếp.
        h3 = {"X-Forwarded-For": "9.9.9.9, 5.6.7.8"}
        assert (await c.post("/api/auth/login", headers=h3)).status_code == 200


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/public/applications"])
async def test_disabled_limiter_lets_everything_through(path: str) -> None:
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=1, public_window_seconds=3600, trust_proxy=False, enabled=False)
    async with _client(app) as c:
        codes = [(await c.post(path)).status_code for _ in range(5)]
    assert codes == [200] * 5
