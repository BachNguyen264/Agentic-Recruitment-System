"""Test SCH-1 trên Postgres THẬT — những bất biến chỉ DB mới chứng minh được. PRD §10b.5, FR-BOOK-2.

**Gated `RUN_BOOKING_IT=1`** (đúng lệ repo với `RUN_EMBED_IT`/`RUN_PARSE_IT` — xem CLAUDE.md) vì
cần một Postgres thật. Mock không thay được các test ở đây: thứ đang kiểm là **hành vi của DB** —
partial unique index, khoá hàng, và hai transaction thật chạy đè nhau.

    RUN_BOOKING_IT=1 uv run --directory apps/backend pytest tests/test_booking_db.py -q

Dữ liệu test tự dọn: mỗi test dùng JD + application riêng mang nhãn `sch1-it`, xoá ở cuối
(`interview_booking` cascade theo application).
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.application import Application
from app.models.booking import BookingStatus, InterviewBooking
from app.models.job_posting import JobPosting
from app.services import booking_flow, booking_service
from app.services.booking_service import (
    AlreadyBooked,
    BookingNotFound,
    HoldExpired,
    SlotTaken,
    confirm_booking,
    generate_slots,
    release_holds,
)

from tests.test_booking import ICT, make_cfg

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_BOOKING_IT"), reason="cần RUN_BOOKING_IT=1 + Postgres thật"
)

_MARK = "sch1-it"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def Session():  # noqa: N802 — dùng như một lớp: `async with Session() as s`
    """Engine RIÊNG cho mỗi test, `NullPool`, huỷ ở cuối.

    KHÔNG dùng `AsyncSessionLocal` toàn cục: pytest-asyncio cấp cho mỗi test một event loop MỚI,
    còn pool của engine toàn cục lại giữ connection asyncpg gắn với loop của test TRƯỚC — test thứ
    hai mượn phải nó là nổ "attached to a different loop". Engine riêng + `NullPool` (mỗi session
    một connection mới, đóng ngay khi xong) làm test độc lập hoàn toàn, và vẫn cho phép hai
    connection ĐỒNG THỜI thật cho test race.
    """
    engine = create_async_engine(
        settings.database_url, connect_args=settings.db_connect_args, poolclass=NullPool
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture
async def apps(Session) -> list[int]:  # noqa: N803
    """Tạo 1 JD + 3 application dùng-rồi-bỏ; xoá sạch ở cuối (booking cascade theo FK)."""
    async with Session() as s:
        job = JobPosting(title=f"[{_MARK}] Backend Engineer", status="OPEN")
        s.add(job)
        await s.flush()
        rows = [Application(job_id=job.id, applicant_email=f"{_MARK}+{i}@example.com") for i in range(3)]
        s.add_all(rows)
        await s.flush()
        ids = [r.id for r in rows]
        job_id = job.id
        await s.commit()
    try:
        yield ids
    finally:
        async with Session() as s:
            await s.execute(delete(Application).where(Application.id.in_(ids)))
            await s.execute(delete(JobPosting).where(JobPosting.id == job_id))
            await s.commit()


async def _held(session, application_id: int) -> list[InterviewBooking]:
    return list(
        (
            await session.execute(
                select(InterviewBooking)
                .where(
                    InterviewBooking.application_id == application_id,
                    InterviewBooking.status == BookingStatus.HELD.value,
                )
                .order_by(InterviewBooking.start_at)
            )
        )
        .scalars()
        .all()
    )


async def _count(session, application_id: int) -> int:
    return (
        await session.execute(
            select(func.count())
            .select_from(InterviewBooking)
            .where(InterviewBooking.application_id == application_id)
        )
    ).scalar_one()


def _free_slot(offset_days: int = 3, hour: int = 8, minute: int = 0) -> datetime:
    """Một mốc giờ trong tương lai, ổn định trong phạm vi một lần chạy test."""
    day = (_now().astimezone(ICT) + timedelta(days=offset_days)).date()
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ICT).astimezone(timezone.utc)


# ── Bấm lại link: bất biến chống RÒ SLOT ──────────────────────────────────────────────────


async def test_repeat_click_returns_same_slots_and_holds_no_more(Session, apps: list[int]) -> None:  # noqa: N803
    """Bất biến số 1 của lát này. Mỗi lần tải trang mà giữ thêm 5 slot thì N lần tải khoá 5N khung
    giờ — một người bấm F5 làm cạn lịch của cả công ty, và KHÔNG có lỗi nào bật ra."""
    app_id = apps[0]
    async with Session() as s:
        first = await generate_slots(s, app_id)
        assert first, "phải sinh được slot"
        first_ids = [b.id for b in first]

        second = await generate_slots(s, app_id)
        assert [b.id for b in second] == first_ids, "bấm lại phải trả ĐÚNG các slot cũ"

        third = await generate_slots(s, app_id)
        assert [b.id for b in third] == first_ids

        assert await _count(s, app_id) == len(first_ids), "KHÔNG được sinh thêm hàng giữ chỗ nào"


async def test_expired_holds_are_regenerated_fresh(Session, apps: list[int]) -> None:  # noqa: N803
    """Hold hết hạn ⇒ lần bấm sau sinh danh sách MỚI (không cần cron dọn — truy vấn tự lọc)."""
    app_id = apps[0]
    async with Session() as s:
        old = await generate_slots(s, app_id)
        old_ids = {b.id for b in old}
        for row in old:  # đẩy hold về quá khứ
            row.hold_expires_at = _now() - timedelta(minutes=1)
        await s.commit()

        fresh = await generate_slots(s, app_id)
        assert fresh and old_ids.isdisjoint({b.id for b in fresh})


# ── Loại trừ chỗ đã bị chiếm ──────────────────────────────────────────────────────────────


async def test_live_hold_of_another_application_is_excluded(Session, apps: list[int]) -> None:  # noqa: N803
    """Hai ứng viên mở link cùng lúc phải thấy DANH SÁCH KHÁC NHAU (§10b.5) — xung đột biến mất
    ngay từ khâu sinh, chứ không đợi tới lúc xác nhận."""
    async with Session() as s:
        a = await generate_slots(s, apps[0])
        b = await generate_slots(s, apps[1])
        assert {x.start_at for x in a}.isdisjoint({x.start_at for x in b})


async def test_booked_slot_is_excluded_for_everyone(Session, apps: list[int]) -> None:  # noqa: N803
    async with Session() as s:
        mine = await generate_slots(s, apps[0])
        chosen = mine[0]
        await confirm_booking(s, apps[0], chosen.id)

        other = await generate_slots(s, apps[1])
        assert chosen.start_at not in {b.start_at for b in other}


async def test_cancelled_slot_becomes_available_again(Session, apps: list[int]) -> None:  # noqa: N803
    """`CANCELLED` KHÔNG chiếm chỗ — khung giờ quay lại danh sách ngay."""
    async with Session() as s:
        mine = await generate_slots(s, apps[0])
        freed = {b.start_at for b in mine}
        assert await release_holds(s, apps[0]) == len(mine)
        await s.commit()

        other = await generate_slots(s, apps[1])
        assert freed & {b.start_at for b in other}, "chỗ đã nhả phải được đề xuất lại"


# ── Xác nhận ──────────────────────────────────────────────────────────────────────────────


async def test_confirm_books_one_and_releases_siblings(Session, apps: list[int]) -> None:  # noqa: N803
    app_id = apps[0]
    async with Session() as s:
        slots = await generate_slots(s, app_id)
        chosen = slots[1]

        booked = await confirm_booking(s, app_id, chosen.id)
        assert booked.status == BookingStatus.BOOKED.value
        assert booked.hold_expires_at is None
        assert not await _held(s, app_id), "4 chỗ giữ anh em phải được nhả hết"

        rows = (
            (await s.execute(select(InterviewBooking).where(InterviewBooking.application_id == app_id)))
            .scalars()
            .all()
        )
        assert sorted(r.status for r in rows) == ["BOOKED"] + ["CANCELLED"] * (len(slots) - 1)


async def test_confirm_is_idempotent(Session, apps: list[int]) -> None:  # noqa: N803
    """Bấm hai lần / tải lại trang sau khi đặt xong KHÔNG được thành lỗi."""
    async with Session() as s:
        slots = await generate_slots(s, apps[0])
        first = await confirm_booking(s, apps[0], slots[0].id)
        again = await confirm_booking(s, apps[0], slots[0].id)
        assert again.id == first.id and again.status == BookingStatus.BOOKED.value


async def test_confirm_rejects_expired_hold(Session, apps: list[int]) -> None:  # noqa: N803
    async with Session() as s:
        slots = await generate_slots(s, apps[0])
        slots[0].hold_expires_at = _now() - timedelta(seconds=1)
        await s.commit()
        with pytest.raises(HoldExpired, match="hết hạn"):
            await confirm_booking(s, apps[0], slots[0].id)


async def test_confirm_rejects_booking_of_another_application(Session, apps: list[int]) -> None:  # noqa: N803
    """Token đặt lịch là công khai — không được biến nó thành công cụ chốt giờ hộ người khác."""
    async with Session() as s:
        slots = await generate_slots(s, apps[0])
        with pytest.raises(BookingNotFound):
            await confirm_booking(s, apps[1], slots[0].id)


async def test_generate_slots_refuses_when_already_booked(Session, apps: list[int]) -> None:  # noqa: N803
    """Đã chốt lịch mà mở lại link ⇒ nổ rõ, KHÔNG lặng lẽ phát thêm chỗ giữ (đặt hai buổi PV)."""
    async with Session() as s:
        slots = await generate_slots(s, apps[0])
        booked = await confirm_booking(s, apps[0], slots[0].id)
        with pytest.raises(AlreadyBooked) as err:
            await generate_slots(s, apps[0])
        assert err.value.booking.id == booked.id


# ── Chốt chặn tầng DB: partial unique index ───────────────────────────────────────────────


async def test_db_rejects_second_booked_at_same_start(Session, apps: list[int]) -> None:  # noqa: N803
    """Chèn THẲNG vào DB một hàng BOOKED trùng `start_at` ⇒ DB phải từ chối (plan §4.4).

    Đây là kiểm tra chính cái index, không phải kiểm tra service: nếu vế `WHERE status='BOOKED'`
    của migration rơi mất, hệ thống vẫn chạy bình thường và chỉ âm thầm cho phép đặt trùng giờ.
    """
    start = _free_slot(offset_days=5, hour=9)
    async with Session() as s:
        s.add(
            InterviewBooking(
                application_id=apps[0],
                start_at=start,
                end_at=start + timedelta(hours=1),
                status=BookingStatus.BOOKED.value,
            )
        )
        await s.commit()

    async with Session() as s:
        s.add(
            InterviewBooking(
                application_id=apps[1],
                start_at=start,
                end_at=start + timedelta(hours=1),
                status=BookingStatus.BOOKED.value,
            )
        )
        with pytest.raises(IntegrityError):
            await s.commit()
        await s.rollback()


async def test_db_allows_two_held_at_same_start(Session, apps: list[int]) -> None:  # noqa: N803
    """Index phải là PARTIAL: hai người cùng ĐANG CÂN NHẮC một khung giờ là hợp lệ
    ("HELD = khuyến nghị, BOOKED = thẩm quyền"). Unique toàn bảng sẽ nổ ngay ở đây."""
    start = _free_slot(offset_days=6, hour=10)
    async with Session() as s:
        for app_id in (apps[0], apps[1]):
            s.add(
                InterviewBooking(
                    application_id=app_id,
                    start_at=start,
                    end_at=start + timedelta(hours=1),
                    status=BookingStatus.HELD.value,
                    hold_expires_at=_now() + timedelta(minutes=10),
                )
            )
        await s.commit()  # KHÔNG được ném lỗi
        n = (
            await s.execute(
                select(func.count())
                .select_from(InterviewBooking)
                .where(InterviewBooking.start_at == start)
            )
        ).scalar_one()
        assert n == 2


# ── RACE THẬT: hai transaction đồng thời chốt cùng một khung giờ ──────────────────────────


async def test_real_race_exactly_one_winner(Session, apps: list[int]) -> None:  # noqa: N803
    """Hai transaction ĐỒNG THỜI xác nhận cùng một `start_at` → đúng MỘT thắng, một nhận `SlotTaken`.

    Dựng thế race bằng cách chèn tay hai hàng HELD cùng giờ cho hai application (bình thường
    `generate_slots` đã loại trừ nhau, nên phải ép mới tái hiện được khe hở mà index tồn tại để bịt).
    Hai session = hai connection = hai transaction thật; kẻ đến sau BỊ CHẶN ở index cho tới khi kẻ
    đầu commit, rồi mới nhận unique violation.
    """
    start = _free_slot(offset_days=7, hour=14)
    hold_until = _now() + timedelta(minutes=10)
    ids: dict[int, int] = {}
    async with Session() as s:
        for app_id in (apps[0], apps[1]):
            row = InterviewBooking(
                application_id=app_id,
                start_at=start,
                end_at=start + timedelta(hours=1),
                status=BookingStatus.HELD.value,
                hold_expires_at=hold_until,
            )
            s.add(row)
            await s.flush()
            ids[app_id] = row.id
        await s.commit()

    async def attempt(app_id: int):
        async with Session() as s:  # session RIÊNG = transaction RIÊNG
            try:
                await confirm_booking(s, app_id, ids[app_id])
                return "won"
            except SlotTaken:
                return "lost"

    results = await asyncio.gather(attempt(apps[0]), attempt(apps[1]))
    assert sorted(results) == ["lost", "won"], f"phải đúng 1 thắng 1 thua, nhận được {results}"

    async with Session() as s:
        booked = (
            (
                await s.execute(
                    select(InterviewBooking).where(
                        InterviewBooking.start_at == start,
                        InterviewBooking.status == BookingStatus.BOOKED.value,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(booked) == 1, "DB chỉ được chứa MỘT hàng BOOKED cho mốc giờ này"


async def test_loser_keeps_other_holds_to_choose_again(Session, apps: list[int]) -> None:  # noqa: N803
    """Thua race thì rollback phải trả lại các chỗ giữ ANH EM (đã nhả dở giữa chừng) để ứng viên
    chọn lại ngay — chỉ MỘT hàng biến mất: chính khung giờ vừa thua, vì nó đã vô giá trị (xem
    `test_race_loser_hold_is_cancelled_so_refresh_offers_new_times`)."""
    winner, loser = apps[0], apps[1]
    async with Session() as s:
        loser_slots = await generate_slots(s, loser)
        contested = loser_slots[0]
        # Người thắng chốt ĐÚNG khung giờ đó qua một hàng của riêng họ.
        s.add(
            InterviewBooking(
                application_id=winner,
                start_at=contested.start_at,
                end_at=contested.end_at,
                status=BookingStatus.BOOKED.value,
            )
        )
        await s.commit()

    async with Session() as s:
        with pytest.raises(SlotTaken):
            await confirm_booking(s, loser, contested.id)
        remaining = await _held(s, loser)
        assert len(remaining) == len(loser_slots) - 1, "chỉ mất đúng khung giờ vừa thua"
        assert contested.start_at not in {b.start_at for b in remaining}


# ── Múi giờ trên DB thật ──────────────────────────────────────────────────────────────────


async def test_slots_land_inside_vietnam_working_hours(Session, apps: list[int]) -> None:  # noqa: N803
    """Đi trọn một vòng qua `timestamptz`: giờ đọc ra khỏi DB vẫn phải nằm trong giờ làm việc VN."""
    cfg = make_cfg()
    async with Session() as s:
        slots = await generate_slots(s, apps[0])
        assert slots
        for row in slots:
            local = row.start_at.astimezone(cfg.tz)
            assert local.isoweekday() in cfg.work_days
            assert cfg.work_start <= local.time() <= cfg.work_end
            assert (row.end_at - row.start_at) == timedelta(minutes=cfg.duration_minutes)


# ══════════════════════════════════════════════════════════════════════════════════════════
# SCH-2 — phiên đặt lịch (token) trên DB thật
# ══════════════════════════════════════════════════════════════════════════════════════════


async def test_booking_token_is_not_one_time(Session, apps: list[int]) -> None:  # noqa: N803
    """Khác magic-link screener: mở lại BAO NHIÊU LẦN cũng được (PRD §10b.3).

    Sinh slot LƯỜI nên mỗi lần mở là danh sách tươi ⇒ link không bao giờ ôi ⇒ không cần "gửi lại
    link" kiểu resend-OTP. Copy nhánh `used_at` của screener vào đây là phá đúng tính chất đó."""
    async with Session() as s:
        row = booking_service.create_booking_session(s, apps[0])
        token = row.token
        await s.commit()

        for _ in range(3):
            again = await booking_service.load_valid_session(s, token)
            assert again.id == row.id


