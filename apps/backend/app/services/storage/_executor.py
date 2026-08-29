"""Thread pool RIÊNG cho storage — tách khỏi executor mặc định mà parser LLM đang chiếm.

VÌ SAO TỒN TẠI (số đo trên prod, không phải lý thuyết):
    `asyncio.to_thread()` luôn dùng **default executor** của event loop — một hàng đợi FIFO DUY NHẤT,
    rộng `min(32, cpu_count + 4)` (trên Render đo được **12**). Cùng lúc đó `parser.py` gọi OpenAI
    **ĐỒNG BỘ** qua `asyncio.to_thread`, mỗi lượt giam một luồng ~10 giây.

    Hệ quả: một lượt upload CV (0,3s) nộp vào lúc 15 pipeline đang parse phải **xếp hàng sau chúng**.
    Đo trên prod với 20 CV nộp cùng lúc:

        N=1  → độ trễ nhận 0,48s
        N=5  → độ trễ nhận 0,74s
        N=20 → độ trễ nhận **13,4s**   ← sập phi tuyến

    Không phải do giữ connection DB (đã bỏ `refresh()` thừa, số KHÔNG đổi), không phải do CPU, không
    phải do Postgres. Chỉ là **xếp hàng sau LLM trong cùng một thread pool**.

CÁCH SỬA: cho storage một executor riêng. Upload không còn chung hàng với parser, nên độ trễ nhận
tách rời hoàn toàn khỏi việc pipeline đang bận bao nhiêu.

VÌ SAO KHÔNG `loop.set_default_executor(...)`: đó là biến toàn cục của cả tiến trình, đổi luôn hành
vi của parser + email + nội bộ LangGraph. Ở đây chỉ cần tách ĐÚNG một nhóm việc, nên phạm vi hẹp
là lựa chọn đúng.

GHI CHÚ ĐO ĐẠC: trên prod **không đọc được** `loop._default_executor` (uvicorn tự chọn `uvloop` trên
Linux, mà uvloop không phơi thuộc tính đó) ⇒ `GET /api/health/metrics` trả `executor: null` ở prod
dù chạy tốt ở local Windows. Executor RIÊNG này thì đọc được ở mọi nơi vì chính ta giữ tham chiếu.
"""

from __future__ import annotations

import asyncio
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from app.core.config import settings

_T = TypeVar("_T")

_EXECUTOR: ThreadPoolExecutor | None = None


def storage_executor() -> ThreadPoolExecutor:
    """Executor dùng chung cho MỌI thao tác storage. Tạo lười, một lần cho cả tiến trình."""
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(
            max_workers=max(1, settings.storage_executor_workers),
            thread_name_prefix="storage",
        )
    return _EXECUTOR


async def run_in_storage_thread(fn: Callable[..., _T], *args: Any, **kwargs: Any) -> _T:
    """Chạy một lời gọi storage ĐỒNG BỘ (đĩa / boto3) trên executor riêng.

    Thay thẳng cho `asyncio.to_thread(fn, *args)` — khác biệt DUY NHẤT là executor nào phục vụ.
    """
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(storage_executor(), functools.partial(fn, *args, **kwargs))


def storage_executor_gauges() -> dict[str, int | None]:
    """Số đo cho `/api/health/metrics`. KHÔNG BAO GIỜ raise — đây là chẩn đoán thuần đọc.

    `threads_alive` là ĐỈNH LỊCH SỬ (ThreadPoolExecutor không bao giờ bỏ luồng khỏi `_threads`), nên
    bằng chứng bão hoà là `queue_depth > 0`, không phải riêng `threads_alive`.
    """
    try:
        if _EXECUTOR is None:
            return {"max_workers": settings.storage_executor_workers, "threads_alive": 0, "queue_depth": 0}
        work_queue = getattr(_EXECUTOR, "_work_queue", None)
        threads = getattr(_EXECUTOR, "_threads", None)
        return {
            "max_workers": _EXECUTOR._max_workers,  # noqa: SLF001 — không có API công khai
            "threads_alive": len(threads) if threads is not None else None,
            "queue_depth": work_queue.qsize() if work_queue is not None else None,
        }
    except Exception:  # noqa: BLE001 — chẩn đoán KHÔNG được phép giết endpoint
        return {"max_workers": None, "threads_alive": None, "queue_depth": None}


def shutdown_storage_executor() -> None:
    """Đóng executor lúc tắt server (lifespan). Idempotent."""
    global _EXECUTOR
    if _EXECUTOR is not None:
        _EXECUTOR.shutdown(wait=False, cancel_futures=True)
        _EXECUTOR = None
