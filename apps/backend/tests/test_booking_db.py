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
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.models.job_posting import JobPosting
from app.services import booking_flow, booking_lifecycle, booking_service
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
        # AWAITING_BOOKING = trạng thái THẬT của một hồ sơ đang cầm link đặt lịch (thư mời đã gửi).
        # Để mặc định SUBMITTED thì `confirm_and_notify` từ chối đúng theo thiết kế, nhưng test lại
        # đang đo chuyện khác.
        rows = [
            Application(
                job_id=job.id,
                applicant_email=f"{_MARK}+{i}@example.com",
                status=ApplicationStatus.AWAITING_BOOKING.value,
            )
            for i in range(3)
        ]
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


# ══════════════════════════════════════════════════════════════════════════════════════════
# Hồi quy cho các lỗi adversarial review tìm ra (đo được trên Postgres thật)
# ══════════════════════════════════════════════════════════════════════════════════════════


async def test_concurrent_page_loads_do_not_multiply_holds(Session, apps: list[int]) -> None:  # noqa: N803
    """TOCTOU: 8 lượt GET chồng nhau trên CÙNG token phải cho ĐÚNG một bộ chỗ giữ.

    Trước khi có khoá tư vấn: 2 lượt → 10 hàng, 8 lượt → 40 hàng, và vì `max_per_day` đếm theo HÀNG
    nên những ngày gần nhất bị đóng với MỌI ứng viên khác. Bất biến "bấm lại trả slot cũ" chỉ đúng
    khi tuần tự; ứng viên bấm F5 hai lần là đủ phá."""
    app_id = apps[0]

    async def load():
        async with Session() as s:
            return [b.id for b in await generate_slots(s, app_id)]

    results = await asyncio.gather(*(load() for _ in range(8)))

    assert all(r == results[0] for r in results), "mọi lượt tải phải thấy CÙNG một bộ slot"
    async with Session() as s:
        assert await _count(s, app_id) == len(results[0]), "KHÔNG được sinh thêm hàng giữ chỗ nào"
        cfg = make_cfg()
        per_day: dict[object, int] = {}
        for row in await _held(s, app_id):
            day = row.start_at.astimezone(cfg.tz).date()
            per_day[day] = per_day.get(day, 0) + 1
        assert max(per_day.values()) <= cfg.max_per_day


async def test_reconfirm_does_not_resend_email(Session, apps: list[int], monkeypatch) -> None:  # noqa: N803
    """Bấm xác nhận lần hai (tải lại/hai tab) KHÔNG được gửi thêm biên nhận.

    Email là kênh DUY NHẤT của hệ thống tới ứng viên; đốt quota Resend bằng thư trùng là làm câm cả
    pipeline (thư mời, thư từ chối, magic-link sàng lọc)."""
    sent: list[int] = []

    async def fake_confirmed(_s, **kw):  # noqa: ANN001
        sent.append(kw["booking"].id)
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", fake_confirmed)

    async with Session() as s:
        row = booking_service.create_booking_session(s, apps[0])
        token = row.token
        await s.commit()
        view = await booking_flow.booking_view(s, token)
        chosen = view["slots"][0]

        first = await booking_flow.confirm_and_notify(s, token, chosen.id)
        second = await booking_flow.confirm_and_notify(s, token, chosen.id)

    assert len(sent) == 1, f"gửi {len(sent)} thư xác nhận cho một lượt đặt"
    assert second["start_at"] == first["start_at"] and second["email_sent"] is True


async def test_rejected_application_cannot_book_with_old_link(Session, apps: list[int]) -> None:  # noqa: N803
    """HR từ chối → link đặt lịch cũ phải CHẾT.

    Nếu không: ứng viên vừa nhận thư từ chối vẫn mở được link, tự đặt giờ, và `confirm_and_notify`
    ghi đè REJECTED thành INTERVIEW_SCHEDULED — một token cũ lật ngược quyết định của con người."""
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()

        assert await booking_service.cancel_sessions(s, app_id) == 1
        await s.commit()

        with pytest.raises(booking_service.TokenExpired):
            await booking_service.load_valid_session(s, token)


