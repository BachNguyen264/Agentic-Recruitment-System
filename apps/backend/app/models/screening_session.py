"""ScreeningSession — phiên trả lời Screener qua magic-link (PRD §7.3, §10, §16).

08b: khi pipeline dừng ở screener (AWAITING_SCREENER), tạo một phiên với **token an toàn**
(secrets.token_urlsafe), **hạn** (expires_at), và ảnh chụp **bộ câu hỏi** của JD tại thời điểm gửi
(bền vững kể cả khi HR sửa JD sau). Ứng viên mở magic-link → trả lời → resume pipeline; đánh dấu
`used_at` (one-time). Câu trả lời (`answers`) lưu lại cho HR tham khảo.

Bảo mật (xem plan §6): token crypto-random + unique; hết hạn/đã dùng bị từ chối; chỉ gắn 1 application.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.application import Application


class ScreeningSession(Base, TimestampMixin):
    __tablename__ = "screening_session"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), index=True
    )
    # Token magic-link: secrets.token_urlsafe(32) ~43 ký tự — unique + index để tra cứu nhanh.
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    # Ảnh chụp bộ câu hỏi JD lúc gửi (PRD §16 ScreeningSession.questions) — KHÔNG đọc live từ JD
    # (bền khi HR sửa JD; đảm bảo ứng viên thấy đúng câu đã gửi + kiểm toán).
    questions: Mapped[list] = mapped_column(JSONB, default=list)
    # Câu trả lời [{question, answer}] — NULL đến khi ứng viên nộp; lưu cho HR (PRD §7.3, §11).
    answers: Mapped[list | None] = mapped_column(JSONB, nullable=True, default=None)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ── Screener timeout (08c — PRD §10 FR-SCR-3/4) ──
    # reminded_at: đã gửi email NHẮC (once-only — sweep set để không nhắc lần hai).
    reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # timed_out_at: đã hết hạn KHÔNG phản hồi → resume no_response → human_review. Đánh dấu để sweep
    # idempotent (không xử timeout hai lần) + phân biệt "hết hạn" với "đã trả lời" (used_at) cho trả lời trễ.
    timed_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    application: Mapped[Application | None] = relationship(back_populates="screening_sessions")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<ScreeningSession id={self.id} app={self.application_id} used={self.used_at is not None}>"
