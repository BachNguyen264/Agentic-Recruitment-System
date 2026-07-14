"""Application (Candidate) — đơn vị chạy qua pipeline. PRD §16 + vòng đời §13.

Schema chừa sẵn chỗ cho 4 trụ cột (PRD §5: confidence/uncertainty_flags/escalation_reason)
và Screener async (PRD §10: screener_sent_at/screener_deadline). KHÔNG có logic thật ở scaffold.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.screening_session import ScreeningSession


class ApplicationStatus(str, enum.Enum):
    """Trạng thái CV — khớp state machine PRD §13. Lưu dạng String (linh hoạt khi PRD đổi)."""

    SUBMITTED = "SUBMITTED"
    PARSING = "PARSING"
    RANKING = "RANKING"
    SCREENING = "SCREENING"
    AWAITING_SCREENER = "AWAITING_SCREENER"
    REMINDED = "REMINDED"
    SCHEDULING = "SCHEDULING"
    PENDING_REVIEW = "PENDING_REVIEW"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    REJECTED = "REJECTED"


class Application(Base, TimestampMixin):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_posting.id", ondelete="SET NULL"), nullable=True, index=True
    )
    applicant_email: Mapped[str] = mapped_column(String(320), index=True)
    cv_file_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Kết quả Parser/Ranker (phase sau).
    parsed_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(
        String(32), default=ApplicationStatus.SUBMITTED.value, index=True
    )

    # ── Chừa chỗ 4 trụ cột (PRD §5 trụ cột 3 "an toàn trước case lạ") ──
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_flags: Mapped[list] = mapped_column(JSONB, default=list)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Chừa chỗ Screener async (PRD §10 suspend/resume) ──
    screener_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    screener_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True
    )
    screening_sessions: Mapped[list[ScreeningSession]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application id={self.id} email={self.applicant_email!r} status={self.status}>"
