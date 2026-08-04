"""add interview_booking + booking_session (SCH-1 pull scheduling)

Revision ID: c7d8e9f0a1b2
Revises: b2c3d4e5f6a7
Create Date: 2026-08-04

HAND-WRITTEN (KHÔNG autogenerate) vì hai lý do:

1. **Partial unique index.** `UNIQUE (start_at) WHERE status = 'BOOKED'` là chốt chặn cuối chống đặt
   trùng (PRD §10b.5, FR-BOOK-2). Alembic autogenerate hay bỏ sót/viết sai vế `WHERE`, mà nếu nó rơi
   mất thì hệ thống VẪN CHẠY — chỉ im lặng cho phép hai ứng viên đặt trùng một khung giờ. Viết tay để
   vế điều kiện là thứ được đọc và kiểm chứng, không phải thứ được suy đoán.
2. **Bảng checkpoint LangGraph.** `checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/
   `checkpoint_migrations` do AsyncPostgresSaver tự quản, KHÔNG nằm trong `Base.metadata` →
   autogenerate sẽ đề xuất DROP chúng (mất suspend/resume 08a). `alembic/env.py::_include_object`
   đã chặn sẵn; migration viết tay thì không có cửa nào để lọt.

Chỉ THÊM bảng mới — không đụng bảng nào đang có.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: str | None = 'b2c3d4e5f6a7'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Giữ khớp với `app/models/booking.py::BOOKED_START_AT_INDEX`.
_BOOKED_START_AT_INDEX = "uq_interview_booking_booked_start_at"


def upgrade() -> None:
    op.create_table(
        "interview_booking",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("hold_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_interview_booking_application_id"),
        "interview_booking",
        ["application_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_interview_booking_start_at"), "interview_booking", ["start_at"], unique=False
    )
    op.create_index(
        op.f("ix_interview_booking_status"), "interview_booking", ["status"], unique=False
    )
    # ── Chốt chặn chống đặt trùng ─────────────────────────────────────────────────────────
    # PARTIAL: chỉ áp cho hàng BOOKED. Nếu bỏ vế WHERE, hai ứng viên cùng GIỮ CHỖ một khung giờ đã
    # nổ ngay ở bước giữ chỗ — phá đúng thiết kế "HELD = khuyến nghị, BOOKED = thẩm quyền" (§10b.5).
    op.create_index(
        _BOOKED_START_AT_INDEX,
        "interview_booking",
        ["start_at"],
        unique=True,
        postgresql_where=sa.text("status = 'BOOKED'"),
    )

    op.create_table(
        "booking_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reminded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("booked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_booking_session_application_id"), "booking_session", ["application_id"], unique=False
    )
    op.create_index(op.f("ix_booking_session_token"), "booking_session", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_booking_session_token"), table_name="booking_session")
    op.drop_index(op.f("ix_booking_session_application_id"), table_name="booking_session")
    op.drop_table("booking_session")

    op.drop_index(_BOOKED_START_AT_INDEX, table_name="interview_booking")
    op.drop_index(op.f("ix_interview_booking_status"), table_name="interview_booking")
    op.drop_index(op.f("ix_interview_booking_start_at"), table_name="interview_booking")
    op.drop_index(op.f("ix_interview_booking_application_id"), table_name="interview_booking")
    op.drop_table("interview_booking")
