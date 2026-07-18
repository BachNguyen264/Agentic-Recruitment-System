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
from fastapi import FastAPI, Request

from app.core.hardening import BodySizeLimitMiddleware, RateLimiter, RateLimitMiddleware

MAX_BYTES = 1024


def _app(*, rate_limited: bool = False, **kw) -> FastAPI:
    """App tối giản để test middleware CÔ LẬP (không kéo theo settings/DB của app thật)."""
    app = FastAPI()

    @app.get("/api/health/live")
    async def live() -> dict:
        return {"status": "ok"}

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/public/screening/{token}")
    async def screening_form(token: str) -> dict:
        return {"ok": True}

    @app.post("/api/public/screening/{token}")
    async def screening_submit(token: str) -> dict:
        return {"ok": True}

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


async def test_chunked_body_under_limit_is_accepted() -> None:
    # KHÔNG có Content-Length (Transfer-Encoding: chunked). Proxy của nền tảng CÓ QUYỀN chuyển tiếp
    # body dạng chunked; nếu ta từ chối thẳng thì mọi lượt nộp CV chết trên bản live trong khi dev
    # vẫn chạy ngon. Phải đi lọt VÀ tới được handler nguyên vẹn.
    async def _chunks():
        yield b"x" * 10

    async with _client(_app()) as c:
        r = await c.post("/api/public/applications", content=_chunks())
    assert r.status_code == 200


