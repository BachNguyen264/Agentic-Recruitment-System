"""booking_service — sinh slot lười, giữ chỗ, xác nhận (SCH-1 · PRD §10b, FR-BOOK-1/2/5).

**Tầng DB/slot thuần** — không biết email, không biết trạng thái `Application`. Ai nối nó vào
nghiệp vụ: `booking_flow` (mời/xác nhận/huỷ) và `booking_lifecycle` (nhắc/hết hạn). Mọi thao tác
trên khung giờ phải đi QUA đây, đừng truy vấn thẳng `interview_booking`.

Ba hàm, ba bất biến phải giữ:

1. `generate_slots` — **sinh LƯỜI** (chỉ khi ứng viên bấm link, không phải lúc gửi mail: §10b.2) và
   **bấm lại phải trả ĐÚNG các slot cũ**. Bất biến thứ hai là chỗ dễ hỏng nhất của cả lát này: giữ
   thêm 5 slot mới mỗi lần tải trang thì N lần tải = khoá 5N khung giờ, và lịch của công ty cạn sạch
   vì một người bấm F5. Vì thế truy vấn hold-còn-hạn nằm ở dòng ĐẦU, trước mọi thứ khác.
2. `confirm_booking` — HELD→BOOKED trong MỘT transaction, chốt chặn cuối là partial unique index của
   DB. Thua race → `SlotTaken` (SCH-2 dịch thành 409 + làm mới danh sách, §10b.5).
3. `release_holds` — nhả chỗ giữ. Hold hết hạn KHÔNG cần cron: mọi truy vấn "đang bị chiếm" đều lọc
   `hold_expires_at > now` nên hàng quá hạn tự thôi chiếm chỗ.

**Múi giờ:** DB lưu `timestamptz` (UTC); sinh/so sánh theo `Asia/Ho_Chi_Minh` (giờ làm việc là khái
niệm ĐỊA PHƯƠNG). Mọi `datetime` qua biên hàm đều phải **aware** — `_as_utc` chặn naive ngay tại cửa,
vì một `datetime` naive lọt vào đây sẽ lệch 7 tiếng mà không báo lỗi ở đâu cả.

**Lưu ý cho SCH-2:** hàng trả về đã commit nhưng `created_at`/`updated_at` là server-default nên
CHƯA nạp — đọc chúng sẽ bắn thêm một truy vấn (mở lại transaction, giữ connection: xem gotcha
`refresh()` trong `docs/AI_GUIDE.md`). Chỉ đọc `id`/`start_at`/`end_at`/`status`/`hold_expires_at`.
"""

from __future__ import annotations

import secrets
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import and_, or_, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.services.booking_config import BookingConfig, load_booking_config

logger = get_logger("app.services.booking")

# Không gian khoá tư vấn Postgres (pg_advisory_xact_lock nhận 2 int4). Số tuỳ ý nhưng phải
# CỐ ĐỊNH và riêng cho đặt lịch, để không đụng khoá của thành phần khác dùng chung cơ chế.
_ADVISORY_LOCK_NS = 0x0B00C1

__all__ = [
    "AlreadyBooked",
    "BookingError",
    "BookingNotFound",
    "HoldExpired",
    "SlotTaken",
    "TokenExpired",
    "TokenNotFound",
    "active_session",
    "booked_session",
    "cancel_booked",
    "cancel_sessions",
    "confirm_booking",
    "create_booking_session",
    "generate_slots",
    "has_any_session",
    "latest_booking",
    "load_valid_session",
    "lock_application",
    "mark_session_booked",
    "mark_session_reopened",
    "no_slot_application_ids",
    "release_holds",
]


