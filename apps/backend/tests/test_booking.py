"""Test SCH-1 — tầng nghiệp vụ đặt lịch, phần KHÔNG cần DB. PRD §10b, FR-BOOK-1/2/5.

Bốn mảng:
  A) `BookingConfig`: đọc env + TỪ CHỐI cấu hình mâu thuẫn (giờ làm, nghỉ trưa, độ dài buổi).
  B) `_candidate_starts`: lưới mốc bắt đầu — ngày làm việc, nghỉ trưa, lead-time, cửa sổ, không tràn
     quá giờ tan làm.
  C) `_pick_mixed`: trộn 5 slot (§10b.4) + tôn trọng `max_per_day`.
  D) `.ics` + seam `CalendarProvider`: RFC 5545 (CRLF, gấp dòng, thoát ký tự), giờ UTC đúng, UID tất định.

Phần cần Postgres THẬT (giữ chỗ, bấm lại link, race hai transaction, partial unique index) nằm ở
`test_booking_db.py` — gated bằng `RUN_BOOKING_IT=1` theo đúng lệ của repo (xem CLAUDE.md).
"""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.models.booking import BookingStatus, InterviewBooking
from app.services.booking_config import (
    BookingConfig,
    BookingConfigError,
    load_booking_config,
)
from app.services.booking_service import (
    BookingError,
    _as_utc,
    _candidate_starts,
    _pick_mixed,
    _slot_key,
)
from app.services.calendar import CalendarError, CalendarEvent, get_calendar_provider
from app.services.calendar.ics import IcsProvider, build_ics, event_uid

ICT = ZoneInfo("Asia/Ho_Chi_Minh")


def make_cfg(**over) -> BookingConfig:
    """Cấu hình mặc định của repo, cho phép ghi đè từng trường — test tự mô tả điều kiện của mình."""
    base = dict(
        tz=ICT,
        work_days=frozenset({1, 2, 3, 4, 5}),
        work_start=time(8, 0),
        work_end=time(17, 30),
        lunch=(time(12, 0), time(13, 30)),
        duration_minutes=60,
        buffer_minutes=15,
        lead_time_hours=24,
        max_per_day=6,
        window_days=21,
        slots_offered=5,
        hold_minutes=5,
        link_ttl_hours=72,
    )
    base.update(over)
    return BookingConfig(**base)


def ict(*args: int) -> datetime:
    """datetime giờ Việt Nam (aware) → dùng cho mốc "bây giờ" trong test."""
    return datetime(*args, tzinfo=ICT)


def local(dt: datetime, cfg: BookingConfig | None = None) -> datetime:
    return dt.astimezone((cfg or make_cfg()).tz)


# ── A) Cấu hình khả dụng ──────────────────────────────────────────────────────────────────


def test_default_env_config_is_valid() -> None:
    """Mặc định trong `.env.example` phải TỰ NÓ hợp lệ — nếu không thì mọi cài đặt mới đều hỏng."""
    cfg = load_booking_config()
    assert cfg.tz.key == "Asia/Ho_Chi_Minh"
    assert cfg.work_days == frozenset({1, 2, 3, 4, 5})
    assert cfg.step_minutes == cfg.duration_minutes + cfg.buffer_minutes


@pytest.mark.parametrize(
    "raw,expected",
    [("1-5", {1, 2, 3, 4, 5}), ("1,3,5", {1, 3, 5}), ("1-5,7", {1, 2, 3, 4, 5, 7}), (" 2 - 3 ", {2, 3})],
)
def test_work_days_parsing(raw: str, expected: set[int]) -> None:
    from app.services.booking_config import _parse_work_days

    assert _parse_work_days(raw) == expected


@pytest.mark.parametrize("raw", ["", "0-5", "1-8", "abc", "5-1"])
def test_work_days_rejects_nonsense(raw: str) -> None:
    from app.services.booking_config import _parse_work_days

    with pytest.raises(BookingConfigError):
        _parse_work_days(raw)


def test_lunch_empty_means_no_lunch_break() -> None:
    from app.services.booking_config import _parse_lunch

    assert _parse_lunch("") is None
    assert _parse_lunch("12:00-13:30") == (time(12, 0), time(13, 30))


def test_config_rejects_work_start_after_end() -> None:
    with pytest.raises(BookingConfigError, match="TRƯỚC BOOKING_WORK_END"):
        make_cfg(work_start=time(18, 0), work_end=time(9, 0))