async def test_confirm_refuses_when_application_no_longer_bookable(Session, apps: list[int]) -> None:  # noqa: N803
    """Hồ sơ đã quay về tay HR (PENDING_REVIEW) → token cũ không được ghi INTERVIEW_SCHEDULED."""
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()
        view = await booking_flow.booking_view(s, token)
        chosen = view["slots"][0]

        app_row = await s.get(Application, app_id)
        app_row.status = ApplicationStatus.PENDING_REVIEW.value
        await s.commit()

        with pytest.raises(booking_service.TokenExpired):
            await booking_flow.confirm_and_notify(s, token, chosen.id)

    async with Session() as s:
        assert (await s.get(Application, app_id)).status == ApplicationStatus.PENDING_REVIEW.value


async def test_invite_reuses_live_session_instead_of_minting_second_token(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Gửi lại lời mời (HR bấm duyệt ở hai tab) phải ra MỘT link và MỘT thư.

    Hai token sống song song = hai email hai link khác nhau; ứng viên không biết cái nào thật, và ta
    có một token mồ côi không ai theo dõi. Sau adversarial review, lượt thứ hai còn bị chặn hẳn ở
    khâu gửi (đã có link sống + hồ sơ đã ở AWAITING_BOOKING = lượt trước xong rồi), nên hộp thư ứng
    viên cũng không nhận thư trùng."""
    urls: list[str] = []

    async def fake_notify(_s, mode, **kw):  # noqa: ANN001
        urls.append(kw["booking_url"])
        return {"mode": mode, "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_notify)

    async with Session() as s:
        app_row = await s.get(Application, apps[0])
        for _ in range(2):
            await booking_flow.dispatch_booking_invite(
                s, app_row, applicant_email="a@e.com", candidate_name="A",
                job_title="Backend", audit_node="human_review",
            )
        assert len(urls) == 1, f"gửi {len(urls)} thư mời cho một quyết định"
        n = (
            await s.execute(
                select(func.count())
                .select_from(BookingSession)
                .where(BookingSession.application_id == apps[0])
            )
        ).scalar_one()
        assert n == 1, "chỉ được có MỘT phiên đặt lịch"


# ══════════════════════════════════════════════════════════════════════════════════════════
# SCH-3 — vòng đời lịch (PRD §10b.6, FR-BOOK-3/4/6). Những bất biến chỉ DB mới chứng minh được.
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _book_one(Session, app_id: int, monkeypatch) -> tuple[str, InterviewBooking]:  # noqa: N803
    """Đưa một hồ sơ tới trạng thái đã-chốt-lịch THẬT (qua đúng đường của SCH-2). Email bị chặn."""
    async def fake_confirmed(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", fake_confirmed)
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()
        view = await booking_flow.booking_view(s, token)
        await booking_flow.confirm_and_notify(s, token, view["slots"][0].id)
    async with Session() as s:
        booking = await booking_service.latest_booking(s, app_id)
    return token, booking


async def test_cancel_frees_the_slot_for_everyone_immediately(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Huỷ → khung giờ khả dụng lại NGAY cho ứng viên KHÁC, không chờ vòng quét nào.

    Đây là bất biến quan trọng nhất của việc huỷ: khung giờ là tài nguyên tranh chấp, giữ thêm phút
    nào là chặn người khác phút đó. Kiểm bằng chính `generate_slots` của ứng viên thứ hai chứ không
    bằng cột `status` — thứ cần đúng là danh sách mà người tiếp theo NHÌN THẤY.
    """
    async def fake_cancelled(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_cancelled", fake_cancelled)
    token, booking = await _book_one(Session, apps[0], monkeypatch)
    taken_at = booking.start_at

    async with Session() as s:  # ứng viên khác: khung giờ đó đang bị chiếm
        others = await generate_slots(s, apps[1])
        assert taken_at not in {b.start_at for b in others}
        await release_holds(s, apps[1])
        await s.commit()

    async with Session() as s:
        out = await booking_flow.cancel_by_candidate(s, token)
        assert out["cancelled"] is True and out["can_rebook"] is True

    async with Session() as s:  # ...và ngay sau khi huỷ thì nó quay lại kho chung
        again = await generate_slots(s, apps[2])
        assert taken_at in {b.start_at for b in again}


async def test_cancel_lets_candidate_rebook_without_extending_deadline(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Huỷ xong chọn lại được — nhưng hạn 72h GỐC giữ nguyên (PRD §10b.6).

    Gia hạn khi huỷ là mở cửa cho vòng lặp đặt-huỷ-đặt không điểm dừng; hạn gốc đóng cửa sau đúng
    72h dù ứng viên huỷ bao nhiêu lần.
    """
    async def fake_cancelled(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_cancelled", fake_cancelled)
    token, _ = await _book_one(Session, apps[0], monkeypatch)

    async with Session() as s:
        before = (await booking_service.load_valid_session(s, token)).expires_at
        await booking_flow.cancel_by_candidate(s, token)

    async with Session() as s:
        after_row = await booking_service.load_valid_session(s, token)
        assert after_row.expires_at == before, "huỷ KHÔNG được gia hạn liên kết"
        assert after_row.booked_at is None
        assert (await s.get(Application, apps[0])).status == ApplicationStatus.AWAITING_BOOKING.value
        # ...và danh sách chọn giờ mở lại được (không còn kẹt ở AlreadyBooked).
        view = await booking_flow.booking_view(s, token)
        assert view["already_booked"] is False and view["slots"]


async def test_expired_link_sweep_returns_to_hr_and_releases_holds(  # noqa: N803
    Session, apps: list[int]
) -> None:
    """Sweep hết hạn: PENDING_REVIEW[booking_no_response], nhả HELD sót, KHÔNG auto-reject."""
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        row.expires_at = _now() - timedelta(minutes=1)  # đã quá hạn
        await s.commit()
        await generate_slots(s, app_id)  # ứng viên có bấm link, bỏ dở giữa chừng

    counts = await booking_lifecycle.sweep_once(Session)
    assert counts["expired"] >= 1

    async with Session() as s:
        app_row = await s.get(Application, app_id)
        assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
        assert app_row.status != ApplicationStatus.REJECTED.value
        assert "booking_no_response" in app_row.uncertainty_flags
        assert await _held(s, app_id) == [], "chỗ giữ bỏ dở phải được nhả"

    # Chạy lại: KHÔNG xử lại (idempotent bằng mốc `cancelled_at` + trạng thái đã rời AWAITING_BOOKING).
    assert (await booking_lifecycle.sweep_once(Session))["expired"] == 0


async def test_sweep_never_touches_a_candidate_who_just_booked(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Ứng viên bấm xác nhận đúng giây chót vẫn THẮNG sweep.

    Hạ hồ sơ của người vừa giành được khung giờ là lấy mất đúng thứ họ vừa giành. Lưới hết hạn có
    HAI chốt chặn cho chuyện này (`booked_at` và trạng thái hồ sơ) và test kiểm CẢ HAI riêng rẽ —
    ở đâu có hai nguồn sự thật thì phải giả định sẽ có lúc chúng nói khác nhau.
    """
    token, _ = await _book_one(Session, apps[0], monkeypatch)
    async with Session() as s:
        sess_row = await booking_service.load_valid_session(s, token)
        sess_row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    counts = await booking_lifecycle.sweep_once(Session)

    async with Session() as s:
        assert (await s.get(Application, apps[0])).status == ApplicationStatus.INTERVIEW_SCHEDULED.value
    assert counts["expired"] == 0

    # Chốt chặn THỨ HAI, đo riêng: dựng đúng trạng thái mâu thuẫn (phiên ĐÃ đặt nhưng hồ sơ lại đang
    # AWAITING_BOOKING) rồi kiểm truy vấn vẫn bỏ qua nó. Không dựng tay thì `booked_at` luôn bị vế
    # trạng thái che mất, và ta không biết nó còn tác dụng hay đã chết từ bao giờ.
    async with Session() as s:
        app_row = await s.get(Application, apps[0])
        app_row.status = ApplicationStatus.AWAITING_BOOKING.value
        await s.commit()
        due = await booking_lifecycle._due_expiry_ids(s, _now())
        booked_sess = await booking_service.booked_session(s, apps[0])
        assert booked_sess is not None and booked_sess.id not in due


async def test_interview_reminder_sent_once_then_never_again(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Nhắc trước buổi PV đúng MỘT lần — vòng sweep chạy lại KHÔNG dội thêm thư."""
    sent: list[int] = []

    async def fake_reminder(_s, **kw):  # noqa: ANN001
        sent.append(kw["application_id"])
        return {"mode": "interview_reminder", "email_sent": True}

    monkeypatch.setattr(booking_lifecycle.scheduler, "notify_interview_reminder", fake_reminder)
    _, booking = await _book_one(Session, apps[0], monkeypatch)

    async with Session() as s:  # kéo buổi PV vào trong cửa sổ nhắc
        row = await s.get(InterviewBooking, booking.id)
        row.start_at = _now() + timedelta(hours=1)
        row.end_at = row.start_at + timedelta(hours=1)
        await s.commit()

    assert (await booking_lifecycle.sweep_once(Session))["interview_reminded"] == 1
    assert (await booking_lifecycle.sweep_once(Session))["interview_reminded"] == 0
    assert sent == [apps[0]]

    async with Session() as s:
        assert (await s.get(InterviewBooking, booking.id)).reminder_sent_at is not None


async def test_link_reminder_reuses_old_token_and_fires_once(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Nhắc chọn lịch: đúng MỘT lần, và DÙNG LẠI link cũ (token KHÔNG one-time — §10b.3)."""
    urls: list[str] = []

    async def fake_reminder(_s, **kw):  # noqa: ANN001
        urls.append(kw["booking_url"])
        return {"mode": "booking_reminder", "email_sent": True}

    monkeypatch.setattr(booking_lifecycle.scheduler, "notify_booking_reminder", fake_reminder)
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        row.expires_at = _now() + timedelta(minutes=5)  # sắp hết hạn → trong cửa sổ nhắc
        token = row.token
        await s.commit()

    assert (await booking_lifecycle.sweep_once(Session))["link_reminded"] == 1
    assert (await booking_lifecycle.sweep_once(Session))["link_reminded"] == 0
    assert urls == [f"{settings.frontend_base_url.rstrip('/')}/booking/{token}"]


async def test_hr_cancel_then_resend_is_the_reschedule_flow(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Hai nút HR ghép lại = đổi lịch: huỷ (slot nhả + về hàng chờ) → gửi lại link (token MỚI)."""
    async def ok(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_cancelled", ok)
    old_token, booking = await _book_one(Session, apps[0], monkeypatch)
    app_id = apps[0]

    async with Session() as s:
        app_row = await booking_flow.cancel_by_hr(s, app_id)
        assert app_row.status == ApplicationStatus.PENDING_REVIEW.value

    async with Session() as s:
        # Link cũ CHẾT — HR đang cầm ca, ứng viên không được lặng lẽ tự đặt lại.
        with pytest.raises(booking_service.TokenExpired):
            await booking_service.load_valid_session(s, old_token)
        assert (await s.get(InterviewBooking, booking.id)).status == BookingStatus.CANCELLED.value

    async def fake_invite(_s, _mode, **_kw):  # noqa: ANN001
        return {"mode": "invite", "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_invite)
    async with Session() as s:
        app_row = await booking_flow.resend_booking_link(s, app_id)
        assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value

    async with Session() as s:
        fresh = await booking_service.active_session(s, app_id)
        assert fresh is not None and fresh.token != old_token


async def test_no_slots_flag_is_set_then_cleared(Session, apps: list[int], monkeypatch) -> None:  # noqa: N803
    """Hết khung giờ → cờ RIÊNG cho HR; có slot trở lại → cờ TỰ TẮT (FR-BOOK-6).

    Ép cạn lịch bằng lead-time một năm thay vì đi chiếm hết slot: tất định, nhanh, và KHÔNG để lại
    hàng giữ chỗ rác trong bảng dùng chung của các test khác.
    """
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()

    empty = make_cfg(lead_time_hours=24 * 365)  # mốc sớm nhất nằm ngoài cửa sổ → không slot nào

    async with Session() as s:
        monkeypatch.setattr(booking_service, "load_booking_config", lambda: empty)
        view = await booking_flow.booking_view(s, token)
        assert view["slots"] == []
        monkeypatch.undo()

    async with Session() as s:
        assert app_id in await booking_service.no_slot_application_ids(s)

    async with Session() as s:  # lịch mở lại (cấu hình thật) → cờ phải tắt
        view = await booking_flow.booking_view(s, token)
        assert view["slots"]
    async with Session() as s:
        assert app_id not in await booking_service.no_slot_application_ids(s)


# ══════════════════════════════════════════════════════════════════════════════════════════
# Hồi quy sau adversarial review SCH-3 — mỗi test dưới đây tương ứng MỘT lỗi đã tái hiện được.
# ══════════════════════════════════════════════════════════════════════════════════════════


async def test_two_concurrent_invites_produce_one_link(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """HR bấm Duyệt ở HAI tab → phải ra ĐÚNG MỘT liên kết.

    Đo được trước khi vá: 2 phiên sống + 2 thư mời với hai link KHÁC NHAU. Ứng viên không biết cái
    nào thật, và cái còn lại thành token mồ côi không lưới nào theo dõi — nó là bàn đạp cho cả lỗi
    "đặt bằng link B, huỷ bằng link A" lẫn lỗi hạ nhầm hồ sơ đã có lịch.
    """
    sent: list[str] = []

    async def fake_invite(_s, _mode, **kw):  # noqa: ANN001
        sent.append(kw["booking_url"])
        return {"mode": "invite", "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_invite)
    app_id = apps[0]
    async with Session() as s:  # bắt đầu từ hàng chờ HR, như đường /review thật
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.PENDING_REVIEW.value
        await s.commit()

    async def dispatch() -> None:
        async with Session() as s:
            app_row = await s.get(Application, app_id)
            await booking_flow.dispatch_booking_invite(
                s, app_row, applicant_email="a@e.com", candidate_name="A",
                job_title="Backend", audit_node="human_review",
            )

    await asyncio.gather(dispatch(), dispatch())

    async with Session() as s:
        live = (await s.execute(select(BookingSession).where(
            BookingSession.application_id == app_id,
            BookingSession.cancelled_at.is_(None)))).scalars().all()
        assert len(live) == 1, f"{len(live)} liên kết sống — ứng viên nhận nhiều link khác nhau"
        assert (await s.get(Application, app_id)).status == ApplicationStatus.AWAITING_BOOKING.value
    assert len(set(sent)) == 1, "hai thư mời trỏ hai liên kết khác nhau"


async def test_sweep_spares_application_holding_a_booked_slot(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Có hàng `BOOKED` thì lưới hết hạn phải TRÁNH, dù mọi CỜ đều nói "chưa đặt".

    Cờ (`booked_at`, trạng thái hồ sơ) có thể lệch khỏi sự thật khi một đường ghi hỏng giữa chừng;
    bảng `interview_booking` mới là sự thật. Thiếu chốt này thì hồ sơ đang cầm lịch (đã có `.ics`
    trong tay) bị báo cho HR là "không phản hồi", và khung giờ BOOKED đó không đường nào nhả nữa —
    biến mất khỏi lịch công ty vĩnh viễn vì partial unique index.
    """
    async def fake_confirmed(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", fake_confirmed)
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()
        view = await booking_flow.booking_view(s, token)
        await booking_flow.confirm_and_notify(s, token, view["slots"][0].id)

    # Dựng ĐÚNG trạng thái lệch: hàng BOOKED còn đó, nhưng mọi cờ đều nói "chưa đặt, quá hạn".
    async with Session() as s:
        sess_row = (await s.execute(
            select(BookingSession).where(BookingSession.token == token))).scalar_one()
        sess_row.booked_at = None
        sess_row.expires_at = _now() - timedelta(minutes=1)
        app_row = await s.get(Application, app_id)
        app_row.status = ApplicationStatus.AWAITING_BOOKING.value
        await s.commit()

    counts = await booking_lifecycle.sweep_once(Session)

    async with Session() as s:
        app_row = await s.get(Application, app_id)
        assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value, "đã hạ nhầm hồ sơ có lịch"
        assert "booking_no_response" not in (app_row.uncertainty_flags or [])
        assert (await booking_service.latest_booking(s, app_id)) is not None
    assert counts["expired"] == 0


async def test_no_slots_case_keeps_its_own_label_after_expiry(  # noqa: N803
    Session, apps: list[int], monkeypatch
) -> None:
    """Hết khung giờ rồi hết hạn → cờ `booking_no_slots`, KHÔNG phải `booking_no_response`.

    Đây là ca DUY NHẤT mà lỗi thuộc về hệ thống. Gộp nó vào "ứng viên không phản hồi" là đảo ngược
    đúng cái quy-trách-nhiệm mà FR-BOOK-6 sinh ra để giữ.
    """
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()

    empty = make_cfg(lead_time_hours=24 * 365)
    async with Session() as s:
        monkeypatch.setattr(booking_service, "load_booking_config", lambda: empty)
        assert (await booking_flow.booking_view(s, token))["slots"] == []
        monkeypatch.undo()

    async with Session() as s:
        sess_row = (await s.execute(
            select(BookingSession).where(BookingSession.token == token))).scalar_one()
        sess_row.expires_at = _now() - timedelta(minutes=1)
        await s.commit()

    assert (await booking_lifecycle.sweep_once(Session))["expired"] == 1

    async with Session() as s:
        app_row = await s.get(Application, app_id)
        assert app_row.status == ApplicationStatus.PENDING_REVIEW.value
        assert "booking_no_slots" in (app_row.uncertainty_flags or [])
        assert "booking_no_response" not in (app_row.uncertainty_flags or [])


async def test_rebook_loop_is_capped(Session, apps: list[int], monkeypatch) -> None:  # noqa: N803
    """Vòng đặt-huỷ-đặt phải DỪNG — TTL chặn theo thời gian, không chặn theo SỐ EMAIL.

    Mỗi vòng phát hai thư (xác nhận + báo huỷ) và trần duy nhất còn lại là rate-limit theo IP, nên
    trong 72h một liên kết có thể đốt hàng trăm lượt gửi. Resend là kênh DUY NHẤT của hệ thống: hết
    quota là thư mời/từ chối/sàng lọc của MỌI ứng viên khác cùng câm.
    """
    async def ok(_s, **_kw):  # noqa: ANN001
        return {"email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_confirmed", ok)
    monkeypatch.setattr(booking_flow.scheduler, "notify_booking_cancelled", ok)
    app_id = apps[0]
    async with Session() as s:
        row = booking_service.create_booking_session(s, app_id)
        token = row.token
        await s.commit()

    cycles = 0
    for _ in range(booking_flow._MAX_REBOOKS + 3):
        async with Session() as s:
            view = await booking_flow.booking_view(s, token)
            if view["already_booked"] or not view["slots"]:
                break
            await booking_flow.confirm_and_notify(s, token, view["slots"][0].id)
        async with Session() as s:
            out = await booking_flow.cancel_by_candidate(s, token)
        cycles += 1
        if not out["can_rebook"]:
            break

    assert cycles == booking_flow._MAX_REBOOKS + 1, f"vòng lặp chạy {cycles} lượt — hạn mức không có tác dụng"
    async with Session() as s:
        app_row = await s.get(Application, app_id)
        assert app_row.status == ApplicationStatus.PENDING_REVIEW.value  # về NGƯỜI, không auto-reject
        assert app_row.status != ApplicationStatus.REJECTED.value
        assert "booking_cancelled" in (app_row.uncertainty_flags or [])


async def test_reinvite_clears_stale_booking_flags(Session, apps: list[int], monkeypatch) -> None:  # noqa: N803
    """Mời LẠI phải gỡ cờ của lượt trước.

    Để nguyên thì một ứng viên đã chốt lịch vẫn mang nhãn "không phản hồi" vĩnh viễn, và
    `handle_booking_timeout` (khử trùng theo TÊN cờ) sẽ im lặng bỏ qua lần hết hạn THẬT tiếp theo.
    """
    async def fake_invite(_s, _mode, **_kw):  # noqa: ANN001
        return {"mode": "invite", "email_sent": True}

    monkeypatch.setattr(booking_flow.scheduler, "notify_decision", fake_invite)
    app_id = apps[0]
    async with Session() as s:
        booking_service.create_booking_session(s, app_id)  # đã từng được mời
        app_row = await s.get(Application, app_id)
        app_row.status = ApplicationStatus.PENDING_REVIEW.value
        app_row.uncertainty_flags = ["booking_no_response", "low_confidence"]
        await s.commit()

    async with Session() as s:
        await booking_flow.resend_booking_link(s, app_id)

    async with Session() as s:
        app_row = await s.get(Application, app_id)
        assert app_row.status == ApplicationStatus.AWAITING_BOOKING.value
        assert "booking_no_response" not in app_row.uncertainty_flags
        assert "low_confidence" in app_row.uncertainty_flags, "chỉ gỡ cờ ĐẶT LỊCH, đừng đụng cờ khác"