async def test_booking_token_unknown_and_expired_and_cancelled(Session, apps: list[int]) -> None:  # noqa: N803
    async with Session() as s:
        with pytest.raises(booking_service.TokenNotFound):
            await booking_service.load_valid_session(s, "khong-ton-tai")

        expired = booking_service.create_booking_session(s, apps[0])
        expired.expires_at = _now() - timedelta(minutes=1)
        cancelled = booking_service.create_booking_session(s, apps[1])
        cancelled.cancelled_at = _now()
        await s.commit()

        with pytest.raises(booking_service.TokenExpired):
            await booking_service.load_valid_session(s, expired.token)
        with pytest.raises(booking_service.TokenExpired):
            await booking_service.load_valid_session(s, cancelled.token)


async def test_expired_link_still_opens_after_booking(Session, apps: list[int]) -> None:  # noqa: N803
    """Hạn 72h là để BẮT ĐẦU đặt lịch, không phải để xem lại lịch ĐÃ chốt — người đã đặt xong mà mở
    link sau 3 ngày vẫn phải thấy "bạn đã đặt lúc X", không phải màn hết hạn."""
    async with Session() as s:
        row = booking_service.create_booking_session(s, apps[0])
        row.expires_at = _now() - timedelta(hours=1)
        booking_service.mark_session_booked(row)
        await s.commit()
        assert (await booking_service.load_valid_session(s, row.token)).id == row.id


