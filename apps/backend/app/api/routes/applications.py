"""Routes Application — POST (nộp CV, multipart) / GET (đọc). PRD §8.2–§8.3.

Nộp CV = upload file (PDF/DOCX) + email + job_id → lưu file local, tạo Application SUBMITTED,
đẩy vào pipeline bất đồng bộ (parser THẬT; ranker/screener/scheduler vẫn stub).
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import DBSession
from app.core.logging import get_logger
from app.models.email_delivery import DeliveryStatus, EmailDelivery
from app.schemas.application import (
    ApplicationCreate,
    ApplicationRead,
    BookedInterview,
    PipelineItem,
    PipelineSnapshot,
    ReviewRequest,
)
from app.services import application_service, booking_flow, booking_service, screening
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


@router.get(
    "",
    response_model=list[ApplicationRead],
    # Danh sách KHÔNG chở `parsed_data` + `score_breakdown` (~80% bytes mỗi dòng đã chấm điểm, đo
    # thật trên prod: 2.984 B/dòng). `packages/shared-types` VỐN ĐÃ khai `ApplicationListItem` không
    # có hai trường này — đây là sửa API cho khớp hợp đồng frontend vốn đã tuyên bố, không phải cắt
    # tính năng. Ai cần chúng thì gọi `GET /applications/{id}` (đúng chỗ của trường nặng).
    #
    # ⚠ BẮT BUỘC dạng `{"__all__": {...}}`. Viết set PHẲNG `{"parsed_data", ...}` trên một
    # `response_model=list[...]` là NO-OP IM LẶNG: Pydantic v2 hiểu set phẳng trên sequence là CHỈ SỐ
    # phần tử và bỏ qua key chuỗi — endpoint vẫn trả đủ trường mà không có lỗi nào.
    response_model_exclude={"__all__": {"parsed_data", "score_breakdown"}},
)
async def list_applications(
    session: DBSession,
    # Tên tham số là `statuses` nhưng query string là `?status=` (alias): đặt tên biến `status` ở đây
    # sẽ CHE module `fastapi.status` vốn đang được dùng trong chính file này.
    statuses: Annotated[
        list[str] | None,
        Query(alias="status", description="Lọc theo trạng thái (lặp lại để chọn nhiều)"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ApplicationRead]:
    """Một TRANG hồ sơ (mới nhất trước). Tổng số lấy từ `GET /applications/pipeline` `counts`.

    `le=200` KHÔNG phải trang trí: router HR không nằm trong bất kỳ xô rate-limit nào
    (`core/hardening.py` chỉ bọc login / ghi công khai / health sâu), nên `?limit=100000` sẽ tuần tự
    hoá cả bảng trong một request. Mặc định giữ 100 vì `scripts/loadtest_apply.py` ghim
    `WINDOW_LIMIT = 100` để đối soát — đổi mặc định là làm script báo sai mà không kêu.
    """
    rows = await application_service.list_applications(
        session, statuses=statuses, limit=limit, offset=offset
    )
    # MỘT truy vấn cho cả trang (không phải mỗi dòng một truy vấn): hồ sơ nào đã chạm cảnh hết
    # khung giờ thì dashboard phải nói đúng là LỊCH đang chặn, không phải ứng viên chậm (SCH-3).
    no_slots = await booking_service.no_slot_application_ids(session)
    return [
        ApplicationRead.model_validate(r).model_copy(
            update={"booking_no_slots": r.id in no_slots}
        )
        for r in rows
    ]


@router.get("/pipeline", response_model=PipelineSnapshot)
async def get_pipeline(session: DBSession) -> PipelineSnapshot:
    """Ảnh chụp pipeline cho bảng điều hành — HAI câu SQL, payload cỡ CỐ ĐỊNH (PRD §12.1).

    ⚠ PHẢI khai TRƯỚC `GET /{application_id}`: FastAPI khớp route theo THỨ TỰ khai báo, nên nếu
    đứng sau thì `/pipeline` rơi vào tay handler kia và chết 422 ("pipeline" không parse ra int).

    Đây là đường bảng điều hành hỏi lại DỒN NHẤT (2 giây một lượt khi có tác tử đang chạy). Trước
    đó nó gọi `GET /api/applications` mỗi 5 giây — trả về TOÀN BỘ hồ sơ kèm `parsed_data`, tức
    payload phình theo số ứng viên trong khi thứ cần vẽ chỉ là 11 con số. (Badge "Hàng đợi review"
    ở `(hr)/layout` VẪN đi đường cũ đó mỗi 5s trên MỌI trang HR — nên đây chưa phải đường duy nhất
    chạy theo nhịp.) Ở đây `counts` đếm bằng `GROUP BY` trên toàn bảng (chính xác hơn đường cũ, vốn
    đếm trong `limit=100` bản ghi mới nhất) và `active` bị chặn cứng 6 dòng.
    """
    return PipelineSnapshot(
        counts=await application_service.status_counts(session),
        active=[
            PipelineItem.model_validate(r)
            for r in await application_service.active_applications(session, limit=6)
        ],
    )


@router.get("/{application_id}", response_model=ApplicationRead)
async def get_application(application_id: int, session: DBSession) -> ApplicationRead:
    app_row = await application_service.get_application(session, application_id)
    if app_row is None:
        raise HTTPException(status_code=404, detail="Application không tồn tại")
    # Chi tiết: kèm câu trả lời sàng lọc + lịch phỏng vấn đã chốt (nếu có) cho HR (PRD §7.3, §10b, §11).
    answers = await screening.latest_answers(session, application_id)
    booking = await booking_service.latest_booking(session, application_id)
    no_slots = await booking_service.no_slot_application_ids(session)
    return ApplicationRead.model_validate(app_row).model_copy(
        update={
            "screener_answers": answers,
            "interview": BookedInterview.model_validate(booking) if booking else None,
            "booking_no_slots": application_id in no_slots,
            # Đã từng được mời chưa — quyết định UI có hiện nút "Gửi lại link đặt lịch" hay không.
            # Hỏi ĐÚNG câu mà `resend_booking_link` hỏi, để nút chỉ xuất hiện khi nó bấm được.
            "has_booking_link": await booking_service.has_any_session(session, application_id),
            # EMAIL-1: lý do bounce/complaint GẦN NHẤT — hai truy vấn RIÊNG theo ĐÚNG status, không
            # gộp chung (xem `_latest_reason`), để HR không đọc nhầm lý do complaint thành lý do bounce.
            "email_bounce_reason": await _latest_reason(
                session, application_id, DeliveryStatus.BOUNCED.value
            ),
            "email_complaint_reason": await _latest_reason(
                session, application_id, DeliveryStatus.COMPLAINED.value
            ),
            "email_send_failure_reason": await _latest_reason(
                session, application_id, DeliveryStatus.FAILED.value
            ),
        }
    )


async def _latest_reason(session: AsyncSession, application_id: int, delivery_status: str) -> str | None:
    """Lý do GẦN NHẤT (`email_delivery.bounce_reason`) của MỘT loại sự kiện xấu cụ thể (bounce HOẶC
    complaint — KHÔNG gộp `status.in_([...])` cả hai vào một câu, vì lý do bounce lẫn với lý do
    complaint sẽ khiến HR đọc sai chuyện đang xảy ra). Cờ nói "có chuyện", câu này nói "chuyện gì".

    ⚠ Kiểu tham số là `AsyncSession`, KHÔNG phải `DBSession` — `DBSession` là alias
    `Annotated[..., Depends(...)]` chỉ có nghĩa ở chữ ký route handler.
    """
    return await session.scalar(
        select(EmailDelivery.bounce_reason)
        .where(
            EmailDelivery.application_id == application_id,
            EmailDelivery.status == delivery_status,
        )
        .order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
        .limit(1)
    )


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


@router.post(
    "/{application_id}/booking/cancel",
    response_model=ApplicationRead,
    summary="HR huỷ lịch phỏng vấn — nhả slot + báo ứng viên → PENDING_REVIEW (SCH-3, FR-BOOK-4)",
)
async def cancel_interview(application_id: int, session: DBSession) -> ApplicationRead:
    """Huỷ lịch đã chốt. Chỉ ca `INTERVIEW_SCHEDULED` mới huỷ được (else 409).

    Đây là NỬA ĐẦU của "đổi lịch": huỷ xong bấm tiếp **Gửi lại link** để ứng viên chọn giờ khác.
    Không có luồng dời-lịch một-chạm — hai bước tường minh thì HR luôn biết ca đang ở đâu.
    Chưa đăng nhập → 401 (`require_hr` áp cấp-router).
    """
    try:
        app_row = await booking_flow.cancel_by_hr(session, application_id)
    except booking_flow.BookingActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return ApplicationRead.model_validate(app_row)


@router.post(
    "/{application_id}/booking/resend",
    response_model=ApplicationRead,
    summary="HR gửi lại link đặt lịch — phiên MỚI (TTL mới) → AWAITING_BOOKING (SCH-3)",
)
async def resend_interview_link(application_id: int, session: DBSession) -> ApplicationRead:
    """Phát liên kết đặt lịch MỚI + gửi lại thư mời. Ca đang `INTERVIEW_SCHEDULED` → 409 (huỷ trước)."""
    try:
        app_row = await booking_flow.resend_booking_link(session, application_id)
    except booking_flow.BookingActionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return ApplicationRead.model_validate(app_row)
