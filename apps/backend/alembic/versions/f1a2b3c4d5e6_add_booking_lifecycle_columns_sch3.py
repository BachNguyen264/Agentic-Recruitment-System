"""add reminder_sent_at + no_slots_at (SCH-3 vòng đời lịch)

Revision ID: f1a2b3c4d5e6
Revises: c7d8e9f0a1b2
Create Date: 2026-08-06

HAND-WRITTEN (KHÔNG autogenerate) — cùng lý do như c7d8e9f0a1b2: autogenerate nhìn thấy các bảng
checkpoint của LangGraph (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/`checkpoint_migrations`)
không có trong `Base.metadata` và sẽ đề xuất DROP chúng — mất suspend/resume 08a. `_include_object`
trong `alembic/env.py` đã chặn sẵn; migration viết tay thì không có cửa nào để lọt.

Hai cột, hai vai trò idempotent KHÁC nhau — đừng gộp:

- `interview_booking.reminder_sent_at` — đã gửi thư NHẮC TRƯỚC BUỔI PHỎNG VẤN chưa (24h trước).
- `booking_session.no_slots_at` — lần ĐẦU ứng viên mở link mà kho khung giờ đã cạn (để dashboard
  hiện nhãn "cần mở thêm lịch" thay vì đổ lỗi ứng viên chậm).

Cả hai NULL-able + không server_default: hàng cũ mang NULL = "chưa xảy ra", đúng nghĩa cần.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: str | None = 'c7d8e9f0a1b2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_booking",
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "booking_session",
        sa.Column("no_slots_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("booking_session", "no_slots_at")
    op.drop_column("interview_booking", "reminder_sent_at")
