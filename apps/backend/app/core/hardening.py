"""Hardening endpoint công khai (slice 13 — hệ thống ra internet).

Ứng viên là GUEST: `/api/public/*` mở cho cả thế giới, và `/api/auth/login` là cửa DUY NHẤT vào khu
HR. Hai lớp phòng thủ ĐƠN GIẢN, in-process (KHÔNG Redis — CLAUDE.md: không dựng hàng đợi/polling):

  1) `BodySizeLimitMiddleware` — chặn body quá lớn TRƯỚC khi handler đọc vào RAM.
  2) `RateLimitMiddleware` — cửa sổ trượt theo IP cho login + ghi công khai + health kiểm sâu.

GIỚI HẠN đã biết: trạng thái nằm trong RAM của MỘT tiến trình → chạy nhiều instance thì mỗi instance
có quota riêng. Đủ cho đồ án (Render 1 instance); muốn chính xác toàn cục thì chuyển sang Redis.
"""

from __future__ import annotations

from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.logging import get_logger

logger = get_logger("app.hardening")

# Method có body — chỉ những method này bị kiểm kích thước và tính vào quota ghi công khai.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})

# Đường công khai có tác dụng phụ (tạo hồ sơ / nộp câu trả lời) — đây mới là thứ cần siết.
_PUBLIC_WRITE_PREFIXES = ("/api/public/applications", "/api/public/screening")


class BodySizeLimitMiddleware:
    """Chặn body vượt `max_bytes` (413), kể cả khi client KHÔNG khai Content-Length.

    Hai đường:
      - Có Content-Length → từ chối NGAY, chưa đọc byte nào (đường thường của trình duyệt).
      - THIẾU Content-Length (vd `Transfer-Encoding: chunked`) → đọc có ĐẾM, cắt ngay khi vượt hạn,
        rồi PHÁT LẠI phần đã đệm cho handler. Đệm tối đa đúng bằng `max_bytes` — chính là mức bảo
        đảm ta muốn, và Render free chỉ có 512MB RAM.

    VÌ SAO không đơn giản trả 411 khi thiếu Content-Length: request thật đi qua proxy của nền tảng,
    mà reverse proxy có quyền chuyển tiếp body dạng chunked thay vì tính lại độ dài. Nếu điều đó xảy
    ra thì MỌI lượt nộp CV chết với 411 trên bản live trong khi dev vẫn chạy ngon — đúng loại lỗi
    "chỉ vỡ khi lên mạng" cần tránh nhất. Đếm byte thì đúng trong cả hai trường hợp.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        raw = Headers(scope=scope).get("content-length")
        if raw is not None:
            try:
                length = int(raw)
            except ValueError:
                await _json(scope, send, 400, "Content-Length không hợp lệ.")
                return
            if length > self.max_bytes:
                await _json(scope, send, 413, "Nội dung gửi lên quá lớn.")
                return
            await self.app(scope, receive, send)
            return

        # Không khai độ dài → vừa đọc vừa đếm, dừng ngay khi vượt hạn.
        chunks: list[bytes] = []
        total = 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break  # http.disconnect — nhường lại cho tầng dưới xử lý.
            total += len(message.get("body", b""))
            if total > self.max_bytes:
                logger.warning("Chặn body quá lớn (chunked, >%s byte) path=%s", self.max_bytes, scope.get("path"))
                await _json(scope, send, 413, "Nội dung gửi lên quá lớn.")
                return
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break

        await self.app(scope, _replay(b"".join(chunks)), send)


def _replay(body: bytes) -> Receive:
    """Phát lại body đã đệm cho handler (một lần), sau đó báo disconnect."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class RateLimiter:
    """Cửa sổ trượt trong RAM: tối đa `max_events` lượt / `window_seconds` cho mỗi key.

    `now` được TIÊM VÀO (không gọi time bên trong) để test được thời gian trôi mà không phải sleep.
    `max_keys` chặn chính rate-limiter trở thành đường DoS: kẻ tấn công đổi IP liên tục sẽ làm dict
    phình vô hạn nếu không dọn.
    """

    def __init__(self, max_events: int, window_seconds: float, max_keys: int = 10_000) -> None:
        if max_events < 1 or window_seconds <= 0:
            # Đặt RATE_LIMIT_*_MAX=0 với ý "tắt giới hạn" sẽ khiến MỌI request 500 (deque rỗng) —
            # nổ ngay lúc khởi động với thông báo rõ, và chỉ tắt bằng RATE_LIMIT_ENABLED=false.
            raise ValueError(
                f"RateLimiter cần max_events>=1 và window_seconds>0 (nhận {max_events}/{window_seconds}). "
                "Muốn TẮT giới hạn thì đặt RATE_LIMIT_ENABLED=false."
            )
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float) -> tuple[bool, float]:
        """(cho_phép, số_giây_thử_lại). Ghi nhận lượt truy cập khi được phép."""
        # Gỡ ra rồi chèn LẠI để key vừa dùng luôn nằm CUỐI dict ⇒ thứ tự chèn = thứ tự dùng gần nhất
        # (LRU cho _evict). Làm ở đây, TRƯỚC cả nhánh từ chối: một kẻ tấn công đang bị chặn vẫn là
        # key ĐANG HOẠT ĐỘNG — nếu chỉ làm mới ở nhánh cho-phép thì nó là key CŨ NHẤT và bị dọn đầu
        # tiên, tức là bơm ít key mồi cho đầy dict là tự reset được quota của chính mình.
        hits = self._hits.pop(key, None)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._evict(now)
            hits = deque()
        self._hits[key] = hits

        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if hits and len(hits) >= self.max_events:
            # Còn phải chờ tới khi lượt CŨ NHẤT rơi khỏi cửa sổ.
            return False, max(1.0, hits[0] + self.window_seconds - now)

        hits.append(now)
        return True, 0.0

    def _evict(self, now: float) -> None:
        """Bỏ key đã hết hạn hoàn toàn; còn chật thì bỏ key ÍT DÙNG GẦN ĐÂY NHẤT (đầu dict)."""
        cutoff = now - self.window_seconds
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]
        while len(self._hits) >= self.max_keys:
            del self._hits[next(iter(self._hits))]


