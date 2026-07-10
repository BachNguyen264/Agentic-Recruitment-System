"""scheduler node — STUB (PRD §7.4).

Thật: điểm thực thi DUY NHẤT mọi email tới ứng viên. Mời -> gửi thư mời + tạo Google Calendar +
nhắc lịch. Từ chối -> gửi thư từ chối. (CLAUDE.md: KHÔNG gửi email rải rác ở node khác.)

Scaffold: pass-through, KHÔNG gửi email/tạo lịch thật.
"""

from __future__ import annotations

from typing import Literal

from app.agents.state import RecruitmentState
from app.core.logging import get_logger
from app.models.application import ApplicationStatus

logger = get_logger("app.agents.scheduler")


def notify_decision(
    mode: Literal["invite", "reject"], *, application_id: int, applicant_email: str
) -> dict:
    """Điểm delegate DUY NHẤT cho email tới ứng viên (PRD §7.4). STUB lát 03b: chỉ GHI LOG ý định.

    Lát 04 sẽ thay log này bằng gửi email/tạo lịch thật — KHÔNG cần sửa luồng review.
    """
    if mode == "invite":
        logger.info(
            "[scheduler] app=%s: SẼ gửi THƯ MỜI + tạo lịch phỏng vấn cho %s (stub — chưa gửi thật)",
            application_id, applicant_email,
        )
    else:
        logger.info(
            "[scheduler] app=%s: SẼ gửi THƯ TỪ CHỐI cho %s (stub — chưa gửi thật)",
            application_id, applicant_email,
        )
    return {"mode": mode, "email_sent": False}


def scheduler_node(state: RecruitmentState) -> dict:
    # TODO (PRD §7.4): chọn gửi email / tạo lịch / cả hai (function calling — phase sau).
    return {
        "status": ApplicationStatus.INTERVIEW_SCHEDULED.value,
        "result": {"action": "invite_sent", "note": "stub — chưa gửi email/đặt lịch thật"},
        "messages": ["[scheduler] stub: gửi thư mời + đặt lịch (chưa thật — PRD §7.4)"],
    }
