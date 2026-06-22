"""AuditLog — nhật ký kiểm toán mọi bước agent + quyết định HR (PRD §16, NFR-3, FR-PIPE-4).

Append-only: chỉ có created_at (không updated_at). Đủ cột để truy vết: node, action, confidence,
uncertainty_flags, escalation_reason, detail.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.application import Application


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True, index=True
    )
    node: Mapped[str] = mapped_column(String(64))        # parser | ranker | screener | scheduler | human_review | system
    action: Mapped[str] = mapped_column(String(128))     # ví dụ: "stub_pass_through", "route:human_review"
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_flags: Mapped[list] = mapped_column(JSONB, default=list)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    application: Mapped[Application | None] = relationship(back_populates="audit_logs")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AuditLog id={self.id} app={self.application_id} node={self.node} action={self.action!r}>"
