"""Hardening endpoint công khai (slice 13 — hệ thống ra internet).

Ứng viên là GUEST: `/api/public/*` mở cho cả thế giới, và `/api/auth/login` là cửa DUY NHẤT vào khu
HR. Hai lớp phòng thủ ĐƠN GIẢN, in-process (KHÔNG Redis — CLAUDE.md: không dựng hàng đợi/polling):

  1) `BodySizeLimitMiddleware` — chặn body quá lớn TRƯỚC khi handler đọc vào RAM.
  2) `RateLimitMiddleware` — cửa sổ trượt theo IP cho login + public (brute-force / spam / dò token).

GIỚI HẠN đã biết: trạng thái nằm trong RAM của MỘT tiến trình → chạy nhiều instance thì mỗi instance
có quota riêng. Đủ cho đồ án (Render 1 instance); muốn chính xác toàn cục thì chuyển sang Redis.
"""

from __future__ import annotations

from collections import deque

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

# Method có body — chỉ những method này mới bắt buộc khai Content-Length.
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH"})


class BodySizeLimitMiddleware:
    """Từ chối request có body vượt `max_bytes` (413) hoặc không khai độ dài (411).

    VÌ SAO chặn cả trường hợp THIẾU Content-Length: không có nó thì không biết trước kích thước, kẻ
    tấn công gửi `Transfer-Encoding: chunked` là lách được limit và ép handler
    (`await file.read()` ở route nộp CV) nuốt hết vào RAM — Render free chỉ 512MB. Trình duyệt LUÔN
    gửi Content-Length cho FormData/JSON nên ứng viên thật không bị ảnh hưởng.

    Middleware ASGI thuần (không phải BaseHTTPMiddleware) để chặn NGAY ở lớp scope, chưa đọc body.
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("method", "") not in _BODY_METHODS:
            await self.app(scope, receive, send)
            return

        raw = Headers(scope=scope).get("content-length")
        if raw is None:
            await _json(send, 411, "Thiếu Content-Length — vui lòng gửi lại yêu cầu.")
            return
        try:
            length = int(raw)
        except ValueError:
            await _json(send, 400, "Content-Length không hợp lệ.")
            return
        if length > self.max_bytes:
            await _json(send, 413, "Nội dung gửi lên quá lớn.")
            return
        await self.app(scope, receive, send)


class RateLimiter:
    """Cửa sổ trượt trong RAM: tối đa `max_events` lượt / `window_seconds` cho mỗi key.

    `now` được TIÊM VÀO (không gọi time bên trong) để test được thời gian trôi mà không phải sleep.
    `max_keys` chặn chính rate-limiter trở thành đường DoS: kẻ tấn công đổi IP liên tục sẽ làm dict
    phình vô hạn nếu không dọn.
    """

    def __init__(self, max_events: int, window_seconds: float, max_keys: int = 10_000) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float) -> tuple[bool, float]:
        """(cho_phép, số_giây_thử_lại). Ghi nhận lượt truy cập khi được phép."""
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._evict(now)
            hits = self._hits.setdefault(key, deque())

        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.max_events:
            # Còn phải chờ tới khi lượt CŨ NHẤT rơi khỏi cửa sổ.
            return False, max(1.0, hits[0] + self.window_seconds - now)

        hits.append(now)
        return True, 0.0

    def _evict(self, now: float) -> None:
        """Bỏ các key đã hết hạn hoàn toàn; nếu vẫn chật thì bỏ key cũ nhất (FIFO của dict)."""
        cutoff = now - self.window_seconds
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= cutoff]:
            del self._hits[key]
        while len(self._hits) >= self.max_keys:
            del self._hits[next(iter(self._hits))]


class RateLimitMiddleware:
    """Rate-limit theo IP cho ĐÚNG các đường công khai nhạy cảm (plan 13 §3.4).

    - `/api/auth/login`  → chống brute-force mật khẩu HR.
    - `/api/public/applications` + `/api/public/screening/*` → chống spam nộp CV và DÒ TOKEN
      magic-link (token là bí mật; thử hàng loạt phải bị chặn).

    KHÔNG đụng `/api/health` (Render ping liên tục để giữ service sống — chặn nó là tự cắt health
    check) và các route HR khác (đã có `require_hr`).
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
        enabled: bool = True,
    ) -> None:
        self.app = app
        self.enabled = enabled
        self.trust_proxy = trust_proxy
        self._login = RateLimiter(login_max, login_window_seconds)
        self._public = RateLimiter(public_max, public_window_seconds)

    def _bucket(self, path: str) -> tuple[str, RateLimiter] | None:
        if path.startswith("/api/auth/login"):
            return "login", self._login
        if path.startswith(("/api/public/applications", "/api/public/screening")):
            return "public", self._public
        return None

    def _client_ip(self, scope: Scope) -> str:
        if self.trust_proxy:
            xff = Headers(scope=scope).get("x-forwarded-for")
            if xff:
                # Lấy phần PHẢI NHẤT: do proxy tin cậy (Render) ghi. Các phần bên trái là do client
                # tự khai → giả mạo được; tin vào chúng là mở cửa cho việc lách rate-limit.
                return xff.split(",")[-1].strip()
        client = scope.get("client")
        return client[0] if client else "unknown"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        bucket = self._bucket(scope.get("path", ""))
        if bucket is None:
            await self.app(scope, receive, send)
            return

        # monotonic: không nhảy khi hệ thống chỉnh giờ/NTP (đồng hồ tường có thể lùi).
        from time import monotonic

        name, limiter = bucket
        allowed, retry_after = limiter.allow(f"{name}:{self._client_ip(scope)}", now=monotonic())
        if allowed:
            await self.app(scope, receive, send)
            return
        await _json(
            send,
            429,
            "Bạn thao tác quá nhanh. Vui lòng thử lại sau ít phút.",
            headers={"retry-after": str(int(retry_after))},
        )


async def _json(send: Send, status: int, detail: str, headers: dict[str, str] | None = None) -> None:
    """Trả lỗi dạng {"detail": ...} — KHỚP định dạng lỗi của FastAPI để frontend xử lý một kiểu."""
    response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
    await response(  # type: ignore[call-arg]
        {"type": "http"}, _empty_receive, send
    )


async def _empty_receive() -> dict:
    return {"type": "http.request", "body": b"", "more_body": False}