class BookingError(Exception):
    """Lỗi đặt lịch mang sẵn HTTP status + thông điệp tiếng Việt để SCH-2 map thẳng ra route."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class BookingNotFound(BookingError):
    status_code = 404


class HoldExpired(BookingError):
    status_code = 409


class SlotTaken(BookingError):
    """Thua race: ai đó vừa BOOKED đúng khung giờ này (partial unique index chặn). → 409 (§10b.5)."""

    status_code = 409


class AlreadyBooked(BookingError):
    """Application này đã chốt lịch rồi. Mang theo hàng đã đặt để SCH-2 hiển thị lại cho ứng viên."""

    status_code = 409

    def __init__(self, message: str, booking: InterviewBooking) -> None:
        super().__init__(message)
        self.booking = booking


class TokenNotFound(BookingError):
    status_code = 404


class TokenExpired(BookingError):
    status_code = 410


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def lock_application(session: AsyncSession, application_id: int) -> None:
    """Khoá tư vấn theo hồ sơ — tuần tự hoá mọi cặp "đọc rồi mới ghi" của đặt lịch. KHÔNG commit.

    Rẻ, tự nhả khi transaction kết thúc, và KHÔNG chặn hồ sơ khác. Dùng ở `generate_slots` (giữ chỗ)
    và `dispatch_booking_invite` (phát liên kết) — cả hai đều từng đo được TOCTOU thật khi hai
    request chồng nhau. Vì khoá gắn với TRANSACTION, caller phải commit/rollback TRƯỚC khi đi làm
    I/O chậm (email), nếu không là giữ luôn cả connection.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:ns, :app_id)"),
        {"ns": _ADVISORY_LOCK_NS, "app_id": application_id},
    )


