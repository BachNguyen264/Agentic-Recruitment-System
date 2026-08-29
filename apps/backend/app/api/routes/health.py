"""Health endpoint — ping THẬT cả 3 dịch vụ managed (Postgres · Redis · Qdrant).

Kèm `/health/metrics` (hardening tải): đồng hồ đo BÃO HOÀ trong tiến trình — HAI pool Postgres
(SQLAlchemy + checkpointer psycopg), HAI thread pool (default executor của asyncio + limiter của
anyio), và số pipeline đang bay. Xem docstring của `metrics()` để biết vì sao nó nằm ở ĐÂY.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import anyio.to_thread
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text

from app.agents import checkpointer
from app.core.config import settings
from app.core.database import engine
from app.core.qdrant_client import qdrant_client
from app.core.redis_client import redis_client
from app.core.security import decode_token
from app.services.storage._executor import storage_executor_gauges
from app.tasks.background import pipeline_gauges

router = APIRouter(tags=["health"])

# Mốc khởi động. `time.monotonic()` chứ KHÔNG phải `time.time()`: đồng hồ hệ thống nhảy (NTP, đổi
# múi giờ) sẽ làm uptime âm hoặc vọt lên hàng năm giữa một lượt load test.
_STARTED_AT = time.monotonic()


async def _check_postgres() -> str:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — báo cáo trạng thái, không raise
        return f"error: {type(exc).__name__}"


async def _check_redis() -> str:
    try:
        return "ok" if await redis_client.ping() else "error: no pong"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


async def _check_qdrant() -> str:
    try:
        await qdrant_client.get_collections()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        return f"error: {type(exc).__name__}"


@router.get("/health/live", summary="Liveness THUẦN (health check của nền tảng)")
async def liveness() -> dict:
    """Chỉ trả lời "tiến trình còn sống" — KHÔNG chạm Postgres/Redis/Qdrant. Đây là path để trỏ
    Health Check của Render (slice 13).

    VÌ SAO tách khỏi `/health`: Render gửi health check VÀI GIÂY MỘT LẦN, liên tục suốt thời gian
    service chạy. Nếu trỏ vào `/health` (ping cả 3 dịch vụ) thì riêng health check đã ~17k lượt/ngày:
    vượt hạn mức Upstash free (10k lệnh/ngày) và giữ Neon luôn thức (đốt compute-hours) — hệ thống tự
    làm hỏng mình khi KHÔNG có ai dùng. Ngoài ra health check phải hỏi "tiến trình còn sống không";
    một dịch vụ phụ chập chờn KHÔNG phải lý do để Render restart cả backend.
    """
    return {"status": "ok"}


@router.get("/health", summary="Kiểm SÂU — ping 3 dịch vụ (dành cho người/chẩn đoán)")
async def health() -> dict:
    services = {
        "postgres": await _check_postgres(),
        "redis": await _check_redis(),
        "qdrant": await _check_qdrant(),
    }
    overall = "ok" if all(v == "ok" for v in services.values()) else "degraded"
    return {"status": overall, "api": "ok", "services": services}


# ──────────────────────────────────────────────────────────────────────────────────────────────────
# METRICS BÃO HOÀ (hardening tải) — đo xem TÀI NGUYÊN NÀO cạn trước
# ──────────────────────────────────────────────────────────────────────────────────────────────────
# Bối cảnh: audit đồng thời chỉ ra nút thắt thật KHÔNG phải DB mà là **một** default ThreadPoolExecutor
# dùng chung — parser gọi OpenAI ĐỒNG BỘ qua `asyncio.to_thread` (~9.4s/CV), R2 save/get, gửi mail
# Resend, và ruột AsyncPostgresSaver đều xếp hàng trong đó (rộng `min(32, cpu+4)`). Ranker (24.7s)
# dùng `ainvoke` nên KHÔNG tốn luồng nào. Vì đường NHẬN CV giữ một connection DB suốt lúc upload R2,
# tắc thread pool sẽ CHUYỂN HOÁ thành cạn pool DB. Load test hôm nay mù cả ba con số đó.


def _as_int(value: object) -> int | None:
    """Ép về int, nuốt MỌI lỗi → None. Dùng cho các ô đọc từ THUỘC TÍNH (không phải hàm).

    Cần riêng vì `CapacityLimiter.total_tokens` là **float** và có thể là `math.inf` (`int(inf)` ném
    OverflowError), còn `dict.get` của psycopg trả None khi thiếu khoá. Ép từng ô một để một ô hỏng
    KHÔNG kéo cả nhóm về None — mất một con số thì vẫn còn đọc được các con số bên cạnh.
    """
    try:
        return int(value)  # type: ignore[call-overload]
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return None


def _gauge(obj: object, name: str) -> int | None:
    """Gọi `obj.name()` và nuốt MỌI lỗi → None.

    Các lớp pool của SQLAlchemy KHÔNG cùng giao diện (`QueuePool`/`AsyncAdaptedQueuePool` có
    `overflow()`, `NullPool`/`StaticPool` thì không). Đổi `poolclass` hoặc nâng SQLAlchemy mà endpoint
    chẩn đoán 500 giữa lúc load test thì mất trắng cả lượt đo — thà trả None cho ô đó.
    """
    try:
        fn = getattr(obj, name, None)
        return int(fn()) if callable(fn) else None
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return None


def _db_pool_gauges() -> dict[str, int | None]:
    """Ảnh chụp pool connection của **SQLAlchemy engine** — THUẦN RAM, KHÔNG mở connection nào.

    CHỈ pool này, KHÔNG phải "tất cả kết nối Postgres của tiến trình": checkpointer LangGraph có pool
    psycopg RIÊNG (xem `_checkpointer_pool_gauges`). Đọc `db_pool` như tổng số là sai.

    Bốn hàm này chỉ đọc biến đếm sẵn có trong pool (`qsize`, `_overflow`), nên đo pool mà không hề
    làm nhiễu pool. Đây chính là lý do endpoint này KHÔNG được phép chạm DB: mượn một connection để
    báo cáo "còn bao nhiêu connection" là tự cộng 1 vào chính con số mình đang đo — và tệ hơn, lúc
    pool ĐÃ cạn (đúng khoảnh khắc cần số liệu nhất) thì nó treo tới `pool_timeout` rồi trả 500.

    Đọc số: `overflow` ÂM là BÌNH THƯỜNG — SQLAlchemy khởi tạo `_overflow = -pool_size`, nên -5 nghĩa
    là "chưa dùng hết 5 connection cơ sở". Bão hoà = `checked_out` chạm `max`.
    """
    pool = getattr(engine, "pool", None)
    if pool is None:  # engine đã dispose / lớp engine lạ
        return {"size": None, "checked_out": None, "overflow": None, "checked_in": None, "max": None}
    size = _gauge(pool, "size")
    max_overflow = getattr(pool, "_max_overflow", None)
    return {
        "size": size,
        "checked_out": _gauge(pool, "checkedout"),
        "overflow": _gauge(pool, "overflow"),
        "checked_in": _gauge(pool, "checkedin"),
        # Trần thật của pool = pool_size + max_overflow (mặc định SQLAlchemy 5 + 10 = 15).
        "max": (size + max_overflow) if (size is not None and isinstance(max_overflow, int)) else None,
    }


def _executor_gauges() -> dict[str, int | None]:
    """Ảnh chụp default ThreadPoolExecutor của event loop — con số quan trọng NHẤT của endpoint này.

    VÌ SAO CHẠM THUỘC TÍNH PRIVATE: asyncio KHÔNG có API công khai nào để hỏi "executor mặc định là
    cái nào" (`loop.set_default_executor` chỉ GHI), và `ThreadPoolExecutor` cũng không phơi ra số
    luồng đang sống lẫn độ sâu hàng đợi. Không có `_default_executor`/`_threads`/`_work_queue` thì
    KHÔNG ĐO ĐƯỢC thứ mà audit đồng thời chỉ đích danh là nút thắt. Đánh đổi chấp nhận được vì đây là
    CHẨN ĐOÁN thuần ĐỌC: mọi truy cập bọc `getattr`/`try`, hỏng thì ô đó thành None chứ KHÔNG bao giờ
    ảnh hưởng đường chạy nghiệp vụ. Nâng Python đổi tên private → mất SỐ, không mất APP.

    `_default_executor` là **None cho tới lần `to_thread`/`run_in_executor` ĐẦU TIÊN** (tạo lười). Nên
    "toàn None" ngay sau khi khởi động là ĐÚNG, không phải lỗi — nghĩa là chưa CV nào chạy parser.

    Đọc số: bão hoà = `threads_alive == max_workers` VÀ `queue_depth > 0`. `queue_depth` chính là số
    lượt gọi (parser LLM / R2 / email) đang XẾP HÀNG chờ luồng — nó tăng thì độ trễ đuôi tăng theo,
    dù CPU vẫn rảnh và pool DB vẫn rỗi.

    CẢNH BÁO ĐỌC SỐ — `threads_alive` KHÔNG phải "số luồng đang bận": `ThreadPoolExecutor` không bao
    giờ bỏ Thread ra khỏi `_threads`, luồng rảnh vẫn nằm đó chờ việc. Nên nó là **đỉnh lịch sử** của
    nhu cầu đồng thời, chỉ TĂNG. Muốn biết "đang bận bao nhiêu" thì không có ở đây — dùng
    `queue_depth > 0` làm bằng chứng bão hoà, ĐỪNG kết luận từ riêng `threads_alive`.

    ĐÂY LÀ MỘT TRONG **HAI** THREAD POOL. Cái này là default executor của asyncio (`asyncio.to_thread`
    → parser LLM, R2, email Resend). Starlette/FastAPI KHÔNG dùng nó — mọi `run_in_threadpool`, mọi
    endpoint `def` đồng bộ, và `await file.read()` trên UploadFile đã tràn đĩa (>1MB, tức MỌI CV thật)
    đi qua thread pool của **anyio** (xem `_anyio_thread_gauges`). Chỉ nhìn ô này rồi kết luận "thread
    pool không bão hoà" là kết luận SAI cho đúng cái đường nhận CV.
    """
    empty: dict[str, int | None] = {"max_workers": None, "threads_alive": None, "queue_depth": None}
    try:
        executor = getattr(asyncio.get_running_loop(), "_default_executor", None)
        if executor is None:
            return empty
        threads = getattr(executor, "_threads", None)
        work_queue = getattr(executor, "_work_queue", None)
        max_workers = getattr(executor, "_max_workers", None)
        return {
            "max_workers": max_workers if isinstance(max_workers, int) else None,
            "threads_alive": len(threads) if threads is not None else None,
            "queue_depth": _gauge(work_queue, "qsize") if work_queue is not None else None,
        }
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return empty


def _anyio_thread_gauges() -> dict[str, int | None]:
    """Thread pool THỨ HAI: `CapacityLimiter` mặc định của anyio — cái Starlette/FastAPI thật sự dùng.

    VÌ SAO BẮT BUỘC CÓ: đường NHẬN CV (`POST /api/public/applications`) đọc file bằng
    `await file.read()`; Starlette đổ multipart vào `SpooledTemporaryFile(max_size=1MB)` nên mọi CV
    thật (1–10MB) đã TRÀN ra đĩa ⇒ cả lượt `write` từng khối lúc upload lẫn lượt `read` cuối cùng đều
    chạy qua `run_in_threadpool` = `anyio.to_thread.run_sync`, KHÔNG qua default executor của asyncio.
    Thiếu ô này thì lúc load test đúng cái pool đang nghẽn lại vô hình, còn `executor.queue_depth` vẫn
    hiện 0 — một con số TRẤN AN nhưng nói về pool khác. Trần mặc định 40 token (anyio), khác 20 của
    executor asyncio, nên hai pool bão hoà ở hai ngưỡng khác nhau.

    KHÔNG NHIỄU: `current_default_thread_limiter()` là API CÔNG KHAI, đọc một `RunVar`; nếu limiter
    chưa tồn tại nó tạo đúng cái `CapacityLimiter(40)` mà anyio sẽ tự tạo ở lần dùng thread đầu tiên —
    cùng object, cùng giá trị, không đổi hành vi. `statistics()` thuần RAM, không khoá, không I/O.

    Đọc số: bão hoà = `borrowed == total_tokens` VÀ `waiting > 0`. `waiting` là số coroutine đang
    CHỜ token — tương đương `queue_depth` bên executor asyncio.

    Ràng buộc: phải gọi TRONG event loop (RunVar theo loop). Ngoài loop → toàn None.
    """
    empty: dict[str, int | None] = {"total_tokens": None, "borrowed": None, "waiting": None}
    try:
        limiter = anyio.to_thread.current_default_thread_limiter()
        stats = limiter.statistics()
        return {
            "total_tokens": _as_int(limiter.total_tokens),
            "borrowed": _as_int(stats.borrowed_tokens),
            "waiting": _as_int(stats.tasks_waiting),
        }
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return empty


def _checkpointer_pool_gauges() -> dict[str, int | None]:
    """Pool Postgres THỨ HAI: pool psycopg của AsyncPostgresSaver (LangGraph) — THUẦN RAM.

    VÌ SAO BẮT BUỘC CÓ: `db_pool` ở trên CHỈ là pool asyncpg của SQLAlchemy engine. Checkpointer mở
    một `AsyncConnectionPool` psycopg RIÊNG tới Neon (`checkpointer._build_pool`, trần
    `CHECKPOINTER_POOL_MAX_SIZE`) và LangGraph ghi checkpoint sau MỖI node ⇒ mỗi pipeline chạm pool
    này nhiều lượt. Nó cạn thì pipeline treo trong khi `db_pool.checked_out` vẫn báo 0/15 — lại đúng
    kiểu con số trấn an mà sai. Hai pool ĐỘC LẬP, cạn độc lập, phải đo riêng.

    `get_stats()` của psycopg_pool là hàm ĐỒNG BỘ, chỉ đọc biến đếm sẵn có (`_nconns`, `len(_pool)`,
    `len(_waiting)`) — KHÔNG khoá, KHÔNG mở connection. `checked_out` là suy ra: đã tạo trừ đang rảnh.

    Đọc `checkpointer._pool` (private) vì module chỉ phơi `get_graph()`; cùng đánh đổi đã nêu ở
    `_executor_gauges` — CHỈ ĐỌC, hỏng thì thành None, không đụng đường chạy nghiệp vụ. `None` trước
    lifespan (`setup_checkpointer` chưa chạy) hoặc sau khi tắt là ĐÚNG, không phải lỗi.
    """
    empty: dict[str, int | None] = {
        "size": None, "available": None, "checked_out": None, "max": None, "waiting": None,
    }
    pool = getattr(checkpointer, "_pool", None)
    if pool is None:
        return empty
    try:
        stats = pool.get_stats()
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return empty
    size = _as_int(stats.get("pool_size"))
    available = _as_int(stats.get("pool_available"))
    return {
        "size": size,
        "available": available,
        "checked_out": (size - available) if (size is not None and available is not None) else None,
        "max": _as_int(stats.get("pool_max")),
        "waiting": _as_int(stats.get("requests_waiting")),
    }


def _rss_bytes() -> int | None:
    """RSS của tiến trình, RẺ tiền: đọc `/proc/self/status` trên Linux (prod Render), None ở nơi khác.

    KHÔNG thêm `psutil` — một dependency mới chỉ để lấy MỘT con số trên MỘT hệ điều hành thì không
    đáng, và bản Windows của nó còn gọi API nặng hơn nhiều so với đọc một file ảo.
    """
    if not sys.platform.startswith("linux"):
        return None  # Windows (máy dev): trả None thay vì đoán bừa.
    try:
        with open("/proc/self/status", encoding="ascii") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024  # kB → byte
    except Exception:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        return None
    return None


async def _require_hr_cookie(request: Request) -> None:
    """Cổng HR **KHÔNG I/O** cho riêng `/health/metrics`: verify JWT trong cookie, DỪNG ở đó.

    KHÁC `deps.require_hr` ở đúng MỘT điểm — bỏ bước `session.get(HrUser, ...)`. LÝ DO bắt buộc:
    `require_hr` phụ thuộc `get_session`, tức MỖI lượt gọi mượn một connection từ chính cái pool mà
    endpoint này sinh ra để đo. Ở nhịp poll 250ms (4 lượt/giây) suốt một lượt load test, cổng auth sẽ
    (a) cộng thêm 1 vào `checked_out` mà nó đang báo cáo — số liệu NÓI DỐI, và (b) lúc pool cạn thì
    CHÍNH nó chờ tới `pool_timeout` rồi 500, làm mất số liệu đúng vào khoảnh khắc duy nhất cần nó.
    Một endpoint chẩn đoán không được phép nhiễu hệ nó đang đo.

    Bảo mật giữ nguyên chốt chặn chính: vẫn là cookie httpOnly + chữ ký HS256 (`decode_token`), người
    chưa đăng nhập KHÔNG đọc được. Khoản mất DUY NHẤT là thu hồi TỨC THÌ: token còn hạn của một HR
    vừa bị xoá vẫn đọc được (tối đa `jwt_expiry_minutes`) — chấp nhận vì payload chỉ là mấy con số
    đếm tài nguyên, KHÔNG có dữ liệu ứng viên. TUYỆT ĐỐI KHÔNG copy cổng này sang endpoint có dữ liệu
    thật; ở đó dùng `require_hr` (Auth boundary 09).
    """
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Chưa đăng nhập.")
    if decode_token(token) is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Phiên không hợp lệ.")


@router.get(
    "/health/metrics",
    dependencies=[Depends(_require_hr_cookie)],
    summary="Đồng hồ đo bão hoà trong tiến trình (HR-only, KHÔNG I/O)",
)
async def metrics() -> dict:
    """Pool DB · thread pool · pipeline đang bay — để load test THẤY tài nguyên nào cạn trước.

    NẰM TRONG ROUTER HEALTH NHƯNG CHỈ MÌNH NÓ BỊ KHOÁ: `main.py` include health router KHÔNG kèm
    `_HR_ONLY`, còn `dependencies=[...]` đặt ở decorator thì chỉ áp cho ĐÚNG route này. TUYỆT ĐỐI
    KHÔNG nâng nó lên thành dependency cấp router: `/api/health/live` là Health Check của Render —
    khoá lại là Render nhận 401, coi service chết và restart vòng lặp ⇒ SỰ CỐ DEPLOY. `/api/health`
    (kiểm sâu) cũng phải MỞ (Auth boundary 09: health luôn công khai). Route này là NGOẠI LỆ có chủ ý
    vì nó phơi ra hình dạng hạ tầng bên trong.

    KHÔNG I/O: mọi con số đọc từ RAM tiến trình (biến đếm của pool, thuộc tính executor, int
    module-level ở `tasks/background`). Nó được thiết kế để bị poll 250ms/lần suốt cả lượt load test.

    KHÔNG BAO GIỜ 500: cả thân hàm nằm trong một `try` — endpoint chẩn đoán mà sập giữa chừng thì
    giết luôn lượt đo, và số liệu load test không chạy lại miễn phí (tốn tiền LLM + email THẬT). Thiếu
    số nào thì ô đó là `null`, KHÔNG bỏ khoá — client cứ đọc theo bộ khoá cố định. HÌNH DẠNG payload
    CỐ ĐỊNH kể cả ở nhánh lỗi: bốn nhóm luôn là dict (các ô bên trong mới thành `null`), để client cứ
    `r["db_pool"]["checked_out"]` mà không phải phòng thủ `None` ở tầng giữa.

    ĐO ĐÚNG **MỘT TIẾN TRÌNH** — chính tiến trình đã phục vụ request này. Backend chạy một process
    (`app/__main__.py`, không `--workers`) nên đây là toàn hệ thống; ngày nào bật nhiều worker thì các
    con số này là của MỘT worker ngẫu nhiên, cộng lại mới ra tổng.

    PHẠM VI `pipelines`: đếm `process_application` (lượt chạy ĐẦU của một CV) — KHÔNG đếm
    `resume_screener` (ứng viên nộp form / sweep 08c gọi lại graph). Hai đường đó vẫn tiêu executor +
    checkpointer_pool, nên `in_flight = 0` KHÔNG có nghĩa "không có graph nào đang chạy".
    """
    try:
        cpu_count = os.cpu_count()
        return {
            "db_pool": _db_pool_gauges(),
            "checkpointer_pool": _checkpointer_pool_gauges(),
            "executor": _executor_gauges(),
            "storage_executor": storage_executor_gauges(),
            "anyio_threads": _anyio_thread_gauges(),
            "pipelines": pipeline_gauges(),
            "cpu_count": cpu_count,
            # Công thức mặc định của ThreadPoolExecutor khi asyncio tạo executor lười. In ra để ĐỐI
            # CHIẾU: nếu nó LỆCH `executor.max_workers` nghĩa là có ai đó đã `set_default_executor`.
            "thread_default_width": min(32, (cpu_count or 1) + 4),
            "rss_bytes": _rss_bytes(),
            "uptime_seconds": round(time.monotonic() - _STARTED_AT, 3),
        }
    except Exception as exc:  # noqa: BLE001 — chẩn đoán: KHÔNG BAO GIỜ raise
        # Giữ NGUYÊN hình dạng lồng nhau (dict-toàn-null), KHÔNG hạ nhóm xuống `None`: client load
        # test đọc `r["db_pool"]["checked_out"]`, đưa `None` vào đó là làm SẬP client ở đúng lượt đo
        # mà endpoint vừa hứa sẽ không làm sập nó.
        return {
            "db_pool": dict.fromkeys(("size", "checked_out", "overflow", "checked_in", "max")),
            "checkpointer_pool": dict.fromkeys(("size", "available", "checked_out", "max", "waiting")),
            "executor": dict.fromkeys(("max_workers", "threads_alive", "queue_depth")),
            "storage_executor": dict.fromkeys(("max_workers", "threads_alive", "queue_depth")),
            "anyio_threads": dict.fromkeys(("total_tokens", "borrowed", "waiting")),
            "pipelines": dict.fromkeys(("in_flight", "started_total", "finished_total", "failed_total")),
            "cpu_count": None,
            "thread_default_width": None,
            "rss_bytes": None,
            "uptime_seconds": None,
            "error": type(exc).__name__,
        }
