"""Pydantic I/O cho Application (scaffold: POST tạo, GET đọc)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import settings
from app.services.email_delivery import (
    EMAIL_BOUNCED_FLAG,
    EMAIL_COMPLAINED_FLAG,
    EMAIL_SEND_FAILED_FLAG,
)
from app.services.review import recommendation as _recommendation

# Dev: chỉ đòi "có @, hai bên không rỗng, domain có dấu chấm, không khoảng trắng". Nới ≠ tắt — rác
# hiển nhiên vẫn phải chết ở đây, chứ không phải chết ở lượt gọi Resend sau khi đã tốn hai lượt LLM
# chấm hồ sơ (~34s, xem CLAUDE.md mục "Hardening tải").
_DEV_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class ApplicationCreate(BaseModel):
    """Ứng viên nộp CV: chỉ cần email + JD (PRD §8.2).

    KHÔNG có `cv_file_ref`: ref/key do SERVER sinh (`storage.build_cv_key`) sau khi có application_id.
    (Slice 06 gỡ bỏ — trường này client đặt được sẽ thành lỗ đọc file tùy ý nếu có endpoint JSON nào
    nhận thẳng schema này; thực tế nó luôn None vì cả hai route đều ghi đè sau khi lưu.)

    **Email: chặt ở prod, nới ở dev (EMAIL-1).** Prod dùng `email-validator` chuẩn — nó từ chối cả
    domain dùng-riêng (`.local`, `localhost`), thứ mà thư gửi tới chắc chắn không tới ai. Nhưng
    chính vì thế mà chạy thử end-to-end trên máy dev với domain nội bộ là không thể, nên dev nới
    xuống một kiểm tra hình thức (cùng lý do slice 09 nới email ĐĂNG NHẬP — xem `docs/AI_GUIDE.md`
    mục "Login email = `str`, NOT `EmailStr`"). Đọc `settings.app_env` lúc VALIDATE chứ không phải
    lúc import: nếu không, test không đổi được môi trường và cả hai chiều đều không khoá được.
    """

    job_id: int | None = None
    applicant_email: str

    @field_validator("applicant_email")
    @classmethod
    def _check_email(cls, value: str) -> str:
        value = (value or "").strip()
        if settings.app_env == "local":
            if not _DEV_EMAIL_RE.fullmatch(value):
                raise ValueError("Email không hợp lệ.")
            return value
        from email_validator import EmailNotValidError, validate_email

        try:
            return validate_email(value, check_deliverability=False).normalized
        except EmailNotValidError as exc:
            raise ValueError("Email không hợp lệ.") from exc


class ReviewRequest(BaseModel):
    """HR quyết định một ca PENDING_REVIEW (PRD §11 FR-HR-4)."""

    decision: Literal["approve", "reject"]
    note: str | None = None


class PublicSubmitResponse(BaseModel):
    """Xác nhận nộp CV công khai (PRD §8.2). KHÔNG lộ điểm/parsed_data/trạng thái cho ứng viên."""

    application_id: int
    message: str = "Đã nhận hồ sơ. Chúng tôi sẽ liên hệ với bạn qua email."


class PipelineItem(BaseModel):
    """Một hồ sơ đang chạy, ở dạng GỌN NHẤT đủ vẽ một dòng trên dashboard.

    Cố ý KHÔNG phải `ApplicationRead`: bảng điều hành hỏi lại vài giây một lần, mà `ApplicationRead`
    chở theo `parsed_data` (cả CV đã bóc tách) + `score_breakdown`. Gửi ngần ấy chỉ để vẽ một dòng
    tên là biến nhịp làm tươi thành đường tải nặng nhất hệ thống lúc bình thường.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    applicant_email: str
    job_id: int | None
    status: str


