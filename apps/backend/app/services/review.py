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
from app.services import audit_service, booking_flow, booking_service

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

    # Gom dữ liệu email TRƯỚC commit (sau commit thuộc tính có thể expire → tránh lazy-load).
    applicant_email = app_row.applicant_email
    job = await session.get(JobPosting, app_row.job_id) if app_row.job_id else None
    job_title = job.title if job else "vị trí ứng tuyển"

    # Bản ghi quyết định HR (FR-HR-5). Bản ghi kết quả email (email_sent/email_failed) do
    # scheduler.notify_decision ghi (điểm phát email DUY NHẤT).
    await audit_service.record(
        session, application_id=application_id, node="human_review", action=decision,
        detail={"note": note, "decided_by": "hr", "mode": mode}, commit=False,
    )

    if decision == "approve":
        # SCH-2: HR duyệt KHÔNG còn ra thẳng INTERVIEW_SCHEDULED — ứng viên phải tự chọn giờ trước
        # (PRD §10b). Trạng thái GIỮ NGUYÊN PENDING_REVIEW cho tới khi thư mời gửi được: nếu tiến
        # trình chết giữa chừng, ca vẫn nằm trong hàng chờ để HR bấm lại. Đặt một trạng thái trung
        # gian ở đây sẽ làm ca biến mất khỏi hàng chờ mà chẳng ai gửi thư.
        await session.commit()
        await booking_flow.dispatch_booking_invite(
            session, app_row, applicant_email=applicant_email,
            job_title=job_title, audit_node="human_review",
        )
        await session.refresh(app_row)
        return app_row

    # Nhánh TỪ CHỐI — GIỮ NGUYÊN như 03b: quyết định lưu trước, email sau. Email lỗi KHÔNG làm sập
    # (notify_decision nuốt lỗi + audit email_failed), quyết định/trạng thái vẫn giữ.
    app_row.status = ApplicationStatus.REJECTED.value
    # SCH-2: huỷ mọi liên kết đặt lịch còn sống TRONG CÙNG transaction. Nếu không, một ứng viên đã
    # từng được mời rồi bị HR từ chối vẫn mở được link cũ, tự đặt lịch, và xuất hiện trên lịch phỏng
    # vấn của HR — quyết định của con người bị một token cũ lật ngược.
    await booking_service.cancel_sessions(session, application_id)
    await session.commit()
    await scheduler.notify_decision(
        session, mode, application_id=application_id, applicant_email=applicant_email,
        job_title=job_title,
    )
    await session.refresh(app_row)
    return app_row
