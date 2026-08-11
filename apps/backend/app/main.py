"""FastAPI entrypoint (scaffold).

Khởi tạo app, CORS cho web dashboard (PWA), lifespan đóng kết nối sạch khi tắt.
Nguồn chân lý nghiệp vụ: PRD.md.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents import checkpointer
from app.api.deps import require_hr
from app.api.routes import agents, applications, auth, health, jobs, public, webhooks
from app.core.config import settings
from app.core.database import engine
from app.core.hardening import (
    BodySizeLimitMiddleware,
    OriginCheckMiddleware,
    RateLimitMiddleware,
)
from app.core.logging import get_logger, setup_logging
from app.core.qdrant_client import qdrant_client
from app.core.redis_client import redis_client
from app.services import screening_scheduler

logger = get_logger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(
        "Backend khởi động (env=%s, enable_llm=%s, confidence_threshold=%s)",
        settings.app_env,
        settings.enable_llm,
        settings.confidence_threshold,
    )
    # Checkpointer Postgres (PRD §10): pool + bảng checkpoint Neon, compile graph — MỘT LẦN ở đây.
    await checkpointer.setup_checkpointer()
    # Sweep timeout Screener (08c, PRD §10 FR-SCR-3/4): SAU checkpointer (sweep resume graph cần
    # graph đã compile với saver). Task ở event loop chính. Đổi InProcess↔QStash không đụng nghiệp vụ.
    scheduler = screening_scheduler.get_scheduler()
    await scheduler.start()
    app.state.screening_scheduler = scheduler
    yield
    # Đóng kết nối sạch — dừng sweep TRƯỚC khi đóng checkpointer (sweep dùng graph/pool).
    await scheduler.stop()
    await checkpointer.teardown_checkpointer()
    await redis_client.aclose()
    await qdrant_client.close()
    await engine.dispose()
    logger.info("Backend tắt — đã đóng sweep + Redis/Qdrant/DB.")


app = FastAPI(
    title="Autonomous Recruitment System — Backend",
    version="0.1.0",
    description="Pipeline tuyển dụng đa tác tử (scaffold). Nguồn chân lý: PRD.md.",
    lifespan=lifespan,
)

_CORS_ORIGINS = settings.cors_allow_origins  # nổ SỚM nếu cấu hình '*' (xem config.cors_allow_origins)

# THỨ TỰ MIDDLEWARE (slice 13): add_middleware CHÈN LÊN ĐẦU → cái thêm SAU nằm NGOÀI. Thứ tự chạy
# mong muốn: CORS → body-size → rate-limit → app, nên thêm theo chiều ngược lại.
# CORS phải NGOÀI CÙNG để 413/429 cũng có header CORS: nếu không, trình duyệt báo "CORS error" và
# frontend KHÔNG đọc được message thân thiện ("Bạn thao tác quá nhanh…") — ứng viên chỉ thấy lỗi lạ.
app.add_middleware(
    RateLimitMiddleware,
    login_max=settings.rate_limit_login_max,
    login_window_seconds=settings.rate_limit_login_window_seconds,
    public_max=settings.rate_limit_public_max,
    public_window_seconds=settings.rate_limit_public_window_seconds,
    trust_proxy=settings.trust_proxy,
    proxy_hops=settings.proxy_trusted_hops,
    client_ip_header=settings.proxy_client_ip_header,
    enabled=settings.rate_limit_enabled,
)
app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_bytes)

# CSRF (SCH-3, sau adversarial review). Nằm NGOÀI rate-limit/body-size (thêm SAU = ngoài hơn) nhưng
# TRONG CORS, để phản hồi 403 vẫn có header CORS và frontend đọc được thông điệp.
# Cùng danh sách với CORS: nếu đăng nhập đang chạy được thì kiểm này không thể chặn nhầm frontend
# thật. Thiếu header `Origin` (curl/script vận hành/load test) → CHO QUA: không phải trình duyệt thì
# không có cookie ambient để lợi dụng.
app.add_middleware(
    OriginCheckMiddleware,
    allowed=frozenset(_CORS_ORIGINS),
    allow_regex="" if _CORS_ORIGINS else r"http://(localhost|127\.0\.0\.1)(:\d+)?",
)

app.add_middleware(
    CORSMiddleware,
    # Deploy (slice 13): CORS_ORIGINS = URL frontend Vercel (danh sách CỤ THỂ — bắt buộc khi có
    # cookie: allow_credentials + '*' bị browser cấm). KHÔNG đặt env → dev: regex localhost mọi cổng
    # (dashboard :3000). Middleware phủ MỌI route, kể cả công khai (/apply, /screening gọi từ frontend).
    allow_origins=_CORS_ORIGINS,
    allow_origin_regex=None if _CORS_ORIGINS else r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Content-Disposition KHÔNG thuộc nhóm header CORS mặc định cho phép đọc → không expose thì JS
    # ở dashboard (khác origin: :3000 vs :8000, và khác domain khi deploy) không đọc được tên file
    # khi tải CV gốc (slice 06).
    expose_headers=["Content-Disposition"],
)

# Slice 09 — Auth HR (PRD §4): require_hr bảo vệ MỌI router HR ở cấp router (áp cho mọi endpoint
# bên trong). CÔNG KHAI giữ MỞ tuyệt đối: health, auth (login/logout), public (JD/nộp CV/screening),
# webhook (EMAIL-1: Resend gọi server-to-server, không có cookie phiên nào để kiểm — chốt chặn của
# nó là CHỮ KÝ, xem `api/routes/webhooks.py`) — ứng viên GUEST không bị chặn. `me` tự bảo vệ trong
# auth router (dependency ở handler).
_HR_ONLY = [Depends(require_hr)]

app.include_router(health.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(public.router, prefix="/api")
# Webhook nhà cung cấp email (EMAIL-1): CÔNG KHAI có chủ ý — Resend gọi server-to-server, không có
# cookie phiên nào để kiểm. Chốt chặn là CHỮ KÝ (`core/webhook_signature`), không phải `require_hr`.
app.include_router(webhooks.router, prefix="/api")
app.include_router(applications.router, prefix="/api", dependencies=_HR_ONLY)
app.include_router(agents.router, prefix="/api", dependencies=_HR_ONLY)
app.include_router(jobs.router, prefix="/api", dependencies=_HR_ONLY)


@app.get("/", tags=["meta"])
async def root() -> dict:
    return {
        "name": "autonomous-recruitment-system",
        "stage": "scaffold",
        "docs": "/docs",
        "health": "/api/health",
    }
