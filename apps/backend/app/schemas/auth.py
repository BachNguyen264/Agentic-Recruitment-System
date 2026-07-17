"""Schemas auth HR (slice 09)."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class HrUserRead(BaseModel):
    """Thông tin HR đang đăng nhập (GET /me). KHÔNG trả password_hash."""

    id: int
    email: str

    model_config = {"from_attributes": True}
