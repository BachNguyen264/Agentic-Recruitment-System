"""application_service — CRUD tối thiểu cho Application (scaffold)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.application import DASHBOARD_ACTIVE_STATUSES, Application, ApplicationStatus
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
    # KHÔNG `refresh()` — nó là NGUYÊN NHÂN GỐC của một nút thắt đo được trên prod, không phải một
    # dòng vô hại. `commit()` NHẢ connection; `refresh()` ngay sau đó autobegin một transaction MỚI
    # và MƯỢN LẠI connection, giữ tới lần commit kế tiếp — mà ở `routes/public.py` lần commit kế
    # tiếp nằm SAU lượt upload CV lên R2 (qua mạng). Hệ quả đo được: 20 lượt nộp đồng thời trên prod
    # làm cạn SẠCH pool 15 connection, độ trễ nhận p50 = 13.4s.
    # An toàn bỏ vì `AsyncSessionLocal` đặt `expire_on_commit=False` (core/database.py) ⇒ sau commit
    # các thuộc tính KHÔNG bị hết hạn, và `id` đã được điền từ RETURNING lúc INSERT flush.
    return app_row


async def get_application(session: AsyncSession, application_id: int) -> Application | None:
    return await session.get(Application, application_id)


async def list_applications(session: AsyncSession, *, limit: int = 100) -> list[Application]:
    result = await session.execute(
        select(Application).order_by(Application.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


async def status_counts(session: AsyncSession) -> dict[str, int]:
    """Đếm hồ sơ theo trạng thái — MỘT câu `GROUP BY`, đọc TOÀN BẢNG.

    Đây là lý do endpoint pipeline không dựng trên `list_applications`: hàm đó có `limit=100`, nên
    dashboard đang đếm trong 100 bản ghi mới nhất chứ không phải cả hệ thống — vượt 100 hồ sơ là mọi
    ô chỉ số nói sai (vd "Đã từ chối" đứng yên). Câu này trả về ĐỦ mọi trạng thái của PRD §13, kể cả
    trạng thái đang có 0 hồ sơ, để client không phải đoán khoá nào tồn tại.
    """
    counts = {s.value: 0 for s in ApplicationStatus}
    rows = await session.execute(
        select(Application.status, func.count()).group_by(Application.status)
    )
    for status, total in rows:
        # Trạng thái lạ (dữ liệu cũ / PRD đổi mà chưa migrate) vẫn hiện ra thay vì bị nuốt.
        counts[status] = int(total)
    return counts


async def active_applications(session: AsyncSession, *, limit: int = 6) -> list[Application]:
    """Vài hồ sơ ĐANG CHẠY gần nhất cho panel "Đang chạy trực tiếp" (PRD §12.1 FR-HR-DASH-1).

    Dùng `DASHBOARD_ACTIVE_STATUSES` — KHÔNG phải `IN_FLIGHT_STATUSES`. Xem chú thích ở
    `models/application.py`: hai tập cố ý khác nhau và trộn chúng là lỗi an toàn, không phải lỗi
    hiển thị.
    """
    result = await session.execute(
        select(Application)
        .where(Application.status.in_(DASHBOARD_ACTIVE_STATUSES))
        .order_by(Application.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
