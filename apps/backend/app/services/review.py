"""review — human_review THẬT (PRD §11, §13). Quyết định HR: duyệt/từ chối một ca PENDING_REVIEW.

Luồng (03b): validate trạng thái → chuyển trạng thái → ghi audit_log (FR-HR-5) → delegate
`scheduler` (điểm thực thi DUY NHẤT, stub log — KHÔNG email thật, lát 04). KHÔNG route qua
screener, KHÔNG checkpointer. `recommendation` chỉ là gợi ý hiển thị (KHÔNG tự quyết).
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes import scheduler
from app.core.config import settings
from app.models.application import Application, ApplicationStatus
from app.services import audit_service

Recommendation = Literal["invite", "consider_reject", "review_carefully"]
ReviewDecision = Literal["approve", "reject"]


class ApplicationNotFound(Exception):
    """Application id không tồn tại (route → 404)."""


class InvalidReviewState(Exception):
    """Application không ở PENDING_REVIEW nên không quyết được (route → 409)."""


def recommendation(score: float | None, flags: list | None) -> Recommendation:
    """Gợi ý hiển thị cho HR (KHÔNG tự quyết): cờ bất định → xem kỹ; else theo ngưỡng đạt."""
    if flags:
        return "review_carefully"
    if score is None:
        return "review_carefully"
    return "invite" if score >= settings.score_pass_threshold else "consider_reject"


async def review_decision(
    session: AsyncSession, application_id: int, decision: ReviewDecision, note: str | None
) -> Application:
    """HR duyệt/từ chối một ca. Chỉ ca PENDING_REVIEW mới quyết được (else InvalidReviewState)."""
    app_row = await session.get(Application, application_id)
    if app_row is None:
        raise ApplicationNotFound(f"Application {application_id} không tồn tại.")
    if app_row.status != ApplicationStatus.PENDING_REVIEW.value:
        raise InvalidReviewState(
            f"Application {application_id} không ở PENDING_REVIEW (hiện: {app_row.status})."
        )

    mode: Literal["invite", "reject"] = "invite" if decision == "approve" else "reject"
    app_row.status = (
        ApplicationStatus.INTERVIEW_SCHEDULED.value
        if decision == "approve"
        else ApplicationStatus.REJECTED.value
    )

    # Bản ghi quyết định HR (FR-HR-5) + bản ghi delegate scheduler — cùng transaction.
    await audit_service.record(
        session, application_id=application_id, node="human_review", action=decision,
        detail={"note": note, "decided_by": "hr", "mode": mode}, commit=False,
    )
    await audit_service.record(
        session, application_id=application_id, node="scheduler", action=f"delegate:{mode}",
        detail={"email_sent": False, "stub": True}, commit=False,
    )
    await session.commit()

    # Delegate SAU khi quyết định đã lưu — scheduler là điểm gửi email DUY NHẤT (stub log lát 03b).
    scheduler.notify_decision(mode, application_id=application_id, applicant_email=app_row.applicant_email)
    await session.refresh(app_row)
    return app_row
