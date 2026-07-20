"""Pydantic I/O cho AuditLog — nhật ký kiểm toán đọc-ra cho HR (PRD §16, NFR-3).

CHỈ ĐỌC: audit_log là append-only, không có endpoint ghi/sửa/xóa từ API.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditEntryRead(BaseModel):
    """Một bước trong agent trace của hồ sơ.

    KHÔNG trả `application_id` (client đã biết — nó nằm trên URL). `detail` trả nguyên: các chỗ ghi
    audit chỉ nhét dữ liệu tóm tắt (status/score/đếm) + email ứng viên ở bước gửi thư — thứ HR vốn
    đã thấy. Endpoint nằm trong router HR nên đã có `require_hr`.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    node: str
    action: str
    confidence: float | None
    uncertainty_flags: list
    escalation_reason: str | None
    detail: dict
    created_at: datetime