def test_config_rejects_lunch_outside_work_hours() -> None:
    with pytest.raises(BookingConfigError, match="nằm TRONG giờ làm việc"):
        make_cfg(lunch=(time(19, 0), time(20, 0)))


def test_config_rejects_duration_longer_than_work_day() -> None:
    """Buổi dài hơn cả ngày làm ⇒ 0 slot mãi mãi, mà triệu chứng lại là "trang trống trơn"."""
    with pytest.raises(BookingConfigError, match="dài hơn cả ngày làm việc"):
        make_cfg(work_start=time(8, 0), work_end=time(10, 0), lunch=None, duration_minutes=180)


def test_config_rejects_zero_hold() -> None:
    with pytest.raises(BookingConfigError, match="BOOKING_HOLD_MINUTES"):
        make_cfg(hold_minutes=0)


# ── B) Lưới mốc bắt đầu ───────────────────────────────────────────────────────────────────


def test_candidates_respect_work_hours_and_lunch() -> None:
    """Thứ Hai 09:00 ICT + lead-time 24h ⇒ ngày đầu tiên có slot là Thứ Ba."""
    cfg = make_cfg()
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    tuesday = [s for s in starts if local(s).date() == ict(2026, 8, 4).date()]
    assert [local(s).strftime("%H:%M") for s in tuesday] == ["09:15", "10:30", "14:15", "15:30"]
    # 11:45 (đè nghỉ trưa 12:00) và 13:00 (đè tới 13:30) phải KHÔNG có mặt.
    assert "11:45" not in {local(s).strftime("%H:%M") for s in starts}
    assert "13:00" not in {local(s).strftime("%H:%M") for s in starts}
    # 16:45 + 60 phút = 17:45 > 17:30 ⇒ không được tràn quá giờ tan làm.
    assert "16:45" not in {local(s).strftime("%H:%M") for s in starts}


def test_candidates_skip_weekend() -> None:
    cfg = make_cfg()
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    assert starts, "phải có slot"
    assert all(local(s).isoweekday() in cfg.work_days for s in starts)
    assert not any(local(s).isoweekday() in (6, 7) for s in starts)


def test_candidates_respect_lead_time() -> None:
    """KHÔNG mời khung giờ sớm hơn `lead_time_hours` kể từ bây giờ (ứng viên cần thời gian thu xếp)."""
    cfg = make_cfg(lead_time_hours=24)
    now = ict(2026, 8, 3, 9, 0).astimezone(timezone.utc)
    starts = _candidate_starts(cfg, now)
    assert min(starts) >= now + timedelta(hours=24)
    # Nới lead-time xuống 0 thì chính hôm nay phải có slot (chứng minh bộ lọc là lead-time, không
    # phải một quy tắc "luôn bỏ hôm nay" nào đó ẩn trong code.)
    today = [s for s in _candidate_starts(make_cfg(lead_time_hours=0), now) if local(s).date() == ict(2026, 8, 3).date()]
    assert today


def test_candidates_respect_window() -> None:
    cfg = make_cfg(window_days=3)
    now = ict(2026, 8, 3, 9, 0).astimezone(timezone.utc)
    starts = _candidate_starts(cfg, now)
    assert starts and max(starts) <= now + timedelta(days=3)


def test_no_lunch_config_keeps_midday_slot() -> None:
    cfg = make_cfg(lunch=None)
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    assert "11:45" in {local(s).strftime("%H:%M") for s in starts}