async def test_chunked_body_over_limit_rejected_413() -> None:
    # Không khai độ dài KHÔNG được thành đường lách hạn mức: đọc có ĐẾM, cắt ngay khi vượt.
    async def _chunks():
        for _ in range(4):
            yield b"x" * (MAX_BYTES // 2)

    async with _client(_app()) as c:
        r = await c.post("/api/public/applications", content=_chunks())
    assert r.status_code == 413


async def test_chunked_body_reaches_handler_intact() -> None:
    # Đệm rồi PHÁT LẠI: handler phải đọc được đúng số byte đã gửi (không mất, không nhân đôi).
    app = FastAPI()

    @app.post("/api/public/applications")
    async def echo(request: Request) -> dict:
        return {"n": len(await request.body())}

    app.add_middleware(BodySizeLimitMiddleware, max_bytes=MAX_BYTES)

    async def _chunks():
        yield b"a" * 100
        yield b"b" * 50

    async with _client(app) as c:
        r = await c.post("/api/public/applications", content=_chunks())
    assert r.status_code == 200
    assert r.json()["n"] == 150


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


def test_eviction_keeps_the_quota_of_a_continuously_active_attacker() -> None:
    """Dọn theo LRU (dùng gần nhất), KHÔNG theo thứ tự tạo key.

    Kẻ tấn công THẬT thì gõ liên tục. Nếu chỉ làm mới vị trí ở nhánh CHO PHÉP thì key đang-bị-chặn
    của nó hoá ra "cũ nhất" và bị dọn trước → quota tự reset, giới hạn thành vô nghĩa. Ở đây key của
    nó được chạm mỗi lượt nên phải SỐNG SÓT qua đợt dọn và vẫn bị chặn.

    (Trong cấu hình thật, tự sinh key mồi gần như bất khả: khoá quota lấy từ phần X-Forwarded-For do
    proxy ghi — client không đặt được. Test này giữ đúng ngữ nghĩa LRU, không mô phỏng lỗ hổng.)
    """
    rl = RateLimiter(max_events=2, window_seconds=900, max_keys=6)
    assert rl.allow("login:ATTACKER", now=0.0)[0] is True
    assert rl.allow("login:ATTACKER", now=1.0)[0] is True
    assert rl.allow("login:ATTACKER", now=2.0)[0] is False  # cạn quota

    for i in range(30):  # nền: key mồi liên tục ép dọn, xen kẽ lượt gõ của kẻ tấn công
        rl.allow(f"login:decoy{i}", now=3.0 + 2 * i)
        assert rl.allow("login:ATTACKER", now=4.0 + 2 * i)[0] is False, "quota bị reset giữa chừng"

    assert len(rl._hits) <= 6  # vẫn bị chặn bộ nhớ


@pytest.mark.parametrize("bad", [(0, 900), (-1, 900), (5, 0)])
def test_rate_limiter_rejects_meaningless_config(bad: tuple[int, float]) -> None:
    # Đặt MAX=0 với ý "tắt giới hạn" mà không kiểm sẽ khiến MỌI login trả 500 (deque rỗng).
    # Nổ lúc khởi động với thông báo rõ hơn nhiều so với 500 hàng loạt lúc chạy.
    with pytest.raises(ValueError, match="RATE_LIMIT_ENABLED"):
        RateLimiter(max_events=bad[0], window_seconds=bad[1])


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


async def test_liveness_never_rate_limited() -> None:
    # Render ping /api/health/live liên tục để giữ service sống — chặn nó là tự cắt health check.
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=1, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        codes = [(await c.get("/api/health/live")).status_code for _ in range(8)]
    assert codes == [200] * 8


async def test_deep_health_is_rate_limited_but_does_not_starve_applicants() -> None:
    """`/api/health` kiểm SÂU (ping Postgres+Redis+Qdrant) mở công khai → phải có hạn mức.

    Không chặn thì `while true; do curl .../api/health; done` đốt sạch 10k lệnh/ngày của Upstash
    free — hạ tầng mà chính hệ thống đang sống nhờ. Nhưng nó phải dùng XÔ RIÊNG: người đi soi
    health KHÔNG được làm ứng viên hết lượt nộp CV.
    """
    app = _app(rate_limited=True, login_max=5, login_window_seconds=900,
               public_max=2, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        assert [(await c.get("/api/health")).status_code for _ in range(3)] == [200, 200, 429]
        assert (await c.post("/api/public/applications")).status_code == 200  # xô riêng


async def test_public_reads_are_not_rate_limited() -> None:
    """ĐỌC công khai KHÔNG bị siết — chỉ GHI.

    Ứng viên là guest, không có tài khoản để khiếu nại. Form screening dùng TanStack Query (mặc
    định refetch mỗi lần focus lại tab), nên nếu ĐỌC cũng tiêu quota thì người vừa soạn câu trả lời
    vừa chuyển tab sẽ hết lượt, POST câu trả lời bị 429 → quá hạn → hồ sơ bị xử `no_response`.
    Mất bài dự tuyển vì cơ chế chống spam là cái giá không chấp nhận được.
    """
    app = _app(rate_limited=True, login_max=5, login_window_seconds=900,
               public_max=2, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        codes = [(await c.get("/api/public/screening/tok123")).status_code for _ in range(10)]
        assert codes == [200] * 10
        # Đọc nhiều KHÔNG được ăn mất lượt GHI: POST câu trả lời vẫn phải qua.
        assert (await c.post("/api/public/screening/tok123")).status_code == 200


async def test_public_writes_still_limited() -> None:
    app = _app(rate_limited=True, login_max=5, login_window_seconds=900,
               public_max=2, public_window_seconds=3600, trust_proxy=False)
    async with _client(app) as c:
        codes = [(await c.post("/api/public/screening/tok123")).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


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


async def test_two_proxy_hops_needs_proxy_hops_2_to_isolate_clients() -> None:
    """Số chặng proxy phải CẤU HÌNH được, không cứng "phần phải nhất".

    Render đặt Cloudflare trước `*.onrender.com` → chuỗi có thể là "<khách>, <cloudflare>, <render>".
    Lấy cứng phần phải nhất khi đó = một địa chỉ HẠ TẦNG dùng chung cho MỌI khách ⇒ cả thế giới
    chung một xô ⇒ vài request là khóa sạch login của HR. Với hops=2 (đúng số chặng) thì tách đúng.
    """
    two_hop = _app(rate_limited=True, login_max=1, login_window_seconds=900,
                   public_max=10, public_window_seconds=3600, trust_proxy=True, proxy_hops=1)
    async with _client(two_hop) as c:
        # Hai khách KHÁC NHAU, cùng đi qua một edge → hops=1 gộp nhầm làm một.
        assert (await c.post("/api/auth/login", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})).status_code == 200
        assert (await c.post("/api/auth/login", headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"})).status_code == 429

    fixed = _app(rate_limited=True, login_max=1, login_window_seconds=900,
                 public_max=10, public_window_seconds=3600, trust_proxy=True, proxy_hops=2)
    async with _client(fixed) as c:
        assert (await c.post("/api/auth/login", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})).status_code == 200
        assert (await c.post("/api/auth/login", headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"})).status_code == 200


async def test_proxy_hops_beyond_chain_length_never_crashes() -> None:
    # Cấu hình hops nhiều hơn số phần tử thực tế (hoặc client không gửi XFF) → phải kẹp về đầu chuỗi,
    # tuyệt đối không IndexError giữa đường request.
    app = _app(rate_limited=True, login_max=5, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True, proxy_hops=9)
    async with _client(app) as c:
        assert (await c.post("/api/auth/login", headers={"X-Forwarded-For": "1.1.1.1"})).status_code == 200
        assert (await c.post("/api/auth/login")).status_code == 200  # không có XFF


# ── CF-Connecting-IP: khóa quota theo IP client THẬT do Cloudflare đặt ────
# Chuỗi thật (log prod): X-Forwarded-For = "<client>, <cloudflare>, <render-nội-bộ>"; phần phải nhất
# là IP hạ tầng Render DÙNG CHUNG → đếm hop rất dễ trúng nhầm. Cloudflare đặt CF-Connecting-IP = IP
# client thật và GHI ĐÈ giá trị client tự gửi → dùng nó là chuẩn xác + không giả mạo được.
_SHARED_XFF_TAIL = "172.71.215.190, 10.29.100.5"  # cloudflare, render-nội-bộ (chung cho mọi khách)


async def test_cf_connecting_ip_isolates_clients_behind_shared_infra() -> None:
    """Hai khách khác nhau, CÙNG đi qua một hạ tầng (XFF phải-nhất giống hệt) → phải TÁCH xô nhờ
    CF-Connecting-IP. Không có fix này thì cả hai chung khóa `...:10.29.100.5` → khách thứ 2 bị 429."""
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True,
               proxy_hops=1, client_ip_header="cf-connecting-ip")
    async with _client(app) as c:
        a = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "42.116.109.239",
            "X-Forwarded-For": f"42.116.109.239, {_SHARED_XFF_TAIL}"})
        b = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "99.99.99.99",
            "X-Forwarded-For": f"99.99.99.99, {_SHARED_XFF_TAIL}"})
    assert a.status_code == 200 and b.status_code == 200  # KHÁC khách → KHÁC xô, không vạ lây


async def test_cf_connecting_ip_beats_spoofed_xff() -> None:
    """Client tự chèn X-Forwarded-For giả KHÔNG thoát được rate-limit: Cloudflare ghi đè
    CF-Connecting-IP = IP thật, nên xoay phần XFF tự-khai vẫn cùng một xô."""
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True,
               proxy_hops=1, client_ip_header="cf-connecting-ip")
    async with _client(app) as c:
        first = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "42.116.109.239",
            "X-Forwarded-For": f"1.2.3.4, 42.116.109.239, {_SHARED_XFF_TAIL}"})
        # Cùng kẻ tấn công (CF-Connecting-IP giữ nguyên), đổi phần XFF tự chèn → vẫn phải bị chặn.
        second = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "42.116.109.239",
            "X-Forwarded-For": f"9.9.9.9, 42.116.109.239, {_SHARED_XFF_TAIL}"})
    assert first.status_code == 200 and second.status_code == 429


