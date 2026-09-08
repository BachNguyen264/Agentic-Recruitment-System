"""Application (Candidate) — đơn vị chạy qua pipeline. PRD §16 + vòng đời §13.

Schema chừa sẵn chỗ cho 4 trụ cột (PRD §5: confidence/uncertainty_flags/escalation_reason)
và Screener async (PRD §10: screener_sent_at/screener_deadline). KHÔNG có logic thật ở scaffold.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.screening_session import ScreeningSession


class ApplicationStatus(str, enum.Enum):
    """Trạng thái CV — khớp state machine PRD §13. Lưu dạng String (linh hoạt khi PRD đổi)."""

    SUBMITTED = "SUBMITTED"
    PARSING = "PARSING"
    RANKING = "RANKING"
    SCREENING = "SCREENING"
    AWAITING_SCREENER = "AWAITING_SCREENER"
    # KHÔNG có `REMINDED`: PRD §13 ghi "+24h → REMINDED → (vẫn AWAITING)" — nhắc là một SỰ KIỆN, không
    # phải trạng thái. Cơ chế thật ghi mốc `screening_session.reminded_at` và GIỮ NGUYÊN
    # AWAITING_SCREENER, đúng như PRD; một hằng số trạng thái không bao giờ được gán chỉ mời gọi code
    # sau viết `status == REMINDED` — điều kiện không bao giờ đúng, và nếu ai đó GÁN thật thì hồ sơ
    # rơi khỏi mọi bộ lọc `AWAITING_SCREENER` (sweep nhắc/hết hạn + `screening._load_valid`).
    SCHEDULING = "SCHEDULING"
    # SCH-2 (PRD §10b, §13): thư mời + link đặt lịch ĐÃ gửi, đang chờ ứng viên tự chọn giờ.
    AWAITING_BOOKING = "AWAITING_BOOKING"
    PENDING_REVIEW = "PENDING_REVIEW"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    REJECTED = "REJECTED"


# Trạng thái "ĐANG BAY" (PRD §13): pipeline CHƯA ra quyết định và CHƯA có email nào tới ứng viên.
# Đây là TẬP DUY NHẤT mà xử-lý-lỗi/đối-soát được phép ghi đè. Mọi trạng thái sau đó đều đã "phát ra
# ngoài" một thứ gì đó không rút lại được:
#   REJECTED / INTERVIEW_SCHEDULED — thư từ chối/thư mời đã tới tay ứng viên.
#   AWAITING_SCREENER             — magic-link ĐÃ gửi; hạ trạng thái là ứng viên nộp câu trả lời bị
#                                   409 và mất bài dự tuyển (họ là guest, không có gì để khiếu nại).
#   SCHEDULING                    — "đã quyết mời, thư mời CÓ THỂ đã gửi" (CLAUDE.md) → kéo về hàng
#                                   chờ HR là mở đường cho "mời xong lại từ chối".
#   AWAITING_BOOKING              — thư mời + LINK ĐẶT LỊCH đã tới tay ứng viên (SCH-2). Hạ trạng thái
#                                   là họ mở link ra thấy hỏng, sau khi vừa được mời phỏng vấn.
IN_FLIGHT_STATUSES = frozenset(
    {
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.PARSING.value,
        ApplicationStatus.RANKING.value,
    }
)

# ⚠ KHÁC HẲN `IN_FLIGHT_STATUSES` ở trên — ĐỪNG gộp hai tập này.
#   IN_FLIGHT_STATUSES  = bất biến AN TOÀN: tập DUY NHẤT được phép ghi đè trạng thái. Nới nó ra là
#                         mở đường cho "mời xong lại từ chối" / giết magic-link đang sống.
#   DASHBOARD_ACTIVE_*  = khái niệm HIỂN THỊ: "chưa tới điểm kết thúc", dùng cho panel đang-chạy của
#                         dashboard (PRD §12.1). Rộng hơn hẳn, và cố ý CHỨA những trạng thái mà việc
#                         ghi đè bị CẤM (AWAITING_SCREENER, SCHEDULING, AWAITING_BOOKING).
# Trộn hai tập lại thì lỗi lộ ra không phải ở dashboard mà ở xử-lý-lỗi/đối-soát — nơi khó thấy nhất.
DASHBOARD_ACTIVE_STATUSES = frozenset(
    {
        ApplicationStatus.SUBMITTED.value,
        ApplicationStatus.PARSING.value,
        ApplicationStatus.RANKING.value,
        ApplicationStatus.SCREENING.value,
        ApplicationStatus.AWAITING_SCREENER.value,
        ApplicationStatus.SCHEDULING.value,
        ApplicationStatus.AWAITING_BOOKING.value,
    }
)


class Application(Base, TimestampMixin):
    __tablename__ = "application"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_posting.id", ondelete="SET NULL"), nullable=True, index=True
    )
    applicant_email: Mapped[str] = mapped_column(String(320), index=True)
    cv_file_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Kết quả Parser/Ranker (phase sau).
    parsed_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_breakdown: Mapped[dict] = mapped_column(JSONB, default=dict)

    status: Mapped[str] = mapped_column(
        String(32), default=ApplicationStatus.SUBMITTED.value, index=True
    )

    # ── Chừa chỗ 4 trụ cột (PRD §5 trụ cột 3 "an toàn trước case lạ") ──
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    uncertainty_flags: Mapped[list] = mapped_column(JSONB, default=list)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Chừa chỗ Screener async (PRD §10 suspend/resume) ──
    screener_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    screener_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    audit_logs: Mapped[list[AuditLog]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True
    )
    screening_sessions: Mapped[list[ScreeningSession]] = relationship(
        back_populates="application", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Application id={self.id} email={self.applicant_email!r} status={self.status}>"