def test_candidate_starts_are_utc_and_aware() -> None:
    """DB lưu UTC — mọi mốc rời khỏi hàm sinh đều phải aware và đã ở UTC."""
    starts = _candidate_starts(make_cfg(), ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    assert all(s.tzinfo is timezone.utc for s in starts)
    # 08:00 giờ Việt Nam = 01:00 UTC.
    morning = next(s for s in starts if local(s).strftime("%H:%M") == "08:00")
    assert morning.strftime("%H:%M") == "01:00"


def test_naive_datetime_is_rejected() -> None:
    """datetime naive lệch đúng 7 tiếng mà KHÔNG ném lỗi ở đâu — phải chặn ngay tại cửa."""
    with pytest.raises(BookingError, match="aware"):
        _as_utc(datetime(2026, 8, 3, 9, 0), "now")


# ── C) Trộn slot (§10b.4) ─────────────────────────────────────────────────────────────────


def test_pick_mixed_spreads_across_days_and_halves() -> None:
    """Không được dồn cả 5 slot vào một buổi khi còn ngày/buổi khác trống — đó là lý do TỒN TẠI
    của luật trộn: 5 slot cùng sáng thứ Ba thì người bận sáng thứ Ba coi như không được mời."""
    cfg = make_cfg()
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    picked = _pick_mixed(starts, cfg, {})

    assert len(picked) == cfg.slots_offered
    assert picked == sorted(picked)
    keys = {_slot_key(s, cfg) for s in picked}
    assert len(keys) >= 3, f"quá dồn cục: {[local(s).strftime('%a %H:%M') for s in picked]}"
    assert len({d for d, _ in keys}) >= 2, "phải rải ít nhất hai ngày"
    assert {is_morning for _, is_morning in keys} == {True, False}, "phải có cả sáng lẫn chiều"


def test_pick_mixed_includes_earliest_slots() -> None:
    """Vẫn phải có mốc SỚM NHẤT — ứng viên muốn phỏng vấn sớm cần thấy lựa chọn sớm."""
    cfg = make_cfg()
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    picked = _pick_mixed(starts, cfg, {})
    assert picked[0] == starts[0]


def test_pick_mixed_respects_max_per_day_already_taken() -> None:
    """Ngày đã kín `max_per_day` (người khác chiếm) thì không được đề xuất thêm giờ nào ngày đó."""
    cfg = make_cfg(max_per_day=4)
    now = ict(2026, 8, 3, 9, 0).astimezone(timezone.utc)
    starts = _candidate_starts(cfg, now)
    tuesday = ict(2026, 8, 4).date()
    picked = _pick_mixed(starts, cfg, {tuesday: 4})
    assert all(local(s).date() != tuesday for s in picked)
    assert len(picked) == cfg.slots_offered  # vẫn đủ 5, lấy từ những ngày sau


def test_pick_mixed_never_exceeds_max_per_day_by_itself() -> None:
    """Tự nó cũng không được vượt hạn mức: 5 slot đề xuất mà max 2/ngày ⇒ tối đa 2 slot mỗi ngày."""
    cfg = make_cfg(max_per_day=2)
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))
    picked = _pick_mixed(starts, cfg, {})
    per_day: dict[object, int] = {}
    for s in picked:
        day = local(s).date()
        per_day[day] = per_day.get(day, 0) + 1
    assert per_day and max(per_day.values()) <= 2


def test_pick_mixed_returns_what_it_has_when_scarce() -> None:
    """Ít hơn 5 khung trống là HỢP LỆ — trả hết những gì có, không lỗi (plan §3.3)."""
    cfg = make_cfg()
    starts = _candidate_starts(cfg, ict(2026, 8, 3, 9, 0).astimezone(timezone.utc))[:2]
    assert len(_pick_mixed(starts, cfg, {})) == 2
    assert _pick_mixed([], cfg, {}) == []


# ── D) .ics + seam lịch ───────────────────────────────────────────────────────────────────


def _booking(bid: int = 7) -> InterviewBooking:
    """InterviewBooking rời (không cần DB) — chỉ để provider đọc id/start_at/end_at."""
    return InterviewBooking(
        id=bid,
        application_id=1,
        start_at=ict(2026, 8, 10, 8, 0).astimezone(timezone.utc),
        end_at=ict(2026, 8, 10, 9, 0).astimezone(timezone.utc),
        status=BookingStatus.BOOKED.value,
    )


def _unfold(text: str) -> str:
    """Bỏ gấp dòng để so sánh nội dung gốc (RFC 5545: CRLF + một dấu cách = dòng nối)."""
    return text.replace("\r\n ", "")


def test_ics_has_required_structure_and_crlf() -> None:
    raw = build_ics(
        uid="booking-7@ars.local",
        start_at=ict(2026, 8, 10, 8, 0),
        end_at=ict(2026, 8, 10, 9, 0),
        summary="Phỏng vấn Backend Engineer",
    )
    text = raw.decode("utf-8")
    assert text.startswith("BEGIN:VCALENDAR\r\n")
    assert text.endswith("END:VCALENDAR\r\n")
    # KHÔNG được có LF trần — một số ứng dụng lịch từ chối cả tệp.
    assert "\n" not in text.replace("\r\n", "")
    for required in ("VERSION:2.0", "PRODID:", "UID:booking-7@ars.local", "DTSTAMP:", "BEGIN:VEVENT"):
        assert required in _unfold(text), required


