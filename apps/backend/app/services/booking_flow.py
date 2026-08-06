"""booking_flow — nối đặt lịch vào luồng nghiệp vụ (SCH-2 · PRD §10b, §13, FR-BOOK-1/2).

Đây là chỗ DUY NHẤT biết cả ba mảnh: `booking_service` (DB/slot), `scheduler` (email), và trạng thái
`Application`. Ba đường tới quyết định **mời** (gate lần-đầu, gate sau-screener, HR duyệt ở `/review`)
đều gọi CHUNG `dispatch_booking_invite` — nếu mỗi đường tự viết lại thì sớm muộn cũng có một đường
quên mất thứ tự email-trước-trạng-thái-sau, và đó là lớp lỗi "trạng thái nói dối" đã cắn ở 03b/08d.

Hai thứ tự ghi ở đây KHÁC NHAU, và sự khác nhau là CÓ CHỦ Ý:

- **Gửi thư mời** (`dispatch_booking_invite`) — *email trước, trạng thái sau* (bất biến 08d). Email
  là kênh DUY NHẤT báo cho ứng viên rằng họ được mời; chưa gửi được thì chưa mời, nên chưa được phép
  ghi `AWAITING_BOOKING`.
- **Xác nhận lịch** (`confirm_and_notify`) — *DB trước, email sau* (§3.3). Ở đây ứng viên **tự bấm và
  đang nhìn màn xác nhận**: họ ĐÃ biết. Khung giờ vừa thắng race phải bền và tức thì. Thư chỉ là biên
  nhận, nên gửi hỏng KHÔNG được phép huỷ lịch — chỉ gắn cờ cho HR gọi lại.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes import scheduler
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingSession
from app.models.job_posting import JobPosting
from app.services import audit_service, booking_service
from app.services.booking_config import load_booking_config

logger = get_logger("app.services.booking_flow")

__all__ = [
    "booking_view",
    "cancel_by_candidate",
    "cancel_by_hr",
    "confirm_and_notify",
    "dispatch_booking_invite",
    "resend_booking_link",
]

_EMAIL_FAILED_FLAG = (
    "Đã đặt lịch phỏng vấn nhưng GỬI THƯ XÁC NHẬN THẤT BẠI — cần báo ứng viên thủ công."
)

# Trạng thái mà một liên kết đặt lịch còn được phép ghi kết quả lên. Cố ý KHÔNG có `PENDING_REVIEW`
# và `REJECTED`: hồ sơ đã quay về tay HR (hoặc đã bị từ chối) thì token cũ không được lật ngược
# quyết định của con người. `INTERVIEW_SCHEDULED` có mặt để lần bấm lặp vẫn êm.
_BOOKABLE_STATUSES = frozenset(
    {
        ApplicationStatus.SCHEDULING.value,
        ApplicationStatus.AWAITING_BOOKING.value,
        ApplicationStatus.INTERVIEW_SCHEDULED.value,
    }
)

# HR gửi lại link đặt lịch được ở hai trạng thái này. `INTERVIEW_SCHEDULED` cố ý VẮNG MẶT: xem
# `resend_booking_link`.
_RESENDABLE_STATUSES = frozenset(
    {ApplicationStatus.PENDING_REVIEW.value, ApplicationStatus.AWAITING_BOOKING.value}
)


class BookingActionError(Exception):
    """Thao tác lịch của HR không hợp lệ (route dịch thẳng ra `status_code`).

    Tách khỏi `booking_service.BookingError`: cái kia là lỗi của ĐƯỜNG CÔNG KHAI với thông điệp viết
    cho ứng viên đọc. Ở đây người đọc là HR, nên thông điệp được phép nói rõ trạng thái nội bộ.
    """

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    """Mốc đọc từ DB → aware UTC. asyncpg trả timestamptz đã aware; hàng dựng trong test có thể naive."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _deadline_text() -> str:
    """Hạn của link, dạng người đọc được ("72 giờ")."""
    hours = load_booking_config().link_ttl_hours
    return f"{int(hours)} giờ" if float(hours).is_integer() else f"{hours:g} giờ"


def _booking_url(token: str) -> str:
    return f"{settings.frontend_base_url.rstrip('/')}/booking/{token}"


def _candidate_name(app_row: Application) -> str:
    return (app_row.parsed_data or {}).get("full_name") or "Ứng viên"


