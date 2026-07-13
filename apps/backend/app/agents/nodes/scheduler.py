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
from app.services.email_templates import invite_email, rejection_email

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


def scheduler_node(state: RecruitmentState) -> dict:
    # STUB & hiện KHÔNG reachable từ routing (route_after_ranker không trả "screener" — BUG A fix):
    # thư MỜI THẬT + INTERVIEW_SCHEDULED CHỈ đặt qua human_review → scheduler.notify_decision("invite")
    # (03b/04). Node này KHÔNG tự đặt INTERVIEW_SCHEDULED (tránh trạng thái "đã hẹn" câm không có email).
    # TODO (PRD §9, 08d): cổng auto-mời — nhánh auto_invite BẬT gọi notify_decision("invite") ở đây.
    return {
        "status": ApplicationStatus.SCHEDULING.value,
        "result": {"action": "scheduler_stub", "note": "chưa gửi mời — mời thật qua human_review"},
        "messages": ["[scheduler] stub (chưa reachable) — mời thật đi qua human_review→notify_decision"],
    }
