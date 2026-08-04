"""Seam lịch ngoài (SCH-1 · PRD §10b.8, §17).

Nghiệp vụ đặt lịch **chỉ** biết `CalendarProvider` — nó KHÔNG biết `.ics` hay Google Calendar tồn
tại. Đổi cách tạo sự kiện = đổi `CALENDAR_PROVIDER`, KHÔNG sửa nghiệp vụ (đúng khuôn `services/storage`).

- `IcsProvider` (mặc định): sinh tệp `.ics` để SCH-2 đính vào email xác nhận. **Không cần OAuth**,
  không gọi mạng, không có trạng thái phía máy chủ.
- `GoogleCalendarProvider` (PRD §17, CHƯA làm): sẽ đọc lịch bận + tạo event thật.

⚠️ SCH-1 chỉ dựng seam — **chưa ai gọi tới**. SCH-2 mới đính `.ics` vào email xác nhận.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import settings
from app.models.booking import InterviewBooking

__all__ = [
    "CalendarError",
    "CalendarEvent",
    "CalendarProvider",
    "get_calendar_provider",
]


class CalendarError(Exception):
    """Lỗi tầng lịch (cấu hình sai / provider ngoài từ chối)."""


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """Kết quả tạo sự kiện.

    `ref`: định danh BỀN của sự kiện — UID iCalendar với `IcsProvider`, event id với provider ngoài.
    Lưu lại để `cancel_event`/dời lịch (SCH-3) chỉ đúng sự kiện đó.

    `ics`: nội dung tệp `.ics` để đính kèm email, hoặc `None` nếu provider tạo sự kiện thẳng trên
    lịch ngoài và không có gì để đính kèm.
    """

    ref: str
    ics: bytes | None = None


class CalendarProvider(Protocol):
    """Hợp đồng tạo/huỷ sự kiện lịch. Async vì provider ngoài (Google) là I/O mạng — giữ async ngay
    từ đầu để đổi provider KHÔNG phải sửa chữ ký ở mọi nơi gọi."""

    async def create_event(
        self,
        booking: InterviewBooking,
        *,
        summary: str,
        description: str = "",
        location: str = "",
    ) -> CalendarEvent: ...

    async def cancel_event(self, ref: str) -> None:
        """Huỷ sự kiện đã tạo. IDEMPOTENT: `ref` không còn tồn tại → không lỗi."""
        ...


@lru_cache
def get_calendar_provider() -> CalendarProvider:
    """Factory theo `CALENDAR_PROVIDER` (singleton)."""
    backend = (settings.calendar_provider or "ics").strip().lower()
    if backend == "ics":
        from app.services.calendar.ics import IcsProvider

        return IcsProvider()
    raise CalendarError(
        f"CALENDAR_PROVIDER không hợp lệ: {backend!r} (hiện chỉ hỗ trợ 'ics'; "
        "'google' nằm ở PRD §17, chưa triển khai)."
    )