async def _job_title(session: AsyncSession, app_row: Application) -> str:
    if app_row.job_id is None:
        return "vị trí ứng tuyển"
    job = await session.get(JobPosting, app_row.job_id)
    return job.title if job is not None else "vị trí ứng tuyển"


async def dispatch_booking_invite(
    session: AsyncSession,
    application: Application,
    *,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    audit_node: str,
) -> bool:
    """Tạo phiên đặt lịch → gửi thư mời KÈM LINK → đặt `AWAITING_BOOKING`. Trả `email_sent`. COMMIT.

    **Thứ tự bất biến 08d:** trạng thái chỉ đổi SAU khi email gửi thành công. Gửi hỏng → hồ sơ về
    `PENDING_REVIEW` cho HR xử lý (KHÔNG auto-reject) và phiên vừa tạo bị huỷ ngay — một liên kết
    chưa từng đến tay ai mà để sống thì SCH-3 sẽ đi nhắc, rồi hạ hồ sơ vì "không phản hồi" một lời
    mời chưa bao giờ được gửi.

    Phiên được tạo TRƯỚC khi gửi (token sinh ở Python nên dựng được link ngay). Chủ ý: một khi thư
    ĐÃ bay đi thì hàng trong DB chắc chắn có mặt — thà thừa một hàng đã huỷ còn hơn để ứng viên mở
    link ra gặp 404 ngay sau khi được mời.

    `audit_node`: "gate" (tự động) hoặc "human_review" (HR duyệt) — để đọc audit biết đường nào tới.
    """
    # Đã có liên kết còn sống thì DÙNG LẠI, đừng phát token thứ hai: HR bấm duyệt ở hai tab (hàng
    # chờ tự làm mới mỗi 5s) hoặc thử lại một request chậm là ra hai email với hai link khác nhau —
    # ứng viên không biết cái nào thật, và ta có một token mồ côi không ai theo dõi.
    session_row = await booking_service.active_session(session, application.id)
    if session_row is None:
        session_row = booking_service.create_booking_session(session, application.id)
        # COMMIT trước khi thư bay đi. `add()` mới chỉ nằm trong bộ nhớ; nếu gửi xong mới ghi mà
        # tiến trình chết ở giữa (BackgroundTasks KHÔNG bền) thì ứng viên cầm một liên kết trỏ vào
        # token không tồn tại → 404 ngay sau khi vừa được mời phỏng vấn.
        await session.commit()
    url = _booking_url(session_row.token)

    result = await scheduler.notify_decision(
        session,
        "invite",
        application_id=application.id,
        applicant_email=applicant_email,
        candidate_name=candidate_name,
        job_title=job_title,
        booking_url=url,
        deadline_text=_deadline_text(),
    )

    if result.get("email_sent"):
        application.status = ApplicationStatus.AWAITING_BOOKING.value
        application.escalation_reason = None
        await audit_service.record(
            session, application_id=application.id, node=audit_node, action="booking_invite_sent",
            detail={"final_status": application.status,
                    "link_expires_at": session_row.expires_at.isoformat()},
            commit=True,
        )
        logger.info("booking_flow: app=%s đã gửi thư mời + link đặt lịch", application.id)
        return True

    session_row.cancelled_at = _now()
    application.status = ApplicationStatus.PENDING_REVIEW.value
    application.escalation_reason = "Gửi thư mời đặt lịch thất bại — cần HR xử lý."
    await audit_service.record(
        session, application_id=application.id, node=audit_node, action="booking_invite_failed",
        escalation_reason="invite_email_failed", commit=True,
    )
    logger.warning("booking_flow: app=%s gửi thư mời THẤT BẠI → PENDING_REVIEW", application.id)
    return False


