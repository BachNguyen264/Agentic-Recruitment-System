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
from app.models.job_posting import JobPosting
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

    # Gom dữ liệu email TRƯỚC commit (sau commit thuộc tính có thể expire → tránh lazy-load).
    applicant_email = app_row.applicant_email
    candidate_name = (app_row.parsed_data or {}).get("full_name") or "Ứng viên"
    job = await session.get(JobPosting, app_row.job_id) if app_row.job_id else None
    job_title = job.title if job else "vị trí ứng tuyển"

    # Bản ghi quyết định HR (FR-HR-5). Bản ghi kết quả email (email_sent/email_failed) do
    # scheduler.notify_decision ghi (điểm phát email DUY NHẤT).
    await audit_service.record(
        session, application_id=application_id, node="human_review", action=decision,
        detail={"note": note, "decided_by": "hr", "mode": mode}, commit=False,
    )
    await session.commit()

    # Delegate SAU khi quyết định đã lưu — scheduler gửi email THẬT (PRD §7.4). Email lỗi KHÔNG
    # làm sập: notify_decision nuốt lỗi + audit email_failed, quyết định/trạng thái vẫn giữ.
    await scheduler.notify_decision(
        session, mode, application_id=application_id, applicant_email=applicant_email,
        candidate_name=candidate_name, job_title=job_title,
    )
    await session.refresh(app_row)
    return app_row