def _as_utc(value: datetime, label: str) -> datetime:
    """Chuẩn hoá về UTC và TỪ CHỐI datetime naive.

    Naive datetime là lỗi im lặng tệ nhất ở tầng này: Python coi nó là giờ hệ thống, so sánh vẫn
    chạy, chỉ có kết quả lệch đúng 7 tiếng (ICT) — nghĩa là slot hiện ra sai buổi mà không có
    exception nào chỉ điểm. Chặn tại cửa thay vì đi truy sau.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise BookingError(f"{label} phải là datetime có múi giờ (aware), nhận được naive: {value!r}")
    return value.astimezone(timezone.utc)


def _period_divider(cfg: BookingConfig) -> time:
    """Ranh giới sáng/chiều = giờ bắt đầu nghỉ trưa (hoặc 12:00 nếu không có nghỉ trưa)."""
    return cfg.lunch[0] if cfg.lunch else time(12, 0)


def _slot_key(start_utc: datetime, cfg: BookingConfig) -> tuple[object, bool]:
    """Khoá "buổi" của một slot: (ngày địa phương, có phải buổi sáng không) — dùng để TRỘN."""
    local = start_utc.astimezone(cfg.tz)
    return local.date(), local.time() < _period_divider(cfg)


def _overlaps_lunch(start_local: datetime, end_local: datetime, cfg: BookingConfig) -> bool:
    if cfg.lunch is None:
        return False
    lunch_start = datetime.combine(start_local.date(), cfg.lunch[0], tzinfo=cfg.tz)
    lunch_end = datetime.combine(start_local.date(), cfg.lunch[1], tzinfo=cfg.tz)
    return start_local < lunch_end and end_local > lunch_start


def _candidate_starts(cfg: BookingConfig, now: datetime) -> list[datetime]:
    """Mọi mốc bắt đầu HỢP LỆ THEO LỊCH LÀM VIỆC trong cửa sổ, tăng dần (UTC).

    Thuần tuý — chưa biết gì về chỗ đã bị chiếm. Lưới mốc neo ở `work_start` mỗi ngày và bước đều
    `duration + buffer`; slot nào ĐÈ lên nghỉ trưa thì bỏ, KHÔNG dồn lưới lại. Giữ lưới đều làm giờ
    phỏng vấn lặp lại giống nhau mỗi ngày — dễ cho người xếp lịch, và dễ kiểm trong test.
    """
    earliest = now + timedelta(hours=cfg.lead_time_hours)
    window_end = now + timedelta(days=cfg.window_days)
    duration = timedelta(minutes=cfg.duration_minutes)
    step = timedelta(minutes=cfg.step_minutes)

    out: list[datetime] = []
    first_day = now.astimezone(cfg.tz).date()
    for offset in range(cfg.window_days + 1):
        day = first_day + timedelta(days=offset)
        if day.isoweekday() not in cfg.work_days:
            continue
        cursor = datetime.combine(day, cfg.work_start, tzinfo=cfg.tz)
        day_end = datetime.combine(day, cfg.work_end, tzinfo=cfg.tz)
        while True:
            slot_end = cursor + duration
            if slot_end > day_end:
                break
            start_utc = cursor.astimezone(timezone.utc)
            if earliest <= start_utc <= window_end and not _overlaps_lunch(cursor, slot_end, cfg):
                out.append(start_utc)
            cursor += step
    return out


async def _occupied(
    session: AsyncSession, cfg: BookingConfig, now: datetime
) -> tuple[set[datetime], dict[object, int]]:
    """Khung giờ ĐANG BỊ CHIẾM trong cửa sổ → (tập mốc bắt đầu, số buổi đã chiếm theo NGÀY địa phương).

    Chiếm chỗ = `BOOKED` **hoặc** (`HELD` và chưa hết hạn) — PRD §10b.5. `CANCELLED` và `HELD` quá
    hạn KHÔNG chiếm chỗ, nên không cần cron dọn.

    Quét từ ĐẦU NGÀY địa phương chứ không từ `now`: buổi phỏng vấn sáng nay đã diễn ra vẫn TÍNH vào
    hạn mức `max_per_day` của hôm nay. Lấy mốc `now` thì những buổi đã qua biến mất khỏi phép đếm và
    ta lặng lẽ xếp quá tải đúng cái ngày vốn đã kín.
    """
    day_start = datetime.combine(
        now.astimezone(cfg.tz).date(), time(0, 0), tzinfo=cfg.tz
    ).astimezone(timezone.utc)
    stmt = select(InterviewBooking.start_at).where(
        InterviewBooking.start_at >= day_start,
        InterviewBooking.start_at <= now + timedelta(days=cfg.window_days),
        or_(
            InterviewBooking.status == BookingStatus.BOOKED.value,
            and_(
                InterviewBooking.status == BookingStatus.HELD.value,
                InterviewBooking.hold_expires_at > now,
            ),
        ),
    )
    taken: set[datetime] = {
        _as_utc(s, "start_at trong DB") for s in (await session.execute(stmt)).scalars().all()
    }
    # Đếm theo MỐC GIỜ DUY NHẤT, không theo số hàng: hai hàng cùng `start_at` (hai người cùng cân
    # nhắc một khung giờ — hợp lệ theo §10b.5) chỉ chiếm MỘT chỗ trong ngày. Đếm theo hàng làm
    # `max_per_day` bị thổi phồng và đóng sạch những ngày gần nhất với MỌI ứng viên khác.
    per_day: dict[object, int] = {}
    for start_utc in taken:
        local_day = start_utc.astimezone(cfg.tz).date()
        per_day[local_day] = per_day.get(local_day, 0) + 1
    return taken, per_day


def _pick_mixed(
    candidates: list[datetime], cfg: BookingConfig, per_day: dict[object, int]
) -> list[datetime]:
    """Chọn tối đa `slots_offered` mốc, TRỘN theo §10b.4: vài mốc sớm nhất + vài mốc rải ngày/buổi khác.

    Vì sao không lấy đơn giản 5 mốc sớm nhất: 5 slot dồn vào một buổi sáng thì người bận đúng sáng
    hôm đó xem như KHÔNG có lựa chọn nào — mà đây là ứng viên ta ĐÃ quyết định mời. Lý do phụ: rải
    ra thì hai ứng viên mở link cùng lúc ít đụng nhau hơn.

    Hoàn toàn tất định (không random) để test khẳng định được kết quả. `per_day` vào đây đã tính cả
    chỗ người khác chiếm; hàm cộng dồn tiếp phần mình chọn để KHÔNG tự vượt `max_per_day`.
    """
    wanted = cfg.slots_offered
    counts = dict(per_day)
    picked: list[datetime] = []
    picked_set: set[datetime] = set()
    used_keys: set[tuple[object, bool]] = set()

    def take(start_utc: datetime) -> None:
        day = start_utc.astimezone(cfg.tz).date()
        if counts.get(day, 0) >= cfg.max_per_day:
            return
        picked.append(start_utc)
        picked_set.add(start_utc)
        used_keys.add(_slot_key(start_utc, cfg))
        counts[day] = counts.get(day, 0) + 1

    # 1) Vài mốc SỚM NHẤT — ứng viên muốn phỏng vấn sớm thì có ngay lựa chọn sớm.
    n_early = max(1, wanted // 2)
    for start_utc in candidates:
        if len(picked) >= n_early:
            break
        take(start_utc)

    # 2) Phần còn lại: ưu tiên (ngày, buổi) CHƯA xuất hiện → đảm bảo có cả sáng lẫn chiều, nhiều ngày.
    for start_utc in candidates:
        if len(picked) >= wanted:
            break
        if start_utc in picked_set or _slot_key(start_utc, cfg) in used_keys:
            continue
        take(start_utc)

    # 3) Vẫn thiếu (lịch thưa) → lấp theo thứ tự thời gian. Ít hơn `slots_offered` là HỢP LỆ, không lỗi.
    for start_utc in candidates:
        if len(picked) >= wanted:
            break
        if start_utc in picked_set:
            continue
        take(start_utc)

    return sorted(picked)


async def generate_slots(
    session: AsyncSession,
    application_id: int,
    *,
    cfg: BookingConfig | None = None,
    now: datetime | None = None,
) -> list[InterviewBooking]:
    """Trả các khung giờ đề xuất cho ứng viên, ĐÃ giữ chỗ (`HELD`), sắp xếp tăng dần. COMMIT.

    Sinh LƯỜI (§10b.2): gọi lúc ứng viên mở link, không phải lúc gửi mail — chỉ tiêu tốn khung giờ
    cho người thực sự có ý định đặt lịch, và danh sách luôn tươi nên MỘT link là đủ.

    **Bấm lại link → trả về ĐÚNG các slot đang giữ, không giữ thêm.** (Không gia hạn hold: hết 10
    phút thì tải lại là có danh sách mới — §10b.3. Gia hạn theo mỗi lần tải sẽ biến hold ngắn
    thành hold vô hạn.)

    Không còn khung giờ nào → trả danh sách RỖNG (không phải lỗi); SCH-2 quyết cách báo cho ứng
    viên / HR. Ít hơn `BOOKING_SLOTS_OFFERED` → trả hết những gì có.

    Raise `AlreadyBooked` nếu application này đã chốt lịch — thà nổ rõ còn hơn lặng lẽ phát thêm
    chỗ giữ cho người đã có lịch (đặt hai buổi phỏng vấn cho một ứng viên).
    """
    cfg = cfg or load_booking_config()
    now = _as_utc(now, "now") if now is not None else _now()

    # ── 0) KHOÁ theo application: "đọc rồi mới ghi" ở đây là TOCTOU thật, đã đo được ─────
    # Hai lượt GET chồng nhau trên CÙNG token đều thấy "chưa có hold nào" rồi cùng chèn: 2 lượt →
    # 10 hàng, 8 lượt → 40 hàng (adversarial review đo trên Postgres thật). Bất biến "bấm lại trả
    # slot cũ" chỉ đúng khi tuần tự — mà ứng viên bấm F5 hai lần hoặc trình duyệt gửi lại request
    # là đủ để phá. (Hai application KHÁC NHAU vẫn được cùng giữ một mốc giờ — đó là thiết kế
    # "HELD = khuyến nghị"; partial unique index xử lý ở bước chốt.)
    await lock_application(session, application_id)

    # ── 1) Đã chốt lịch rồi thì KHÔNG phát thêm slot ─────────────────────────────────────
    booked = (
        await session.execute(
            select(InterviewBooking)
            .where(
                InterviewBooking.application_id == application_id,
                InterviewBooking.status == BookingStatus.BOOKED.value,
            )
            .order_by(InterviewBooking.start_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if booked is not None:
        await session.commit()  # nhả khoá tư vấn trước khi ném
        raise AlreadyBooked("Hồ sơ này đã đặt lịch phỏng vấn.", booked)

    # ── 2) BẤM LẠI: đang giữ chỗ còn hạn → trả ĐÚNG các slot đó (bất biến chống rò slot) ──
    existing = list(
        (
            await session.execute(
                select(InterviewBooking)
                .where(
                    InterviewBooking.application_id == application_id,
                    InterviewBooking.status == BookingStatus.HELD.value,
                    InterviewBooking.hold_expires_at > now,
                )
                .order_by(InterviewBooking.start_at)
            )
        )
        .scalars()
        .all()
    )
    if existing:
        logger.info(
            "booking: app=%s mở lại link — trả %d slot đang giữ (KHÔNG giữ thêm)",
            application_id,
            len(existing),
        )
        await session.commit()  # nhả khoá tư vấn (và transaction) trước khi trả về
        return existing

    # ── 3) Sinh mới ──────────────────────────────────────────────────────────────────────
    taken, per_day = await _occupied(session, cfg, now)
    candidates = [s for s in _candidate_starts(cfg, now) if s not in taken]
    chosen = _pick_mixed(candidates, cfg, per_day)
    if not chosen:
        logger.warning(
            "booking: app=%s KHÔNG còn khung giờ trống trong %d ngày tới", application_id, cfg.window_days
        )
        await session.commit()
        return []

    hold_until = now + timedelta(minutes=cfg.hold_minutes)
    duration = timedelta(minutes=cfg.duration_minutes)
    rows = [
        InterviewBooking(
            application_id=application_id,
            start_at=start_utc,
            end_at=start_utc + duration,
            status=BookingStatus.HELD.value,
            hold_expires_at=hold_until,
        )
        for start_utc in chosen
    ]
    session.add_all(rows)
    await session.flush()  # lấy id; KHÔNG refresh (refresh mở lại transaction — xem AI_GUIDE)
    await session.commit()
    logger.info("booking: app=%s giữ %d slot tới %s", application_id, len(rows), hold_until.isoformat())
    return rows


async def release_holds(
    session: AsyncSession, application_id: int, *, exclude_id: int | None = None
) -> int:
    """Nhả mọi chỗ đang giữ của một application → `CANCELLED`. Trả số hàng đã nhả. **KHÔNG commit.**

    Caller commit (thường là cùng transaction với việc lật `BOOKED` — xem `confirm_booking`).
    `CANCELLED` KHÔNG chiếm chỗ nên khung giờ trở lại khả dụng ngay.
    """
    stmt = (
        update(InterviewBooking)
        .where(
            InterviewBooking.application_id == application_id,
            InterviewBooking.status == BookingStatus.HELD.value,
        )
        .values(status=BookingStatus.CANCELLED.value, hold_expires_at=None)
    )
    if exclude_id is not None:
        stmt = stmt.where(InterviewBooking.id != exclude_id)
    return (await session.execute(stmt)).rowcount or 0


async def confirm_booking(
    session: AsyncSession,
    application_id: int,
    booking_id: int,
    *,
    now: datetime | None = None,
) -> InterviewBooking:
    """Chốt một khung giờ: `HELD → BOOKED`, nhả các chỗ giữ anh em. COMMIT.

    Chống race hai lớp (§10b.5): khoá hàng (`SELECT … FOR UPDATE`) chặn hai lần xác nhận cùng MỘT
    hàng; **partial unique index** của DB chặn hai hàng KHÁC NHAU cùng `start_at` cùng thành
    `BOOKED` — kẻ thua nhận `SlotTaken` (→ 409 + làm mới danh sách ở SCH-2).

    Gọi lại khi đã `BOOKED` (tải lại trang / bấm hai lần) → trả chính hàng đó, KHÔNG lỗi.
    """
    now = _as_utc(now, "now") if now is not None else _now()

    row = (
        await session.execute(
            select(InterviewBooking).where(InterviewBooking.id == booking_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.application_id != application_id:
        # Gộp "không tồn tại" với "của người khác" vào MỘT thông điệp: token đặt lịch là công khai,
        # đừng biến nó thành công cụ dò xem booking id nào có thật.
        raise BookingNotFound("Khung giờ không hợp lệ.")

    if row.status == BookingStatus.BOOKED.value:
        # Idempotent — NHƯNG phải đóng transaction trước khi trả về: `SELECT … FOR UPDATE` ở trên
        # đang giữ khoá hàng + một connection của pool, và caller sẽ đi gọi Resend ngay sau đây.
        # Đo được 1.29s giữ connection xuyên suốt lượt gửi mail ở đường bấm-lại (Load boundary cấm).
        await session.commit()
        return row
    if row.status != BookingStatus.HELD.value:
        raise HoldExpired("Khung giờ này không còn được giữ. Xin tải lại và chọn giờ khác.")
    if row.hold_expires_at is None or _as_utc(row.hold_expires_at, "hold_expires_at") <= now:
        raise HoldExpired("Chỗ giữ đã hết hạn. Xin tải lại trang để chọn lại khung giờ.")

    # Nhả anh em TRƯỚC khi lật BOOKED: câu UPDATE này sẽ autoflush mọi thay đổi đang treo, nên nếu
    # lật trước thì IntegrityError của race bật ra ngay giữa hàm thay vì ở `commit()` — đúng chỗ ta
    # đang bắt. Thứ tự này giữ MỘT điểm ném lỗi duy nhất.
    released = await release_holds(session, application_id, exclude_id=booking_id)

    row.status = BookingStatus.BOOKED.value
    row.hold_expires_at = None
    try:
        await session.commit()
    except DBAPIError as exc:
        # IntegrityError = thua partial unique index (ai đó vừa BOOKED mốc giờ này).
        # DBAPIError khác = deadlock/serialization: hai tab của CÙNG ứng viên chốt hai booking_id
        # khác nhau khoá chéo nhau qua release_holds (đã tái hiện được). Cả hai đều là "thử lại đi",
        # nên trả CHUNG 409 — để lọt ra ngoài thì route ném 500 và ứng viên thấy màn lỗi thô.
        # Rollback trả lại NGUYÊN TRẠNG, kể cả các chỗ giữ anh em vừa nhả — ứng viên thua race vẫn
        # còn đủ lựa chọn khác để chọn lại ngay.
        await session.rollback()
        logger.info("booking: app=%s thua race ở booking=%s (%s)", application_id, booking_id, exc.orig)
        # Chỗ giữ VỪA THUA đã vô giá trị (người khác đang BOOKED đúng mốc giờ đó) — huỷ ngay. Nếu
        # để nguyên, lần "làm mới danh sách" kế tiếp sẽ trả về CHÍNH khung giờ vừa thua (nhánh
        # bấm-lại trả các hold còn hạn) và ứng viên bấm mãi cũng chỉ nhận thêm 409.
        try:
            await session.execute(
                update(InterviewBooking)
                .where(
                    InterviewBooking.id == booking_id,
                    InterviewBooking.status == BookingStatus.HELD.value,
                )
                .values(status=BookingStatus.CANCELLED.value, hold_expires_at=None)
            )
            await session.commit()
        except Exception:  # noqa: BLE001 — dọn dẹp phụ trợ: hỏng thì hold cũng tự hết hạn
            await session.rollback()
            logger.warning("booking: không huỷ được chỗ giữ thua race booking=%s", booking_id)
        raise SlotTaken("Giờ này vừa có người đặt mất. Xin chọn một khung giờ khác.") from exc

    logger.info(
        "booking: app=%s chốt booking=%s lúc %s (nhả %d chỗ giữ)",
        application_id,
        booking_id,
        row.start_at.isoformat(),
        released,
    )
    return row


# ══════════════════════════════════════════════════════════════════════════════════════════
# Phiên đặt lịch (SCH-2) — LIÊN KẾT gửi cho ứng viên
# ══════════════════════════════════════════════════════════════════════════════════════════

_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) → ~43 ký tự url-safe (như screener 08b)


def create_booking_session(
    session: AsyncSession, application_id: int, *, now: datetime | None = None
) -> BookingSession:
    """Tạo phiên đặt lịch: token crypto-random + hạn `BOOKING_LINK_TTL_HOURS`. **KHÔNG commit.**

    Token gán sẵn ở Python nên caller dựng được link NGAY (trước flush) để bỏ vào thư mời — giống
    `screening.create_session`. Caller commit CÙNG lúc đổi trạng thái sang `AWAITING_BOOKING`.
    """
    at = _as_utc(now, "now") if now is not None else _now()
    row = BookingSession(
        application_id=application_id,
        token=secrets.token_urlsafe(_TOKEN_BYTES),
        expires_at=at + timedelta(hours=load_booking_config().link_ttl_hours),
    )
    session.add(row)
    return row


async def load_valid_session(
    session: AsyncSession, token: str, *, now: datetime | None = None
) -> BookingSession:
    """Tra + validate token đặt lịch. Token sai → 404; huỷ/hết hạn → 410.

    **KHÔNG one-time** (khác magic-link screener — PRD §10b.3): mở lại bao nhiêu lần cũng được, vì
    mỗi lần mở là sinh danh sách slot TƯƠI nên link không bao giờ ôi. Đừng copy nhánh `used_at` của
    `screening._load_valid` vào đây.

    Cũng **KHÔNG** ràng buộc `application.status == AWAITING_BOOKING`: sau khi chốt lịch, trạng thái
    thành `INTERVIEW_SCHEDULED` mà link vẫn phải mở được để hiện "bạn đã đặt lúc X" (`generate_slots`
    tự ném `AlreadyBooked`). Ràng buộc trạng thái ở đây sẽ làm ứng viên vừa đặt xong bấm lại thấy lỗi.
    """
    at = _as_utc(now, "now") if now is not None else _now()
    row = (
        await session.execute(select(BookingSession).where(BookingSession.token == token))
    ).scalar_one_or_none()
    if row is None:
        raise TokenNotFound("Liên kết không hợp lệ.")
    if row.cancelled_at is not None:
        raise TokenExpired("Liên kết đặt lịch đã bị huỷ. Bộ phận Tuyển dụng sẽ liên hệ với bạn.")
    # Đã đặt xong thì BỎ QUA hạn: hạn 72h là để BẮT ĐẦU đặt lịch (§10b.3), không phải để xem lại
    # lịch đã chốt. Hết hạn mà chưa đặt mới là hết cơ hội.
    if row.booked_at is None and _as_utc(row.expires_at, "expires_at") <= at:
        raise TokenExpired(
            "Liên kết đặt lịch đã hết hạn. Bộ phận Tuyển dụng sẽ liên hệ lại với bạn."
        )
    return row


def mark_session_booked(row: BookingSession, *, now: datetime | None = None) -> None:
    """Đánh dấu phiên đã chốt được giờ. KHÔNG phải cờ one-time — chỉ để SCH-3 khỏi nhắc phiên này."""
    row.booked_at = _as_utc(now, "now") if now is not None else _now()


def mark_session_reopened(row: BookingSession) -> None:
    """Ứng viên vừa HUỶ lịch → phiên quay lại trạng thái "chưa chốt" để họ chọn giờ khác (SCH-3).

    Xoá `booked_at` là thao tác BẮT BUỘC, không phải dọn dẹp cho đẹp: `load_valid_session` cố ý BỎ
    QUA hạn 72h khi `booked_at` có giá trị (để người đã đặt xong còn mở lại link xem lịch). Giữ
    nguyên nó sau khi huỷ nghĩa là liên kết sống VĨNH VIỄN — đúng cái "gia hạn TTL" mà PRD §10b.6
    cấm, và là cửa cho vòng lặp đặt-huỷ-đặt không điểm dừng. `expires_at` KHÔNG đổi: hạn gốc vẫn là
    hạn gốc.
    """
    row.booked_at = None


async def cancel_booked(
    session: AsyncSession, application_id: int, *, now: datetime | None = None
) -> InterviewBooking | None:
    """Huỷ lịch ĐÃ chốt của một hồ sơ → khung giờ nhả NGAY. **KHÔNG commit.** Trả hàng vừa huỷ.

    Trả `None` khi hồ sơ không có lịch nào đang `BOOKED` — đó là chuyện BÌNH THƯỜNG, không phải lỗi:
    ứng viên bấm link huỷ hai lần, hoặc HR vừa huỷ xong thì ứng viên mới bấm. Caller xử lý êm.

    `SELECT … FOR UPDATE` để hai lượt huỷ đồng thời (ứng viên bấm + HR bấm) không cùng đọc ra một
    hàng rồi cùng tưởng mình là người huỷ — chỉ một bên được gửi thư "đã huỷ".

    Nhả TỨC THÌ (không chờ sweep): khung giờ là tài nguyên tranh chấp, giữ thêm phút nào là chặn
    ứng viên khác phút đó. `CANCELLED` không nằm trong tập "đang bị chiếm" nên slot khả dụng lại
    ngay ở lượt `generate_slots` kế tiếp, và partial unique index chỉ ràng buộc hàng `BOOKED`.
    """
    at = _as_utc(now, "now") if now is not None else _now()
    row = (
        await session.execute(
            select(InterviewBooking)
            .where(
                InterviewBooking.application_id == application_id,
                InterviewBooking.status == BookingStatus.BOOKED.value,
            )
            .order_by(InterviewBooking.start_at)
            .with_for_update()
        )
    ).scalars().first()
    if row is None:
        return None
    row.status = BookingStatus.CANCELLED.value
    row.hold_expires_at = None
    logger.info(
        "booking: app=%s HUỶ lịch booking=%s (%s) — khung giờ nhả lúc %s",
        application_id, row.id, row.start_at.isoformat(), at.isoformat(),
    )
    return row


async def latest_booking(
    session: AsyncSession, application_id: int
) -> InterviewBooking | None:
    """Lịch phỏng vấn ĐÃ chốt của một hồ sơ — cho HR xem ở trang chi tiết. CHỈ ĐỌC.

    Huỷ/gửi lại link đi qua `booking_flow.cancel_by_hr`/`resend_booking_link` (có nhả slot, gửi thư
    và ghi audit) — đừng sửa hàng lấy từ đây.
    """
    stmt = (
        select(InterviewBooking)
        .where(
            InterviewBooking.application_id == application_id,
            InterviewBooking.status == BookingStatus.BOOKED.value,
        )
        .order_by(InterviewBooking.start_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def active_session(
    session: AsyncSession, application_id: int, *, now: datetime | None = None
) -> BookingSession | None:
    """Liên kết đặt lịch CÒN SỐNG của một hồ sơ (chưa huỷ, chưa hết hạn), nếu có.

    Dùng để KHÔNG phát token thứ hai khi lời mời được gửi lại (HR bấm duyệt ở hai tab, hoặc thử lại
    một request chậm). Hai token sống song song nghĩa là hai email với hai liên kết khác nhau —
    ứng viên không biết cái nào thật, và ta có một token mồ côi không ai theo dõi.
    """
    at = _as_utc(now, "now") if now is not None else _now()
    stmt = (
        select(BookingSession)
        .where(
            BookingSession.application_id == application_id,
            BookingSession.cancelled_at.is_(None),
            BookingSession.expires_at > at,
        )
        .order_by(BookingSession.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def no_slot_application_ids(session: AsyncSession) -> set[int]:
    """id các hồ sơ đang KẸT vì HẾT KHUNG GIỜ — dashboard hiện nhãn riêng (SCH-3 §3.5, FR-BOOK-6).

    MỘT truy vấn cho cả danh sách, không phải một truy vấn mỗi dòng: trang `/applications` liệt kê
    mọi hồ sơ nên đường N+1 ở đây sẽ hỏng đúng lúc dữ liệu lớn lên. Tập trả về thường rất nhỏ (chỉ
    những phiên đã CHẠM cảnh hết lịch mà chưa được gỡ cờ).

    Chỉ tính phiên còn sống và chưa đặt được giờ: đặt xong rồi thì cảnh báo cũ không còn nghĩa gì.
    """
    stmt = select(BookingSession.application_id).where(
        BookingSession.no_slots_at.is_not(None),
        BookingSession.cancelled_at.is_(None),
        BookingSession.booked_at.is_(None),
    )
    return set((await session.execute(stmt)).scalars().all())


async def has_any_session(session: AsyncSession, application_id: int) -> bool:
    """Hồ sơ này đã TỪNG được phát liên kết đặt lịch chưa (kể cả liên kết đã huỷ/hết hạn)?

    Dùng để phân biệt "gửi LẠI" với "mời lần đầu" (SCH-3 §3.4). Cố ý KHÔNG lọc `cancelled_at`: câu
    hỏi là "đã từng", không phải "đang còn".
    """
    stmt = select(BookingSession.id).where(
        BookingSession.application_id == application_id
    ).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none() is not None


async def booked_session(
    session: AsyncSession, application_id: int
) -> BookingSession | None:
    """Phiên ĐÃ chốt giờ của một hồ sơ — để dựng lại LIÊN KẾT quản lý lịch trong thư nhắc (SCH-3).

    KHÔNG lọc `expires_at` (khác `active_session`): hạn 72h là hạn để **bắt đầu** đặt lịch, còn
    người đã đặt xong thì vẫn phải mở được link để xem/huỷ — `load_valid_session` bỏ qua hạn khi
    `booked_at` có giá trị, nên truy vấn này phải khớp với luật đó. Lọc theo hạn ở đây sẽ khiến thư
    nhắc trước buổi PV mất nút huỷ đúng lúc ứng viên cần nó nhất (buổi PV thường nằm SAU 72h).
    """
    stmt = (
        select(BookingSession)
        .where(
            BookingSession.application_id == application_id,
            BookingSession.cancelled_at.is_(None),
            BookingSession.booked_at.is_not(None),
        )
        .order_by(BookingSession.booked_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def cancel_sessions(
    session: AsyncSession, application_id: int, *, now: datetime | None = None
) -> int:
    """Huỷ mọi liên kết đặt lịch còn sống của một hồ sơ. Trả số phiên đã huỷ. **KHÔNG commit.**

    Gọi khi hồ sơ rẽ sang hướng KHÔNG còn phỏng vấn nữa (HR từ chối). Bỏ bước này thì ứng viên vừa
    nhận thư từ chối vẫn mở được link cũ và tự đặt lịch — `confirm_and_notify` sẽ ghi đè `REJECTED`
    thành `INTERVIEW_SCHEDULED` và họ xuất hiện trên lịch của HR.
    """
    at = _as_utc(now, "now") if now is not None else _now()
    stmt = (
        update(BookingSession)
        .where(
            BookingSession.application_id == application_id,
            BookingSession.cancelled_at.is_(None),
        )
        .values(cancelled_at=at)
    )
    return (await session.execute(stmt)).rowcount or 0