async def booking_view(session: AsyncSession, token: str) -> dict:
    """GET công khai: validate token → sinh/trả slot đang giữ. Projection AN TOÀN.

    Trả về CHỈ những gì ứng viên cần thấy: tiêu đề JD, tên họ, và các khung giờ. TUYỆT ĐỐI không
    rubric/điểm/gate/parsed_data/trạng thái nội bộ (kỷ luật 08b) — hình dạng payload được chốt ở
    `schemas/booking.py` và có test khẳng định sự VẮNG MẶT của chúng.

    Đã đặt lịch rồi → `already_booked=True` + giờ đã đặt. Đó là **trạng thái UI, KHÔNG phải lỗi**:
    token không one-time nên mở lại link là chuyện bình thường, và ném lỗi ở đây sẽ cho ứng viên vừa
    đặt xong xem một màn hình vỡ.
    """
    session_row = await booking_service.load_valid_session(session, token)
    app_row = await session.get(Application, session_row.application_id)
    if app_row is None:  # FK CASCADE nên gần như không xảy ra; vẫn xử lý êm thay vì 500.
        raise booking_service.TokenNotFound("Liên kết không hợp lệ.")

    job_title = await _job_title(session, app_row)
    base = {"job_title": job_title, "candidate_name": _candidate_name(app_row)}
    had_no_slots = session_row.no_slots_at is not None

    try:
        slots = await booking_service.generate_slots(session, app_row.id)
    except booking_service.AlreadyBooked as exc:
        return {
            **base,
            "already_booked": True,
            "booked_start_at": exc.booking.start_at,
            "booked_end_at": exc.booking.end_at,
            "slots": [],
            "hold_expires_at": None,
        }

    await _record_slot_availability(
        session, session_row, app_row, had_no_slots=had_no_slots, has_slots=bool(slots)
    )

    return {
        **base,
        "already_booked": False,
        "booked_start_at": None,
        "booked_end_at": None,
        "slots": slots,
        # Mọi slot trong một lượt giữ chung một hạn — UI đếm ngược theo mốc này (không gia hạn).
        "hold_expires_at": slots[0].hold_expires_at if slots else None,
    }


async def _record_slot_availability(
    session: AsyncSession,
    session_row: BookingSession,
    app_row: Application,
    *,
    had_no_slots: bool,
    has_slots: bool,
) -> None:
    """Ghi nhận việc ứng viên GẶP (hoặc thôi gặp) cảnh hết khung giờ — SCH-3 §3.5, FR-BOOK-6.

    Vì sao cần cột riêng thay vì suy ra từ trạng thái: hồ sơ vẫn đứng ở `AWAITING_BOOKING` trong cả
    hai tình huống "ứng viên chưa bấm link" và "ứng viên đã bấm nhưng lịch trống rỗng". Gộp chúng
    lại thành một nhãn là đổ lỗi cho người không có lỗi — HR nhìn dashboard tưởng ứng viên chậm
    trong khi thứ đang chặn là lịch của chính công ty.

    Ghi MỘT lần (mốc thời gian, không đếm) và **xoá ngay khi có slot trở lại** — cảnh báo không tự
    tắt là cảnh báo sẽ bị phớt lờ, kể cả khi HR đã mở thêm lịch từ lâu.
    """
    if had_no_slots is not has_slots:
        return  # tình hình y hệt lần trước (vẫn hết, hoặc vẫn có) — khỏi ghi DB

    if has_slots:
        session_row.no_slots_at = None
        await session.commit()
        logger.info("booking_flow: app=%s đã có khung giờ trở lại — gỡ cảnh báo hết lịch", app_row.id)
        return

    session_row.no_slots_at = _now()
    await audit_service.record(
        session, application_id=app_row.id, node="scheduler", action="booking_no_slots",
        escalation_reason="no_slots",
        detail={"window_days": load_booking_config().window_days}, commit=True,
    )
    logger.warning(
        "booking_flow: app=%s mở link nhưng HẾT khung giờ trống — cần HR mở thêm lịch", app_row.id
    )


