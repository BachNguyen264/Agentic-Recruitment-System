"""scheduler — điểm thực thi DUY NHẤT mọi email tới ứng viên (PRD §7.4).

Mời/từ chối, thư sàng lọc + nhắc, và bốn loại thư vòng đời lịch (xác nhận, nhắc trước buổi PV,
nhắc chọn lịch, báo huỷ) — tất cả gửi THẬT qua Resend với template CỐ ĐỊNH. Tệp `.ics` đi qua seam
`CalendarProvider`. (CLAUDE.md: KHÔNG gửi email rải rác ở node khác.)

`scheduler_node` (cuối file) là phần chạy TRONG graph và chỉ là một marker trạng thái: node không
có DB session nên không gửi được gì — mọi lượt gửi đều do các hàm `notify_*` ở đây thực hiện, gọi
từ background task / `booking_flow` / sweep SAU khi graph chạy.

**KHÔNG hàm `notify_*` nào được phép ném.** Mọi caller đều đứng SAU một quyết định đã ghi vào DB
(đã REJECTED, lịch đã chốt, mốc đã nhắc), nên ném ra ngoài chỉ tạo trạng thái nửa vời. Lỗi gửi →
log + audit ``email_failed`` + trả ``email_sent=False``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import RecruitmentState
from app.core.logging import get_logger
from app.models.application import ApplicationStatus
from app.models.booking import InterviewBooking
from app.models.email_delivery import DeliveryStatus, EmailDelivery
from app.services import audit_service, email_service
from app.services.calendar import get_calendar_provider
from app.services.email_templates import (
    booking_cancelled_email,
    booking_confirmed_email,
    booking_reminder_email,
    interview_reminder_email,
    invite_email,
    rejection_email,
    screener_email,
    screener_reminder_email,
)

logger = get_logger("app.agents.scheduler")

Attachments = list[tuple[str, bytes, str]]

_ICS_MIME = "text/calendar; charset=utf-8"


async def _interview_ics(
    booking: InterviewBooking, *, job_title: str, application_id: int, mode: str
) -> tuple[Attachments | None, str | None]:
    """Sinh tệp `.ics` MỜI-lịch cho một buổi phỏng vấn → (đính kèm, `calendar_ref`).

    Sinh hỏng KHÔNG được chặn thư — trả `(None, None)` + log. Buổi phỏng vấn vẫn diễn ra dù ứng
    viên có thêm được vào ứng dụng lịch hay không; và với thư xác nhận thì khung giờ ĐÃ `BOOKED`
    trong DB rồi, nên biên nhận còn quan trọng hơn tệp đính kèm. Một chính sách xuống cấp DUY NHẤT
    cho mọi thư có `.ics` — trước đây thư xác nhận âm thầm không được gửi khi tệp lỗi.
    """
    try:
        event = await get_calendar_provider().create_event(
            booking,
            summary=f"Phỏng vấn — {job_title}",
            description=f"Buổi phỏng vấn vị trí {job_title}.",
        )
    except Exception:  # noqa: BLE001 — thiếu tệp lịch còn hơn thiếu thư
        logger.warning("[scheduler] app=%s: không sinh được .ics cho thư %s", application_id, mode)
        return None, None
    return ([("phong-van.ics", event.ics, _ICS_MIME)] if event.ics else None), event.ref


async def _flag_send_failure(session: AsyncSession, application_id: int) -> None:
    """Gắn `email_send_failed` lên hồ sơ khi Resend TỪ CHỐI ngay lúc gửi. KHÔNG đổi trạng thái.

    Vì sao cần (quan sát trên PROD 29/08/2026): một hồ sơ bị **auto-từ-chối** rồi thư từ chối gửi
    hỏng sẽ nằm lại ở `REJECTED` với `uncertainty_flags` RỖNG — không màn HR nào nói rằng ứng viên
    chưa hề được báo. Vết duy nhất là một dòng `audit_log`, mà HR không có giao diện để đọc. Đường
    MỜI thì đã được `booking_flow.dispatch_booking_invite` xử riêng (hạ về PENDING_REVIEW + ghi lý
    do); đường TỪ CHỐI thì không có ai xử ⇒ đúng loại "thất bại im lặng" mà PRD §13 cấm.

    Dùng ĐÚNG cờ mà webhook `email.failed` dùng (EMAIL-2): gửi-hỏng-đồng-bộ và báo-hỏng-qua-webhook
    là CÙNG một sự kiện với hai đường vào, nên phải cho CÙNG một tín hiệu. Cờ này đã được mọi màn HR
    render sẵn ở MỌI trạng thái, nên không cần đụng gì tới giao diện.

    KHÔNG đổi `status`: đó là quyết định của caller (chỉ caller biết thư này đứng sau việc gì).
    KHÔNG bao giờ ném — hàm này chạy trong nhánh `except` của một lượt gửi đã hỏng; ném ở đây sẽ
    thay một lỗi email bằng một lỗi 500.
    """
    try:
        # Import CỤC BỘ: `booking_flow` import chính module này ⇒ import ở đầu file là vòng tròn.
        from app.models.application import Application
        from app.services.booking_flow import with_flag
        from app.services.email_delivery import EMAIL_SEND_FAILED_FLAG

        app_row = await session.get(Application, application_id)
        if app_row is not None:
            app_row.uncertainty_flags = with_flag(
                app_row.uncertainty_flags, EMAIL_SEND_FAILED_FLAG
            )
    except Exception:  # noqa: BLE001
        logger.exception("[scheduler] app=%s: không gắn được cờ email_send_failed", application_id)


async def _dispatch(
    session: AsyncSession,
    *,
    application_id: int,
    mode: str,
    applicant_email: str,
    subject: str,
    html: str,
    attachments: Attachments | None = None,
    detail: dict | None = None,
) -> dict:
    """Gửi + ghi audit cho MỘT loại thư (SCH-3 dùng chung cho 3 loại thư vòng đời lịch).

    Cùng khuôn với `notify_decision`/`notify_screener`: lỗi gửi → log + audit ``email_failed`` +
    trả ``email_sent=False``, **KHÔNG raise**. Không hàm nào ở đây được phép ném: mọi caller đều
    đứng SAU một quyết định đã ghi vào DB (lịch đã huỷ, mốc đã nhắc), nên ném ra ngoài chỉ tạo
    trạng thái nửa vời chứ không cứu được gì.
    """
    try:
        email_id = await email_service.send_email(
            to=applicant_email, subject=subject, html=html, attachments=attachments
        )
    except Exception as exc:  # noqa: BLE001 — nuốt có kiểm soát: email lỗi KHÔNG làm sập luồng
        logger.warning(
            "[scheduler] app=%s: GỬI EMAIL %s THẤT BẠI tới %s: %s",
            application_id, mode, applicant_email, exc,
        )
        # Gắn cờ TRƯỚC audit: `record(commit=True)` commit một lần cho cả hai (cùng một sự kiện).
        await _flag_send_failure(session, application_id)
        await audit_service.record(
            session, application_id=application_id, node="scheduler", action="email_failed",
            detail={"mode": mode, "to": applicant_email, "error": str(exc)}, commit=True,
        )
        return {"mode": mode, "email_sent": False, "error": str(exc)}

    logger.info("[scheduler] app=%s: đã gửi email %s tới %s", application_id, mode, applicant_email)
    # Lưu vết GIAO HÀNG (EMAIL-1). Cùng transaction với audit bên dưới: hai bản ghi này nói về cùng
    # một sự kiện, tách ra là mở cửa cho "có audit mà không có vết giao hàng". Thiếu `email_id`
    # (Resend không trả) → BỎ QUA: một hàng không có khoá đối chiếu thì webhook chẳng bao giờ tìm
    # thấy, giữ lại chỉ là rác. `mode` đi thẳng vào `kind` — MỘT từ vựng, xem models/email_delivery.
    if email_id:
        session.add(
            EmailDelivery(
                resend_email_id=email_id,
                application_id=application_id,
                kind=mode,
                recipient=applicant_email,
                status=DeliveryStatus.SENT.value,
            )
        )
    await audit_service.record(
        session, application_id=application_id, node="scheduler", action=f"email_sent:{mode}",
        detail={"mode": mode, "to": applicant_email, "email_id": email_id, **(detail or {})},
        commit=True,
    )
    return {"mode": mode, "email_sent": True}


async def notify_decision(
    session: AsyncSession,
    mode: Literal["invite", "reject"],
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    booking_url: str | None = None,
    deadline_text: str = "",
) -> dict:
    """Điểm phát email DUY NHẤT tới ứng viên (PRD §7.4). Gửi thư MỜI/TỪ CHỐI THẬT qua Resend.

    Template CỐ ĐỊNH (không LLM). Lỗi gửi → log + audit ``email_failed``, KHÔNG raise: quyết định HR
    (đã commit ở review 03b) VẪN giữ. Đừng gọi send_email ở node khác.

    SCH-2: thư mời BẮT BUỘC kèm ``booking_url`` (ứng viên tự chọn giờ — PRD §10b). Thiếu link là lỗi
    LẬP TRÌNH nên nổ ngay: nếu để nó âm thầm gửi thư mời không link, ứng viên nhận lời mời rồi không
    có đường nào đặt lịch và nằm chờ mãi ở ``AWAITING_BOOKING`` — hỏng câm, đúng lớp lỗi tệ nhất.
    """
    if mode == "invite":
        if not booking_url:
            raise ValueError(
                "notify_decision('invite') phải kèm booking_url — thư mời KHÔNG có link đặt lịch "
                "sẽ để ứng viên mắc kẹt (PRD §10b.1)."
            )
        subject, html = invite_email(
            candidate_name, job_title, booking_url=booking_url, deadline_text=deadline_text
        )
    else:
        subject, html = rejection_email(candidate_name, job_title)

    return await _dispatch(
        session, application_id=application_id, mode=mode,
        applicant_email=applicant_email, subject=subject, html=html,
    )


async def notify_screener(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    form_url: str,
    deadline_text: str,
    reminder: bool = False,
) -> dict:
    """Gửi thư (mời/NHẮC) trả lời bộ câu hỏi sàng lọc qua magic-link (PRD §7.3, §10). Điểm phát email
    DUY NHẤT (như notify_decision). Template CỐ ĐỊNH (không LLM). `reminder=True` (08c FR-SCR-3) dùng
    template nhắc + audit ``email_sent:screener_reminder`` (cùng magic-link). Lỗi gửi → nuốt có kiểm
    soát + audit ``email_failed``, KHÔNG raise: hồ sơ vẫn AWAITING_SCREENER + session vẫn còn → sweep
    (nhắc/timeout) xử tiếp."""
    mode = "screener_reminder" if reminder else "screener"
    builder = screener_reminder_email if reminder else screener_email
    subject, html = builder(
        candidate_name, job_title, form_url=form_url, deadline_text=deadline_text
    )
    return await _dispatch(
        session, application_id=application_id, mode=mode,
        applicant_email=applicant_email, subject=subject, html=html,
    )


async def notify_booking_confirmed(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    booking: InterviewBooking,
    manage_url: str | None = None,
) -> dict:
    """Thư XÁC NHẬN lịch phỏng vấn + đính kèm `.ics` (SCH-2 · PRD §10b.1, §12.4 FR-NOTI-1).

    Điểm phát email DUY NHẤT, như hai hàm trên. Tệp `.ics` đi qua seam `CalendarProvider` (SCH-1) —
    đổi sang Google Calendar sau này KHÔNG phải sửa chỗ này.

    Lỗi gửi → audit `email_failed` + trả `email_sent=False`, **KHÔNG raise**: khác 08d một cách CÓ
    CHỦ Ý — ở đây khung giờ đã BOOKED trong DB và ứng viên vừa thấy màn xác nhận trên web, nên thư
    chỉ là biên nhận. Huỷ lịch chỉ vì gửi thư hỏng mới là cái sai lớn.

    Sinh `.ics` hỏng thì thư vẫn ĐI (không đính kèm) — xem `_interview_ics`. Nuốt luôn cả thư xác
    nhận vì một tệp đính kèm là bỏ rơi đúng người vừa đặt lịch xong.
    """
    subject, html = booking_confirmed_email(
        candidate_name, job_title, start_at=booking.start_at, end_at=booking.end_at,
        manage_url=manage_url,
    )
    attachments, calendar_ref = await _interview_ics(
        booking, job_title=job_title, application_id=application_id, mode="booking_confirmed"
    )
    return await _dispatch(
        session, application_id=application_id, mode="booking_confirmed",
        applicant_email=applicant_email, subject=subject, html=html, attachments=attachments,
        detail={"start_at": booking.start_at.isoformat(), "calendar_ref": calendar_ref},
    )


async def notify_interview_reminder(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    booking: InterviewBooking,
    manage_url: str | None = None,
) -> dict:
    """Thư NHẮC trước buổi phỏng vấn + `.ics` (SCH-3 · PRD §10b.6, FR-BOOK-4). Một lần duy nhất.

    Sinh `.ics` hỏng KHÔNG được làm mất lời nhắc: buổi phỏng vấn vẫn diễn ra dù ứng viên có thêm
    được vào ứng dụng lịch hay không, nên vẫn gửi thư (không đính kèm) thay vì bỏ nhắc.
    """
    subject, html = interview_reminder_email(
        candidate_name, job_title, start_at=booking.start_at, end_at=booking.end_at,
        manage_url=manage_url,
    )
    attachments, calendar_ref = await _interview_ics(
        booking, job_title=job_title, application_id=application_id, mode="interview_reminder"
    )
    return await _dispatch(
        session, application_id=application_id, mode="interview_reminder",
        applicant_email=applicant_email, subject=subject, html=html, attachments=attachments,
        detail={"start_at": booking.start_at.isoformat(), "calendar_ref": calendar_ref},
    )


async def notify_booking_reminder(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    booking_url: str,
    deadline_text: str,
) -> dict:
    """Thư NHẮC ứng viên chọn giờ khi liên kết sắp hết hạn (SCH-3 · FR-BOOK-3). DÙNG LẠI link cũ."""
    subject, html = booking_reminder_email(
        candidate_name, job_title, booking_url=booking_url, deadline_text=deadline_text
    )
    return await _dispatch(
        session, application_id=application_id, mode="booking_reminder",
        applicant_email=applicant_email, subject=subject, html=html,
    )


async def notify_booking_cancelled(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    start_at: datetime,
    end_at: datetime | None = None,
    booking_id: int | None = None,
    rebook_url: str | None = None,
    by_hr: bool = False,
) -> dict:
    """Thư báo buổi phỏng vấn ĐÃ HUỶ + `.ics` **METHOD:CANCEL** (SCH-3 · FR-BOOK-4).

    `rebook_url` chỉ được truyền khi liên kết CŨ còn hạn và hồ sơ thật sự quay lại `AWAITING_BOOKING`
    — hứa một đường chọn lại không tồn tại là đúng lớp "trạng thái nói dối" dự án này tránh.

    Tệp huỷ là thứ GỠ buổi phỏng vấn khỏi ứng dụng lịch của ứng viên (họ đã thêm nó từ thư xác nhận
    hoặc thư nhắc). Bỏ nó đi thì lịch của họ vẫn báo một buổi ở khung giờ đã nhả cho người khác.
    Sinh tệp hỏng KHÔNG được chặn thư huỷ: biết mình bị huỷ quan trọng hơn tệp đính kèm.
    """
    subject, html = booking_cancelled_email(
        candidate_name, job_title, start_at=start_at, rebook_url=rebook_url, by_hr=by_hr
    )
    attachments: Attachments | None = None
    if booking_id is not None and end_at is not None:
        try:
            # Dựng một hàng TẠM (không `add()` vào session) thay vì truyền object ORM thật: mọi
            # caller đều đã đóng transaction trước khi tới đây, nên chạm thuộc tính của hàng thật sẽ
            # nạp lười trên một session đã rollback — đúng bẫy `refresh()`/expire của SCH-2.
            stub = InterviewBooking(
                id=booking_id, application_id=application_id, start_at=start_at, end_at=end_at,
            )
            event = await get_calendar_provider().cancel_event(
                stub, summary=f"Phỏng vấn — {job_title}"
            )
            if event is not None and event.ics:
                attachments = [("huy-phong-van.ics", event.ics, _ICS_MIME)]
        except Exception:  # noqa: BLE001 — thiếu tệp huỷ còn hơn thiếu thư huỷ
            logger.warning("[scheduler] app=%s: không sinh được .ics huỷ", application_id)

    return await _dispatch(
        session, application_id=application_id, mode="booking_cancelled",
        applicant_email=applicant_email, subject=subject, html=html, attachments=attachments,
        detail={"start_at": start_at.isoformat(), "by_hr": by_hr, "can_rebook": bool(rebook_url)},
    )


def scheduler_node(state: RecruitmentState) -> dict:
    # 08d — nhánh AUTO-MỜI (reachable qua route_after_screener khi ca sạch + JD auto_invite BẬT). MARKER
    # thuần: đặt SCHEDULING = "đã quyết mời, chờ gửi thư" (KHÔNG phải INTERVIEW_SCHEDULED — thư mời chưa
    # gửi). Node KHÔNG có DB session → KHÔNG gửi email ở đây; điểm phát email DUY NHẤT là
    # scheduler.notify_decision("invite") gọi ở background.resume_screener SAU graph (đối xứng gate node
    # 03c). INTERVIEW_SCHEDULED chỉ đặt khi thư mời ĐÃ gửi (tránh "trạng thái nói dối" — plan §3.2).
    return {
        "status": ApplicationStatus.SCHEDULING.value,
        "messages": ["[scheduler] auto-mời: SCHEDULING → background gửi thư mời (notify_decision invite)"],
    }
