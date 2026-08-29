"""FastAPI entrypoint (scaffold).

Khởi tạo app, CORS cho web dashboard (PWA), lifespan đóng kết nối sạch khi tắt.
Nguồn chân lý nghiệp vụ: PRD.md.
"""

from __future__ import annotations

import time
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
from app.services.storage import get_storage
from app.services.storage._executor import shutdown_storage_executor

logger = get_logger("app.main")


def _warm_llm_imports() -> None:
    """Nhập sẵn `langchain_openai` để lượt nhập LẠNH không rơi vào ứng viên đầu tiên.

    KHÔNG BAO GIỜ raise: đây thuần là tối ưu khởi động. Nhập hỏng (thiếu gói, lỗi mạng lúc build) thì
    hành vi quay về đúng như CŨ — nhập lười ở lần dùng đầu — chứ tuyệt đối không được chặn server
    khởi động, vì như thế là biến một tối ưu thành sự cố deploy.

    Bỏ qua khi `ENABLE_LLM=false`: khi đó parser/ranker chạy nhánh stub và KHÔNG hề chạm langchain,
    nên nạp trước chỉ tổ kéo dài thời gian khởi động mà không đổi được gì.
    """
    if not settings.enable_llm:
        return
    started = time.perf_counter()
    try:
        import langchain_openai  # noqa: F401 — nạp để làm ấm module cache, không dùng trực tiếp
    except Exception:  # noqa: BLE001 — tối ưu khởi động KHÔNG được phép giết server
        logger.warning("Không nạp trước được langchain_openai — sẽ nhập lười như cũ", exc_info=True)
        return
    logger.info("Đã nạp trước ngăn xếp LLM trong %.2fs", time.perf_counter() - started)


def _warm_storage_client() -> None:
    """Dựng sẵn client storage (boto3/R2) — thủ phạm CHÍNH của cú chậm-lần-đầu. KHÔNG BAO GIỜ raise.

    Xem `R2Storage.warmup` để biết số đo và danh sách giả thuyết đã bị bác. Tóm tắt: client tạo lười
    DƯỚI MỘT KHOÁ, nên trên container vừa deploy, 20 lượt nộp đồng thời cùng xếp hàng sau lượt đầu
    (import boto3 + nạp service model + TLS) rồi được nhả ra cùng lúc — 18,7s thay vì 0,22s.
    """
    started = time.perf_counter()
    try:
        storage = get_storage()
        warm = getattr(storage, "warmup", None)
        if callable(warm):
            warm()
            logger.info("Đã làm ấm client storage trong %.2fs", time.perf_counter() - started)
    except Exception:  # noqa: BLE001 — tối ưu khởi động KHÔNG được phép giết server
        logger.warning("Không làm ấm được storage — sẽ tạo lười ở lần dùng đầu", exc_info=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info(
        "Backend khởi động (env=%s, enable_llm=%s, confidence_threshold=%s)",
        settings.app_env,
        settings.enable_llm,
        settings.confidence_threshold,
    )
    # Nạp TRƯỚC ngăn xếp LLM (đo tải): `parser._build_parser_llm` và `embedding_service._embeddings`
    # cố ý `import langchain_openai` LƯỜI (chỉ nhập khi thật sự cần). Cái giá là lượt nhập ĐẦU TIÊN
    # rơi vào ứng viên đầu tiên sau mỗi lần deploy — và lượt nhập đó GIỮ GIL, nên nó không làm chậm
    # một request mà đóng băng CẢ TIẾN TRÌNH.
    # SỐ ĐO: `import langchain_openai` mất **1,5s** trên máy dev 16 CPU; Render gói free chỉ ~0,1 CPU
    # ⇒ ước 15–22s. Khớp với hiện tượng quan sát được trên prod: ba lần đo NGAY SAU DEPLOY đều cho độ
    # trễ nhận 13–18s với các lượt DỒN CỤC quanh cùng một mốc (dấu hiệu "cùng chờ một sự kiện rồi
    # được nhả ra cùng lúc"), trong khi lúc đã ấm là 0,22s — kể cả khi 15 pipeline đang chạy.
    # Trả cái giá đó Ở ĐÂY, lúc khởi động, khi CHƯA có ứng viên nào chờ.
    _warm_llm_imports()
    _warm_storage_client()
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
    shutdown_storage_executor()
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