async def confirm_and_notify(session: AsyncSession, token: str, booking_id: int) -> dict:
    """POST công khai: chốt giờ → thư xác nhận + `.ics` → `INTERVIEW_SCHEDULED`. Thứ tự §3.3.

    `confirm_booking` chạy TRƯỚC và có quyền ném (`SlotTaken`/`HoldExpired`/`BookingNotFound`) — route
    dịch thành 409/404 và ứng viên chọn lại. **Sau khi nó thành công thì tuyệt đối không ném nữa:**
    khung giờ đã thuộc về ứng viên này, mọi trục trặc phía sau (email, audit, commit) chỉ được ghi
    log + gắn cờ. Ném ra ngoài sẽ trả 500 cho người vừa đặt lịch THÀNH CÔNG — họ bấm lại, và lần này
    gặp `AlreadyBooked` hoặc tệ hơn là nghĩ mình chưa có lịch.
    """
    session_row = await booking_service.load_valid_session(session, token)
    app_row = await session.get(Application, session_row.application_id)
    if app_row is None:
        raise booking_service.TokenNotFound("Liên kết không hợp lệ.")

    # Gom dữ liệu email TRƯỚC khi confirm commit (tránh lazy-load sau commit — gotcha refresh()).
    application_id = app_row.id
    applicant_email = app_row.applicant_email
    candidate_name = _candidate_name(app_row)
    job_title = await _job_title(session, app_row)

    # Hồ sơ đã rẽ sang hướng KHÔNG còn phỏng vấn (HR từ chối, hoặc SCH-3 hạ vì hết hạn) thì token cũ
    # KHÔNG được phép lật ngược quyết định đó. `load_valid_session` cố ý không kiểm trạng thái (để
    # người đã đặt xong vẫn mở lại link được), nên chốt chặn nằm ở đây.
    if app_row.status not in _BOOKABLE_STATUSES:
        raise booking_service.TokenExpired(
            "Liên kết này không còn hiệu lực. Bộ phận Tuyển dụng sẽ liên hệ với bạn."
        )

    already_settled = session_row.booked_at is not None
    booking = await booking_service.confirm_booking(session, application_id, booking_id)

    # Giá trị nguyên thuỷ, lấy TRƯỚC mọi thao tác có thể hỏng. Nếu commit cuối thất bại, SQLAlchemy
    # đánh dấu HẾT THẢY object trong session là expired; đọc `booking.id` lúc đó sẽ nạp lười trên
    # một session đang cần rollback và ném `PendingRollbackError` — tức chính khối `except` sinh ra
    # để "không bao giờ ném sau khi đã chốt" lại là thứ ném ra ngoài (adversarial review tái hiện).
    booked_id, start_at, end_at = booking.id, booking.start_at, booking.end_at

    if already_settled:
        # Bấm xác nhận lần hai (tải lại trang, mạng chớp, hai tab). Biên nhận đã gửi rồi — gửi thêm
        # là spam ứng viên và đốt quota Resend, kênh DUY NHẤT của cả hệ thống.
        logger.info("booking_flow: app=%s xác nhận lặp — bỏ qua gửi lại thư", application_id)
        return {"job_title": job_title, "start_at": start_at, "end_at": end_at, "email_sent": True}

    email_sent = False
    try:
        result = await scheduler.notify_booking_confirmed(
            session, application_id=application_id, applicant_email=applicant_email,
            candidate_name=candidate_name, job_title=job_title, booking=booking,
            # SCH-3: liên kết HUỶ nằm trong thư xác nhận, và nó là CHÍNH token này (§10b.6) — mở ra
            # thấy lịch đã chốt kèm nút huỷ. Không phát token thứ hai chỉ để huỷ.
            manage_url=_booking_url(token),
        )
        email_sent = bool(result.get("email_sent"))
    except Exception:  # noqa: BLE001 — lịch ĐÃ chốt; thư hỏng không được phép làm hỏng lượt đặt
        logger.exception(
            "booking_flow: gửi thư xác nhận lỗi app=%s — lịch VẪN giữ, gắn cờ cho HR", application_id
        )

    try:
        app_row.status = ApplicationStatus.INTERVIEW_SCHEDULED.value
        app_row.escalation_reason = None if email_sent else _EMAIL_FAILED_FLAG
        booking_service.mark_session_booked(session_row)
        await audit_service.record(
            session, application_id=application_id, node="scheduler", action="booking_confirmed",
            escalation_reason=None if email_sent else "booking_email_failed",
            detail={"booking_id": booked_id, "start_at": start_at.isoformat(),
                    "email_sent": email_sent},
            commit=True,
        )
    except Exception:  # noqa: BLE001 — hàng BOOKED là sự thật rồi; đừng ném vào mặt người vừa đặt
        # KHÔNG chạm vào object ORM nào ở đây (xem ghi chú `booked_id` bên trên). Rollback để session
        # còn dùng được cho phần dọn dẹp của dependency; nếu chính nó hỏng thì cũng nuốt nốt.
        logger.exception(
            "booking_flow: ghi INTERVIEW_SCHEDULED lỗi app=%s — booking=%s VẪN là BOOKED",
            application_id, booked_id,
        )
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("booking_flow: rollback cũng lỗi app=%s", application_id)

    return {
        "job_title": job_title,
        "start_at": start_at,
        "end_at": end_at,
        "email_sent": email_sent,
    }