class PipelineSnapshot(BaseModel):
    """Ảnh chụp pipeline cho bảng điều hành (PRD §12.1 FR-HR-DASH-1) — payload KÍCH THƯỚC CỐ ĐỊNH.

    `counts` là ĐỦ mọi trạng thái PRD §13 (kể cả đang 0), đếm trên TOÀN BẢNG. Việc gom trạng thái nào
    vào nút nào (`SUBMITTED`+`PARSING` → parser, …) do client giữ: đó là cách đọc PRD, không phải dữ
    liệu, và nhân đôi nó xuống backend chỉ tạo thêm một chỗ để hai bên lệch nhau.
    """

    counts: dict[str, int]
    active: list[PipelineItem]
    generated_at: datetime


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
    # Hồ sơ này đã TỪNG được phát liên kết đặt lịch chưa (SCH-3). Gương của điều kiện
    # `has_any_session` mà `resend_booking_link` dùng để chặn: thiếu nó, dashboard hiện nút "Gửi
    # lại link" cho MỌI ca `PENDING_REVIEW` — kể cả ca chưa ai duyệt — và HR chỉ biết mình bấm nhầm
    # sau khi nhận 409. CHỈ populate ở endpoint chi tiết (như `interview`, tránh N+1 ở danh sách).
    has_booking_link: bool = False
    # Lý do bounce/complaint rút gọn (từ `email_delivery.bounce_reason` của sự kiện XẤU GẦN NHẤT của
    # ĐÚNG loại đó) — hai cột RIÊNG, KHÔNG trộn: bounce cần "tìm địa chỉ đúng rồi liên hệ lại", complaint
    # cần "ngừng gửi cho người này", nên HR phải biết đang đọc cái nào. CHỈ populate ở endpoint chi
    # tiết (như `interview`/`has_booking_link`, tránh N+1 ở danh sách).
    email_bounce_reason: str | None = None
    email_complaint_reason: str | None = None
    # Lý do KỸ THUẬT khi dịch vụ gửi không đẩy được thư đi (`failed.reason` của Resend, vd
    # `reached_daily_quota`). Cột thứ BA chứ không dùng lại `email_bounce_reason`: bounce và failed
    # là hai câu chuyện ngược nhau, và trộn chung thì HR không biết nên đi tìm địa chỉ khác hay đi
    # sửa cấu hình gửi.
    email_send_failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field  # gợi ý hiển thị cho ReviewCard (PRD §11) — dẫn xuất, KHÔNG tự quyết.
    @property
    def recommendation(self) -> str:
        return _recommendation(self.score, self.uncertainty_flags)

    # EMAIL-1: thư MỜI/SÀNG LỌC không tới được ứng viên (webhook Resend báo bounce). Dẫn xuất từ
    # `uncertainty_flags` nên CÓ ở CẢ danh sách lẫn chi tiết mà không tốn thêm truy vấn nào (giống
    # nếp `booking_no_slots`) — `uncertainty_flags` đã có sẵn trên cả hai endpoint.
    @computed_field
    @property
    def email_bounced(self) -> bool:
        return EMAIL_BOUNCED_FLAG in (self.uncertainty_flags or [])

    # Ứng viên đã bấm "đây là spam" trên một lá thư ĐÃ TỚI NƠI — cờ RIÊNG, KHÔNG gộp chung nhãn với
    # bounce: bounce và complaint đòi hai cách xử TRÁI NGƯỢC nhau (xem docstring `services/email_delivery`).
    @computed_field
    @property
    def email_complained(self) -> bool:
        return EMAIL_COMPLAINED_FLAG in (self.uncertainty_flags or [])

    # Dịch vụ gửi KHÔNG đẩy được thư đi (`email.failed`) — thư chưa hề rời hệ thống. Cờ thứ BA, tách
    # khỏi `email_bounced`: bounce ⇒ địa chỉ ứng viên có vấn đề, đi tìm kênh liên hệ khác; failed ⇒
    # phía TA có vấn đề (hạn mức/domain/khoá API), sửa rồi gửi lại cho chính địa chỉ đó.
    @computed_field
    @property
    def email_send_failed(self) -> bool:
        return EMAIL_SEND_FAILED_FLAG in (self.uncertainty_flags or [])

    @computed_field  # có file CV để tải không (slice 06) — thay cho việc lộ key/path ra client.
    @property
    def has_cv(self) -> bool:
        return bool(self.cv_file_ref)
