"""Pydantic I/O cho Application (scaffold: POST tạo, GET đọc)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field

from app.services.review import recommendation as _recommendation


class ApplicationCreate(BaseModel):
    """Ứng viên nộp CV: chỉ cần email + JD (PRD §8.2).

    KHÔNG có `cv_file_ref`: ref/key do SERVER sinh (`storage.build_cv_key`) sau khi có application_id.
    (Slice 06 gỡ bỏ — trường này client đặt được sẽ thành lỗ đọc file tùy ý nếu có endpoint JSON nào
    nhận thẳng schema này; thực tế nó luôn None vì cả hai route đều ghi đè sau khi lưu.)
    """

    job_id: int | None = None
    applicant_email: EmailStr


class ReviewRequest(BaseModel):
    """HR quyết định một ca PENDING_REVIEW (PRD §11 FR-HR-4)."""

    decision: Literal["approve", "reject"]
    note: str | None = None


class PublicSubmitResponse(BaseModel):
    """Xác nhận nộp CV công khai (PRD §8.2). KHÔNG lộ điểm/parsed_data/trạng thái cho ứng viên."""

    application_id: int
    message: str = "Đã nhận hồ sơ. Chúng tôi sẽ liên hệ với bạn qua email."


class BookedInterview(BaseModel):
    """Khung giờ phỏng vấn ứng viên đã tự chọn (SCH-2). Chỉ mốc thời gian — HR không cần id nội bộ."""

    model_config = ConfigDict(from_attributes=True)

    start_at: datetime
    end_at: datetime


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int | None
    applicant_email: str
    # KHÔNG trả `cv_file_ref` ra client: trước slice 06 nó lộ ĐƯỜNG DẪN TUYỆT ĐỐI của server, sau
    # slice 06 sẽ lộ KEY bucket. Frontend chỉ cần biết CÓ CV hay không để hiện nút tải; bytes lấy
    # qua endpoint `GET /api/applications/{id}/cv` (có require_hr).
    cv_file_ref: str | None = Field(default=None, exclude=True)
    parsed_data: dict
    score: float | None
    score_breakdown: dict
    status: str
    # 4 trụ cột (PRD §5)
    confidence: float | None
    uncertainty_flags: list = Field(default_factory=list)
    escalation_reason: str | None
    # Screener async (PRD §10)
    screener_sent_at: datetime | None
    screener_deadline: datetime | None
    # Câu trả lời sàng lọc [{question, answer}] — hiện cho HR (PRD §7.3, §11). Rỗng nếu chưa/không
    # sàng lọc. CHỈ populate ở endpoint chi tiết (list để rỗng, tránh N+1).
    screener_answers: list = Field(default_factory=list)
    # Lịch phỏng vấn ĐÃ chốt (SCH-2 · PRD §10b) — None nếu ứng viên chưa chọn giờ. CHỈ populate ở
    # endpoint chi tiết (như screener_answers, tránh N+1 ở danh sách).
    interview: BookedInterview | None = None
    # SCH-3 (FR-BOOK-6): ứng viên ĐÃ mở link nhưng kho khung giờ trống rỗng. Cần một trường RIÊNG
    # chứ không suy từ `status`, vì cả hai tình huống "chưa bấm link" và "bấm rồi mà hết lịch" đều
    # đứng ở `AWAITING_BOOKING` — gộp lại thành một nhãn là đổ lỗi cho người không có lỗi.
    booking_no_slots: bool = False
    created_at: datetime
    updated_at: datetime

    @computed_field  # gợi ý hiển thị cho ReviewCard (PRD §11) — dẫn xuất, KHÔNG tự quyết.
    @property
    def recommendation(self) -> str:
        return _recommendation(self.score, self.uncertainty_flags)

    @computed_field  # có file CV để tải không (slice 06) — thay cho việc lộ key/path ra client.
    @property
    def has_cv(self) -> bool:
        return bool(self.cv_file_ref)
