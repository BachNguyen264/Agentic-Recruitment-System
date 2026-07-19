"""add JD content fields (JD-1): level, salary, benefits, employment_type

Revision ID: a1b2c3d4e5f6
Revises: 2c0dce11f4bb
Create Date: 2026-07-19 10:00:00.000000

JD-1 (PRD §16, §8.1): bổ sung trường hướng-ứng-viên cho JobPosting. THÊM 4 cột nullable
(JD legacy = NULL). `requirements` KHÔNG đổi — đã là Text từ scaffold (list→"\n".join là
app-side); JD-1 lưu HTML thẳng vào cột Text đó, không cần ALTER. Hand-written (chỉ add_column,
KHÔNG autogenerate) → không đụng 4 bảng checkpoint LangGraph (include_object guard vẫn có ở env.py).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: str | None = '2c0dce11f4bb'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column('job_posting', sa.Column('level', sa.String(length=32), nullable=True))
    op.add_column('job_posting', sa.Column('salary', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('job_posting', sa.Column('benefits', sa.Text(), nullable=True))
    op.add_column('job_posting', sa.Column('employment_type', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('job_posting', 'employment_type')
    op.drop_column('job_posting', 'benefits')
    op.drop_column('job_posting', 'salary')
    op.drop_column('job_posting', 'level')
