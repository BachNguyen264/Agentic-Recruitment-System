"""audit_service — ghi AuditLog (PRD §16, NFR-3, FR-PIPE-4).

Mọi bước agent + quyết định HR phải ghi audit. Ở scaffold, node/tasks gọi hàm này để ghi vết.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog


async def record(
    session: AsyncSession,
    *,
    application_id: int | None,
    node: str,
    action: str,
    confidence: float | None = None,
    uncertainty_flags: list | None = None,
    escalation_reason: str | None = None,
    detail: dict | None = None,
    commit: bool = True,
) -> AuditLog:
    """Tạo một dòng audit_log. ``commit=False`` để gộp nhiều ghi trong một transaction."""
    entry = AuditLog(
        application_id=application_id,
        node=node,
        action=action,
        confidence=confidence,
        uncertainty_flags=uncertainty_flags or [],
        escalation_reason=escalation_reason,
        detail=detail or {},
    )
    session.add(entry)
    if commit:
        await session.commit()
        await session.refresh(entry)
    else:
        await session.flush()
    return entry


async def list_for_application(
    session: AsyncSession, application_id: int, *, limit: int = 200
) -> list[AuditLog]:
    """Nhật ký kiểm toán của MỘT hồ sơ, THEO THỨ TỰ THỜI GIAN (cũ → mới).

    Dùng cho màn chi tiết ứng viên: agent trace THẬT (mốc thời gian + từng bước node ghi lại),
    thay cho việc suy đoán trạng thái node từ dữ liệu hồ sơ.

    Sắp xếp theo (created_at, id): nhiều bước trong CÙNG một transaction chia sẻ một
    `server_default=now()` (now() cố định trong transaction) nên created_at TRÙNG NHAU — thiếu `id`
    thứ tự sẽ nhảy lung tung và trace đọc ra sai trình tự pipeline.
    """
    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.application_id == application_id)
        .order_by(AuditLog.created_at, AuditLog.id)
        .limit(limit)
    )
    return list(result.scalars().all())
