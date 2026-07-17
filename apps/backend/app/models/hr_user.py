"""HrUser — tài khoản HR Admin đăng nhập (slice 09, PRD §4).

CHỈ HR Admin có tài khoản; ứng viên là GUEST (không đăng nhập — fire-and-forget). Một vai duy nhất
(KHÔNG RBAC/nhiều vai). Tài khoản SEED sẵn từ env (scripts/seed_hr_admin.py) — KHÔNG có luồng đăng
ký/quên/reset trong hệ thống. Mật khẩu lưu dạng BĂM bcrypt (app/core/security.py), KHÔNG plaintext.
"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class HrUser(Base, TimestampMixin):
    __tablename__ = "hr_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Email đăng nhập — unique. Lưu chữ thường (chuẩn hóa ở seed/login) để tra cứu nhất quán.
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Băm bcrypt (~60 ký tự). KHÔNG BAO GIỜ lưu plaintext.
    password_hash: Mapped[str] = mapped_column(String(255))

    def __repr__(self) -> str:  # pragma: no cover
        return f"<HrUser id={self.id} email={self.email!r}>"
