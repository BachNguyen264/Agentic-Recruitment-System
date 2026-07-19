"""add rubric_suggestion_count (JD-3): cap AI gợi ý rubric / JD

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-19 12:00:00.000000

JD-3 (PRD §16, §12.1 FR-HR-RUBRIC-1): thêm 1 cột đếm số lần AI gợi ý rubric cho JD (cap 3 lần/JD,
reset khi nội dung JD đổi). NOT NULL + server_default='0' → hàng JD legacy backfill = 0. Hand-written
(chỉ add_column, KHÔNG autogenerate) → không đụng 4 bảng checkpoint LangGraph (include_object guard
vẫn có ở env.py).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: str | None = 'a1b2c3d4e5f6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'job_posting',
        sa.Column('rubric_suggestion_count', sa.Integer(), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('job_posting', 'rubric_suggestion_count')
