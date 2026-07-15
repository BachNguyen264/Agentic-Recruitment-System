"""screening_scheduler — SEAM lập lịch timeout Screener (08c · PRD §10).

Interface MỎNG `ScreeningTimeoutScheduler` (Protocol): vòng đời start/stop + on_session_created.
Impl `InProcessScheduler`: sweep loop = asyncio background task ở lifespan (event loop CHÍNH). Đổi
sang QStash sau chỉ cần impl MỚI cùng Protocol — nghiệp vụ (`screening_timeout` handlers) KHÔNG đổi.

CLAUDE.md: KHÔNG Redis polling; sweep in-process quét Postgres. Đây là file DUY NHẤT biết "cơ chế".
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.services import screening_timeout

logger = get_logger("app.services.screening_scheduler")


class ScreeningTimeoutScheduler(Protocol):
    """Cơ chế lập lịch timeout Screener (mỏng). App phụ thuộc INTERFACE này, KHÔNG phụ thuộc impl."""

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def on_session_created(self, application_id: int) -> None: ...


class InProcessScheduler:
    """Sweep loop trong tiến trình: mỗi `interval_seconds` gọi `sweep_once` (quét Postgres). Task bền
    trong event loop CHÍNH (lifespan) → await graph resume + AsyncPostgresSaver tự nhiên (KHÔNG
    asyncio.run per-item — bẫy 08a). Một vòng lỗi KHÔNG giết loop."""

    def __init__(self, interval_seconds: int) -> None:
        self._interval = max(1, interval_seconds)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="screener-timeout-sweep")
        logger.info("InProcessScheduler: sweep loop BẬT (mỗi %ss).", self._interval)

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("InProcessScheduler: sweep loop đã DỪNG.")

    async def on_session_created(self, application_id: int) -> None:
        # InProcess: NO-OP — sweep đọc DB theo chu kỳ nên tự khám phá session mới. Seam để QStash sau
        # đăng ký callback theo hạn (khi đó mới wiring lời gọi từ background); nay chưa cần (YAGNI).
        return None

    async def _run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                await screening_timeout.sweep_once(AsyncSessionLocal)
            except asyncio.CancelledError:
                raise  # dừng sạch khi stop()
            except Exception:  # noqa: BLE001 — một vòng lỗi KHÔNG giết loop (sweep vòng sau)
                logger.exception("InProcessScheduler: lỗi một vòng sweep — tiếp tục vòng sau.")


def get_scheduler() -> ScreeningTimeoutScheduler:
    """Chọn impl qua config (mặc định InProcess). Gọi ở lifespan; app phụ thuộc INTERFACE trả về."""
    return InProcessScheduler(interval_seconds=settings.screener_sweep_interval_seconds)