async def test_falls_back_to_xff_hops_when_cf_header_absent() -> None:
    """Proxy KHÔNG phải Cloudflare (không có CF-Connecting-IP) → dự phòng đếm hop X-Forwarded-For."""
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True,
               proxy_hops=2, client_ip_header="cf-connecting-ip")
    async with _client(app) as c:  # KHÔNG gửi CF-Connecting-IP
        a = await c.post("/api/auth/login", headers={"X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
        b = await c.post("/api/auth/login", headers={"X-Forwarded-For": "2.2.2.2, 9.9.9.9"})
    assert a.status_code == 200 and b.status_code == 200  # hops=2 → parts[-2] tách đúng hai khách


async def test_empty_client_ip_header_ignores_cf_and_uses_xff() -> None:
    """Tắt (rỗng) → BỎ QUA CF-Connecting-IP, chỉ dùng X-Forwarded-For (deploy không có Cloudflare)."""
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=10, public_window_seconds=3600, trust_proxy=True,
               proxy_hops=1, client_ip_header="")
    async with _client(app) as c:
        a = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "42.116.109.239", "X-Forwarded-For": "1.1.1.1, 9.9.9.9"})
        b = await c.post("/api/auth/login", headers={
            "CF-Connecting-IP": "99.99.99.99", "X-Forwarded-For": "2.2.2.2, 9.9.9.9"})
    # client_ip_header rỗng → khóa theo XFF phải-nhất (9.9.9.9) cho cả hai → khách 2 bị 429.
    assert a.status_code == 200 and b.status_code == 429


@pytest.mark.parametrize("path", ["/api/auth/login", "/api/public/applications"])
async def test_disabled_limiter_lets_everything_through(path: str) -> None:
    app = _app(rate_limited=True, login_max=1, login_window_seconds=900,
               public_max=1, public_window_seconds=3600, trust_proxy=False, enabled=False)
    async with _client(app) as c:
        codes = [(await c.post(path)).status_code for _ in range(5)]
    assert codes == [200] * 5
