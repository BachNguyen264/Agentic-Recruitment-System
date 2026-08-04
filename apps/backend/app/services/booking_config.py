"""Cấu hình khả dụng phỏng vấn — đọc + KIỂM env một lần, thành một đối tượng bất biến.

PRD §10b.7 / FR-BOOK-5: khả dụng là **toàn cục** (không theo từng JD) — đúng mô hình single-tenant.

Vì sao tách khỏi `Settings`: `Settings` giữ CHUỖI thô từ env ("08:00", "1-5", "12:00-13:30"); ở đây
mới phân tích thành `time`/`frozenset` và **kiểm tính nhất quán** (giờ làm hợp lệ, nghỉ trưa nằm
trong giờ làm, buổi phỏng vấn nhét vừa một ngày). Gộp vào `Settings` thì mọi test sinh slot phải vá
14 thuộc tính rời rạc; tách ra thì test dựng thẳng một `BookingConfig` — đó là lý do duy nhất, và
đủ, cho lớp này.

Múi giờ: `ZoneInfo` (stdlib). Mọi `datetime` ở tầng đặt lịch đều **aware** — xem `booking_service`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from functools import lru_cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings

__all__ = ["BookingConfig", "BookingConfigError", "load_booking_config"]


class BookingConfigError(ValueError):
    """Cấu hình khả dụng sai — nêu rõ biến env nào sai và sai ở đâu."""


def _parse_time(raw: str, field: str) -> time:
    """ "HH:MM" → time. Sai định dạng thì nổ NGAY với tên biến, đừng đoán bừa 00:00."""
    text = (raw or "").strip()
    try:
        hh, mm = text.split(":")
        return time(hour=int(hh), minute=int(mm))
    except (ValueError, AttributeError) as exc:
        raise BookingConfigError(f"{field} phải có dạng HH:MM (nhận được {raw!r}).") from exc


def _parse_work_days(raw: str) -> frozenset[int]:
    """ "1-5" / "1,3,5" / "1-5,7" → tập ISO weekday (1=Thứ Hai … 7=Chủ Nhật)."""
    days: set[int] = set()
    for chunk in (raw or "").split(","):
        part = chunk.strip()
        if not part:
            continue
        try:
            if "-" in part:
                lo, hi = (int(x) for x in part.split("-", 1))
                if lo > hi:
                    raise ValueError
                days.update(range(lo, hi + 1))
            else:
                days.add(int(part))
        except ValueError as exc:
            raise BookingConfigError(
                f"BOOKING_WORK_DAYS không đọc được ở đoạn {part!r} — dùng dạng '1-5' hoặc '1,3,5'."
            ) from exc
    if not days:
        raise BookingConfigError("BOOKING_WORK_DAYS rỗng — phải có ít nhất một ngày làm việc.")
    if any(d < 1 or d > 7 for d in days):
        raise BookingConfigError(
            f"BOOKING_WORK_DAYS chứa ngày ngoài 1..7 ({sorted(days)}) — 1=Thứ Hai, 7=Chủ Nhật."
        )
    return frozenset(days)


def _parse_lunch(raw: str) -> tuple[time, time] | None:
    """ "12:00-13:30" → (bắt đầu, kết thúc). RỖNG = không nghỉ trưa (hợp lệ)."""
    text = (raw or "").strip()
    if not text:
        return None
    if "-" not in text:
        raise BookingConfigError(f"BOOKING_LUNCH phải có dạng HH:MM-HH:MM (nhận được {raw!r}).")
    lo, hi = text.split("-", 1)
    return _parse_time(lo, "BOOKING_LUNCH (vế đầu)"), _parse_time(hi, "BOOKING_LUNCH (vế sau)")


@dataclass(frozen=True, slots=True)
class BookingConfig:
    """Ảnh chụp bất biến của khả dụng. Dựng thẳng trong test; prod đi qua `load_booking_config()`."""

    tz: ZoneInfo
    work_days: frozenset[int]
    work_start: time
    work_end: time
    lunch: tuple[time, time] | None
    duration_minutes: int
    buffer_minutes: int
    lead_time_hours: float
    max_per_day: int
    window_days: int
    slots_offered: int
    hold_minutes: float
    link_ttl_hours: float

    def __post_init__(self) -> None:
        if self.work_start >= self.work_end:
            raise BookingConfigError(
                f"BOOKING_WORK_START ({self.work_start}) phải TRƯỚC BOOKING_WORK_END ({self.work_end})."
            )
        if self.duration_minutes <= 0:
            raise BookingConfigError("BOOKING_DURATION_MINUTES phải > 0.")
        if self.buffer_minutes < 0:
            raise BookingConfigError("BOOKING_BUFFER_MINUTES không được âm.")
        if self.lead_time_hours < 0:
            raise BookingConfigError("BOOKING_LEAD_TIME_HOURS không được âm.")
        for name, value in (
            ("BOOKING_MAX_PER_DAY", self.max_per_day),
            ("BOOKING_WINDOW_DAYS", self.window_days),
            ("BOOKING_SLOTS_OFFERED", self.slots_offered),
        ):
            if value < 1:
                raise BookingConfigError(f"{name} phải >= 1 (nhận được {value}).")
        if self.hold_minutes <= 0:
            raise BookingConfigError("BOOKING_HOLD_MINUTES phải > 0 — hold 0 phút thì giữ chỗ vô nghĩa.")
        if self.link_ttl_hours <= 0:
            raise BookingConfigError("BOOKING_LINK_TTL_HOURS phải > 0.")
        if self.lunch is not None:
            lunch_start, lunch_end = self.lunch
            if lunch_start >= lunch_end:
                raise BookingConfigError(
                    f"BOOKING_LUNCH: giờ bắt đầu ({lunch_start}) phải TRƯỚC giờ kết thúc ({lunch_end})."
                )
            if lunch_start < self.work_start or lunch_end > self.work_end:
                raise BookingConfigError(
                    f"BOOKING_LUNCH ({lunch_start}–{lunch_end}) phải nằm TRONG giờ làm việc "
                    f"({self.work_start}–{self.work_end})."
                )
        # Buổi phỏng vấn phải nhét vừa một ngày làm việc — nếu không thì KHÔNG BAO GIỜ sinh nổi slot
        # nào, và triệu chứng ("ứng viên mở link thấy trống trơn") không hề chỉ về cấu hình.
        work_minutes = (self.work_end.hour * 60 + self.work_end.minute) - (
            self.work_start.hour * 60 + self.work_start.minute
        )
        if self.duration_minutes > work_minutes:
            raise BookingConfigError(
                f"BOOKING_DURATION_MINUTES ({self.duration_minutes}) dài hơn cả ngày làm việc "
                f"({work_minutes} phút) — sẽ không sinh được slot nào."
            )

    @property
    def step_minutes(self) -> int:
        """Khoảng cách giữa hai mốc bắt đầu liên tiếp = độ dài buổi + đệm dọn dẹp."""
        return self.duration_minutes + self.buffer_minutes


@lru_cache
def load_booking_config() -> BookingConfig:
    """Đọc `Settings` → `BookingConfig` đã kiểm. Cache vì cấu hình không đổi trong một tiến trình."""
    try:
        tz = ZoneInfo(settings.booking_timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise BookingConfigError(
            f"BOOKING_TIMEZONE không hợp lệ: {settings.booking_timezone!r}. "
            "Cần tên IANA (vd 'Asia/Ho_Chi_Minh') và gói dữ liệu múi giờ phải có mặt."
        ) from exc
    return BookingConfig(
        tz=tz,
        work_days=_parse_work_days(settings.booking_work_days),
        work_start=_parse_time(settings.booking_work_start, "BOOKING_WORK_START"),
        work_end=_parse_time(settings.booking_work_end, "BOOKING_WORK_END"),
        lunch=_parse_lunch(settings.booking_lunch),
        duration_minutes=settings.booking_duration_minutes,
        buffer_minutes=settings.booking_buffer_minutes,
        lead_time_hours=settings.booking_lead_time_hours,
        max_per_day=settings.booking_max_per_day,
        window_days=settings.booking_window_days,
        slots_offered=settings.booking_slots_offered,
        hold_minutes=settings.booking_hold_minutes,
        link_ttl_hours=settings.booking_link_ttl_hours,
    )