# ══════════════════════════════════════════════════════════════════════════════════════════
# Vòng đời sau khi đã chốt lịch (SCH-3 · PRD §10b.6, FR-BOOK-4)
# ══════════════════════════════════════════════════════════════════════════════════════════
#
# Cả ba đường huỷ dưới đây theo THỨ TỰ CỦA `confirm_and_notify`: **DB trước, email sau**. Lý do
# giống hệt: khung giờ là tài nguyên tranh chấp — nhả nó phải TỨC THÌ và bền, còn thư chỉ là biên
# nhận. Giữ chỗ lại chờ Resend trả lời là chặn ứng viên khác vì một lý do không liên quan tới họ.
_CANDIDATE_CANCEL_FLAG = "Ứng viên đã huỷ lịch và đang tự chọn lại khung giờ khác."
_CANDIDATE_CANCEL_EXPIRED_FLAG = (
    "Ứng viên đã huỷ lịch phỏng vấn nhưng liên kết đặt lịch đã hết hạn — cần HR sắp xếp lại."
)
_HR_CANCEL_FLAG = "HR đã huỷ lịch phỏng vấn — cần sắp xếp lại với ứng viên."


async def cancel_by_candidate(session: AsyncSession, token: str) -> dict:
    """Ứng viên tự huỷ lịch qua **chính token đặt lịch** (không phát token thứ hai — §10b.6).

    Hai kết cục, quyết bởi liên kết CŨ còn hạn hay không:

    - còn hạn → `AWAITING_BOOKING`, ứng viên chọn lại ngay trong hạn cũ. **KHÔNG gia hạn TTL**:
      gia hạn mỗi lần huỷ là tự tạo vòng lặp đặt-huỷ-đặt không có điểm dừng, còn hạn gốc thì đóng
      cửa sau đúng 72h dù có huỷ bao nhiêu lần.
    - hết hạn → `PENDING_REVIEW` + cờ, HR xử tiếp. (KHÔNG auto-reject — huỷ ≠ từ chối.)

    Bấm huỷ lần hai / hồ sơ không còn ở `INTERVIEW_SCHEDULED` → trả `cancelled=False`, **200 chứ
    không phải lỗi**: người vừa huỷ xong mà bấm lại thì thấy màn hình bình thường, và một token cũ
    KHÔNG có cửa lật ngược quyết định HR đã ghi trong lúc đó (bài học lỗi #6 của SCH-2).
    """
    session_row = await booking_service.load_valid_session(session, token)
    app_row = await session.get(Application, session_row.application_id)
    if app_row is None:
        raise booking_service.TokenNotFound("Liên kết không hợp lệ.")

    # Gom TRƯỚC mọi commit (gotcha refresh()/expire — lỗi #3 SCH-2).
    application_id = app_row.id
    applicant_email = app_row.applicant_email
    candidate_name = _candidate_name(app_row)
    job_title = await _job_title(session, app_row)

    if app_row.status != ApplicationStatus.INTERVIEW_SCHEDULED.value:
        await session.rollback()  # nhả connection ngay, đừng ôm transaction đọc suốt phần còn lại
        return {"cancelled": False, "job_title": job_title, "can_rebook": False, "email_sent": False}

    booking = await booking_service.cancel_booked(session, application_id)
    if booking is None:
        # Trạng thái nói có lịch nhưng bảng thì không — không tự ý sửa trạng thái ở đường công khai.
        logger.warning("booking_flow: app=%s INTERVIEW_SCHEDULED nhưng không có hàng BOOKED", application_id)
        await session.rollback()
        return {"cancelled": False, "job_title": job_title, "can_rebook": False, "email_sent": False}

    start_at = booking.start_at  # nguyên thuỷ, lấy TRƯỚC commit
    can_rebook = _as_utc(session_row.expires_at) > _now()

    if can_rebook:
        booking_service.mark_session_reopened(session_row)
        app_row.status = ApplicationStatus.AWAITING_BOOKING.value
        app_row.escalation_reason = _CANDIDATE_CANCEL_FLAG
    else:
        await booking_service.cancel_sessions(session, application_id)
        app_row.status = ApplicationStatus.PENDING_REVIEW.value
        app_row.escalation_reason = _CANDIDATE_CANCEL_EXPIRED_FLAG

    await audit_service.record(
        session, application_id=application_id, node="scheduler", action="booking_cancelled",
        escalation_reason="booking_cancelled",
        detail={"by": "candidate", "start_at": start_at.isoformat(),
                "final_status": app_row.status, "can_rebook": can_rebook},
        commit=True,
    )

    result = await scheduler.notify_booking_cancelled(
        session, application_id=application_id, applicant_email=applicant_email,
        candidate_name=candidate_name, job_title=job_title, start_at=start_at,
        rebook_url=_booking_url(token) if can_rebook else None,
    )
    return {
        "cancelled": True,
        "job_title": job_title,
        "can_rebook": can_rebook,
        "email_sent": bool(result.get("email_sent")),
    }


