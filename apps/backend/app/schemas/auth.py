"""Schemas auth HR (slice 09)."""

from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    # `str` (KHÔNG EmailStr): email chỉ là ĐỊNH DANH đăng nhập, so khớp với DB. EmailStr từ chối các
    # TLD đặc biệt (vd `.local`) → tài khoản seed domain nội bộ sẽ không đăng nhập được. Không thêm
    # bảo mật gì (đã băm + thông báo chung); chuẩn hóa strip+lower ở handler.
    email: str
    password: str


class HrUserRead(BaseModel):
    """Thông tin HR đang đăng nhập (GET /me). KHÔNG trả password_hash."""

    id: int
    email: str

    model_config = {"from_attributes": True}
