"""Routes Application — POST (nộp CV, multipart) / GET (đọc). PRD §8.2–§8.3.

Nộp CV = upload file (PDF/DOCX) + email + job_id → lưu file local, tạo Application SUBMITTED,
đẩy vào pipeline bất đồng bộ (parser THẬT; ranker/screener/scheduler vẫn stub).
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DBSession
from app.schemas.application import ApplicationCreate, ApplicationRead, ReviewRequest
from app.services import application_service
from app.services import review as review_service
from app.tasks.background import process_application
from app.tools import cv_storage

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    session: DBSession,
    background_tasks: BackgroundTasks,
    applicant_email: str = Form(...),
    job_id: int | None = Form(None),
    file: UploadFile = File(...),
) -> ApplicationRead:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in cv_storage.ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Chỉ nhận CV định dạng .pdf hoặc .docx")

    try:
        data = ApplicationCreate(job_id=job_id, applicant_email=applicant_email)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Email không hợp lệ") from None

    content = await file.read()
    app_row = await application_service.create_application(session, data)
    # cv_file_ref cần application_id -> lưu file SAU khi có id, rồi cập nhật.
    app_row.cv_file_ref = cv_storage.save_cv(app_row.id, file.filename or "", content)
    await session.commit()
    await session.refresh(app_row)

    # PRD §8.3: đẩy vào xử lý bất đồng bộ (chạy SAU response). Mỗi CV một pipeline độc lập.
    background_tasks.add_task(process_application, app_row.id)
    return ApplicationRead.model_validate(app_row)


@router.get("", response_model=list[ApplicationRead])
async def list_applications(session: DBSession) -> list[ApplicationRead]:
    rows = await application_service.list_applications(session)
    return [ApplicationRead.model_validate(r) for r in rows]


@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: DBSession) -> ApplicationRead:
    app_row = await application_service.get_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    return ApplicationRead.model_validate(app_row)


@router.post(
    "/{application_id}/review",
    response_model=ApplicationRead,
    summary="HR duyệt/từ chối ca PENDING_REVIEW (PRD §11)",
)
async def review_application(
    application_id: int, payload: ReviewRequest, session: DBSession
) -> ApplicationRead:
    """MUTATION: chỉ ca PENDING_REVIEW mới quyết được (else 409). Delegate scheduler (stub log)."""
    try:
        app_row = await review_service.review_decision(
            session, application_id, payload.decision, payload.note
        )
    except review_service.ApplicationNotFound:
        raise HTTPException(status_code=404, detail="Application không tồn tại") from None
    except review_service.InvalidReviewState as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return ApplicationRead.model_validate(app_row)
