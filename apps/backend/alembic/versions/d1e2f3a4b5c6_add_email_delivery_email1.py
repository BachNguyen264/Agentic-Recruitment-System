"""add email_delivery (EMAIL-1 — lưu vết giao hàng + khoá đối chiếu webhook)

Revision ID: d1e2f3a4b5c6
Revises: a3b4c5d6e7f8
Create Date: 2026-08-10

HAND-WRITTEN (KHÔNG autogenerate) — cùng lý do như c7d8e9f0a1b2/f1a2b3c4d5e6: autogenerate nhìn
thấy các bảng checkpoint của LangGraph (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/
`checkpoint_migrations`) không có trong `Base.metadata` và sẽ đề xuất DROP chúng — mất suspend/resume
08a. `_include_object` trong `alembic/env.py` đã chặn sẵn; migration viết tay thì không có cửa lọt.

`resend_email_id` UNIQUE là chốt idempotency ở tầng DB: webhook nhận sự kiện trùng vẫn chỉ có một
hàng để cập nhật, không sinh bản sao.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: str | None = 'a3b4c5d6e7f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_delivery",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resend_email_id", sa.String(length=64), nullable=False),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="SENT"),
        sa.Column("bounce_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_email_delivery_resend_email_id", "email_delivery", ["resend_email_id"], unique=True
    )
    op.create_index("ix_email_delivery_application_id", "email_delivery", ["application_id"])
    op.create_index("ix_email_delivery_kind", "email_delivery", ["kind"])
    op.create_index("ix_email_delivery_status", "email_delivery", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_delivery_status", table_name="email_delivery")
    op.drop_index("ix_email_delivery_kind", table_name="email_delivery")
    op.drop_index("ix_email_delivery_application_id", table_name="email_delivery")
    op.drop_index("ix_email_delivery_resend_email_id", table_name="email_delivery")
    op.drop_table("email_delivery")
