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
from app.services import audit_service, email_service
from app.services.email_templates import (
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
) -> dict:
    """Điểm phát email DUY NHẤT tới ứng viên (PRD §7.4). Gửi thư MỜI/TỪ CHỐI THẬT qua Resend.

    Template CỐ ĐỊNH (không LLM). Lỗi gửi → log + audit ``email_failed``, KHÔNG raise: quyết định HR
    (đã commit ở review 03b) VẪN giữ. Calendar hoãn (lát sau). Đừng gọi send_email ở node khác.
    """
    builder = invite_email if mode == "invite" else rejection_email
    subject, html = builder(candidate_name, job_title)

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
