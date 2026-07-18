"""Routes CÔNG KHAI cho ứng viên guest (PRD §8.2, §12.2 FR-AP-1/2). KHÔNG auth.

BẢO MẬT: JD trả về dùng projection AN TOÀN (PublicJobRead — KHÔNG rubric/gate/screener); chỉ nhận JD
OPEN; validate loại/size/magic-bytes file ở SERVER. TÁI DÙNG logic tạo application + pipeline hiện có
(application_service + cv_storage + process_application) — KHÔNG viết lại pipeline.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DBSession
from app.schemas.application import ApplicationCreate, PublicSubmitResponse
from app.schemas.job_posting import PublicJobRead
from app.core.logging import get_logger
from app.schemas.screening import PublicScreeningRead, ScreeningSubmit, ScreeningSubmitResponse
from app.services import application_service, job_service, screening
from app.services.storage import StorageError, build_cv_key, content_type_for, get_storage
from app.tasks.background import process_application
from app.tools import cv_storage

logger = get_logger("app.api.public")

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/jobs", response_model=list[PublicJobRead], summary="JD đang mở (công khai)")
async def list_open_jobs(session: DBSession) -> list[PublicJobRead]:
    rows = await job_service.list_open_jobs(session)
    return [PublicJobRead.model_validate(r) for r in rows]


@router.get("/jobs/{job_id}", response_model=PublicJobRead, summary="Chi tiết JD đang mở (công khai)")
async def get_open_job(job_id: int, session: DBSession) -> PublicJobRead:
    job = await job_service.get_open_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vị trí không tồn tại hoặc đã đóng.")
    return PublicJobRead.model_validate(job)


@router.post(
    "/applications",
    response_model=PublicSubmitResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ứng viên nộp CV (guest) — gắn JD OPEN + validate file (PRD §8.2)",
)
async def submit_application(
    session: DBSession,
    background_tasks: BackgroundTasks,
    job_id: int = Form(...),
    applicant_email: str = Form(...),
    file: UploadFile = File(...),
) -> PublicSubmitResponse:
    # 1) JD phải tồn tại + OPEN (chống nộp vào JD đã đóng / job_id sai).
    job = await job_service.get_open_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Vị trí không tồn tại hoặc đã đóng.")

    # 2) Email hợp lệ (guest — chỉ cần email).
    try:
        data = ApplicationCreate(job_id=job_id, applicant_email=applicant_email)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Email không hợp lệ.") from None

    # 3) File: loại + size + MAGIC BYTES ở SERVER (không tin client/đuôi file).
    content = await file.read()
    try:
        cv_storage.validate_cv(file.filename or "", content)
    except cv_storage.InvalidCV as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    # 4) Tạo application gắn job_id + lưu file QUA SEAM STORAGE (local/R2 tùy config) + đẩy pipeline
    #    async (TÁI DÙNG luồng hiện có). cv_file_ref = KEY storage, KHÔNG phải path (slice 06).
    app_row = await application_service.create_application(session, data)
    key = build_cv_key(app_row.id, file.filename or "")
    try:
        await get_storage().save(key, content, content_type_for(file.filename or ""))
    except StorageError as exc:
        # Lưu file HỎNG (R2 sập/credentials sai) → KHÔNG để lại hồ sơ trỏ file rỗng: parser coi
        # cv_file_ref rỗng là "không có CV" và chạy nhánh STUB → hồ sơ trôi tiếp như đã parse THÀNH
        # CÔNG (confidence 1.0). Xóa hồ sơ vừa tạo + báo ứng viên thử lại.
        logger.error("Nộp CV: lưu storage thất bại (app=%s, key=%s): %s", app_row.id, key, exc)
        await session.delete(app_row)
        await session.commit()
        raise HTTPException(
            status_code=503, detail="Hệ thống đang lỗi lưu trữ hồ sơ. Vui lòng thử lại sau ít phút."
        ) from None
    app_row.cv_file_ref = key
    await session.commit()
    await session.refresh(app_row)
    background_tasks.add_task(process_application, app_row.id)

    # 5) Xác nhận gọn — KHÔNG trả điểm/parsed_data/trạng thái cho ứng viên.
    return PublicSubmitResponse(application_id=app_row.id)


@router.get(
    "/screening/{token}",
    response_model=PublicScreeningRead,
    summary="Câu hỏi sàng lọc theo magic-link (PRD §7.3, §10)",
)
async def get_screening(token: str, session: DBSession) -> PublicScreeningRead:
    """Validate token (tồn tại/chưa dùng/chưa hết hạn/AWAITING_SCREENER) → CHỈ tiêu đề JD + câu hỏi.
    Token sai→404, hết hạn→410, đã dùng/sai trạng thái→409. KHÔNG lộ rubric/gate/điểm/parsed_data."""
    try:
        job_title, questions = await screening.get_form(session, token)
    except screening.ScreeningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return PublicScreeningRead(job_title=job_title, questions=questions)


@router.post(
    "/screening/{token}",
    response_model=ScreeningSubmitResponse,
    summary="Nộp câu trả lời sàng lọc → resume pipeline (PRD §10 FR-SCR-2)",
)
async def submit_screening(
    token: str, payload: ScreeningSubmit, session: DBSession
) -> ScreeningSubmitResponse:
    """Row-lock + re-validate → resume pipeline BẰNG câu trả lời (thay endpoint dev 08a) → đánh dấu
    one-time. Trả xác nhận gọn (KHÔNG lộ điểm/trạng thái nội bộ)."""
    try:
        await screening.submit_answers(session, token, payload.answers)
    except screening.ScreeningError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return ScreeningSubmitResponse(
        status="submitted", message="Cảm ơn bạn! Câu trả lời đã được ghi nhận."
    )
