"""AppConfig — cấu hình hệ thống sửa được lúc chạy (PRD §NFR-8).

MỘT DÒNG = MỘT CẤU HÌNH. Cố ý KHÔNG dùng một dòng JSONB chứa tất cả, vì hai lý do đã trả giá:

  1. Mutate JSONB tại chỗ thì SQLAlchemy KHÔNG đánh dấu dirty và thay đổi mất im lặng — bẫy này đã
     có thật ở `job_service.set_gate_config` (nó phải copy dict ra rồi gán lại cả dict). Mỗi cấu
     hình một dòng thì không có cơ hội mắc.
  2. `audit_log` ghi được ĐÍCH DANH ai đổi cấu hình nào, từ giá trị nào sang giá trị nào. Một dòng
     JSONB chỉ ghi được "có ai đó sửa config".

CHỈ LƯU DÒNG KHÁC MẶC ĐỊNH. Bảng rỗng = chạy hoàn toàn theo mặc định trong `Settings`. Xoá một dòng
= trả cấu hình đó về mặc định. Nhờ vậy đổi mặc định trong code sẽ tự lan tới mọi môi trường chưa
từng chỉnh tay cấu hình đó — nếu lưu cả 39 dòng ngay từ đầu thì mặc định mới sẽ bị dòng cũ che mất.

`value` là JSONB chứa MỘT giá trị vô hướng (số/chuỗi/null), không phải object.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    # Ai đổi. SET NULL chứ không CASCADE: xoá tài khoản HR KHÔNG được kéo theo cấu hình hệ thống.
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("hr_user.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AppConfig {self.key}={self.value!r}>"
