"""application_service — CRUD tối thiểu cho Application (scaffold)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import Application, ApplicationStatus
from app.schemas.application import ApplicationCreate


async def create_application(session: AsyncSession, data: ApplicationCreate) -> Application:
    # cv_file_ref để None: route lưu file QUA SEAM storage rồi gán KEY (cần application_id trước).
    app_row = Application(
        job_id=data.job_id,
        applicant_email=str(data.applicant_email),
        status=ApplicationStatus.SUBMITTED.value,
    )
    session.add(app_row)
    await session.commit()
    await session.refresh(app_row)
    return app_row


async def get_application(session: AsyncSession, application_id: int) -> Application | None:
    return await session.get(Application, application_id)


async def list_applications(session: AsyncSession, *, limit: int = 100) -> list[Application]:
    result = await session.execute(
        select(Application).order_by(Application.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())
