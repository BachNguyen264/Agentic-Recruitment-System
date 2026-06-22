"""scheduler node — STUB (PRD §7.4).

Thật: điểm thực thi DUY NHẤT mọi email tới ứng viên. Mời -> gửi thư mời + tạo Google Calendar +
nhắc lịch. Từ chối -> gửi thư từ chối. (CLAUDE.md: KHÔNG gửi email rải rác ở node khác.)

Scaffold: pass-through, KHÔNG gửi email/tạo lịch thật.
"""

from __future__ import annotations

from app.agents.state import RecruitmentState
from app.models.application import ApplicationStatus


def scheduler_node(state: RecruitmentState) -> dict:
    # TODO (PRD §7.4): chọn gửi email / tạo lịch / cả hai (function calling — phase sau).
    return {
        "status": ApplicationStatus.INTERVIEW_SCHEDULED.value,
        "result": {"action": "invite_sent", "note": "stub — chưa gửi email/đặt lịch thật"},
        "messages": ["[scheduler] stub: gửi thư mời + đặt lịch (chưa thật — PRD §7.4)"],
    }
