"""Schema CÔNG KHAI cho trang đặt lịch (SCH-2 · PRD §10b, §12.2).

**Projection an toàn — kỷ luật 08b.** Ứng viên là GUEST: họ chỉ được thấy thứ cần để chọn giờ. Mọi
trường nội bộ (`rubric`, `score`, `score_breakdown`, `gate_config`, `parsed_data`, `confidence`,
`uncertainty_flags`, `status`, `cv_file_ref`) TUYỆT ĐỐI không đi qua đây. Whitelist tường minh như
dưới đây là lý do một field mới thêm vào model KHÔNG tự động rò ra ngoài — có test khẳng định sự
vắng mặt của chúng.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PublicSlot(BaseModel):
    """Một khung giờ đề xuất. `booking_id` là thứ ứng viên gửi lại khi xác nhận."""

    booking_id: int
    start_at: datetime
    end_at: datetime


class PublicBookingRead(BaseModel):
    """Nội dung trang chọn giờ. Mốc thời gian trả dạng ISO có múi giờ — frontend hiển thị theo
    `Asia/Ho_Chi_Minh` (không để trình duyệt tự đoán múi giờ của máy người dùng)."""

    job_title: str
    # Đã chốt lịch rồi → UI hiện "Bạn đã đặt lịch lúc X" thay vì danh sách chọn. Đây là TRẠNG THÁI,
    # không phải lỗi: token không one-time nên mở lại link là chuyện bình thường.
    already_booked: bool = False
    booked_start_at: datetime | None = None
    booked_end_at: datetime | None = None
    slots: list[PublicSlot] = Field(default_factory=list)
    # Hạn giữ chỗ chung của cả lượt — UI đếm ngược theo mốc này. Hold KHÔNG được gia hạn khi tải lại
    # (quyết định SCH-1), nên thiếu đồng hồ đếm ngược là ứng viên bị bất ngờ khi hết giờ.
    hold_expires_at: datetime | None = None


class BookingConfirm(BaseModel):
    booking_id: int


class BookingConfirmResponse(BaseModel):
    job_title: str
    start_at: datetime
    end_at: datetime
    # Để UI nói THẬT: gửi được thì báo "đã gửi thư xác nhận", không gửi được thì báo bộ phận Tuyển
    # dụng sẽ liên hệ. Hứa một email không tồn tại đúng là lớp "trạng thái nói dối" mà dự án né.
    email_sent: bool


class BookingCancelResponse(BaseModel):
    """Kết quả huỷ lịch của ứng viên (SCH-3 · FR-BOOK-4). Vẫn KHÔNG lộ trạng thái nội bộ hồ sơ."""

    # `False` = không có gì để huỷ (bấm hai lần, hoặc HR đã huỷ trước). Đây là TRẠNG THÁI, không
    # phải lỗi — cùng tinh thần `already_booked` ở trên.
    cancelled: bool
    job_title: str
    # Liên kết cũ CÒN HẠN → ứng viên tự chọn giờ khác ngay. Hết hạn → HR sẽ liên hệ. UI phải nói
    # đúng cái nào, vì hai câu dẫn tới hai hành vi hoàn toàn khác nhau của người đọc.
    can_rebook: bool
    email_sent: bool
