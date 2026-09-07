"""Pydantic I/O cho khu quản trị (Cấu hình hệ thống + Nhật ký kiểm toán)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConfigFieldOut(BaseModel):
    """Một ô cấu hình, đủ để giao diện tự dựng form mà không cần biết gì về nghiệp vụ."""

    key: str
    label: str
    tooltip: str
    kind: str  # int | float | str | enum
    value: Any
    default: Any
    minimum: float | None = None
    maximum: float | None = None
    choices: list[str] | None = None
    unit: str | None = None
    nullable: bool = False
    warning: str | None = None
    # Đang KHÁC mặc định (có hàng trong `app_config`) → giao diện hiện dấu "đã chỉnh" + nút khôi phục.
    is_overridden: bool = False


class ConfigGroupOut(BaseModel):
    group: str
    fields: list[ConfigFieldOut]


class ConfigUpdateRequest(BaseModel):
    """Cập nhật MỘT PHẦN: chỉ gửi những ô đã đổi.

    Giá trị để `Any` vì mỗi ô một kiểu; việc ép kiểu + kiểm ràng buộc do `config_registry.coerce()`
    làm, ở đó mới biết ô nào kiểu gì. Để pydantic đoán kiểu ở đây sẽ biến "abc" thành lỗi 422 cụt
    ngủn của framework thay vì câu tiếng Việt nói rõ ô nào sai và vì sao.
    """

    values: dict[str, Any] = Field(default_factory=dict)


class ConfigUpdateResult(BaseModel):
    saved: list[str]
    changed: list[str]


class AuditLogItem(BaseModel):
    id: int
    application_id: int | None
    # Kèm sẵn email ứng viên để danh sách không phải gọi thêm một vòng lấy tên cho từng dòng.
    applicant_email: str | None
    node: str
    action: str
    confidence: float | None
    uncertainty_flags: list
    escalation_reason: str | None
    detail: dict
    created_at: datetime


class AuditLogPage(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[AuditLogItem]