def test_ics_time_is_utc_and_round_trips_to_vietnam_time() -> None:
    """08:00 giờ Việt Nam ⇒ `010000Z`; đọc ngược lại phải ra đúng 08:00 Asia/Ho_Chi_Minh."""
    text = build_ics(
        uid="u", start_at=ict(2026, 8, 10, 8, 0), end_at=ict(2026, 8, 10, 9, 0), summary="PV"
    ).decode("utf-8")
    line = next(l for l in _unfold(text).split("\r\n") if l.startswith("DTSTART:"))
    assert line == "DTSTART:20260810T010000Z"

    parsed = datetime.strptime(line.split(":", 1)[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    assert parsed.astimezone(ICT).strftime("%Y-%m-%d %H:%M") == "2026-08-10 08:00"

    end_line = next(l for l in _unfold(text).split("\r\n") if l.startswith("DTEND:"))
    end = datetime.strptime(end_line.split(":", 1)[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    assert (end - parsed) == timedelta(hours=1)


def test_ics_escapes_special_characters() -> None:
    text = build_ics(
        uid="u",
        start_at=ict(2026, 8, 10, 8, 0),
        end_at=ict(2026, 8, 10, 9, 0),
        summary="PV: Backend, cấp Senior; phòng A",
        description="Dòng 1\nDòng 2",
        location="Tầng 3, toà A",
    ).decode("utf-8")
    flat = _unfold(text)
    assert "PV: Backend\\, cấp Senior\\; phòng A" in flat
    assert "DESCRIPTION:Dòng 1\\nDòng 2" in flat
    assert "LOCATION:Tầng 3\\, toà A" in flat


def test_ics_folds_long_lines_without_breaking_utf8() -> None:
    """Tiếng Việt có dấu là 2–3 byte/ký tự: cắt giữa ký tự thì tệp hỏng ngay ở byte đó."""
    summary = "Phỏng vấn vị trí Kỹ sư Backend cấp cao tại Công ty Trách nhiệm Hữu hạn Một Thành Viên"
    text = build_ics(
        uid="u", start_at=ict(2026, 8, 10, 8, 0), end_at=ict(2026, 8, 10, 9, 0), summary=summary
    ).decode("utf-8")  # decode thành công = không byte UTF-8 nào bị cắt đôi

    lines = text.split("\r\n")
    assert any(l.startswith(" ") for l in lines), "dòng dài phải được gấp"
    assert all(len(l.encode("utf-8")) <= 75 for l in lines if l), "mọi dòng phải <= 75 octet"
    assert f"SUMMARY:{summary}" in _unfold(text)


def test_ics_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError, match="aware"):
        build_ics(uid="u", start_at=datetime(2026, 8, 10, 8, 0), end_at=ict(2026, 8, 10, 9, 0), summary="PV")


def test_event_uid_is_deterministic() -> None:
    """UID tất định để SCH-3 dời lịch CẬP NHẬT sự kiện cũ thay vì tạo bản sao."""
    assert event_uid(7) == event_uid(7)
    assert event_uid(7) != event_uid(8)
    assert event_uid(7).startswith("booking-7@")


async def test_ics_provider_create_event_returns_attachment() -> None:
    event = await IcsProvider().create_event(_booking(), summary="Phỏng vấn")
    assert isinstance(event, CalendarEvent)
    assert event.ref == event_uid(7)
    assert event.ics is not None and b"DTSTART:20260810T010000Z" in event.ics


async def test_ics_provider_cancel_is_noop_and_idempotent() -> None:
    """Không có sự kiện phía máy chủ để xoá — gọi bao nhiêu lần cũng không lỗi (SCH-3 gửi email huỷ)."""
    provider = IcsProvider()
    assert await provider.cancel_event("booking-7@ars.local") is None
    assert await provider.cancel_event("booking-7@ars.local") is None


def test_calendar_provider_factory(monkeypatch: pytest.MonkeyPatch) -> None:
    get_calendar_provider.cache_clear()
    assert isinstance(get_calendar_provider(), IcsProvider)

    from app.core.config import settings

    monkeypatch.setattr(settings, "calendar_provider", "google", raising=False)
    get_calendar_provider.cache_clear()
    with pytest.raises(CalendarError, match="google"):
        get_calendar_provider()
    get_calendar_provider.cache_clear()
