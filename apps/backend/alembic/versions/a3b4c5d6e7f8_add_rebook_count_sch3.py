"""add booking_session.rebook_count (SCH-3 — chặn vòng đặt-huỷ-đặt đốt quota email)

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-08-06

HAND-WRITTEN (cùng lý do c7d8e9f0a1b2/f1a2b3c4d5e6: autogenerate đề xuất DROP các bảng checkpoint
của LangGraph vì chúng không nằm trong `Base.metadata`).

VÌ SAO cần cột này dù TTL 72h đã chặn vòng lặp: TTL chặn theo THỜI GIAN, không chặn theo SỐ EMAIL.
Mỗi vòng đặt-rồi-huỷ phát HAI thư (xác nhận + báo huỷ), và trần duy nhất còn lại là rate-limit theo
IP (20 lượt/giờ) ⇒ một liên kết có thể đốt hàng trăm lượt gửi trong hạn của nó. Resend là kênh DUY
NHẤT của cả hệ thống nên hết quota là thư mời/từ chối/sàng lọc của MỌI ứng viên khác cùng câm.

`server_default="0"` để hàng CŨ không NULL (cột NOT NULL).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3b4c5d6e7f8'
down_revision: str | None = 'f1a2b3c4d5e6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "booking_session",
        sa.Column("rebook_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("booking_session", "rebook_count")