async def cancel_by_hr(session: AsyncSession, application_id: int) -> Application:
    """HR huỷ lịch từ dashboard → nhả slot + báo ứng viên → `PENDING_REVIEW` (§3.4, FR-BOOK-4).

    Huỷ luôn LIÊN KẾT đặt lịch: HR huỷ nghĩa là HR đang cầm ca này: để link cũ sống thì ứng viên tự
    đặt lại một giờ khác trong khi HR tưởng ca đang nằm ở hàng chờ mình. Muốn ứng viên chọn lại thì
    bấm **Gửi lại link** — đó là nửa còn lại của "đổi lịch".
    """
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise BookingActionError(f"Application {application_id} không tồn tại.", status_code=404)
    if app_row.status != ApplicationStatus.INTERVIEW_SCHEDULED.value:
        raise BookingActionError(
            f"Hồ sơ này không có lịch phỏng vấn để huỷ (hiện: {app_row.status}).", status_code=409
        )

    applicant_email = app_row.applicant_email
    candidate_name = _candidate_name(app_row)
    job_title = await _job_title(session, app_row)

    booking = await booking_service.cancel_booked(session, application_id)
    if booking is None:
        await session.rollback()
        raise BookingActionError("Không tìm thấy lịch phỏng vấn đang chốt cho hồ sơ này.", status_code=409)
    start_at = booking.start_at

    await booking_service.cancel_sessions(session, application_id)
    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = _HR_CANCEL_FLAG
    await audit_service.record(
        session, application_id=application_id, node="human_review", action="booking_cancelled",
        escalation_reason="booking_cancelled",
        detail={"by": "hr", "start_at": start_at.isoformat(), "final_status": app_row.status},
        commit=True,
    )

    await scheduler.notify_booking_cancelled(
        session, application_id=application_id, applicant_email=applicant_email,
        candidate_name=candidate_name, job_title=job_title, start_at=start_at, by_hr=True,
    )
    return app_row


async def resend_booking_link(session: AsyncSession, application_id: int) -> Application:
    """HR gửi lại link đặt lịch → phiên MỚI (TTL mới) + thư mời → `AWAITING_BOOKING` (§3.4).

    Huỷ phiên cũ TRƯỚC khi phát phiên mới, vì hai lý do khác nhau: (a) `dispatch_booking_invite` cố
    ý DÙNG LẠI phiên còn sống — không dọn thì "gửi lại" chỉ gửi lại đúng liên kết sắp hết hạn, đúng
    thứ HR đang muốn thay; (b) hai liên kết sống song song thì ứng viên không biết cái nào thật.

    KHÔNG cho gọi khi đang `INTERVIEW_SCHEDULED`: lịch đã chốt mà phát thêm đường chọn giờ là mở cửa
    cho một ứng viên chiếm hai khung giờ. Muốn đổi lịch thì **Huỷ lịch** trước — hai bước, tường minh.
    """
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise BookingActionError(f"Application {application_id} không tồn tại.", status_code=404)
    if app_row.status not in _RESENDABLE_STATUSES:
        raise BookingActionError(
            f"Chỉ gửi lại link khi hồ sơ đang chờ HR hoặc chờ ứng viên chọn lịch (hiện: {app_row.status}). "
            "Nếu đã có lịch, hãy Huỷ lịch trước.",
            status_code=409,
        )

    applicant_email = app_row.applicant_email
    candidate_name = _candidate_name(app_row)
    job_title = await _job_title(session, app_row)

    await booking_service.cancel_sessions(session, application_id)
    await session.commit()

    await dispatch_booking_invite(
        session, app_row, applicant_email=applicant_email, candidate_name=candidate_name,
        job_title=job_title, audit_node="human_review",
    )
    return app_row
