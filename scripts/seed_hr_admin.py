"""seed_hr_admin — tạo tài khoản HR Admin ban đầu từ env (slice 09, PRD §4).

Hệ thống KHÔNG có luồng đăng ký (một vai HR, seed sẵn). Script này chạy lúc setup/deploy để nạp
tài khoản đầu tiên từ `HR_ADMIN_EMAIL` / `HR_ADMIN_PASSWORD`. IDEMPOTENT: email đã tồn tại → bỏ qua
(KHÔNG đổi mật khẩu — tránh vô tình ghi đè). Mật khẩu băm bcrypt (app.core.security).

Chạy (từ gốc repo; cần venv + .env của backend):
    uv run --directory apps/backend python ../../scripts/seed_hr_admin.py

`reset_demo_data.py` KHÔNG xóa hr_user (tài khoản không phải demo data) — an toàn chạy lại.
"""

from __future__ import annotations

import asyncio
import sys

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.hr_user import HrUser


async def seed() -> None:
    email = (settings.hr_admin_email or "").strip().lower()
    password = settings.hr_admin_password or ""
    if not email or not password:
        print("[seed] THIẾU HR_ADMIN_EMAIL / HR_ADMIN_PASSWORD trong env — không seed.")
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        existing = (
            await session.execute(select(HrUser).where(HrUser.email == email))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"[seed] HR admin {email!r} đã tồn tại (id={existing.id}) — bỏ qua (idempotent).")
            return

        user = HrUser(email=email, password_hash=hash_password(password))
        session.add(user)
        await session.commit()
        await session.refresh(user)
        print(f"[seed] Đã tạo HR admin {email!r} (id={user.id}).")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # tránh lỗi encode tiếng Việt trên Windows console
    except Exception:
        pass
    asyncio.run(seed())


if __name__ == "__main__":
    main()
