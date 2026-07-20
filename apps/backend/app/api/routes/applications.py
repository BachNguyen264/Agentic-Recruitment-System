"""Routes Application — POST (nộp CV, multipart) / GET (đọc). PRD §8.2–§8.3.

Nộp CV = upload file (PDF/DOCX) + email + job_id → lưu file local, tạo Application SUBMITTED,
đẩy vào pipeline bất đồng bộ (parser THẬT; ranker/screener/scheduler vẫn stub).
"""

from __future__ import annotations

from pathlib import PurePosixPath

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Response, UploadFile, status
from pydantic import ValidationError

from app.api.deps import DBSession
from app.core.logging import get_logger
from app.schemas.application import ApplicationCreate, ApplicationRead, ReviewRequest
from app.schemas.audit import AuditEntryRead
from app.services import application_service, audit_service, screening
from app.services import review as review_service
from app.services.storage import (
    StorageError,
    StorageNotFound,
    build_cv_key,
    content_type_for,
    get_storage,
)
from app.tasks.background import process_application
from app.tools import cv_storage

logger = get_logger("app.api.applications")

router = APIRouter(prefix="/applications", tags=["applications"])


@router.post("", response_model=ApplicationRead, status_code=status.HTTP_201_CREATED)
async def create_application(
    session: DBSession,
    background_tasks: BackgroundTasks,
    applicant_email: str = Form(...),
    job_id: int | None = Form(None),
    file: UploadFile = File(...),
) -> ApplicationRead:
    try:
        data = ApplicationCreate(job_id=job_id, applicant_email=applicant_email)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Email không hợp lệ") from None

    # Slice 06: dùng CHUNG validate_cv với đường nộp công khai (trước đây chỉ kiểm đuôi → bytes
    # không giới hạn/không đúng loại vẫn ghi được; nay đẩy lên object storage nên phải chặn ở đây).
    content = await file.read()
    try:
        cv_storage.validate_cv(file.filename or "", content)
    except cv_storage.InvalidCV as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None

    app_row = await application_service.create_application(session, data)
    # cv_file_ref cần application_id -> lưu file SAU khi có id, rồi cập nhật. Lưu QUA SEAM storage.
    key = build_cv_key(app_row.id, file.filename or "")
    try:
        await get_storage().save(key, content, content_type_for(file.filename or ""))
    except StorageError as exc:
        # Xem public.py: hồ sơ có cv_file_ref rỗng sẽ khiến parser chạy nhánh STUB → "parse thành
        # công" giả. Thà xóa hồ sơ + báo lỗi còn hơn để dữ liệu nói dối.
        logger.error("Upload CV (HR): lưu storage thất bại (app=%s, key=%s): %s", app_row.id, key, exc)
        await session.delete(app_row)
        await session.commit()
        raise HTTPException(status_code=503, detail="Lỗi lưu trữ file CV. Vui lòng thử lại.") from None
    app_row.cv_file_ref = key
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
    # Chi tiết: kèm câu trả lời sàng lọc (nếu có) cho HR (PRD §7.3, §11).
    answers = await screening.latest_answers(session, application_id)
    return ApplicationRead.model_validate(app_row).model_copy(update={"screener_answers": answers})


@router.get(
    "/{application_id}/audit",
    response_model=list[AuditEntryRead],
    summary="Nhật ký kiểm toán của hồ sơ — agent trace THẬT (PRD §16)",
)
async def get_application_audit(
    application_id: int, session: DBSession
) -> list[AuditEntryRead]:
    """Trả các bước đã ghi vào `audit_log`, cũ → mới.

    Đây là nguồn cho "Agent trace" ở màn chi tiết: mốc thời gian + node + hành động THẬT do pipeline
    ghi lại, thay cho việc suy đoán trạng thái node từ dữ liệu hồ sơ. Chỉ đọc (append-only).
    404 khi hồ sơ không tồn tại — phân biệt với hồ sơ CÓ THẬT nhưng chưa có bước nào (trả []).
    """
    app_row = await application_service.get_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    rows = await audit_service.list_for_application(session, application_id)
    return [AuditEntryRead.model_validate(r) for r in rows]


@router.get(
    "/{application_id}/cv",
    summary="HR tải CV gốc — STREAM qua storage (KHÔNG public URL; PRD NFR-4)",
    response_class=Response,
)
async def download_cv(application_id: int, session: DBSession) -> Response:
    """Trả bytes CV gốc cho HR.

    BẢO MẬT (NFR-4 — CV là dữ liệu cá nhân): endpoint này nằm trong router HR nên đã có
    `require_hr` (slice 09) — CHƯA ĐĂNG NHẬP → 401. File được STREAM qua `storage.get()`, KHÔNG
    bao giờ phát public URL và bucket R2 giữ PRIVATE, nên mọi lượt tải đều đi qua kiểm đăng nhập.
    """
    app_row = await application_service.get_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    if not app_row.cv_file_ref:
        raise HTTPException(status_code=404, detail="Hồ sơ này không có file CV.")

    try:
        data = await get_storage().get(app_row.cv_file_ref)
    except StorageNotFound:
        raise HTTPException(status_code=404, detail="File CV không còn trong kho lưu trữ.") from None
    except StorageError as exc:
        # Gồm cả cv_file_ref ĐỊNH DẠNG CŨ (path tuyệt đối, trước slice 06) → key không hợp lệ.
        # Chi tiết (có KEY/bucket) chỉ vào LOG — không trả ra response (đã cố ý bỏ cv_file_ref khỏi
        # API thì cũng không được rò qua thông báo lỗi).
        logger.error("Tải CV: lỗi storage (app=%s): %s", application_id, exc)
        raise HTTPException(status_code=502, detail="Không lấy được file CV từ kho lưu trữ.") from None

    # Tên tải về suy từ id + đuôi của key — KHÔNG lộ key/bucket, không kèm tên gốc (PII).
    suffix = PurePosixPath(app_row.cv_file_ref).suffix.lower()
    filename = f"CV-{application_id}{suffix}"
    return Response(
        content=data,
        media_type=content_type_for(app_row.cv_file_ref),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
