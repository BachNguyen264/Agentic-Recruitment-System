"""Base ORM + mixin dùng chung."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base  # re-export: mọi model kế thừa Base này

__all__ = ["Base", "TimestampMixin"]


class TimestampMixin:
    """Thêm created_at / updated_at (timezone-aware) cho model."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
