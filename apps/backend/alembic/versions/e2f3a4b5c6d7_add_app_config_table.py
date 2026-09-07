"""add app_config (cấu hình hệ thống sửa được lúc chạy — PRD §NFR-8)

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-09-08

HAND-WRITTEN (KHÔNG autogenerate) — cùng lý do như d1e2f3a4b5c6/c7d8e9f0a1b2: autogenerate nhìn thấy
các bảng checkpoint của LangGraph không có trong `Base.metadata` và sẽ đề xuất DROP chúng.

MỘT DÒNG = MỘT CẤU HÌNH, và CHỈ lưu dòng khác mặc định (xem docstring của models/app_config.py).
Bảng rỗng là trạng thái hợp lệ và cũng là trạng thái sau khi migrate — hệ thống chạy y hệt như
trước migration này, không cần seed gì.

`updated_by` dùng SET NULL chứ KHÔNG CASCADE: xoá một tài khoản HR không được phép kéo theo cấu hình
toàn hệ thống. Mất dấu vết "ai đổi" thì `audit_log` vẫn còn giữ.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e2f3a4b5c6d7'
down_revision: str | None = 'd1e2f3a4b5c6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_config",
        sa.Column("key", sa.String(length=64), primary_key=True, nullable=False),
        # nullable: một số cấu hình có giá trị hợp lệ là "để trống" (vd địa chỉ nhận thư trả lời).
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["hr_user.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("app_config")
