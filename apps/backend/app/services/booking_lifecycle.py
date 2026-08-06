"""booking_lifecycle — nghiệp vụ VÒNG ĐỜI lịch phỏng vấn (SCH-3 · PRD §10b.6, FR-BOOK-3/4).

Ba lưới, ba câu hỏi khác nhau — cùng chạy trong sweep loop 08c:

1. **Nhắc trước buổi phỏng vấn** (`BOOKING_INTERVIEW_REMINDER_HOURS`, mặc định 24h) — email + `.ics`.
2. **Nhắc chọn lịch** khi liên kết còn `BOOKING_REMINDER_HOURS` nữa là hết hạn — DÙNG LẠI link cũ.
3. **Liên kết hết hạn mà chưa đặt** → `PENDING_REVIEW` + cờ `booking_no_response` + nhả HELD còn sót.

**TUYỆT ĐỐI KHÔNG auto-reject ở bất kỳ nhánh nào.** Ứng viên không bấm link có thể vì mail vào thư
rác, vì đang ốm, vì đổi số điện thoại — im lặng KHÔNG phải lời từ chối, và một hồ sơ đã được HỆ
THỐNG quyết định mời thì chỉ CON NGƯỜI mới được rút lại lời mời đó. Đối xứng FR-SCR-3 của Screener.

TÁCH khỏi cơ chế lập lịch (`screening_scheduler.py`) y như `screening_timeout`/`stuck_applications`:
file này chỉ nhận `AsyncSession`/`session_factory` và không biết ai gọi mình. Đổi sang QStash sau
KHÔNG phải sửa gì ở đây.

Idempotent bằng **cột mốc thời gian**, không phải bộ đếm: `InterviewBooking.reminder_sent_at`,
`BookingSession.reminded_at`, `BookingSession.cancelled_at`. Mốc trả lời được cả "đã làm chưa" lẫn
"làm lúc nào" khi truy vết sự cố, còn bộ đếm thì lệch một nhịp là không ai biết lệch từ đâu.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.nodes import scheduler
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.models.job_posting import JobPosting
from app.services import audit_service, booking_service
from app.services.booking_config import BookingConfig, load_booking_config

logger = get_logger("app.services.booking_lifecycle")

_NO_RESPONSE_REASON = "Ứng viên không chọn khung giờ phỏng vấn trong thời hạn của liên kết."
_NO_SLOTS_REASON = (
    "Ứng viên đã mở liên kết nhưng KHÔNG còn khung giờ trống, và liên kết đã hết hạn — "
    "lỗi ở lịch của công ty, không phải ứng viên. Cần mở thêm lịch rồi liên hệ lại."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _remaining_text(expires_at: datetime, now: datetime) -> str:
    """Thời gian CÒN LẠI dạng người đọc được — đọc được cả khi verify đặt ngưỡng nhỏ (phút)."""
    secs = max(0, int((expires_at - now).total_seconds()))
    if secs >= 3600:
        return f"{secs // 3600} giờ"
    if secs >= 60:
        return f"{secs // 60} phút"
    return "ít phút tới"


def _booking_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/booking/{token}"


async def _job_title(session: AsyncSession, app_row: Application) -> str:
    if app_row.job_id is None:
        return "vị trí ứng tuyển"
    job = await session.get(JobPosting, app_row.job_id)
    return job.title if job is not None else "vị trí ứng tuyển"


def _candidate_name(app_row: Application) -> str:
    return (app_row.parsed_data or {}).get("full_name") or "Ứng viên"


# ── Truy vấn "đến hạn" (đọc, KHÔNG khoá) ─────────────────────────────────────────────────


async def _due_interview_reminder_ids(
    session: AsyncSession, now: datetime, cfg: BookingConfig
) -> list[int]:
    """id booking cần NHẮC TRƯỚC BUỔI PV: còn `BOOKED`, chưa nhắc, buổi PV nằm trong cửa sổ nhắc.

    `start_at > now` loại buổi đã diễn ra: một lời nhắc tới sau buổi phỏng vấn thì tệ hơn không nhắc.
    Join `Application` kiểm `INTERVIEW_SCHEDULED` để không nhắc hồ sơ mà HR vừa huỷ lịch trong lúc
    sweep đang chạy (hàng `BOOKED` và trạng thái hồ sơ luôn đổi cùng transaction, nhưng lưới cứ kiểm
    cả hai — hai nguồn nói khác nhau thì im lặng vẫn hơn gửi nhầm).
    """
    stmt = (
        select(InterviewBooking.id)
        .join(Application, Application.id == InterviewBooking.application_id)
        .where(
            InterviewBooking.status == BookingStatus.BOOKED.value,
            InterviewBooking.reminder_sent_at.is_(None),
            InterviewBooking.start_at > now,
            InterviewBooking.start_at <= now + timedelta(hours=cfg.interview_reminder_hours),
            Application.status == ApplicationStatus.INTERVIEW_SCHEDULED.value,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _due_link_reminder_ids(
    session: AsyncSession, now: datetime, cfg: BookingConfig
) -> list[int]:
    """id phiên cần NHẮC CHỌN LỊCH: chưa đặt/chưa huỷ/chưa nhắc, CHƯA hết hạn, sắp hết hạn."""
    stmt = (
        select(BookingSession.id)
        .join(Application, Application.id == BookingSession.application_id)
        .where(
            BookingSession.booked_at.is_(None),
            BookingSession.cancelled_at.is_(None),
            BookingSession.reminded_at.is_(None),
            BookingSession.expires_at > now,
            BookingSession.expires_at <= now + timedelta(hours=cfg.reminder_hours),
            Application.status == ApplicationStatus.AWAITING_BOOKING.value,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


def _has_live_booking(application_id) -> object:  # noqa: ANN001
    """Điều kiện SQL: hồ sơ này đang có một khung giờ `BOOKED`.

    Tách ra vì dùng ở HAI chỗ (truy vấn quét + re-check trong khoá) và hai chỗ đó BẮT BUỘC hỏi
    cùng một câu — lệch nhau là tái sinh đúng lớp lỗi mà cả hai đang chặn.
    """
    return (
        select(InterviewBooking.id)
        .where(
            InterviewBooking.application_id == application_id,
            InterviewBooking.status == BookingStatus.BOOKED.value,
        )
        .exists()
    )


async def _due_expiry_ids(session: AsyncSession, now: datetime) -> list[int]:
    """id phiên HẾT HẠN mà chưa đặt được giờ: quá `expires_at`, chưa đặt, chưa huỷ, app còn chờ.

    Chốt chặn CUỐI là `~_has_live_booking`: ba điều kiện kia đều là CỜ (`booked_at`, trạng thái hồ
    sơ) — thứ có thể lệch khỏi sự thật nếu một đường ghi nào đó hỏng giữa chừng. Bảng
    `interview_booking` mới là sự thật. Thiếu chốt này, một hồ sơ đang cầm lịch đã chốt (có `.ics`
    trong tay) bị báo cho HR là "không phản hồi", và khung giờ `BOOKED` đó không đường nào nhả nữa
    nên biến mất khỏi lịch công ty vĩnh viễn.
    """
    stmt = (
        select(BookingSession.id)
        .join(Application, Application.id == BookingSession.application_id)
        .where(
            BookingSession.booked_at.is_(None),
            BookingSession.cancelled_at.is_(None),
            BookingSession.expires_at <= now,
            Application.status == ApplicationStatus.AWAITING_BOOKING.value,
            ~_has_live_booking(BookingSession.application_id),
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _lock_session(session: AsyncSession, session_id: int) -> BookingSession | None:
    stmt = select(BookingSession).where(BookingSession.id == session_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def _lock_booking(session: AsyncSession, booking_id: int) -> InterviewBooking | None:
    stmt = select(InterviewBooking).where(InterviewBooking.id == booking_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


# ── Handler nghiệp vụ (cơ chế nào gọi cũng được) ─────────────────────────────────────────


async def send_interview_reminder(session: AsyncSession, booking: InterviewBooking) -> None:
    """NHẮC trước buổi phỏng vấn, MỘT lần (FR-BOOK-4). Caller đã row-lock + re-check.

    `reminder_sent_at` được ghi + commit **TRƯỚC** khi gửi → at-most-once: gửi lỗi cũng KHÔNG nhắc
    lại. Cùng lựa chọn với `send_screening_reminder` của 08c, và lý do vẫn thế — thà thiếu một lời
    nhắc còn hơn mỗi vòng sweep lại dội thêm một email vào hộp thư ứng viên khi Resend đang trục trặc.
    """
    app_row = await session.get(Application, booking.application_id)
    if app_row is None:  # hồ sơ đã bị xoá — bỏ qua an toàn
        return
    job_title = await _job_title(session, app_row)
    name = _candidate_name(app_row)
    applicant_email = app_row.applicant_email
    link_row = await booking_service.booked_session(session, booking.application_id)
    manage_url = _booking_url(link_row.token) if link_row is not None else None

    booking.reminder_sent_at = _now()
    await session.commit()

    await scheduler.notify_interview_reminder(
        session, application_id=booking.application_id, applicant_email=applicant_email,
        candidate_name=name, job_title=job_title, booking=booking, manage_url=manage_url,
    )


async def send_booking_reminder(session: AsyncSession, sess: BookingSession) -> None:
    """NHẮC ứng viên chọn giờ khi liên kết sắp hết hạn, MỘT lần (FR-BOOK-3). Caller đã row-lock.

    DÙNG LẠI đúng token cũ — token đặt lịch KHÔNG one-time (§10b.3) và mỗi lần mở là danh sách slot
    TƯƠI, nên không có lý do gì phát link thứ hai.
    """
    app_row = await session.get(Application, sess.application_id)
    if app_row is None:
        return
    job_title = await _job_title(session, app_row)
    name = _candidate_name(app_row)
    applicant_email = app_row.applicant_email
    url = _booking_url(sess.token)
    deadline = _remaining_text(sess.expires_at, _now())

    sess.reminded_at = _now()  # once-only: chốt TRƯỚC khi gửi
    await session.commit()

    await scheduler.notify_booking_reminder(
        session, application_id=sess.application_id, applicant_email=applicant_email,
        candidate_name=name, job_title=job_title, booking_url=url, deadline_text=deadline,
    )


async def handle_booking_timeout(session: AsyncSession, sess: BookingSession) -> None:
    """Liên kết HẾT HẠN mà chưa đặt → `PENDING_REVIEW[booking_no_response]` (FR-BOOK-3).

    **KHÔNG auto-reject, KHÔNG gửi email cho ứng viên.** Đây chưa phải một quyết định — nó là việc
    đưa ca trở lại cho HR. Gửi thư lúc này là thay HR thông báo một kết luận chưa ai đưa ra.

    Ba việc trong MỘT transaction (audit `commit=True` đóng cả cụm): nhả HELD còn sót, khoá liên kết,
    hạ trạng thái. Nhả HELD là bắt buộc dù hold tự hết hạn theo `hold_expires_at` — một phiên bỏ dở
    đúng lúc hết hạn liên kết vẫn đang chiếm chỗ tới phút cuối của hold, và khung giờ là tài nguyên
    tranh chấp.

    Idempotent hai lớp: `cancelled_at` khiến vòng quét sau không nhặt lại phiên này, và trạng thái
    rời khỏi `AWAITING_BOOKING` khiến chính hồ sơ đó rơi khỏi lưới.
    """
    app_row = await session.get(Application, sess.application_id)
    if app_row is None:
        return
    # Re-check TRONG khoá, hỏi ĐÚNG câu mà truy vấn quét đã hỏi: giữa lúc quét và lúc khoá, ứng viên
    # có thể vừa chốt xong giờ. Hạ hồ sơ của người vừa giành được khung giờ là lấy mất thứ họ vừa
    # giành — và không đường nào nhả lại hàng BOOKED đó.
    if (await session.execute(select(_has_live_booking(sess.application_id)))).scalar():
        logger.info(
            "sweep-booking: app=%s có lịch đã chốt — BỎ QUA lượt hạ vì hết hạn", sess.application_id
        )
        return

    released = await booking_service.release_holds(session, sess.application_id)
    # Huỷ MỌI liên kết còn sống, không chỉ phiên đang xử: hồ sơ vừa rời hướng phỏng vấn, mà một
    # phiên mồ côi (do hai lượt mời chồng nhau) còn sống là còn đường để token cũ lật ngược quyết
    # định này — đúng lỗi #6 của SCH-2, lần này ở phía hết hạn.
    await booking_service.cancel_sessions(session, sess.application_id)

    # Quy TRÁCH NHIỆM cho đúng chỗ. Ứng viên đã mở link mà lịch trống rỗng thì họ KHÔNG có gì để
    # bấm — dán nhãn "không phản hồi" lên họ chính là cái đổ-lỗi-nhầm-người mà FR-BOOK-6 sinh ra để
    # chặn, và nó xoá luôn nhãn "hết khung giờ" (vì `no_slot_application_ids` lọc `cancelled_at`).
    blocked_by_us = sess.no_slots_at is not None
    flag = "booking_no_slots" if blocked_by_us else "booking_no_response"
    reason = _NO_SLOTS_REASON if blocked_by_us else _NO_RESPONSE_REASON
    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = reason
    # Gán LẠI cả danh sách: JSONB mutate tại chỗ không được SQLAlchemy đánh dấu bẩn nên UPDATE sẽ
    # bỏ qua cột này (cùng bẫy đã gặp với parsed_data).
    flags = list(app_row.uncertainty_flags or [])
    if flag not in flags:
        app_row.uncertainty_flags = [*flags, flag]

    await audit_service.record(
        session, application_id=sess.application_id, node="scheduler",
        action=flag, uncertainty_flags=[flag], escalation_reason=reason,
        detail={"expires_at": sess.expires_at.isoformat(), "released_holds": released,
                "blocked_by_no_slots": blocked_by_us},
        commit=True,
    )
    logger.warning(
        "sweep-booking: app=%s hết hạn link đặt lịch → PENDING_REVIEW[%s] (nhả %d chỗ giữ)",
        sess.application_id, flag, released,
    )


# ── Một vòng quét ────────────────────────────────────────────────────────────────────────


async def sweep_once(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """MỘT vòng quét vòng đời lịch: nhắc buổi PV · nhắc chọn lịch · hết hạn.

    Mỗi mục xử lý trong transaction RIÊNG (row-lock + re-check TRONG lock để chống đua với chính
    ứng viên đang bấm). Lỗi một mục KHÔNG làm chết cả vòng — cùng khuôn `screening_timeout.sweep_once`.
    """
    now = _now()
    cfg = load_booking_config()
    async with session_factory() as read_sess:
        reminder_ids = await _due_interview_reminder_ids(read_sess, now, cfg)
        link_ids = await _due_link_reminder_ids(read_sess, now, cfg)
        expiry_ids = await _due_expiry_ids(read_sess, now)

    counts = {"interview_reminded": 0, "link_reminded": 0, "expired": 0, "errors": 0}

    for bid in reminder_ids:
        try:
            async with session_factory() as s:
                row = await _lock_booking(s, bid)
                # Re-check trong lock: ứng viên/HR có thể vừa huỷ, hoặc một sweep khác vừa nhắc.
                if row is None or row.status != BookingStatus.BOOKED.value \
                        or row.reminder_sent_at is not None:
                    continue
                await send_interview_reminder(s, row)
                counts["interview_reminded"] += 1
        except Exception:  # noqa: BLE001 — một mục lỗi KHÔNG làm chết cả vòng
            counts["errors"] += 1
            logger.exception("sweep-booking: lỗi khi NHẮC buổi phỏng vấn booking id=%s", bid)

    for sid in link_ids:
        try:
            async with session_factory() as s:
                sess = await _lock_session(s, sid)
                # Re-check: ứng viên có thể vừa đặt xong (booked_at) giữa lúc quét và lúc khoá.
                if sess is None or sess.booked_at is not None or sess.cancelled_at is not None \
                        or sess.reminded_at is not None:
                    continue
                await send_booking_reminder(s, sess)
                counts["link_reminded"] += 1
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
            logger.exception("sweep-booking: lỗi khi NHẮC chọn lịch session id=%s", sid)

    for sid in expiry_ids:
        try:
            async with session_factory() as s:
                sess = await _lock_session(s, sid)
                # Re-check quan trọng NHẤT trong ba cái: ứng viên bấm xác nhận đúng giây chót vẫn
                # phải THẮNG. Hạ hồ sơ của người vừa đặt được lịch là lấy mất thứ họ vừa giành.
                if sess is None or sess.booked_at is not None or sess.cancelled_at is not None:
                    continue
                await handle_booking_timeout(s, sess)
                counts["expired"] += 1
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
            logger.exception("sweep-booking: lỗi khi xử HẾT HẠN link đặt lịch session id=%s", sid)

    if any(counts.values()):
        logger.info(
            "sweep-booking: interview_reminded=%s link_reminded=%s expired=%s errors=%s",
            counts["interview_reminded"], counts["link_reminded"], counts["expired"],
            counts["errors"],
        )
    return counts
