"""audit_service — ghi AuditLog (PRD §16, NFR-3, FR-PIPE-4).

Mọi bước agent + quyết định HR phải ghi audit. Ở scaffold, node/tasks gọi hàm này để ghi vết.
"""

from __future__ import annotations

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