async def test_booking_view_projection_and_already_booked(Session, apps: list[int]) -> None:  # noqa: N803
    """GET công khai đi trọn vòng trên DB thật: danh sách slot → sau khi chốt thì `already_booked`."""
    async with Session() as s:
        row = booking_service.create_booking_session(s, apps[0])
        await s.commit()

        view = await booking_flow.booking_view(s, row.token)
        assert view["already_booked"] is False
        assert view["slots"] and view["hold_expires_at"] is not None
        assert set(view) == {
            "job_title", "candidate_name", "already_booked",
            "booked_start_at", "booked_end_at", "slots", "hold_expires_at",
        }

        chosen = view["slots"][0]
        await confirm_booking(s, apps[0], chosen.id)

        after = await booking_flow.booking_view(s, row.token)
        assert after["already_booked"] is True
        assert after["booked_start_at"] == chosen.start_at
        assert after["slots"] == []


async def test_race_loser_hold_is_cancelled_so_refresh_offers_new_times(  # noqa: N803
    Session, apps: list[int]
) -> None:
    """Thua race → chỗ giữ vừa thua bị HUỶ, nên "tải danh sách mới" KHÔNG trả lại đúng giờ đó.

    Không có bước này thì UI làm mới xong vẫn hiện khung giờ vừa mất, ứng viên bấm lại và chỉ nhận
    thêm 409 — vòng lặp không lối ra."""
    winner, loser = apps[0], apps[1]
    async with Session() as s:
        loser_slots = await generate_slots(s, loser)
        contested = loser_slots[0]
        s.add(
            InterviewBooking(
                application_id=winner, start_at=contested.start_at, end_at=contested.end_at,
                status=BookingStatus.BOOKED.value,
            )
        )
        await s.commit()

    async with Session() as s:
        with pytest.raises(SlotTaken):
            await confirm_booking(s, loser, contested.id)

    async with Session() as s:
        refreshed = await generate_slots(s, loser)
        assert contested.start_at not in {b.start_at for b in refreshed}
        assert len(refreshed) == len(loser_slots) - 1  # 4 chỗ giữ kia còn nguyên