class RateLimitMiddleware:
    """Rate-limit theo IP cho ĐÚNG các đường công khai nhạy cảm (plan 13 §3.4).

    - `/api/auth/login` → chống brute-force mật khẩu HR.
    - GHI công khai (`POST /api/public/applications`, `POST /api/public/screening/*`) → chống spam.
    - `/api/health` (kiểm SÂU) → nó ping Postgres+Redis+Qdrant mỗi lượt và mở cho cả thế giới; không
      chặn thì một vòng lặp curl đốt sạch hạn mức Upstash free (10k lệnh/ngày) mà hệ thống đang sống nhờ.

    KHÔNG đụng: `/api/health/live` (Render ping liên tục để giữ service sống — chặn nó là tự cắt
    health check), các route HR khác (đã có `require_hr`), và ĐỌC công khai (`GET` JD / form
    screening). ĐỌC không bị siết vì ứng viên guest KHÔNG có tài khoản để khiếu nại: nếu họ tiêu hết
    quota chỉ bằng việc mở lại form (TanStack Query refetch khi focus lại tab) thì lượt POST mang câu
    trả lời sẽ bị 429 → quá hạn → `no_response` → hồ sơ bị xử như không phản hồi. Mất bài dự tuyển vì
    một cơ chế chống spam là cái giá KHÔNG chấp nhận được; token magic-link vốn đã đủ entropy.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        login_max: int,
        login_window_seconds: float,
        public_max: int,
        public_window_seconds: float,
        trust_proxy: bool,
        proxy_hops: int = 1,
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self.proxy_hops = max(1, proxy_hops)
        self._login = RateLimiter(login_max, login_window_seconds)
        self._public = RateLimiter(public_max, public_window_seconds)
        self._logged_probe = False

    def _bucket(self, path: str, method: str) -> tuple[str, RateLimiter] | None:
        if path.startswith("/api/auth/login"):
            return "login", self._login
        if path == "/api/health":  # SO SÁNH ĐÚNG BẰNG: không được trùm lên /api/health/live.
            return "health", self._public
        if method in _BODY_METHODS and path.startswith(_PUBLIC_WRITE_PREFIXES):
            return "public", self._public
        return None

    def _client_ip(self, scope: Scope) -> str:
        """IP dùng làm khóa quota. Sau proxy thì lấy từ X-Forwarded-For, nếu không thì lấy peer TCP.

        `proxy_hops` = SỐ proxy tin cậy đứng trước app; ta lấy phần tử thứ `hops` TỪ PHẢI SANG. Các
        phần bên trái là do client tự khai (giả mạo được) nên không bao giờ được tin.
        VÌ SAO cấu hình được thay vì cứ lấy phần phải nhất: số chặng phụ thuộc hạ tầng (Render đặt
        Cloudflare trước `*.onrender.com` ⇒ có thể 2 chặng). Đoán sai một chặng thì khóa quota thành
        MỘT địa chỉ hạ tầng dùng chung cho mọi khách → cả thế giới chung một xô → chỉ cần vài request
        là khóa sạch login của HR lẫn đường nộp CV. Dùng log `probe` bên dưới để chỉnh cho đúng.
        """
        peer = scope.get("client")
        peer_ip = peer[0] if peer else "unknown"
        if not self.trust_proxy:
            return peer_ip
        xff = Headers(scope=scope).get("x-forwarded-for")
        parts = [p.strip() for p in (xff or "").split(",") if p.strip()]
        if not parts:
            return peer_ip
        return parts[-min(self.proxy_hops, len(parts))]

    def _probe_once(self, scope: Scope, resolved: str) -> None:
        """In MỘT lần địa chỉ đã suy ra + chuỗi X-Forwarded-For thô, ngay lượt bị giới hạn đầu tiên.

        Nếu không có dòng này thì cấu hình proxy sai KHÔNG có triệu chứng nào cho tới lúc mọi người
        cùng dính 429 — nhìn hệt như "hệ thống hỏng". Có nó thì mở log Render là biết ngay khóa quota
        đang là IP thật của khách hay một địa chỉ hạ tầng dùng chung (khi đó chỉnh PROXY_TRUSTED_HOPS).
        """
        if self._logged_probe:
            return
        self._logged_probe = True
        peer = scope.get("client")
        logger.info(
            "Rate-limit: khóa quota = %r (trust_proxy=%s, hops=%s, peer=%s, X-Forwarded-For=%r). "
            "Nếu địa chỉ này GIỐNG NHAU cho mọi khách thì cả hệ thống dùng chung một xô — chỉnh "
            "TRUST_PROXY_HEADERS / PROXY_TRUSTED_HOPS.",
            resolved,
            self.trust_proxy,
            self.proxy_hops,
            peer[0] if peer else None,
            Headers(scope=scope).get("x-forwarded-for"),
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bucket = self._bucket(scope.get("path", ""), scope.get("method", ""))
        if bucket is None:
            await self.app(scope, receive, send)
            return

        # monotonic: không nhảy khi hệ thống chỉnh giờ/NTP (đồng hồ tường có thể lùi).
        from time import monotonic

        name, limiter = bucket
        ip = self._client_ip(scope)
        self._probe_once(scope, ip)
        allowed, retry_after = limiter.allow(f"{name}:{ip}", now=monotonic())
        if allowed:
            await self.app(scope, receive, send)
            return
        logger.warning("Rate-limit CHẶN: bucket=%s ip=%s path=%s", name, ip, scope.get("path"))
        await _json(
            scope,
            send,
            429,
            "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.",
            headers={"retry-after": str(int(retry_after))},
        )


async def _json(
    scope: Scope, send: Send, status: int, detail: str, headers: dict[str, str] | None = None
) -> None:
    """Trả lỗi dạng {"detail": ...} — KHỚP định dạng lỗi của FastAPI để frontend xử lý một kiểu."""
    response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
    await response(scope, _noop_receive, send)


async def _noop_receive() -> Message:
    return {"type": "http.disconnect"}
