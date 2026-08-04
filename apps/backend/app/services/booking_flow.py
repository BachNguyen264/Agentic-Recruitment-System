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
from app.models.job_posting import JobPosting
from app.services import audit_service, booking_service
from app.services.booking_config import load_booking_config

logger = get_logger("app.services.booking_flow")

__all__ = ["booking_view", "confirm_and_notify", "dispatch_booking_invite"]

_EMAIL_FAILED_FLAG = (
    "Đã đặt lịch phỏng vấn nhưng GỬI THƯ XÁC NHẬN THẤT BẠI — cần báo ứng viên thủ công."
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
    session_row = booking_service.create_booking_session(session, application.id)
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

    return {
        **base,
        "already_booked": False,
        "booked_start_at": None,
        "booked_end_at": None,
        "slots": slots,
        # Mọi slot trong một lượt giữ chung một hạn — UI đếm ngược theo mốc này (không gia hạn).
        "hold_expires_at": slots[0].hold_expires_at if slots else None,
    }


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

    booking = await booking_service.confirm_booking(session, application_id, booking_id)

    email_sent = False
    try:
        result = await scheduler.notify_booking_confirmed(
            session, application_id=application_id, applicant_email=applicant_email,
            candidate_name=candidate_name, job_title=job_title, booking=booking,
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
            detail={"booking_id": booking.id, "start_at": booking.start_at.isoformat(),
                    "email_sent": email_sent},
            commit=True,
        )
    except Exception:  # noqa: BLE001 — hàng BOOKED là sự thật rồi; đừng ném vào mặt người vừa đặt
        logger.exception(
            "booking_flow: ghi INTERVIEW_SCHEDULED lỗi app=%s — booking=%s VẪN là BOOKED",
            application_id, booking.id,
        )

    return {
        "job_title": job_title,
        "start_at": booking.start_at,
        "end_at": booking.end_at,
        "email_sent": email_sent,
    }
