"""JobPosting (JD) — PRD §16. Rubric/screener_questions/gate_config là JSONB (chừa chỗ, phase sau)."""

from __future__ import annotations

from sqlalchemy import String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


def _default_gate_config() -> dict:
    # PRD §9 FR-GATE-3: mặc định cả hai gate TẮT (an toàn nhất).
    return {"auto_reject": False, "auto_invite": False}


class JobPosting(Base, TimestampMixin):
    __tablename__ = "job_posting"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    # description/requirements/benefits: văn bản ĐỊNH DẠNG (HTML do HR soạn ở editor — JD-1). Cột vẫn
    # Text (requirements đã là Text từ scaffold, không đổi kiểu). Bóc HTML → plain-text trước khi vào
    # embedding/LLM (build_jd_text / jd_dict) — định dạng KHÔNG lọt vào semantic matching/prompt.
    description: Mapped[str] = mapped_column(Text, default="")
    requirements: Mapped[str | None] = mapped_column(Text, nullable=True)

    # JD-1 (PRD §16, §8.1): trường hướng-ứng-viên bổ sung. Đều nullable (JD legacy = NULL).
    level: Mapped[str | None] = mapped_column(String(32), nullable=True)  # intern..manager
    # salary: {min, max, currency, negotiable} — JSONB (nhóm lại; NULL = chưa nhập). Read chuẩn hóa.
    salary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    benefits: Mapped[str | None] = mapped_column(Text, nullable=True)  # quyền lợi (văn bản định dạng)
    employment_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # full_time.., internship

    # rubric: list tiêu chí + trọng số (PRD §7.2) — [{criterion, weight}]. Row scaffold cũ có thể
    # còn dict {} (JSONB nhận cả hai; JobPostingRead chuẩn hóa). screener_questions: PRD §10 FR-SCR-6.
    rubric: Mapped[list] = mapped_column(JSONB, default=list)
    screener_questions: Mapped[list] = mapped_column(JSONB, default=list)
    # gate_config: {auto_reject, auto_invite} (PRD §9). Có thể đặt theo từng JD (FR-GATE-1).
    gate_config: Mapped[dict] = mapped_column(JSONB, default=_default_gate_config)

    status: Mapped[str] = mapped_column(String(32), default="OPEN")  # OPEN | CLOSED | DRAFT
    embedding_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)  # con trỏ Qdrant (phase sau)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<JobPosting id={self.id} title={self.title!r} status={self.status}>"
