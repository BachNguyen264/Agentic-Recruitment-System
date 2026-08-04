"""scheduler node — STUB (PRD §7.4).

Thật: điểm thực thi DUY NHẤT mọi email tới ứng viên. Mời -> gửi thư mời + tạo Google Calendar +
nhắc lịch. Từ chối -> gửi thư từ chối. (CLAUDE.md: KHÔNG gửi email rải rác ở node khác.)

Scaffold: pass-through, KHÔNG gửi email/tạo lịch thật.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import RecruitmentState
from app.core.logging import get_logger
from app.models.application import ApplicationStatus
from app.models.booking import InterviewBooking
from app.services import audit_service, email_service
from app.services.calendar import get_calendar_provider
from app.services.email_templates import (
    booking_confirmed_email,
    invite_email,
    rejection_email,
    screener_email,
    screener_reminder_email,
)

logger = get_logger("app.agents.scheduler")


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

    try:
        await email_service.send_email(to=applicant_email, subject=subject, html=html)
    except Exception as exc:  # noqa: BLE001 — nuốt có kiểm soát: email lỗi KHÔNG làm sập luồng
        logger.warning(
            "[scheduler] app=%s: GỬI EMAIL %s THẤT BẠI tới %s: %s",
            application_id, mode, applicant_email, exc,
        )
        await audit_service.record(
            session, application_id=application_id, node="scheduler", action="email_failed",
            detail={"mode": mode, "to": applicant_email, "error": str(exc)}, commit=True,
        )
        return {"mode": mode, "email_sent": False, "error": str(exc)}

    logger.info("[scheduler] app=%s: đã gửi email %s tới %s", application_id, mode, applicant_email)
    await audit_service.record(
        session, application_id=application_id, node="scheduler", action=f"email_sent:{mode}",
        detail={"mode": mode, "to": applicant_email}, commit=True,
    )
    return {"mode": mode, "email_sent": True}


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
    try:
        await email_service.send_email(to=applicant_email, subject=subject, html=html)
    except Exception as exc:  # noqa: BLE001 — nuốt có kiểm soát: email lỗi KHÔNG làm sập luồng
        logger.warning(
            "[scheduler] app=%s: GỬI EMAIL %s THẤT BẠI tới %s: %s",
            application_id, mode, applicant_email, exc,
        )
        await audit_service.record(
            session, application_id=application_id, node="scheduler", action="email_failed",
            detail={"mode": mode, "to": applicant_email, "error": str(exc)}, commit=True,
        )
        return {"mode": mode, "email_sent": False, "error": str(exc)}

    logger.info("[scheduler] app=%s: đã gửi email %s tới %s", application_id, mode, applicant_email)
    await audit_service.record(
        session, application_id=application_id, node="scheduler", action=f"email_sent:{mode}",
        detail={"mode": mode, "to": applicant_email}, commit=True,
    )
    return {"mode": mode, "email_sent": True}


async def notify_booking_confirmed(
    session: AsyncSession,
    *,
    application_id: int,
    applicant_email: str,
    candidate_name: str,
    job_title: str,
    booking: InterviewBooking,
) -> dict:
    """Thư XÁC NHẬN lịch phỏng vấn + đính kèm `.ics` (SCH-2 · PRD §10b.1, §12.4 FR-NOTI-1).

    Điểm phát email DUY NHẤT, như hai hàm trên. Tệp `.ics` đi qua seam `CalendarProvider` (SCH-1) —
    đổi sang Google Calendar sau này KHÔNG phải sửa chỗ này.

    Lỗi gửi (hoặc lỗi sinh `.ics`) → audit `email_failed` + trả `email_sent=False`, **KHÔNG raise**:
    khác 08d một cách CÓ CHỦ Ý — ở đây khung giờ đã BOOKED trong DB và ứng viên vừa thấy màn xác
    nhận trên web, nên thư chỉ là biên nhận. Huỷ lịch chỉ vì gửi thư hỏng mới là cái sai lớn.
    """
    subject, html = booking_confirmed_email(
        candidate_name, job_title, start_at=booking.start_at, end_at=booking.end_at
    )
    try:
        event = await get_calendar_provider().create_event(
            booking,
            summary=f"Phỏng vấn — {job_title}",
            description=f"Buổi phỏng vấn vị trí {job_title}.",
        )
        attachments = (
            [("phong-van.ics", event.ics, "text/calendar; charset=utf-8")] if event.ics else None
        )
        await email_service.send_email(
            to=applicant_email, subject=subject, html=html, attachments=attachments
        )
    except Exception as exc:  # noqa: BLE001 — nuốt có kiểm soát: lịch ĐÃ chốt, thư chỉ là biên nhận
        logger.warning(
            "[scheduler] app=%s: GỬI EMAIL xác nhận lịch THẤT BẠI tới %s: %s",
            application_id, applicant_email, exc,
        )
        await audit_service.record(
            session, application_id=application_id, node="scheduler", action="email_failed",
            detail={"mode": "booking_confirmed", "to": applicant_email, "error": str(exc)},
            commit=True,
        )
        return {"mode": "booking_confirmed", "email_sent": False, "error": str(exc)}

    logger.info(
        "[scheduler] app=%s: đã gửi thư xác nhận lịch (%s) tới %s",
        application_id, booking.start_at.isoformat(), applicant_email,
    )
    await audit_service.record(
        session, application_id=application_id, node="scheduler",
        action="email_sent:booking_confirmed",
        detail={"to": applicant_email, "start_at": booking.start_at.isoformat(),
                "calendar_ref": event.ref},
        commit=True,
    )
    return {"mode": "booking_confirmed", "email_sent": True, "calendar_ref": event.ref}


def scheduler_node(state: RecruitmentState) -> dict:
    # 08d — nhánh AUTO-MỜI (reachable qua route_after_screener khi ca sạch + JD auto_invite BẬT). MARKER
    # thuần: đặt SCHEDULING = "đã quyết mời, chờ gửi thư" (KHÔNG phải INTERVIEW_SCHEDULED — thư mời chưa
    # gửi). Node KHÔNG có DB session → KHÔNG gửi email ở đây; điểm phát email DUY NHẤT là
    # scheduler.notify_decision("invite") gọi ở background.resume_screener SAU graph (đối xứng gate node
    # 03c). INTERVIEW_SCHEDULED chỉ đặt khi thư mời ĐÃ gửi (tránh "trạng thái nói dối" — plan §3.2).
    return {
        "status": ApplicationStatus.SCHEDULING.value,
        "result": {"action": "auto_invite", "note": "quyết định mời — background gửi thư mời thật"},
        "messages": ["[scheduler] auto-mời: SCHEDULING → background gửi thư mời (notify_decision invite)"],
    }
