# EMAIL-1 — Làm chắc tầng gửi email · Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Đóng lỗ *"provider chấp nhận ≠ người nhận nhận được"* — mỗi lá thư có một hàng lưu vết
giao hàng đối chiếu được với webhook của Resend, bounce làm hồ sơ **nổi lên cho HR** thay vì để
dashboard nói dối, và tầng gửi chịu được giới hạn 2 req/s.

**Architecture:** Toàn bộ thay đổi nằm ở **tầng email**, không chạm graph/ranker/parser/screener/
booking. `email_service.send_email` giữ nguyên vai trò "một chỗ gọi Resend" nhưng nay **trả về
`resend_email_id`**, tự **giữ nhịp + retry**, và đính `reply_to` + bản `text`.
`scheduler._dispatch` — nơi gọi **DUY NHẤT** của `send_email`, và đã sẵn có `mode` +
`application_id` + `session` — ghi một hàng `email_delivery` cùng transaction với audit. Chiều
ngược lại là một endpoint công khai mới `POST /api/webhooks/resend`: verify chữ ký Svix bằng
stdlib, tra hàng theo `resend_email_id`, cập nhật trạng thái giao hàng, rồi **có điều kiện** hạ hồ
sơ về `PENDING_REVIEW` + gắn cờ `email_bounced`.

**Tech Stack:** Python 3.12 · FastAPI · SQLAlchemy 2 async · Alembic (migration **viết tay**) ·
Pydantic v2 · Resend SDK · stdlib `hmac`/`hashlib`/`base64` · Next.js 14 + plain Tailwind.

**Spec:** [`docs/superpowers/specs/2026-08-10-email-hardening.md`](../specs/2026-08-10-email-hardening.md) — đọc §2 (quyết định đã chốt) và §5 (bảng
xử lý bounce) trước khi bắt đầu.

---

## Global Constraints

Áp cho **mọi** task dưới đây:

- **Branch:** `fix/email-hardening`, tách từ `main` (booking đã merge — `c9fa373`). Commit nhỏ,
  prefix theo lát: `feat(email): …`, `feat(api): …`, `fix(email): …`, `test(email): …`, `docs: …`.
- **Ngôn ngữ:** docstring + comment **tiếng Việt**, khớp mật độ và giọng văn của file xung quanh.
  Comment giải thích **VÌ SAO**, không mô tả lại code.
- **Async-first.** Không I/O đồng bộ trong đường async. Resend SDK là sync ⇒ luôn bọc
  `asyncio.to_thread`.
- **Config từ env** qua pydantic-settings. KHÔNG hardcode secret/URL/ngưỡng.
- **Typing đầy đủ** (Python type hints; TS không có `any` lỏng).
- **Load boundary:** TUYỆT ĐỐI không giữ session/connection qua I/O mạng. Retry làm lượt gửi dài
  thêm tới ~8s ⇒ mọi caller phải đã `commit()` trước khi gọi `notify_*` (đã đúng hôm nay — Task 3
  có test khoá lại).
- **`scheduler` là điểm phát email DUY NHẤT.** Không rải `send_email` ra chỗ khác.
- **"KHÔNG đụng booking" nghĩa là không đổi HÀNH VI booking.** *Đọc* thì được: Task 7 `import`
  `booking_flow.with_flag` (helper thuần, vốn đã là bản dùng chung với `booking_lifecycle`) và
  truy vấn `interview_booking`/`screening_session` để hỏi sự thật. Cấm là: sửa thân hàm của
  `booking_flow`/`booking_lifecycle`/`booking_service`, đổi thứ tự ghi của chúng, hay thêm lượt
  gửi email mới vào đó.
- **Thứ tự thi công: Task 7 chạy TRƯỚC Task 6** (service trước route — xem ghi chú ở Task 6).
- **KHÔNG auto-reject ở bất kỳ nhánh nào.** Bounce → cờ (+ `PENDING_REVIEW` có điều kiện), không
  bao giờ → `REJECTED`.
- **NFR-4:** log **email id**, KHÔNG log nội dung thư / địa chỉ đầy đủ trong thông báo lỗi trả ra
  ngoài.
- **Migration viết tay** (không autogenerate) — `alembic/env.py` đã có `include_object` guard cho 4
  bảng checkpoint của LangGraph, nhưng migration viết tay thì không có cửa nào để lọt.
- **Bẫy ORM sau commit:** lấy giá trị nguyên thuỷ ra biến cục bộ **trước** khi commit; không chạm
  thuộc tính object ORM trong handler lỗi/log (`refresh()` mở lại transaction; `rollback()` expire
  object bất kể `expire_on_commit=False`).
- Lệnh: backend/test/git chạy ở **Bash** (`git -C d:/Web/Project/DATN …`, KHÔNG `cd`); pnpm/next/tsc
  chạy ở **PowerShell**.
- `make test` phải xanh sau MỖI task.

**Env mới (giá trị chốt):**

| Biến | Mặc định | Task thêm |
|---|---|---|
| `EMAIL_MIN_INTERVAL_MS` | `550` | 3 |
| `EMAIL_MAX_RETRIES` | `3` | 3 |
| `EMAIL_REPLY_TO` | `None` | 4 |
| `RESEND_WEBHOOK_SECRET` | `None` | 6 |
| `RESEND_WEBHOOK_TOLERANCE_SECONDS` | `300` | 6 |

**Từ vựng `kind` (chốt — trùng chuỗi `mode` đang chạy, KHÔNG bịa tên mới):**
`invite` · `reject` · `screener` · `screener_reminder` · `booking_confirmed` ·
`interview_reminder` · `booking_reminder` · `booking_cancelled` · `submission_ack` (để dành).

---

## File Structure

| File | Trách nhiệm | Task |
|---|---|---|
| `apps/backend/app/models/email_delivery.py` | **Tạo.** `EmailKind`, `DeliveryStatus`, thứ bậc trạng thái, model `EmailDelivery`. | 1 |
| `apps/backend/app/models/__init__.py` | **Sửa.** Export model mới (để Alembic/metadata thấy). | 1 |
| `apps/backend/alembic/versions/d1e2f3a4b5c6_add_email_delivery_email1.py` | **Tạo.** Migration viết tay. | 1 |
| `apps/backend/app/services/email_service.py` | **Sửa.** Trả `resend_email_id`; giữ nhịp + retry + phân loại lỗi; `reply_to` + `text`. | 2·3·4 |
| `apps/backend/app/agents/nodes/scheduler.py` | **Sửa.** `_dispatch` ghi hàng `email_delivery`. Đây là chỗ DUY NHẤT sửa ở tầng scheduler. | 2 |
| `apps/backend/app/services/email_templates.py` | **Sửa.** Chèn URL thô vào `interview_reminder_email` để bản `text` không mất link huỷ. | 4 |
| `apps/backend/app/core/webhook_signature.py` | **Tạo.** Verify chữ ký Svix bằng stdlib. Thuần hàm, 0 I/O. | 5 |
| `apps/backend/app/api/routes/webhooks.py` | **Tạo.** `POST /api/webhooks/resend` — verify → parse → giao cho service. | 6 |
| `apps/backend/app/main.py` | **Sửa.** Đăng ký router webhook (KHÔNG `require_hr`). | 6 |
| `apps/backend/app/services/email_delivery.py` | **Tạo.** Nghiệp vụ: chuyển trạng thái giao hàng, bảng quyết định bounce, gắn/gỡ cờ, audit. | 7 |
| `apps/backend/app/schemas/application.py` | **Sửa.** Validate email chặt-prod/nới-dev; `email_bounced` + `email_bounce_reason`. | 8·9 |
| `apps/backend/app/api/routes/applications.py` | **Sửa.** Nạp `email_bounce_reason` ở endpoint chi tiết. | 9 |
| `packages/shared-types/src/index.ts` | **Sửa.** Hai trường mới. | 9 |
| `apps/dashboard/app/(hr)/applications/page.tsx` · `[id]/page.tsx` · `components/ReviewCard.tsx` | **Sửa.** Nhãn ⚠ bounce. | 9 |
| `apps/backend/tests/test_email_delivery.py` | **Tạo.** Model + `_dispatch` ghi hàng + giữ nhịp/retry. | 1·2·3 |
| `apps/backend/tests/test_webhook_resend.py` | **Tạo.** Chữ ký, middleware, idempotent, bảng bounce. | 5·6·7 |
| `apps/backend/tests/test_email.py` · `test_public_apply.py` · `test_hardening.py` | **Sửa.** Cập nhật fake `_send_sync`; test validate email; test miễn trừ webhook. | 3·4·6·8 |
| `.env.example` · `docs/AI_GUIDE.md` · `CLAUDE.md` | **Sửa.** Env mới + gotcha mới + trạng thái lát. | 10 |

---

## Task 1: Bảng `email_delivery` — model + migration

**Files:**
- Create: `apps/backend/app/models/email_delivery.py`
- Modify: `apps/backend/app/models/__init__.py`
- Create: `apps/backend/alembic/versions/d1e2f3a4b5c6_add_email_delivery_email1.py`
- Test: `apps/backend/tests/test_email_delivery.py`

**Interfaces:**
- Produces: `EmailKind` (str enum, 9 giá trị) · `DeliveryStatus` (str enum: `SENT`/`DELIVERED`/`BOUNCED`/`COMPLAINED`) · `outranks(new: str, current: str) -> bool` · model `EmailDelivery` với cột `id, resend_email_id, application_id, kind, recipient, status, bounce_reason, created_at, updated_at`.

- [ ] **Bước 1: Tách branch từ `main`**

```bash
git -C d:/Web/Project/DATN checkout main
git -C d:/Web/Project/DATN pull --ff-only 2>/dev/null || true
git -C d:/Web/Project/DATN checkout -b fix/email-hardening
git -C d:/Web/Project/DATN log --oneline -1     # kỳ vọng: c9fa373 Feature/booking schedule
```

- [ ] **Bước 2: Viết test THẤT BẠI cho model + thứ bậc trạng thái**

Tạo `apps/backend/tests/test_email_delivery.py`:

```python
"""Test EMAIL-1 — bảng lưu vết giao hàng + thứ bậc trạng thái.

Không cần DB: đây là bất biến của MÔ HÌNH (từ vựng `kind` + luật chuyển trạng thái). Phần chạm
DB thật nằm ở `test_webhook_resend.py` (gated).
"""

from __future__ import annotations

from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind, outranks


def test_kind_values_match_scheduler_modes() -> None:
    """`kind` PHẢI là đúng chuỗi `mode` mà scheduler dùng — audit ghi `email_sent:{mode}`, nên đặt
    tên thứ hai là tạo hai từ vựng cho một thứ và không đối soát audit ↔ delivery được nữa."""
    assert {k.value for k in EmailKind} == {
        "invite", "reject", "screener", "screener_reminder",
        "booking_confirmed", "interview_reminder", "booking_reminder", "booking_cancelled",
        "submission_ack",
    }


def test_delivered_outranks_sent() -> None:
    assert outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.SENT.value)


def test_bounce_can_arrive_after_delivered() -> None:
    """Máy chủ nhận báo lại bounce SAU khi đã nhận thư — chuyện thật, phải áp được."""
    assert outranks(DeliveryStatus.BOUNCED.value, DeliveryStatus.DELIVERED.value)


def test_late_delivered_never_erases_bounce() -> None:
    assert not outranks(DeliveryStatus.DELIVERED.value, DeliveryStatus.BOUNCED.value)


def test_duplicate_event_is_noop() -> None:
    """Resend gửi lại sự kiện trùng là bình thường — cùng hạng thì KHÔNG áp lại (idempotent)."""
    for s in DeliveryStatus:
        assert not outranks(s.value, s.value)


def test_unknown_status_never_applied() -> None:
    """Mã lạ (Resend thêm sự kiện mới) KHÔNG được lọt vào cột status."""
    assert not outranks("OPENED", DeliveryStatus.SENT.value)


def test_model_column_default_is_sent() -> None:
    """Cột `status` phải mặc định SENT ở TẦNG MODEL (không phải chỉ ở `_dispatch`): mọi đường ghi
    một hàng giao hàng đều bắt đầu từ 'đã gửi', và webhook chỉ nâng cấp lên từ đó."""
    assert EmailDelivery.__table__.c.status.default.arg == DeliveryStatus.SENT.value
    assert EmailDelivery.__table__.c.resend_email_id.unique is True
    assert EmailDelivery.__table__.c.bounce_reason.nullable is True
```

- [ ] **Bước 3: Chạy test để xác nhận nó HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.models.email_delivery'`

- [ ] **Bước 4: Viết model**

Tạo `apps/backend/app/models/email_delivery.py`:

```python
"""EmailDelivery — lưu vết GIAO HÀNG của từng lá thư (EMAIL-1 · PRD §7.4, §12.4 FR-NOTI-1).

`Emails.send()` trả OK chỉ nghĩa là **Resend đã nhận**. Bounce xảy ra bất đồng bộ vài giây tới
vài phút sau, qua webhook — nên phải có một hàng để webhook đó tra vào. Khoá đối chiếu là
`resend_email_id`: đây là thứ DUY NHẤT hai bên cùng biết.

Bảng riêng chứ không phải một cột trên `application`: một hồ sơ nhận NHIỀU thư (mời, nhắc, xác
nhận, huỷ) và mỗi lá có số phận giao hàng riêng — thư mời bounce là chuyện khác hẳn thư nhắc
bounce (xem bảng quyết định ở `services/email_delivery`).
"""

from __future__ import annotations

import enum

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class EmailKind(str, enum.Enum):
    """Loại thư. Giá trị PHẢI TRÙNG chuỗi `mode` của `scheduler._dispatch`.

    Lý do là một bất biến chứ không phải sở thích: audit_log đã ghi `email_sent:{mode}` từ lát 04,
    nên đặt tên thứ hai ở đây là tạo hai từ vựng cho cùng một thứ — và lúc truy vết sự cố thì
    không nối được dòng audit với hàng giao hàng nữa.
    """

    INVITE = "invite"
    REJECT = "reject"
    SCREENER = "screener"
    SCREENER_REMINDER = "screener_reminder"
    BOOKING_CONFIRMED = "booking_confirmed"
    INTERVIEW_REMINDER = "interview_reminder"
    BOOKING_REMINDER = "booking_reminder"
    BOOKING_CANCELLED = "booking_cancelled"
    # ĐỂ DÀNH: hệ thống hiện KHÔNG gửi thư xác nhận nộp CV (thêm nó là feature mới — xem spec §2
    # quyết định #3). Giữ giá trị + phân loại bounce sẵn để sau này bật lên không phải đụng enum.
    SUBMISSION_ACK = "submission_ack"


class DeliveryStatus(str, enum.Enum):
    """Số phận một lá thư. Lưu dạng String như `ApplicationStatus`/`BookingStatus`."""

    SENT = "SENT"
    DELIVERED = "DELIVERED"
    BOUNCED = "BOUNCED"
    COMPLAINED = "COMPLAINED"


# Thứ bậc — MỘT quy tắc lo cả hai chuyện: thứ tự sự kiện lẫn idempotency.
#
# Resend KHÔNG bảo đảm thứ tự và có gửi lại sự kiện trùng. Nếu cứ tới đâu ghi đè đó thì một
# `delivered` tới muộn sẽ XOÁ dấu bounce — hồ sơ vừa được gắn cờ lại sạch sẽ trở lại, và HR không
# bao giờ biết. Chỉ áp khi hạng CAO HƠN: `delivered` (1) không đè được `bounced` (2), sự kiện
# trùng cùng hạng là no-op, và bounce tới SAU delivered (chuyện thật — máy chủ nhận báo lại) vẫn áp
# được vì 2 > 1.
_RANK: dict[str, int] = {
    DeliveryStatus.SENT.value: 0,
    DeliveryStatus.DELIVERED.value: 1,
    DeliveryStatus.BOUNCED.value: 2,
    DeliveryStatus.COMPLAINED.value: 3,
}


def outranks(new: str, current: str) -> bool:
    """`new` có được phép ghi đè `current` không. Mã lạ → False (không bao giờ lọt vào cột)."""
    return _RANK.get(new, -1) > _RANK.get(current, -1)


class EmailDelivery(Base, TimestampMixin):
    __tablename__ = "email_delivery"

    id: Mapped[int] = mapped_column(primary_key=True)
    # KHOÁ ĐỐI CHIẾU với webhook. unique để sự kiện trùng tra ra đúng một hàng; NOT NULL vì hàng
    # không có id thì webhook chẳng bao giờ tìm thấy — vô dụng, xem `_dispatch` (bỏ qua, chỉ log).
    resend_email_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # nullable: chừa đường cho thư KHÔNG thuộc hồ sơ nào (chưa có, nhưng cột này rẻ hơn migration
    # sau). CASCADE giống `audit_log` — xoá hồ sơ thì vết giao hàng đi theo.
    application_id: Mapped[int | None] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=True, index=True
    )
    kind: Mapped[str] = mapped_column(String(32), index=True)
    recipient: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(
        String(16), default=DeliveryStatus.SENT.value, index=True
    )
    # Lý do bounce rút gọn từ Resend — hiện cho HR ở trang chi tiết. CẮT NGẮN ở tầng service
    # (`_MAX_REASON`), không tin độ dài do bên ngoài gửi tới.
    bounce_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<EmailDelivery id={self.id} app={self.application_id} "
            f"kind={self.kind} status={self.status}>"
        )
```

- [ ] **Bước 5: Export model để Alembic/metadata thấy**

Mở `apps/backend/app/models/__init__.py`, thêm import + `__all__` entry theo ĐÚNG nếp file đó đang
dùng cho `booking` (đọc file trước rồi bắt chước; không đổi định dạng sẵn có).

- [ ] **Bước 6: Chạy lại test**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py -q`
Expected: PASS (7 test)

- [ ] **Bước 7: Viết migration TAY**

Tạo `apps/backend/alembic/versions/d1e2f3a4b5c6_add_email_delivery_email1.py`:

```python
"""add email_delivery (EMAIL-1 — lưu vết giao hàng + khoá đối chiếu webhook)

Revision ID: d1e2f3a4b5c6
Revises: a3b4c5d6e7f8
Create Date: 2026-08-10

HAND-WRITTEN (KHÔNG autogenerate) — cùng lý do như c7d8e9f0a1b2/f1a2b3c4d5e6: autogenerate nhìn
thấy các bảng checkpoint của LangGraph (`checkpoints`/`checkpoint_blobs`/`checkpoint_writes`/
`checkpoint_migrations`) không có trong `Base.metadata` và sẽ đề xuất DROP chúng — mất suspend/resume
08a. `_include_object` trong `alembic/env.py` đã chặn sẵn; migration viết tay thì không có cửa lọt.

`resend_email_id` UNIQUE là chốt idempotency ở tầng DB: webhook nhận sự kiện trùng vẫn chỉ có một
hàng để cập nhật, không sinh bản sao.
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: str | None = 'a3b4c5d6e7f8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "email_delivery",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resend_email_id", sa.String(length=64), nullable=False),
        sa.Column(
            "application_id",
            sa.Integer(),
            sa.ForeignKey("application.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("recipient", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="SENT"),
        sa.Column("bounce_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_email_delivery_resend_email_id", "email_delivery", ["resend_email_id"], unique=True
    )
    op.create_index("ix_email_delivery_application_id", "email_delivery", ["application_id"])
    op.create_index("ix_email_delivery_kind", "email_delivery", ["kind"])
    op.create_index("ix_email_delivery_status", "email_delivery", ["status"])


def downgrade() -> None:
    op.drop_index("ix_email_delivery_status", table_name="email_delivery")
    op.drop_index("ix_email_delivery_kind", table_name="email_delivery")
    op.drop_index("ix_email_delivery_application_id", table_name="email_delivery")
    op.drop_index("ix_email_delivery_resend_email_id", table_name="email_delivery")
    op.drop_table("email_delivery")
```

- [ ] **Bước 8: Chạy migration + xác minh 4 bảng checkpoint còn sống**

```bash
cd d:/Web/Project/DATN && make migrate
uv run --directory apps/backend python -c "
import asyncio
from sqlalchemy import text
from app.core.database import engine
async def main():
    async with engine.connect() as c:
        r = await c.execute(text(\"select tablename from pg_tables where schemaname='public' and (tablename like 'checkpoint%' or tablename='email_delivery') order by 1\"))
        print([x[0] for x in r])
    await engine.dispose()
asyncio.run(main())
"
```
Expected: `['checkpoint_blobs', 'checkpoint_migrations', 'checkpoint_writes', 'checkpoints', 'email_delivery']` — đủ **5** tên (4 checkpoint SỐNG + bảng mới).

- [ ] **Bước 9: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add apps/backend/app/models/email_delivery.py apps/backend/app/models/__init__.py apps/backend/alembic/versions/d1e2f3a4b5c6_add_email_delivery_email1.py apps/backend/tests/test_email_delivery.py
git -C d:/Web/Project/DATN commit -m "feat(email): bảng email_delivery + khoá đối chiếu resend_email_id"
```

---

## Task 2: `send_email` trả email id · `_dispatch` ghi hàng giao hàng

**Files:**
- Modify: `apps/backend/app/services/email_service.py:23-61`
- Modify: `apps/backend/app/agents/nodes/scheduler.py:69-107` (chỉ `_dispatch`)
- Modify: `apps/backend/tests/test_email.py`
- Test: `apps/backend/tests/test_email_delivery.py` (thêm)

**Interfaces:**
- Consumes: `EmailKind`, `DeliveryStatus`, `EmailDelivery` (Task 1).
- Produces: `email_service.send_email(...) -> str | None` (trả `resend_email_id`, `None` khi Resend không trả id) · `email_service._send_sync(to, subject, html, attachments) -> dict | None`.

> **KHÔNG sửa 10 nơi gọi `notify_*`.** `_dispatch` đã có `mode`, `application_id`, `applicant_email`
> và một `session` đang mở để ghi audit — nó là caller DUY NHẤT của `send_email`. Thêm `kind` /
> `application_id` vào chữ ký `send_email` (như plan gốc phác) chỉ là luồn dữ liệu đi vòng.

- [ ] **Bước 1: Viết test THẤT BẠI — `_dispatch` ghi đúng một hàng `email_delivery`**

Thêm vào `apps/backend/tests/test_email_delivery.py`:

```python
import pytest

from app.agents.nodes import scheduler
from app.models.audit_log import AuditLog
from app.models.email_delivery import EmailDelivery


class FakeSession:
    """AsyncSession tối thiểu — cùng khuôn với tests/test_scheduler_email.py."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, obj) -> None:
        self.added.append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        pass

    async def refresh(self, _obj) -> None:
        pass


def _deliveries(session: FakeSession) -> list[EmailDelivery]:
    return [o for o in session.added if isinstance(o, EmailDelivery)]


async def test_dispatch_records_delivery_row(monkeypatch) -> None:
    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return "email_abc123"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()

    out = await scheduler.notify_decision(
        session, "invite", application_id=42, applicant_email="a@e.com",
        candidate_name="A", job_title="Backend",
        booking_url="http://localhost:3000/booking/tok", deadline_text="72 giờ",
    )

    assert out["email_sent"] is True
    rows = _deliveries(session)
    assert len(rows) == 1
    assert rows[0].resend_email_id == "email_abc123"
    assert rows[0].kind == EmailKind.INVITE.value
    assert rows[0].application_id == 42
    assert rows[0].recipient == "a@e.com"
    assert rows[0].status == DeliveryStatus.SENT.value


async def test_dispatch_skips_delivery_row_when_no_email_id(monkeypatch) -> None:
    """Không có id thì webhook không bao giờ tra được — hàng đó vô dụng, đừng ghi rác."""

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        return None

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    session = FakeSession()
    await scheduler.notify_decision(
        session, "reject", application_id=43, applicant_email="b@e.com",
        candidate_name="B", job_title="Kế toán",
    )
    assert _deliveries(session) == []
    assert any(isinstance(o, AuditLog) for o in session.added)  # audit VẪN ghi


async def test_dispatch_records_no_row_when_send_fails(monkeypatch) -> None:
    async def boom(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        raise scheduler.email_service.EmailError("Resend down")

    monkeypatch.setattr(scheduler.email_service, "send_email", boom)
    session = FakeSession()
    out = await scheduler.notify_decision(
        session, "reject", application_id=44, applicant_email="c@e.com",
        candidate_name="C", job_title="X",
    )
    assert out["email_sent"] is False
    assert _deliveries(session) == []


async def test_dispatch_uses_mode_verbatim_as_kind(monkeypatch) -> None:
    """Bất biến từ vựng, kiểm qua ĐƯỜNG THẬT: `kind` của hàng ghi ra phải khớp hậu tố của dòng audit
    `email_sent:{mode}`. Hai giá trị đó lệch nhau là lúc audit và vết giao hàng thôi đối soát được."""
    monkeypatch.setattr(
        scheduler.email_service, "send_email",
        lambda **_kw: _async_value("e_mode"),  # xem helper bên dưới
    )
    session = FakeSession()
    await scheduler.notify_screener(
        session, application_id=7, applicant_email="a@e.com", candidate_name="A",
        job_title="B", form_url="http://x.test/screening/t", deadline_text="72 giờ",
        reminder=True,
    )
    kind = _deliveries(session)[0].kind
    actions = [a.action for a in session.added if isinstance(a, AuditLog)]
    assert f"email_sent:{kind}" in actions
    assert kind == EmailKind.SCREENER_REMINDER.value
```

Kèm helper nhỏ ở đầu phần test đó (để `monkeypatch.setattr` gán được một hàm async bằng `lambda`):

```python
async def _async_value(value):  # noqa: ANN001, ANN202
    return value
```

- [ ] **Bước 2: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py -q`
Expected: FAIL — `assert len(rows) == 1` nhận `0` (chưa ghi hàng nào).

- [ ] **Bước 3: `send_email` trả về email id**

Trong `apps/backend/app/services/email_service.py`, đổi `_send_sync` để **trả** phản hồi Resend và
`send_email` để bóc `id` ra:

```python
def _send_sync(to: str, subject: str, html: str, attachments: list[dict] | None) -> dict | None:
    """Gọi Resend SDK (đồng bộ) — chạy trong thread riêng qua asyncio.to_thread. Trả phản hồi thô."""
    import resend

    resend.api_key = settings.resend_api_key
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "html": html}
    if attachments:
        payload["attachments"] = attachments
    return resend.Emails.send(payload)
```

và cuối `send_email`:

```python
    try:
        response = await asyncio.to_thread(_send_sync, to, subject, html, encoded)
    except Exception as exc:  # noqa: BLE001 — gói mọi lỗi Resend/mạng thành EmailError rõ ràng
        raise EmailError(f"Resend gửi email thất bại: {exc}") from exc

    # ID của Resend là KHOÁ ĐỐI CHIẾU duy nhất với webhook (EMAIL-1). Thiếu nó thì lá thư này không
    # theo dõi được nữa — vẫn coi là gửi THÀNH CÔNG (Resend đã nhận), chỉ mất khả năng đối soát;
    # ném ở đây sẽ biến một lá thư đã bay đi thành "gửi hỏng", đúng lớp trạng-thái-nói-dối ngược.
    email_id = (response or {}).get("id") if isinstance(response, dict) else None
    if not email_id:
        logger.warning("email: Resend KHÔNG trả email id (subject=%r) — không theo dõi được bounce", subject)
    logger.info("email: đã gửi tới %s (id=%s)", to, email_id)
    return email_id
```

Đổi chữ ký thành `-> str | None` và cập nhật docstring (nói rõ trả gì + vì sao thiếu id không phải lỗi).
**Bỏ** dòng log cũ có `subject=%r` kèm địa chỉ đầy đủ nếu nó trùng lặp — giữ đúng một dòng log/lượt gửi.

- [ ] **Bước 4: `_dispatch` ghi hàng `email_delivery`**

Trong `apps/backend/app/agents/nodes/scheduler.py`, thêm import model rồi sửa nhánh thành công của
`_dispatch` (KHÔNG import `services/email_delivery` — sẽ tạo vòng import qua `booking_flow`):

```python
from app.models.email_delivery import DeliveryStatus, EmailDelivery
```

```python
    logger.info("[scheduler] app=%s: đã gửi email %s tới %s", application_id, mode, applicant_email)
    # Lưu vết GIAO HÀNG (EMAIL-1). Cùng transaction với audit bên dưới: hai bản ghi này nói về cùng
    # một sự kiện, tách ra là mở cửa cho "có audit mà không có vết giao hàng". Thiếu `email_id`
    # (Resend không trả) → BỎ QUA: một hàng không có khoá đối chiếu thì webhook chẳng bao giờ tìm
    # thấy, giữ lại chỉ là rác. `mode` đi thẳng vào `kind` — MỘT từ vựng, xem models/email_delivery.
    if email_id:
        session.add(
            EmailDelivery(
                resend_email_id=email_id,
                application_id=application_id,
                kind=mode,
                recipient=applicant_email,
                status=DeliveryStatus.SENT.value,
            )
        )
    await audit_service.record(
        session, application_id=application_id, node="scheduler", action=f"email_sent:{mode}",
        detail={"mode": mode, "to": applicant_email, "email_id": email_id, **(detail or {})},
        commit=True,
    )
```

với `email_id` lấy từ lượt gửi:

```python
    try:
        email_id = await email_service.send_email(
            to=applicant_email, subject=subject, html=html, attachments=attachments
        )
    except Exception as exc:  # noqa: BLE001 — nuốt có kiểm soát: email lỗi KHÔNG làm sập luồng
        ...  # giữ NGUYÊN khối except hiện có
```

- [ ] **Bước 5: Cập nhật `tests/test_email.py` cho chữ ký trả-về mới**

Ba fake `_send_sync` trong file đó đang trả `None` — thêm `return {"id": "email_test"}` vào
`fake_send` của `test_send_email_success_passes_params` và
`test_send_email_encodes_attachment_base64`, rồi thêm một khẳng định mới:

```python
async def test_send_email_returns_resend_id(monkeypatch) -> None:
    """ID trả về là KHOÁ ĐỐI CHIẾU với webhook — mất nó là mất khả năng phát hiện bounce."""
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {"id": "email_xyz"})
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "email_xyz"


async def test_send_email_tolerates_missing_id(monkeypatch) -> None:
    """Resend không trả id → thư VẪN coi là đã gửi (nó đã bay đi), chỉ mất đường theo dõi."""
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {})
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") is None
```

- [ ] **Bước 6: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py tests/test_email.py tests/test_scheduler_email.py -q`
Expected: PASS toàn bộ.

- [ ] **Bước 7: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(email): send_email trả resend_email_id + _dispatch ghi vết giao hàng"
```

---

## Task 3: Giữ nhịp < 2 req/s + retry có backoff

**Files:**
- Modify: `apps/backend/app/core/config.py` (thêm 2 env)
- Modify: `apps/backend/app/services/email_service.py`
- Test: `apps/backend/tests/test_email_delivery.py` (thêm mục "giữ nhịp/retry")

**Interfaces:**
- Consumes: `send_email` (Task 2).
- Produces: `email_service.EmailQuotaExhausted(EmailError)` · điểm tiêm test `email_service._sleep` và `email_service._monotonic` · `email_service._classify(exc) -> str` (`"retry"`/`"quota"`/`"permanent"`).

- [ ] **Bước 1: Thêm env**

Trong `apps/backend/app/core/config.py`, ngay dưới `email_from`:

```python
    # ── Giữ nhịp + retry khi gọi Resend (EMAIL-1) ────────────────────
    # Resend giới hạn 2 req/s. Sweep loop (08c + SCH-3) có thể bắn nhiều thư trong MỘT vòng, nên
    # lượt gửi được NỐI TIẾP HOÁ và cách nhau ít nhất ngần này — tự đâm giới hạn của chính mình là
    # lỗi ta gây ra, không phải lỗi ngoại cảnh. 550ms > 500ms để có biên an toàn.
    email_min_interval_ms: int = 550
    # Số lần thử lại tối đa cho lỗi TẠM THỜI (429 do bùng nổ, 5xx, lỗi mạng). KHÔNG áp cho lỗi
    # vĩnh viễn (400/422 — địa chỉ sai định dạng) và KHÔNG áp cho cạn quota ngày/tháng: thử lại
    # một hạn mức đã cạn chỉ làm chậm mọi lá thư khác đang xếp hàng sau.
    email_max_retries: int = 3
```

- [ ] **Bước 2: Viết test THẤT BẠI cho nhịp + phân loại lỗi**

Thêm vào `apps/backend/tests/test_email_delivery.py`:

```python
# ── Giữ nhịp + retry (EMAIL-1 §3.3) ──────────────────────────────────────────
from app.services import email_service


@pytest.fixture
def paced(monkeypatch):
    """Thời gian + sleep được TIÊM VÀO (như RateLimiter của hardening) — test không ngủ thật."""
    clock = {"t": 1000.0}
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)
        clock["t"] += seconds

    monkeypatch.setattr(email_service, "_monotonic", lambda: clock["t"])
    monkeypatch.setattr(email_service, "_sleep", fake_sleep)
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_min_interval_ms", 550)
    monkeypatch.setattr(email_service.settings, "email_max_retries", 3)
    return slept


async def test_consecutive_sends_keep_min_interval(paced, monkeypatch) -> None:
    """Ba lượt gửi liên tiếp phải cách nhau ≥ EMAIL_MIN_INTERVAL_MS — sweep bắn cả cụm là chuyện thường."""
    monkeypatch.setattr(email_service, "_send_sync", lambda *a: {"id": "e"})
    for _ in range(3):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    # lượt đầu không phải chờ; hai lượt sau mỗi lượt ngủ đúng 0.55s
    assert [round(s, 3) for s in paced if s > 0] == [0.55, 0.55]


def _resend_error(code, error_type):  # noqa: ANN001, ANN202
    from resend.exceptions import ResendError

    return ResendError(code=code, error_type=error_type, message="x", suggested_action="")


async def test_retries_on_burst_rate_limit_then_succeeds(paced, monkeypatch) -> None:
    calls = {"n": 0}

    def flaky(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise _resend_error("429", "rate_limit_exceeded")
        return {"id": "e_ok"}

    monkeypatch.setattr(email_service, "_send_sync", flaky)
    assert await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>") == "e_ok"
    assert calls["n"] == 2


async def test_does_not_retry_permanent_error(paced, monkeypatch) -> None:
    """400 = địa chỉ sai định dạng. Thử lại 3 lần chỉ tốn 3 lượt gọi và vẫn hỏng y hệt."""
    calls = {"n": 0}

    def bad(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("400", "validation_error")

    monkeypatch.setattr(email_service, "_send_sync", bad)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 1


async def test_daily_quota_is_distinguishable_and_not_retried(paced, monkeypatch) -> None:
    """Cạn quota ngày là tài nguyên DÙNG CHUNG cạn: mọi ứng viên khác cũng câm. Phải phân biệt được."""
    calls = {"n": 0}

    def quota(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("429", "daily_quota_exceeded")

    monkeypatch.setattr(email_service, "_send_sync", quota)
    with pytest.raises(email_service.EmailQuotaExhausted):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 1


async def test_gives_up_after_max_retries(paced, monkeypatch) -> None:
    calls = {"n": 0}

    def always_429(*_a):  # noqa: ANN002, ANN202
        calls["n"] += 1
        raise _resend_error("429", "rate_limit_exceeded")

    monkeypatch.setattr(email_service, "_send_sync", always_429)
    with pytest.raises(email_service.EmailError):
        await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert calls["n"] == 4  # 1 lượt đầu + 3 lần thử lại
```

- [ ] **Bước 3: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py -q -k "paced or interval or retr or quota"`
Expected: FAIL — `AttributeError: module 'app.services.email_service' has no attribute '_monotonic'`

- [ ] **Bước 4: Cài đặt giữ nhịp + retry**

Trong `apps/backend/app/services/email_service.py`, thêm ở đầu module:

```python
import asyncio
import base64
import random
import time

# Điểm TIÊM cho test (cùng triết lý `now` của core/hardening.RateLimiter): thời gian và giấc ngủ đi
# qua hai tên module-level, nên test đo được nhịp mà không phải ngủ thật.
_sleep = asyncio.sleep
_monotonic = time.monotonic

# Nối tiếp hoá MỌI lượt gọi Resend trong tiến trình. Không có nó thì sweep loop (08c + SCH-3) bắn
# cả cụm thư trong một vòng và tự đâm giới hạn 2 req/s của chính mình — rồi vì lá thư đó không có
# đường thử lại, nó mất luôn. Giữ khoá QUA CẢ vòng retry là CÓ CHỦ Ý: 429 nghĩa là "chậm lại", nên
# để lượt gửi khác chen vào giữa lúc đang lùi là làm hỏng đúng thứ ta đang sửa.
_send_lock = asyncio.Lock()
_last_send_at: float = 0.0

# Mã HTTP mà thử lại chắc chắn vô ích: sai định dạng / sai khoá / không tồn tại.
_PERMANENT_CODES = frozenset({"400", "401", "403", "404", "422"})
# Hai loại 429 KHÁC NHAU về bản chất: bùng nổ (chậm lại là qua) vs cạn hạn mức ngày/tháng (chờ tới
# ngày mai mới qua). Gộp chung là biến "hệ thống câm cả ngày" thành một dòng log lẫn vào lỗi mạng.
_QUOTA_TYPES = frozenset({"daily_quota_exceeded", "monthly_quota_exceeded"})

_MAX_BACKOFF_SECONDS = 8.0


class EmailQuotaExhausted(EmailError):
    """Cạn hạn mức Resend (ngày/tháng).

    Tách khỏi `EmailError` vì đây KHÔNG phải sự cố của một lá thư mà của **tài nguyên dùng chung**:
    Resend là kênh duy nhất của cả hệ thống, nên cạn quota nghĩa là thư mời, thư từ chối và
    magic-link sàng lọc của MỌI ứng viên khác cũng câm. Nó phải nhìn ra được ngay trong log.
    """


def _classify(exc: Exception) -> str:
    """-> "retry" | "quota" | "permanent". Mặc định "retry" cho lỗi lạ/lỗi mạng (hỏng-mở)."""
    from resend.exceptions import ResendError

    if isinstance(exc, ResendError):
        if getattr(exc, "error_type", "") in _QUOTA_TYPES:
            return "quota"
        if str(getattr(exc, "code", "")) in _PERMANENT_CODES:
            return "permanent"
        return "retry"  # 429 bùng nổ + 5xx + mã chưa biết
    return "retry"  # timeout / lỗi mạng của tầng requests


def _backoff_seconds(attempt: int) -> float:
    """Luỹ thừa + jitter. Jitter để nhiều tiến trình (nếu sau này chạy nhiều instance) không cùng
    thức dậy một lúc rồi lại cùng đâm vào giới hạn."""
    base = min(_MAX_BACKOFF_SECONDS, 0.5 * (2 ** (attempt - 1)))
    return base * (1.0 + random.random() * 0.25)
```

Rồi thay lượt gọi trần trong `send_email` bằng một hàm nối tiếp hoá:

```python
async def _paced_send(
    to: str, subject: str, html: str, attachments: list[dict] | None
) -> dict | None:
    """Gọi Resend đúng nhịp + thử lại lỗi tạm thời. Đây là chỗ DUY NHẤT chạm `_send_sync`."""
    global _last_send_at

    async with _send_lock:
        attempt = 0
        while True:
            wait = (settings.email_min_interval_ms / 1000.0) - (_monotonic() - _last_send_at)
            if wait > 0:
                await _sleep(wait)
            try:
                response = await asyncio.to_thread(_send_sync, to, subject, html, attachments)
            except Exception as exc:  # noqa: BLE001 — phân loại rồi mới quyết thử lại hay không
                # Lượt HỎNG vẫn tính là đã chạm Resend: nó vẫn tiêu một lượt của hạn mức 2 req/s.
                _last_send_at = _monotonic()
                kind = _classify(exc)
                if kind == "quota":
                    logger.error(
                        "email: CẠN HẠN MỨC RESEND — mọi thư của MỌI ứng viên sẽ câm cho tới khi "
                        "hạn mức đặt lại. Chi tiết: %s", exc,
                    )
                    raise EmailQuotaExhausted(f"Cạn hạn mức Resend: {exc}") from exc
                if kind == "permanent" or attempt >= settings.email_max_retries:
                    raise EmailError(f"Resend gửi email thất bại: {exc}") from exc
                attempt += 1
                delay = _backoff_seconds(attempt)
                logger.warning(
                    "email: lỗi tạm thời (%s) — thử lại lần %s/%s sau %.2fs",
                    exc, attempt, settings.email_max_retries, delay,
                )
                await _sleep(delay)
                continue
            _last_send_at = _monotonic()
            return response
```

và trong `send_email` thay `await asyncio.to_thread(_send_sync, ...)` bằng
`response = await _paced_send(to, subject, html, encoded)` — **bỏ** khối `try/except` bọc ngoài cũ
(việc gói lỗi nay nằm trong `_paced_send`; giữ cả hai sẽ biến `EmailQuotaExhausted` thành
`EmailError` thường và mất đúng thứ vừa xây).

- [ ] **Bước 5: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py tests/test_email.py -q`
Expected: PASS.

- [ ] **Bước 6: Test khoá Load boundary — `_dispatch` không mở transaction trước lượt gửi**

Thêm vào `apps/backend/tests/test_email_delivery.py`:

```python
async def test_dispatch_does_not_touch_db_before_sending(monkeypatch) -> None:
    """Retry kéo dài lượt gửi tới ~8s. Nếu `_dispatch` chạm DB TRƯỚC khi gửi thì nó mở một
    transaction và ôm một connection của pool suốt ngần ấy — Load boundary cấm (pool chỉ 15).
    Khoá bằng test vì đây là loại lỗi không có triệu chứng cho tới lúc tải cao."""
    touched_before_send: list[str] = []
    sent = {"done": False}

    class TrackingSession(FakeSession):
        def add(self, obj) -> None:
            if not sent["done"]:
                touched_before_send.append(type(obj).__name__)
            super().add(obj)

        async def flush(self) -> None:
            if not sent["done"]:
                touched_before_send.append("flush")

    async def fake_send(*, to, subject, html, attachments=None):  # noqa: ANN001, ANN003
        sent["done"] = True
        return "e_1"

    monkeypatch.setattr(scheduler.email_service, "send_email", fake_send)
    await scheduler.notify_decision(
        TrackingSession(), "reject", application_id=1, applicant_email="a@e.com",
        candidate_name="A", job_title="B",
    )
    assert touched_before_send == []
```

Run: `uv run --directory apps/backend pytest tests/test_email_delivery.py -q`
Expected: PASS (nếu FAIL thì `_dispatch` đang chạm DB trước lượt gửi — sửa `_dispatch`, đừng sửa test).

- [ ] **Bước 7: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(email): giữ nhịp < 2 req/s + retry backoff 429/5xx, phân biệt cạn quota"
```

---

## Task 4: `reply_to` + bản `text`

**Files:**
- Modify: `apps/backend/app/core/config.py` (thêm `email_reply_to`)
- Modify: `apps/backend/app/services/email_service.py`
- Modify: `apps/backend/app/services/email_templates.py:130-169` (`interview_reminder_email`)
- Modify: `apps/backend/tests/test_email.py`

**Interfaces:**
- Consumes: `_paced_send`, `_send_sync` (Task 3).
- Produces: `send_email(..., text: str | None = None) -> str | None`. `_send_sync(to, subject, html, text, attachments)` — **thêm tham số `text` ở vị trí thứ 4**, mọi fake trong test phải cập nhật.

- [ ] **Bước 1: Thêm env**

```python
    # Địa chỉ nhận thư trả lời (EMAIL-1). Vừa là UX (ứng viên bấm Reply là tới HR thật), vừa là tín
    # hiệu deliverability: địa chỉ gửi kiểu `noreply@` không có hòm thư bị nhà cung cấp trừ điểm.
    # Rỗng = không đặt `reply_to` (giữ nguyên hành vi cũ).
    email_reply_to: str | None = None
```

- [ ] **Bước 2: Viết test THẤT BẠI**

Thêm vào `apps/backend/tests/test_email.py`:

```python
async def test_payload_includes_reply_to_and_text(monkeypatch) -> None:
    """Reply phải về hòm thư HR thật, và multipart (text + html) giảm tín hiệu spam."""
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_reply_to", "tuyendung@congty.vn")
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    captured: dict = {}
    monkeypatch.setattr(resend.Emails, "send", lambda p: captured.update(p) or {"id": "e"})

    await email_service.send_email(
        to="a@e.com", subject="Mời", html="<p>Xin chào</p><p>http://x.test/booking/tok</p>"
    )

    assert captured["reply_to"] == "tuyendung@congty.vn"
    assert "Xin chào" in captured["text"]
    assert "http://x.test/booking/tok" in captured["text"]  # LINK không được rơi mất ở bản text
    assert "<p>" not in captured["text"]


async def test_reply_to_omitted_when_not_configured(monkeypatch) -> None:
    import resend

    monkeypatch.setattr(email_service.settings, "resend_api_key", "re_test")
    monkeypatch.setattr(email_service.settings, "email_reply_to", None)
    monkeypatch.setattr(email_service, "_last_send_at", 0.0)
    captured: dict = {}
    monkeypatch.setattr(resend.Emails, "send", lambda p: captured.update(p) or {"id": "e"})
    await email_service.send_email(to="a@e.com", subject="s", html="<p>h</p>")
    assert "reply_to" not in captured
```

Và một test cho template (cùng file `test_email.py`):

```python
def test_interview_reminder_keeps_raw_url_for_text_part() -> None:
    """`html_to_text` BỎ href, chỉ giữ text-node. Thư nhắc trước buổi PV mà chỉ có <a> thì bản text
    mất nút huỷ — đúng lúc ứng viên cần nó nhất. Mọi template có link đều in cả URL thô."""
    from app.core.html_text import html_to_text
    from app.services.email_templates import interview_reminder_email
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 8, 20, 2, 0, tzinfo=timezone.utc)
    _, html = interview_reminder_email(
        "A", "Backend", start_at=start, end_at=start + timedelta(hours=1),
        manage_url="http://x.test/booking/tok",
    )
    assert "http://x.test/booking/tok" in html_to_text(html)
```

- [ ] **Bước 3: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_email.py -q`
Expected: FAIL — `KeyError: 'reply_to'` và test template FAIL (URL không có trong bản text).

- [ ] **Bước 4: Thêm `reply_to` + `text` vào payload**

`apps/backend/app/services/email_service.py`:

```python
def _send_sync(
    to: str, subject: str, html: str, text: str, attachments: list[dict] | None
) -> dict | None:
    """Gọi Resend SDK (đồng bộ) — chạy trong thread riêng qua asyncio.to_thread. Trả phản hồi thô."""
    import resend

    resend.api_key = settings.resend_api_key
    payload: dict = {"from": settings.email_from, "to": [to], "subject": subject, "html": html}
    if text:
        payload["text"] = text
    if settings.email_reply_to:
        payload["reply_to"] = settings.email_reply_to
    if attachments:
        payload["attachments"] = attachments
    return resend.Emails.send(payload)
```

Thêm import ở đầu `email_service.py`: `from app.core.html_text import html_to_text`.

Trong `send_email`, thêm tham số + dẫn xuất bản text:

```python
async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> str | None:
    # (giữ NGUYÊN phần đầu thân hàm: kiểm `settings.resend_api_key` + mã hoá base64 `attachments`)
    # Bản THUẦN VĂN BẢN đi kèm HTML (multipart): thư chỉ-HTML là một tín hiệu spam kinh điển, và
    # một số ứng dụng mail vẫn hiển thị bản text. Dùng lại `html_to_text` (JD-1, 0-dependency).
    # ⚠ `html_to_text` chỉ giữ TEXT-NODE, không giữ href — nên mọi template có liên kết đều in cả
    # URL thô ra thân thư (xem email_templates); mất bất biến đó là bản text mất luôn link.
    body_text = text if text is not None else html_to_text(html)
```

rồi truyền vào `_paced_send(to, subject, html, body_text, encoded)` và cập nhật `_paced_send` để
nhận thêm `text`.

- [ ] **Bước 5: Vá `interview_reminder_email`**

Trong `apps/backend/app/services/email_templates.py`, nhánh `if manage_url:` của
`interview_reminder_email` hiện chỉ có thẻ `<a>`. Thêm dòng URL thô cho khớp bốn template anh em:

```python
        change = (
            "<p>Nếu có việc đột xuất, bạn có thể huỷ hoặc chọn giờ khác tại đây:</p>"
            f'<p><a href="{href}">Xem hoặc huỷ lịch phỏng vấn</a></p>'
            # URL thô: `html_to_text` (bản text của thư) chỉ giữ text-node, không giữ href — thiếu
            # dòng này là bản text mất nút huỷ đúng lúc ứng viên cần nó nhất.
            f'<p style="word-break:break-all;color:#475569">{href}</p>'
        )
```

- [ ] **Bước 6: Cập nhật các fake `_send_sync` cũ (thêm tham số `text`)**

Trong `tests/test_email.py`: `boom(to, subject, html, attachments)` →
`boom(to, subject, html, text, attachments)`; tương tự cho hai `fake_send` còn lại. Trong
`test_send_email_success_passes_params`, khẳng định thêm `text` được truyền xuống.

- [ ] **Bước 7: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_email.py tests/test_email_delivery.py -q`
Expected: PASS.

- [ ] **Bước 8: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(email): reply_to + bản text kèm HTML (và giữ URL thô ở thư nhắc PV)"
```

---

## Task 5: Verify chữ ký Svix bằng stdlib

**Files:**
- Create: `apps/backend/app/core/webhook_signature.py`
- Test: `apps/backend/tests/test_webhook_resend.py`

**Interfaces:**
- Produces:
  ```python
  def verify_svix_signature(
      *, secret: str, msg_id: str, timestamp: str, signature_header: str,
      body: bytes, now: float, tolerance_seconds: float,
  ) -> bool
  def sign_svix_payload(*, secret: str, msg_id: str, timestamp: str, body: bytes) -> str  # "v1,<b64>"
  ```
  `sign_svix_payload` tồn tại để **test tự dựng chữ ký hợp lệ** mà không cần gọi Resend; nó cũng là
  bản đặc tả chạy được của thuật toán.

- [ ] **Bước 1: Viết test THẤT BẠI**

Tạo `apps/backend/tests/test_webhook_resend.py`:

```python
"""Test EMAIL-1 — webhook Resend: chữ ký, miễn trừ middleware, idempotent, bảng xử lý bounce.

Webhook là endpoint CÔNG KHAI CÓ MUTATION: không verify chữ ký thì bất kỳ ai cũng giả được sự kiện
bounce và phá hồ sơ của ứng viên thật. Đây là phần được test kỹ nhất của lát này.
"""

from __future__ import annotations

import json

from app.core.webhook_signature import sign_svix_payload, verify_svix_signature

_SECRET = "whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw"  # khoá mẫu của Svix docs — KHÔNG phải secret thật
_ID = "msg_2b3c"
_TS = "1786000000"
_NOW = 1786000000.0
_BODY = b'{"type":"email.bounced","data":{"email_id":"e_1"}}'


def _sig() -> str:
    return sign_svix_payload(secret=_SECRET, msg_id=_ID, timestamp=_TS, body=_BODY)


def _verify(**over) -> bool:  # noqa: ANN003
    kw = dict(
        secret=_SECRET, msg_id=_ID, timestamp=_TS, signature_header=_sig(),
        body=_BODY, now=_NOW, tolerance_seconds=300.0,
    )
    kw.update(over)
    return verify_svix_signature(**kw)


def test_valid_signature_passes() -> None:
    assert _verify() is True


def test_tampered_body_fails() -> None:
    assert _verify(body=b'{"type":"email.bounced","data":{"email_id":"e_HACKED"}}') is False


def test_wrong_secret_fails() -> None:
    assert _verify(secret="whsec_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=") is False


def test_missing_signature_fails() -> None:
    assert _verify(signature_header="") is False


def test_replay_outside_tolerance_fails() -> None:
    """Chữ ký ĐÚNG nhưng cũ: kẻ chặn được một request hợp lệ sẽ phát lại nó mãi mãi nếu không chặn."""
    assert _verify(now=_NOW + 301.0) is False
    assert _verify(now=_NOW - 301.0) is False


def test_within_tolerance_passes() -> None:
    assert _verify(now=_NOW + 299.0) is True


def test_garbage_timestamp_fails() -> None:
    assert _verify(timestamp="không-phải-số") is False


def test_accepts_any_matching_version_in_multi_signature_header() -> None:
    """Svix gửi NHIỀU chữ ký khi đang xoay khoá — khớp một cái là đủ."""
    header = f"v1,khongphaichuky {_sig()}"
    assert _verify(signature_header=header) is True


def test_ignores_unknown_signature_version() -> None:
    assert _verify(signature_header="v2,YWJj") is False
```

- [ ] **Bước 2: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.core.webhook_signature'`

- [ ] **Bước 3: Viết bộ verify**

Tạo `apps/backend/app/core/webhook_signature.py`:

```python
"""Verify chữ ký webhook chuẩn Svix — Resend dùng chuẩn này (EMAIL-1).

Thuần stdlib (`hmac`/`hashlib`/`base64`), KHÔNG thêm dependency — cùng nếp `IcsProvider` (SCH-1) và
`html_text` (JD-1). Thuật toán đủ nhỏ để đọc hết trong một màn hình, và test tự dựng được chữ ký
hợp lệ nên không phải gọi mạng để kiểm.

    signed_content = f"{svix-id}.{svix-timestamp}.{raw body}"
    expected       = base64( HMAC-SHA256( base64decode(secret sau 'whsec_'), signed_content ) )

Hai chốt chặn, KHÔNG được bỏ cái nào:
  1) So sánh bằng `hmac.compare_digest` — so bằng `==` rò rỉ thời gian, và đây là thứ duy nhất
     ngăn người lạ giả sự kiện bounce để phá hồ sơ ứng viên thật.
  2) Cửa sổ thời gian theo `svix-timestamp` — chữ ký ĐÚNG mà không có hạn thì một request hợp lệ bị
     chặn lại sẽ phát lại được mãi mãi.

**Body phải là BYTES THÔ.** Parse JSON rồi serialize lại sẽ đổi khoảng trắng/thứ tự khoá và chữ ký
không bao giờ khớp — đây là lỗi #1 khi tự cài verify webhook.
"""

from __future__ import annotations

import base64
import hashlib
import hmac

__all__ = ["sign_svix_payload", "verify_svix_signature"]

_PREFIX = "whsec_"
_VERSION = "v1"


def _key(secret: str) -> bytes | None:
    """`whsec_<base64>` → bytes khoá. Secret hỏng → None (gọi là từ chối, không nổ)."""
    raw = secret[len(_PREFIX):] if secret.startswith(_PREFIX) else secret
    try:
        return base64.b64decode(raw, validate=True)
    except (ValueError, TypeError):
        return None


def _digest(key: bytes, msg_id: str, timestamp: str, body: bytes) -> str:
    signed = b".".join([msg_id.encode("utf-8"), timestamp.encode("utf-8"), body])
    return base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode("ascii")


def sign_svix_payload(*, secret: str, msg_id: str, timestamp: str, body: bytes) -> str:
    """Dựng header `svix-signature` hợp lệ. Dùng cho TEST và để đặc tả thuật toán bằng code chạy được."""
    key = _key(secret)
    if key is None:
        raise ValueError("Secret webhook không hợp lệ (phải là whsec_<base64>).")
    return f"{_VERSION},{_digest(key, msg_id, timestamp, body)}"


def verify_svix_signature(
    *,
    secret: str,
    msg_id: str,
    timestamp: str,
    signature_header: str,
    body: bytes,
    now: float,
    tolerance_seconds: float,
) -> bool:
    """True chỉ khi chữ ký khớp VÀ mốc thời gian nằm trong cửa sổ. Mọi ca bất thường → False.

    `now` được TIÊM VÀO (không gọi `time` bên trong) để test đo được cửa sổ replay mà không phải
    ngủ — cùng triết lý `RateLimiter.allow(..., now)` của `core/hardening`.
    """
    key = _key(secret)
    if key is None or not signature_header:
        return False

    try:
        sent_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(now - sent_at) > tolerance_seconds:
        return False

    expected = _digest(key, msg_id, timestamp, body)
    for part in signature_header.split(" "):
        version, _, candidate = part.partition(",")
        if version != _VERSION or not candidate:
            continue
        if hmac.compare_digest(candidate, expected):
            return True
    return False
```

- [ ] **Bước 4: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py -q`
Expected: PASS (9 test)

- [ ] **Bước 5: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add apps/backend/app/core/webhook_signature.py apps/backend/tests/test_webhook_resend.py
git -C d:/Web/Project/DATN commit -m "feat(email): verify chữ ký webhook Svix bằng stdlib (0 dependency)"
```

---

## Task 6: Endpoint `POST /api/webhooks/resend` + miễn trừ middleware

**Files:**
- Modify: `apps/backend/app/core/config.py` (thêm 2 env)
- Create: `apps/backend/app/api/routes/webhooks.py`
- Modify: `apps/backend/app/main.py:16,116-121`
- Modify: `apps/backend/tests/test_hardening.py`
- Test: `apps/backend/tests/test_webhook_resend.py` (thêm)

**Interfaces:**
- Consumes: `verify_svix_signature` (Task 5).
- Produces: route `POST /api/webhooks/resend`; hàm `webhooks._parse_event(body: bytes) -> dict`.
  Task 7 sẽ nối `email_delivery.handle_event(session, event)` vào đây — ở task này endpoint chỉ
  verify + parse + trả 204 (nghiệp vụ để trống có chủ ý, chia hai task cho reviewer gác được riêng).

- [ ] **Bước 1: Thêm env**

```python
    # ── Webhook Resend (EMAIL-1) ─────────────────────────────────────
    # Secret ký của webhook (`whsec_...`), lấy khi tạo webhook trên dashboard Resend. CHƯA cấu hình
    # → endpoint trả 503 chứ KHÔNG âm thầm nhận: một webhook nhận mọi thứ không ký còn tệ hơn không
    # có webhook, vì bất kỳ ai cũng giả được sự kiện bounce để phá hồ sơ ứng viên thật.
    resend_webhook_secret: str | None = None
    # Cửa sổ chống replay theo `svix-timestamp`. Chữ ký đúng mà không có hạn thì một request hợp lệ
    # bị chặn lại sẽ phát lại được mãi mãi.
    resend_webhook_tolerance_seconds: float = 300.0
```

- [ ] **Bước 2: Viết test THẤT BẠI cho route + middleware**

Thêm vào `apps/backend/tests/test_webhook_resend.py`:

```python
# ── Endpoint ────────────────────────────────────────────────────────────────
import httpx
import pytest

from app.core.hardening import OriginCheckMiddleware, RateLimitMiddleware


def _headers(body: bytes, *, secret: str = _SECRET, ts: str = _TS) -> dict[str, str]:
    return {
        "svix-id": _ID,
        "svix-timestamp": ts,
        "svix-signature": sign_svix_payload(secret=secret, msg_id=_ID, timestamp=ts, body=body),
        "content-type": "application/json",
    }


@pytest.fixture
def client(monkeypatch):
    """App THẬT nhưng chỉ mount router webhook — không kéo theo lifespan/DB của app đầy đủ.

    `get_session` được ghi đè bằng một object rỗng: dependency của FastAPI chạy TRƯỚC thân handler,
    nên không ghi đè thì cả test 401/503 cũng mở một connection Postgres thật (chậm + đòi DB cho
    những test vốn không cần).
    """
    from fastapi import FastAPI

    from app.api.routes import webhooks
    from app.core.database import get_session

    monkeypatch.setattr(webhooks.settings, "resend_webhook_secret", _SECRET)
    monkeypatch.setattr(webhooks.settings, "resend_webhook_tolerance_seconds", 300.0)
    monkeypatch.setattr(webhooks, "_now", lambda: _NOW)

    app = FastAPI()
    app.include_router(webhooks.router, prefix="/api")
    app.dependency_overrides[get_session] = lambda: object()
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_valid_signature_accepted(client, monkeypatch) -> None:
    seen: list[dict] = []
    from app.api.routes import webhooks

    async def fake_handle(_session, event: dict) -> None:  # noqa: ANN001
        seen.append(event)

    monkeypatch.setattr(webhooks, "_handle", fake_handle)
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=_headers(_BODY))
    assert r.status_code == 204
    assert seen and seen[0]["type"] == "email.bounced"


async def test_forged_signature_rejected_401(client, monkeypatch) -> None:
    """Giả mạo → 401 và KHÔNG chạm nghiệp vụ (không có tác dụng phụ nào)."""
    from app.api.routes import webhooks

    async def boom(*_a):  # noqa: ANN002, ANN202
        raise AssertionError("nghiệp vụ KHÔNG được chạy khi chữ ký sai")

    monkeypatch.setattr(webhooks, "_handle", boom)
    bad = dict(_headers(_BODY), **{"svix-signature": "v1,YWJjZA=="})
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=bad)
    assert r.status_code == 401


async def test_missing_signature_headers_rejected_401(client) -> None:
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY,
                         headers={"content-type": "application/json"})
    assert r.status_code == 401


async def test_secret_not_configured_returns_503(client, monkeypatch) -> None:
    """Chưa cấu hình secret → TỪ CHỐI, không phải "cho qua vì chưa bật"."""
    from app.api.routes import webhooks

    monkeypatch.setattr(webhooks.settings, "resend_webhook_secret", None)
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=_BODY, headers=_headers(_BODY))
    assert r.status_code == 503


async def test_invalid_json_with_valid_signature_returns_400(client) -> None:
    body = b"khong-phai-json"
    async with client as c:
        r = await c.post("/api/webhooks/resend", content=body, headers=_headers(body))
    assert r.status_code == 400


# ── Miễn trừ middleware: hành vi ta ĐANG DỰA VÀO mà chưa có test nào giữ ─────
async def test_webhook_is_exempt_from_rate_limit() -> None:
    """Resend gọi từ VÀI IP cố định. Siết theo IP là gom hết vào một xô → 429 → MẤT sự kiện bounce,
    và mất im lặng (Resend thử lại vài lần rồi thôi)."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/api/webhooks/resend")
    async def hook() -> dict:
        return {"ok": True}

    app.add_middleware(
        RateLimitMiddleware, login_max=1, login_window_seconds=60,
        public_max=1, public_window_seconds=60, trust_proxy=False, enabled=True,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        for _ in range(5):
            assert (await c.post("/api/webhooks/resend", json={})).status_code == 200


async def test_webhook_passes_origin_check_without_origin_header() -> None:
    """Request server-to-server KHÔNG có header `Origin` — phải cho qua, nếu không webhook chết hẳn."""
    from fastapi import FastAPI

    app = FastAPI()

    @app.post("/api/webhooks/resend")
    async def hook() -> dict:
        return {"ok": True}

    app.add_middleware(OriginCheckMiddleware, allowed=frozenset({"https://ars.vercel.app"}))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        assert (await c.post("/api/webhooks/resend", json={})).status_code == 200
```

- [ ] **Bước 3: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py -q`
Expected: FAIL — `ImportError: cannot import name 'webhooks' from 'app.api.routes'`

- [ ] **Bước 4: Viết route**

Tạo `apps/backend/app/api/routes/webhooks.py`:

```python
"""Webhook từ nhà cung cấp email (EMAIL-1 · PRD §7.4, §12.4 FR-NOTI-1).

Đây là chiều NGƯỢC LẠI của tầng email: `Emails.send()` trả OK chỉ nghĩa là Resend đã nhận; bounce
tới vài giây–vài phút sau qua endpoint này. Không có nó thì dashboard nói "Đã hẹn phỏng vấn" trong
khi ứng viên chưa từng nhận được thư nào.

**Endpoint CÔNG KHAI CÓ MUTATION** — ba chốt chặn, mỗi cái vá một đường tấn công khác nhau:

1. **Verify chữ ký BẮT BUỘC** (Svix, xem `core/webhook_signature`). Sai/thiếu → 401, KHÔNG chạm
   nghiệp vụ. Thiếu nó thì bất kỳ ai cũng POST được một sự kiện "bounced" để đẩy hồ sơ của ứng viên
   thật về hàng chờ HR.
2. **Chưa cấu hình secret → 503**, không phải "cho qua". Một webhook nhận mọi thứ không ký còn tệ
   hơn không có webhook.
3. **Miễn trừ rate-limit** — Resend gọi từ vài IP cố định, siết theo IP là gom hết vào một xô rồi
   429 và MẤT sự kiện bounce. Hôm nay `RateLimitMiddleware._bucket()` không khớp `/api/webhooks/*`
   nên đã miễn trừ sẵn; `tests/test_webhook_resend.py` khoá lại để lần sửa `_bucket()` sau không
   âm thầm nuốt mất. Cùng lý do với `OriginCheckMiddleware`: request không có header `Origin`
   (server-to-server) được cho qua — đó là hành vi hiện có, nay có test giữ.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.deps import DBSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.webhook_signature import verify_svix_signature
from app.services import email_delivery

logger = get_logger("app.api.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Điểm tiêm cho test (cùng triết lý `now` của RateLimiter) — cửa sổ replay đo được mà không phải ngủ.
_now = time.time
# Gián tiếp qua một tên module-level để test khẳng định được "chữ ký sai ⇒ nghiệp vụ KHÔNG chạy".
_handle = email_delivery.handle_event


@router.post(
    "/resend",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sự kiện giao hàng từ Resend — verify chữ ký rồi cập nhật trạng thái (EMAIL-1)",
)
async def resend_webhook(request: Request, session: DBSession) -> Response:
    if not settings.resend_webhook_secret:
        logger.error("Webhook Resend: RESEND_WEBHOOK_SECRET chưa cấu hình — từ chối mọi sự kiện.")
        raise HTTPException(status_code=503, detail="Webhook chưa được cấu hình.")

    # BYTES THÔ. Parse JSON rồi serialize lại sẽ đổi khoảng trắng/thứ tự khoá ⇒ chữ ký không bao giờ
    # khớp — lỗi #1 khi tự cài verify webhook.
    body = await request.body()
    headers = request.headers
    # Svix đổi tên header sang chuẩn `webhook-*`; chấp nhận cả hai để không vỡ khi Resend nâng cấp.
    msg_id = headers.get("svix-id") or headers.get("webhook-id") or ""
    timestamp = headers.get("svix-timestamp") or headers.get("webhook-timestamp") or ""
    signature = headers.get("svix-signature") or headers.get("webhook-signature") or ""

    if not verify_svix_signature(
        secret=settings.resend_webhook_secret,
        msg_id=msg_id,
        timestamp=timestamp,
        signature_header=signature,
        body=body,
        now=_now(),
        tolerance_seconds=settings.resend_webhook_tolerance_seconds,
    ):
        # KHÔNG nói rõ sai ở đâu (chữ ký / thời gian) — đó là thông tin miễn phí cho người đang dò.
        logger.warning("Webhook Resend: chữ ký KHÔNG hợp lệ (id=%r) — bỏ qua.", msg_id)
        raise HTTPException(status_code=401, detail="Chữ ký không hợp lệ.")

    try:
        event = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Payload không phải JSON hợp lệ.") from None
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Payload không đúng định dạng.")

    await _handle(session, event)
    # 204 kể cả khi không tra được hàng nào: Resend thử lại khi nhận mã lỗi, và thử lại một sự kiện
    # ta cố ý bỏ qua là vô ích cho cả hai bên.
    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

> **Thứ tự thi công: Task 7 chạy TRƯỚC Task 6.** `services/email_delivery.handle_event` là code
> thuần nghiệp vụ, không phụ thuộc gì vào route; còn route thì import nó. Làm ngược lại buộc phải
> tạo một hàm rỗng "điền sau" — và một stub không làm gì là thứ vừa qua được test vừa là defect
> thật. Số hiệu task giữ nguyên (ledger ghi thứ tự chạy thật).

- [ ] **Bước 5: Đăng ký router (KHÔNG `require_hr`)**

Trong `apps/backend/app/main.py`:

```python
from app.api.routes import agents, applications, auth, health, jobs, public, webhooks
```

và, cạnh các `include_router` công khai:

```python
# Webhook nhà cung cấp email (EMAIL-1): CÔNG KHAI có chủ ý — Resend gọi server-to-server, không có
# cookie phiên nào để kiểm. Chốt chặn là CHỮ KÝ (`core/webhook_signature`), không phải `require_hr`.
app.include_router(webhooks.router, prefix="/api")
```

Sửa luôn comment khối `_HR_ONLY` bên trên để liệt kê webhook vào nhóm giữ MỞ (health, auth, public,
webhook) — người sửa sau đọc comment đó để biết cái gì cố ý mở.

- [ ] **Bước 6: Thêm test khoá `_bucket()` ở `tests/test_hardening.py`**

```python
async def test_webhook_path_is_not_rate_limited() -> None:
    """EMAIL-1: `/api/webhooks/*` phải nằm NGOÀI mọi xô quota. Resend gọi từ vài IP cố định — siết
    theo IP là gom cả nhà cung cấp vào một xô rồi 429, và sự kiện bounce mất IM LẶNG."""
    from app.core.hardening import RateLimitMiddleware

    mw = RateLimitMiddleware(
        app=None, login_max=1, login_window_seconds=60, public_max=1,
        public_window_seconds=60, trust_proxy=False,
    )
    assert mw._bucket("/api/webhooks/resend", "POST") is None
```

- [ ] **Bước 7: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py tests/test_hardening.py -q`
Expected: PASS.

- [ ] **Bước 8: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(api): webhook Resend verify chữ ký, miễn trừ rate-limit + CSRF"
```

---

## Task 7: Nghiệp vụ bounce — cập nhật giao hàng, gắn/gỡ cờ, hạ trạng thái CÓ ĐIỀU KIỆN

**Files:**
- Modify (viết đầy): `apps/backend/app/services/email_delivery.py`
- Test: `apps/backend/tests/test_webhook_resend.py` (thêm) + `apps/backend/tests/test_email_delivery_db.py` (tạo, gated)

**Interfaces:**
- Consumes: `EmailDelivery`, `DeliveryStatus`, `EmailKind`, `outranks` (Task 1); `booking_flow.with_flag`; `audit_service.record`.
- Produces: `email_delivery.handle_event(session: AsyncSession, event: dict) -> None` · hằng số `EMAIL_BOUNCED_FLAG = "email_bounced"`.

**Bảng quyết định (spec §5) — cài đúng, không suy diễn thêm:**

| `kind` | Trạng thái thư đó thiết lập | Bounce ⇒ |
|---|---|---|
| `invite` | `AWAITING_BOOKING` | cờ + (nếu status khớp **và** không có `interview_booking` nào `BOOKED`) → `PENDING_REVIEW` |
| `screener` · `screener_reminder` | `AWAITING_SCREENER` | cờ + (nếu status khớp **và** chưa có `screening_session.answers`) → `PENDING_REVIEW` |
| `reject` | — | **chỉ cờ**, GIỮ `REJECTED` (quyết định #4) |
| `booking_confirmed` · `interview_reminder` · `booking_reminder` · `booking_cancelled` | — | **chỉ cờ** |
| `submission_ack` | — | chỉ cờ (chưa có đường phát) |

- [ ] **Bước 1: Viết test THẤT BẠI (thuần, không DB) cho ánh xạ sự kiện**

Thêm vào `apps/backend/tests/test_webhook_resend.py`:

```python
# ── Ánh xạ sự kiện → trạng thái giao hàng ───────────────────────────────────
from app.models.email_delivery import DeliveryStatus
from app.services import email_delivery as svc


def test_event_type_mapping() -> None:
    assert svc.status_for_event("email.sent") == DeliveryStatus.SENT.value
    assert svc.status_for_event("email.delivered") == DeliveryStatus.DELIVERED.value
    assert svc.status_for_event("email.bounced") == DeliveryStatus.BOUNCED.value
    assert svc.status_for_event("email.complained") == DeliveryStatus.COMPLAINED.value


def test_unknown_event_type_ignored() -> None:
    """Resend còn gửi `email.opened`/`email.clicked`/`email.delivery_delayed` — không phải sự kiện
    của ta, và cũng KHÔNG được coi là lỗi (trả 204, đừng bắt Resend thử lại)."""
    assert svc.status_for_event("email.opened") is None
    assert svc.status_for_event("") is None


def test_bounce_reason_extracted_and_truncated() -> None:
    reason = svc.bounce_reason_of({"bounce": {"type": "Permanent", "subType": "General",
                                              "message": "x" * 900}})
    assert reason is not None and len(reason) <= svc._MAX_REASON
    assert "Permanent" in reason


def test_bounce_reason_none_when_absent() -> None:
    assert svc.bounce_reason_of({}) is None


def test_email_id_read_from_either_field() -> None:
    """Payload Resend đã đổi hình dạng giữa các phiên bản tài liệu — đọc cả hai, đừng đoán một."""
    assert svc.email_id_of({"data": {"email_id": "e_1"}}) == "e_1"
    assert svc.email_id_of({"data": {"id": "e_2"}}) == "e_2"
    assert svc.email_id_of({"data": {}}) is None


def test_single_channel_map_excludes_reject() -> None:
    """Quyết định #4: bounce thư TỪ CHỐI chỉ gắn cờ. Hàng chờ HR chỉ có hai nút, và cả hai đều dẫn
    tới hậu quả sai (mời một người đã bị từ chối / bounce vòng hai vào đúng địa chỉ chết)."""
    assert "reject" not in svc._SINGLE_CHANNEL
    assert set(svc._SINGLE_CHANNEL) == {"invite", "screener", "screener_reminder"}
```

- [ ] **Bước 2: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py -q -k "event or bounce_reason or email_id or single_channel"`
Expected: FAIL — `AttributeError: module 'app.services.email_delivery' has no attribute 'status_for_event'`

- [ ] **Bước 3: Viết service**

Viết đầy `apps/backend/app/services/email_delivery.py`:

```python
"""email_delivery — biến sự kiện giao hàng của Resend thành hành động nghiệp vụ (EMAIL-1).

Nguyên tắc trên hết, kế thừa thẳng bài học SCH-3 **"hỏi sự thật, đừng hỏi cờ"**: webhook tới SAU
vài phút, và trong khoảng đó HR có thể đã xử lý, ứng viên có thể đã đặt lịch. Vì vậy mọi lượt hạ
trạng thái đều CÓ ĐIỀU KIỆN — chỉ hạ khi hồ sơ **vẫn đang đứng đúng ở trạng thái mà lá thư đó thiết
lập**, và điều kiện phải hỏi **BẢNG** (`interview_booking`, `screening_session`) chứ không chỉ hỏi
cột trạng thái. Đã đi tiếp thì **chỉ gắn cờ**.

**KHÔNG auto-reject ở bất kỳ nhánh nào.** Thư không tới được ≠ ứng viên bị loại.

Vì sao bounce thư **`reject`** chỉ gắn cờ chứ không hạ về `PENDING_REVIEW`: hàng chờ HR chỉ có hai
nút — "Duyệt → mời phỏng vấn" (mời một người vừa bị từ chối) và "Từ chối → gửi thư từ chối" (bounce
vòng hai vào đúng địa chỉ chết). Hạ trạng thái ở đó là lật ngược một quyết định đã ghi mà không mở
ra hành động đúng nào. HR thấy nhãn ⚠ trên hồ sơ và liên hệ tay.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingStatus, InterviewBooking
from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind, outranks
from app.models.screening_session import ScreeningSession
from app.services import audit_service
from app.services.booking_flow import with_flag

logger = get_logger("app.services.email_delivery")

__all__ = ["EMAIL_BOUNCED_FLAG", "handle_event"]

EMAIL_BOUNCED_FLAG = "email_bounced"

# Lý do escalation là chuỗi CỐ ĐỊNH (không nhét chi tiết bounce vào): chi tiết sống ở
# `email_delivery.bounce_reason` và hiện riêng cho HR. Cố định thì lúc `delivered` về sau, ta so
# khớp được ĐÚNG câu này để gỡ — không xoá nhầm lý do escalation của một chuyện khác.
_REASON_INVITE = "Thư MỜI phỏng vấn không tới được ứng viên — cần liên hệ thủ công."
_REASON_SCREENER = "Thư SÀNG LỌC không tới được ứng viên — cần liên hệ thủ công."
_BOUNCE_REASONS = frozenset({_REASON_INVITE, _REASON_SCREENER})

# kind -> (trạng thái mà thư đó thiết lập, lý do escalation).
# `reject` VẮNG MẶT có chủ ý (xem docstring). `submission_ack` vắng mặt vì chưa có đường phát nào.
# Bốn loại thư đặt lịch còn lại là BIÊN NHẬN — ứng viên đã thấy màn xác nhận trên web hoặc tự bấm,
# nên thư không tới không đổi được sự thật nào; chỉ gắn cờ.
_SINGLE_CHANNEL: dict[str, tuple[str, str]] = {
    EmailKind.INVITE.value: (ApplicationStatus.AWAITING_BOOKING.value, _REASON_INVITE),
    EmailKind.SCREENER.value: (ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER),
    EmailKind.SCREENER_REMINDER.value: (
        ApplicationStatus.AWAITING_SCREENER.value, _REASON_SCREENER
    ),
}

_EVENT_STATUS: dict[str, str] = {
    "email.sent": DeliveryStatus.SENT.value,
    "email.delivered": DeliveryStatus.DELIVERED.value,
    "email.bounced": DeliveryStatus.BOUNCED.value,
    "email.complained": DeliveryStatus.COMPLAINED.value,
}

_NEGATIVE = frozenset({DeliveryStatus.BOUNCED.value, DeliveryStatus.COMPLAINED.value})

# Lý do bounce là văn bản do BÊN NGOÀI gửi tới — cắt ngắn trước khi vào DB/UI.
_MAX_REASON = 500


def status_for_event(event_type: str) -> str | None:
    """`email.bounced` → `BOUNCED`. Sự kiện không quan tâm (`opened`/`clicked`/…) → None."""
    return _EVENT_STATUS.get(event_type or "")


def email_id_of(event: dict) -> str | None:
    """Khoá đối chiếu. Payload Resend đã đổi hình dạng giữa các bản tài liệu (`email_id` vs `id`) —
    đọc cả hai thay vì đoán một rồi im lặng bỏ lỡ mọi sự kiện."""
    data = event.get("data") or {}
    value = data.get("email_id") or data.get("id")
    return str(value) if value else None


def bounce_reason_of(data: dict) -> str | None:
    """Gộp `type/subType/message` của Resend thành một câu cho HR đọc. Không có → None."""
    bounce = (data or {}).get("bounce") or {}
    parts = [str(bounce.get(k)) for k in ("type", "subType", "message") if bounce.get(k)]
    if not parts:
        return None
    return " · ".join(parts)[:_MAX_REASON]


async def handle_event(session: AsyncSession, event: dict) -> None:
    """Điểm vào DUY NHẤT từ webhook. KHÔNG BAO GIỜ ném: route đã trả 204 là hứa với Resend rằng sự
    kiện được nhận, và ném ở đây chỉ khiến Resend thử lại một thứ sẽ hỏng y hệt."""
    try:
        await _process(session, event)
    except Exception:  # noqa: BLE001 — xem docstring
        logger.exception("Webhook Resend: xử lý sự kiện lỗi — bỏ qua, KHÔNG bắt Resend thử lại.")
        try:
            await session.rollback()
        except Exception:  # noqa: BLE001
            logger.exception("Webhook Resend: rollback cũng lỗi.")


async def _process(session: AsyncSession, event: dict) -> None:
    """Thân thật. Tên KHÁC `webhooks._handle` (bí danh của route) có chủ ý — hai tên giống nhau ở
    hai module là thứ làm người đọc tưởng mình đang nhìn cùng một hàm."""
    new_status = status_for_event(str(event.get("type") or ""))
    if new_status is None:
        return
    email_id = email_id_of(event)
    if not email_id:
        logger.warning("Webhook Resend: sự kiện %r không có email id — bỏ qua.", event.get("type"))
        return

    # Khoá HÀNG: Resend có thể bắn `delivered` và `bounced` gần như cùng lúc, và cả hai đều đọc-rồi-ghi.
    row = (
        await session.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == email_id).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        # Thư gửi TRƯỚC khi có bảng này, hoặc webhook trỏ nhầm môi trường. Không phải lỗi.
        logger.info("Webhook Resend: không có vết giao hàng cho id=%s — bỏ qua.", email_id)
        await session.commit()  # đóng transaction đọc, đừng ôm connection
        return

    if not outranks(new_status, row.status):
        # Sự kiện trùng / tới muộn. Đây LÀ tính idempotent, không phải trường hợp lạ.
        await session.commit()
        return

    # Nguyên thuỷ, lấy TRƯỚC mọi thao tác có thể hỏng (bẫy expire — gotcha SCH-2 #3).
    kind, application_id, recipient = row.kind, row.application_id, row.recipient
    row.status = new_status
    # Chỉ ghi/đọc lý do ở sự kiện XẤU. Đọc `row.bounce_reason` cho một sự kiện `delivered` sẽ lôi ra
    # lý do của lần bounce TRƯỚC và nhét nó vào dòng audit "đã giao hàng" — đọc log lên tưởng lá thư
    # vừa tới cũng có vấn đề.
    reason_text: str | None = None
    if new_status in _NEGATIVE:
        reason_text = bounce_reason_of(event.get("data") or {})
        row.bounce_reason = reason_text

    app_row = (
        await session.get(Application, application_id) if application_id is not None else None
    )
    final_status = app_row.status if app_row is not None else None

    if app_row is not None:
        if new_status in _NEGATIVE:
            final_status = await _apply_bounce(session, app_row, kind=kind)
        elif new_status == DeliveryStatus.DELIVERED.value:
            _clear_bounce(app_row, recipient=recipient)

    await audit_service.record(
        session,
        application_id=application_id,
        node="scheduler",
        action=f"email_{new_status.lower()}",
        escalation_reason=EMAIL_BOUNCED_FLAG if new_status in _NEGATIVE else None,
        detail={
            "kind": kind, "email_id": email_id, "reason": reason_text,
            "final_status": final_status,
        },
        commit=True,
    )
    # `record(commit=True)` kết thúc bằng `refresh()` — nó autobegin một transaction MỚI và giữ lại
    # connection (gotcha refresh(), AI_GUIDE). Đóng nó ngay. `commit()` chứ không `rollback()`:
    # rollback expire mọi object bất kể `expire_on_commit=False`.
    await session.commit()
    logger.info(
        "Webhook Resend: id=%s kind=%s → %s (app=%s, status=%s)",
        email_id, kind, new_status, application_id, final_status,
    )


async def _apply_bounce(session: AsyncSession, app_row: Application, *, kind: str) -> str:
    """Gắn cờ + (có điều kiện) hạ về PENDING_REVIEW. Trả trạng thái CUỐI của hồ sơ."""
    app_row.uncertainty_flags = with_flag(app_row.uncertainty_flags, EMAIL_BOUNCED_FLAG)

    mapping = _SINGLE_CHANNEL.get(kind)
    if mapping is None:
        return app_row.status  # thư biên nhận / thư từ chối → chỉ cờ

    expected_status, reason = mapping
    if app_row.status != expected_status:
        # Hồ sơ đã đi tiếp trong lúc webhook đang trên đường. KHÔNG kéo ngược.
        return app_row.status
    if await _already_moved_on(session, app_row.id, kind=kind):
        # Cờ trạng thái nói một đằng, BẢNG nói một nẻo. Tin bảng (bài học SCH-3).
        logger.warning(
            "Webhook Resend: app=%s trạng thái %s nhưng bảng cho thấy đã đi tiếp — chỉ gắn cờ.",
            app_row.id, app_row.status,
        )
        return app_row.status

    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = reason
    return app_row.status


async def _already_moved_on(session: AsyncSession, application_id: int, *, kind: str) -> bool:
    """Hỏi BẢNG, không hỏi cờ. Hai câu hỏi khác nhau cho hai họ thư khác nhau."""
    if kind == EmailKind.INVITE.value:
        count = await session.scalar(
            select(func.count())
            .select_from(InterviewBooking)
            .where(
                InterviewBooking.application_id == application_id,
                InterviewBooking.status == BookingStatus.BOOKED.value,
            )
        )
        return bool(count)
    count = await session.scalar(
        select(func.count())
        .select_from(ScreeningSession)
        .where(
            ScreeningSession.application_id == application_id,
            ScreeningSession.answers.isnot(None),
        )
    )
    return bool(count)


def _clear_bounce(app_row: Application, *, recipient: str) -> None:
    """GỠ cờ khi một lá thư sau ĐÃ tới cùng địa chỉ đó (bài học SCH-3: gắn cờ thì phải có đường gỡ).

    Không gỡ thì hồ sơ mang nhãn báo động vĩnh viễn kể cả sau khi địa chỉ đã hoạt động trở lại — và
    cảnh báo không bao giờ tắt là cảnh báo sẽ bị phớt lờ.
    """
    if recipient != app_row.applicant_email:
        return
    flags = list(app_row.uncertainty_flags or [])
    if EMAIL_BOUNCED_FLAG not in flags:
        return
    app_row.uncertainty_flags = [f for f in flags if f != EMAIL_BOUNCED_FLAG]
    # Chỉ xoá lý do NẾU nó đúng là câu ta đặt — đừng xoá lý do escalation của một chuyện khác.
    if app_row.escalation_reason in _BOUNCE_REASONS:
        app_row.escalation_reason = None
```

- [ ] **Bước 4: Chạy test thuần**

Run: `uv run --directory apps/backend pytest tests/test_webhook_resend.py -q`
Expected: PASS.

- [ ] **Bước 5: Viết test DB THẬT cho bảng quyết định (gated)**

Tạo `apps/backend/tests/test_email_delivery_db.py`:

```python
"""Test EMAIL-1 trên Postgres THẬT — bảng quyết định bounce + idempotent.

**Gated `RUN_EMAIL_IT=1`** (đúng lệ repo với RUN_BOOKING_IT/RUN_EMBED_IT). Cần DB thật vì thứ đang
kiểm là hành vi đọc-ghi có khoá hàng và các điều kiện "hỏi BẢNG" — mock sẽ chứng minh chính giả
định của mình.

    RUN_EMAIL_IT=1 uv run --directory apps/backend pytest tests/test_email_delivery_db.py -q
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingStatus, InterviewBooking
from app.models.email_delivery import DeliveryStatus, EmailDelivery, EmailKind
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.services import email_delivery as svc

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_EMAIL_IT"), reason="cần RUN_EMAIL_IT=1 + Postgres thật"
)

_MARK = "email1-it"


@pytest.fixture
async def Session():  # noqa: N802
    """Engine RIÊNG + NullPool mỗi test — pytest-asyncio cấp mỗi test một event loop MỚI, còn pool
    toàn cục giữ connection asyncpg gắn với loop trước (gotcha SCH-1)."""
    engine = create_async_engine(
        settings.database_url, connect_args=settings.db_connect_args, poolclass=NullPool
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture
async def app_id(Session):  # noqa: N803
    async with Session() as s:
        job = JobPosting(title=f"[{_MARK}] Backend", status="OPEN")
        s.add(job)
        await s.flush()
        row = Application(
            job_id=job.id, applicant_email=f"{_MARK}@example.com",
            status=ApplicationStatus.AWAITING_BOOKING.value,
        )
        s.add(row)
        await s.flush()
        aid, jid = row.id, job.id
        await s.commit()
    try:
        yield aid
    finally:
        async with Session() as s:
            await s.execute(delete(Application).where(Application.id == aid))
            await s.execute(delete(JobPosting).where(JobPosting.id == jid))
            await s.commit()


async def _delivery(Session, app_id: int, kind: str, email_id: str) -> None:  # noqa: N803
    async with Session() as s:
        s.add(EmailDelivery(
            resend_email_id=email_id, application_id=app_id, kind=kind,
            recipient=f"{_MARK}@example.com", status=DeliveryStatus.SENT.value,
        ))
        await s.commit()


def _event(kind: str, email_id: str) -> dict:
    return {
        "type": f"email.{kind}",
        "data": {"email_id": email_id, "bounce": {"type": "Permanent", "message": "mailbox not found"}},
    }


async def test_invite_bounce_demotes_untouched_application(Session, app_id) -> None:  # noqa: N803
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_inv_1")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_inv_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags
        assert row.escalation_reason == svc._REASON_INVITE
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_inv_1")
        )).scalar_one()
        assert d.status == DeliveryStatus.BOUNCED.value
        assert "mailbox not found" in (d.bounce_reason or "")


async def test_invite_bounce_only_flags_when_application_moved_on(Session, app_id) -> None:  # noqa: N803
    """HR đã xử lý trong lúc webhook trên đường → KHÔNG kéo ngược, chỉ gắn cờ."""
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.REJECTED.value
        await s.commit()
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_inv_2")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_inv_2"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.REJECTED.value
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags


async def test_invite_bounce_asks_the_table_not_the_flag(Session, app_id) -> None:  # noqa: N803
    """Trạng thái nói AWAITING_BOOKING nhưng BẢNG có hàng BOOKED — tin bảng (bài học SCH-3).

    Chốt chặn này chết đi mà bộ test vẫn xanh nếu chỉ kiểm qua đường trạng-thái-đã-đổi, nên phải
    dựng đúng trạng thái MÂU THUẪN rồi đo.
    """
    start = datetime.now(timezone.utc) + timedelta(days=3)
    async with Session() as s:
        s.add(InterviewBooking(
            application_id=app_id, start_at=start, end_at=start + timedelta(hours=1),
            status=BookingStatus.BOOKED.value,
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_inv_3")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_inv_3"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_BOOKING.value  # KHÔNG hạ
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags
    async with Session() as s:
        await s.execute(delete(InterviewBooking).where(InterviewBooking.application_id == app_id))
        await s.commit()


async def test_screener_bounce_only_flags_when_answers_exist(Session, app_id) -> None:  # noqa: N803
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        s.add(ScreeningSession(
            application_id=app_id, token=f"{_MARK}-tok", questions=[],
            answers=[{"question": "q", "answer": "a"}],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER.value, "e_scr_1")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_scr_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_SCREENER.value


async def test_reject_bounce_never_reopens_the_decision(Session, app_id) -> None:  # noqa: N803
    """Quyết định #4: chỉ gắn cờ, GIỮ REJECTED."""
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.REJECTED.value
        await s.commit()
    await _delivery(Session, app_id, EmailKind.REJECT.value, "e_rej_1")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_rej_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.REJECTED.value
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags


async def test_booking_confirm_bounce_never_changes_status(Session, app_id) -> None:  # noqa: N803
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.INTERVIEW_SCHEDULED.value
        await s.commit()
    await _delivery(Session, app_id, EmailKind.BOOKING_CONFIRMED.value, "e_bc_1")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_bc_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags


async def test_duplicate_event_is_idempotent(Session, app_id) -> None:  # noqa: N803
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_dup")
    for _ in range(3):
        async with Session() as s:
            await svc.handle_event(s, _event("bounced", "e_dup"))
    async with Session() as s:
        rows = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.application_id == app_id)
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].status == DeliveryStatus.BOUNCED.value


async def test_late_delivered_does_not_erase_bounce(Session, app_id) -> None:  # noqa: N803
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_late")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_late"))
    async with Session() as s:
        await svc.handle_event(s, {"type": "email.delivered", "data": {"email_id": "e_late"}})
    async with Session() as s:
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_late")
        )).scalar_one()
        assert d.status == DeliveryStatus.BOUNCED.value
        row = await s.get(Application, app_id)
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags  # cờ KHÔNG bị gỡ


async def test_later_delivery_to_same_address_clears_the_flag(Session, app_id) -> None:  # noqa: N803
    """Phải CÓ đường gỡ cờ, nếu không nhãn báo động sống vĩnh viễn và sẽ bị phớt lờ (SCH-3)."""
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_flag_1")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_flag_1"))
    await _delivery(Session, app_id, EmailKind.BOOKING_REMINDER.value, "e_flag_2")
    async with Session() as s:
        await svc.handle_event(s, {"type": "email.delivered", "data": {"email_id": "e_flag_2"}})
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert svc.EMAIL_BOUNCED_FLAG not in row.uncertainty_flags
        assert row.escalation_reason is None


async def test_unknown_email_id_is_silent_noop(Session) -> None:  # noqa: N803
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_khong_ton_tai"))  # KHÔNG được ném
```

- [ ] **Bước 6: Chạy test DB thật**

```bash
cd d:/Web/Project/DATN && RUN_EMAIL_IT=1 uv run --directory apps/backend pytest tests/test_email_delivery_db.py -q
```
Expected: 10 PASS. (Nếu `make test` không có `RUN_EMAIL_IT` thì chúng skip — đúng lệ repo.)

- [ ] **Bước 7: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(email): xử lý bounce — cờ email_bounced + PENDING_REVIEW có điều kiện (hỏi bảng)"
```

---

## Task 8: Validate email — chặt ở prod, nới ở dev

**Files:**
- Modify: `apps/backend/app/schemas/application.py:13-22`
- Test: `apps/backend/tests/test_public_apply.py` (thêm)

**Interfaces:**
- Produces: `ApplicationCreate.applicant_email: str` với validator phụ thuộc `settings.app_env` (đọc lúc VALIDATE, không phải lúc import — để test monkeypatch được).

> **Hiện trạng đã kiểm chứng:** `applicant_email` đang là `EmailStr` ⇒ **đã chặt ở CẢ HAI môi trường**,
> và 422 đã bắn **trước** `create_application` ở cả hai đường nộp ⇒ "không tốn LLM" đã đúng. Delta
> thực của task này là **nới ở dev** (`.local` để test được) + test hồi quy khoá cả hai chiều.

- [ ] **Bước 1: Viết test THẤT BẠI**

Thêm vào `apps/backend/tests/test_public_apply.py`:

```python
# ── Validate email: chặt ở prod / nới ở dev (EMAIL-1 §3.5) ──────────────────
import pytest
from pydantic import ValidationError

from app.core.config import settings as _settings
from app.schemas.application import ApplicationCreate


@pytest.mark.parametrize("bad", ["khong-co-a-cong", "a@@e.com", "a@", "@e.com", ""])
def test_prod_rejects_malformed_email(monkeypatch, bad: str) -> None:
    monkeypatch.setattr(_settings, "app_env", "production")
    with pytest.raises(ValidationError):
        ApplicationCreate(job_id=1, applicant_email=bad)


def test_prod_rejects_special_use_tld(monkeypatch) -> None:
    """`.local` là domain nội bộ — thư gửi tới đó chắc chắn không tới ai."""
    monkeypatch.setattr(_settings, "app_env", "production")
    with pytest.raises(ValidationError):
        ApplicationCreate(job_id=1, applicant_email="hr@congty.local")


def test_dev_allows_local_domain(monkeypatch) -> None:
    """Nới ở dev để test end-to-end được với domain `.local` — cùng lý do slice 09 nới email đăng nhập."""
    monkeypatch.setattr(_settings, "app_env", "local")
    assert ApplicationCreate(job_id=1, applicant_email="hr@congty.local").applicant_email == "hr@congty.local"


def test_dev_still_rejects_obvious_garbage(monkeypatch) -> None:
    """Nới ≠ tắt: không có @ hoặc không có dấu chấm ở domain thì vẫn phải 422."""
    monkeypatch.setattr(_settings, "app_env", "local")
    for bad in ("khong-co-a-cong", "a@e", "a b@e.com"):
        with pytest.raises(ValidationError):
            ApplicationCreate(job_id=1, applicant_email=bad)
```

- [ ] **Bước 2: Chạy test để xác nhận HỎNG**

Run: `uv run --directory apps/backend pytest tests/test_public_apply.py -q -k "email"`
Expected: FAIL — `test_dev_allows_local_domain` ném `ValidationError` (hôm nay `EmailStr` chặt ở mọi môi trường).

- [ ] **Bước 3: Cài validator**

Trong `apps/backend/app/schemas/application.py`, thay `EmailStr` bằng `str` + validator:

```python
import re

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.core.config import settings

# Dev: chỉ đòi "có @, hai bên không rỗng, domain có dấu chấm, không khoảng trắng". Nới ≠ tắt —
# rác hiển nhiên vẫn phải chết ở đây, chứ không phải chết ở lượt gọi Resend sau khi đã tốn hai
# lượt LLM chấm hồ sơ.
_DEV_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")


class ApplicationCreate(BaseModel):
    """Ứng viên nộp CV: chỉ cần email + JD (PRD §8.2).

    KHÔNG có `cv_file_ref`: ref/key do SERVER sinh (`storage.build_cv_key`) sau khi có application_id.

    **Email: chặt ở prod, nới ở dev (EMAIL-1).** Prod dùng `email-validator` chuẩn — nó từ chối cả
    domain dùng-riêng (`.local`, `localhost`), thứ mà thư gửi tới chắc chắn không tới ai. Nhưng
    chính vì thế mà chạy thử end-to-end trên máy dev với domain nội bộ là không thể, nên dev nới
    xuống một kiểm tra hình thức (cùng lý do slice 09 nới email ĐĂNG NHẬP — xem AI_GUIDE).
    Đọc `settings.app_env` lúc VALIDATE chứ không phải lúc import: nếu không, test không đổi được
    môi trường và cả hai chiều đều không khoá được.
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
```

- [ ] **Bước 4: Chạy test**

Run: `uv run --directory apps/backend pytest tests/test_public_apply.py tests/test_review.py -q`
Expected: PASS. (`test_review.py` chạy kèm vì `ApplicationCreate` dùng chung với đường HR.)

- [ ] **Bước 5: Khẳng định "422 TRƯỚC khi tốn LLM"**

`test_public_apply.py` cố ý test ở mức UNIT (schema + service), không dựng HTTP client — giữ nguyên
nếp đó. Gọi thẳng handler với `FakeSession` đã có sẵn trong file: `submit_application` chạy
`get_open_job` rồi `ApplicationCreate` và **ném trước khi chạm `file` hoặc `create_application`**,
nên không cần DB, không cần file thật.

```python
async def test_bad_email_raises_422_before_creating_anything(monkeypatch) -> None:
    """Email hỏng phải chết ở CỬA. Để nó đi tiếp là tạo một hồ sơ + tốn hai lượt LLM (parser +
    ranker, đo được ~34s) cho một ứng viên không bao giờ liên hệ được."""
    from fastapi import HTTPException

    from app.api.routes import public

    class ExplodingSession(FakeSession):
        """Bất kỳ lượt ghi nào cũng là bằng chứng validate đã chạy MUỘN."""

        def add(self, *_a):  # noqa: ANN002, ANN202
            raise AssertionError("KHÔNG được tạo hồ sơ khi email sai định dạng")

        async def commit(self):  # noqa: ANN202
            raise AssertionError("KHÔNG được commit khi email sai định dạng")

    monkeypatch.setattr(_settings, "app_env", "production")
    with pytest.raises(HTTPException) as exc:
        await public.submit_application(
            ExplodingSession(_job()), None, job_id=2,
            applicant_email="hr@congty.local", file=None,
        )
    assert exc.value.status_code == 422
```

> `file=None` an toàn ở đây vì `file.read()` nằm SAU bước validate email — và nếu ai đó đảo thứ tự
> hai bước đó, test này sẽ nổ `AttributeError` thay vì im lặng cho qua. Đó là ý đồ.

- [ ] **Bước 6: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A apps/backend
git -C d:/Web/Project/DATN commit -m "feat(api): validate email chặt ở prod, nới ở dev (domain .local)"
```

---

## Task 9: Phơi cho HR — backend schema + dashboard

**Files:**
- Modify: `apps/backend/app/schemas/application.py` (`ApplicationRead`)
- Modify: `apps/backend/app/api/routes/applications.py:95-113`
- Modify: `packages/shared-types/src/index.ts:59-112`
- Modify: `apps/dashboard/app/(hr)/applications/page.tsx`
- Modify: `apps/dashboard/app/(hr)/applications/[id]/page.tsx`
- Modify: `apps/dashboard/components/ReviewCard.tsx`

**Interfaces:**
- Consumes: `EMAIL_BOUNCED_FLAG` (Task 7); `EmailDelivery` (Task 1).
- Produces: `ApplicationRead.email_bounced: bool` (dẫn xuất từ `uncertainty_flags`, có ở CẢ danh sách lẫn chi tiết) và `ApplicationRead.email_bounce_reason: str | None` (CHỈ ở chi tiết, tránh N+1 — cùng nếp `interview`/`has_booking_link`).

- [ ] **Bước 1: Thêm hai trường vào `ApplicationRead`**

```python
    # EMAIL-1: thư gửi ra KHÔNG tới được ứng viên (webhook Resend báo bounce/complaint). Dẫn xuất
    # từ `uncertainty_flags` nên CÓ ở cả danh sách lẫn chi tiết mà không tốn thêm truy vấn nào.
    @computed_field
    @property
    def email_bounced(self) -> bool:
        return "email_bounced" in (self.uncertainty_flags or [])

    # Lý do bounce rút gọn (từ `email_delivery.bounce_reason`). CHỈ populate ở endpoint chi tiết —
    # cùng nếp `interview`/`has_booking_link`, để danh sách không thành N+1.
    email_bounce_reason: str | None = None
```

- [ ] **Bước 2: Nạp lý do ở endpoint chi tiết**

Trong `apps/backend/app/api/routes/applications.py::get_application`, thêm vào `model_copy(update=…)`:

```python
            "email_bounce_reason": await _latest_bounce_reason(session, application_id),
```

và một helper nhỏ trong cùng file. Thêm import ở đầu file:
`from sqlalchemy import select` và
`from app.models.email_delivery import DeliveryStatus, EmailDelivery`.

⚠ Kiểu tham số là `AsyncSession`, **KHÔNG** phải `DBSession` — `DBSession` là alias `Annotated[...,
Depends(...)]` chỉ có nghĩa ở chữ ký route handler; dùng nó cho hàm thường là gắn một dependency
FastAPI vào chỗ không ai giải nó.

```python
async def _latest_bounce_reason(session: AsyncSession, application_id: int) -> str | None:
    """Lý do bounce GẦN NHẤT của hồ sơ. Cờ nói "có chuyện", câu này nói "chuyện gì" — HR cần cả hai
    để quyết gọi điện hay gõ lại địa chỉ."""
    return await session.scalar(
        select(EmailDelivery.bounce_reason)
        .where(
            EmailDelivery.application_id == application_id,
            EmailDelivery.status.in_(
                [DeliveryStatus.BOUNCED.value, DeliveryStatus.COMPLAINED.value]
            ),
        )
        .order_by(EmailDelivery.created_at.desc(), EmailDelivery.id.desc())
        .limit(1)
    )
```

- [ ] **Bước 3: Cập nhật shared-types**

`packages/shared-types/src/index.ts` — thêm vào `ApplicationListItem`:

```ts
  // EMAIL-1: thư gửi ra KHÔNG tới được ứng viên (webhook Resend báo bounce/complaint). Dẫn xuất từ
  // uncertainty_flags ở backend nên có ở CẢ danh sách lẫn chi tiết.
  email_bounced?: boolean;
```

và vào `ApplicationDetail`:

```ts
  // Lý do bounce rút gọn — chỉ có ở endpoint chi tiết. Cờ nói "có chuyện", câu này nói "chuyện gì".
  email_bounce_reason: string | null;
```

- [ ] **Bước 4: Nhãn ⚠ ở danh sách**

`apps/dashboard/app/(hr)/applications/page.tsx` — trong `<div className="flex flex-wrap items-center gap-2">`
ở dòng ~135, chèn NGAY SAU `<Tag tone={applicationStatusTone(a)}>` và **NGOÀI** điều kiện
`a.status === "PENDING_REVIEW"` bên dưới nó:

```tsx
                        {/* EMAIL-1: KHÁC cờ "cần chú ý" bên dưới ở chỗ nó hiện với MỌI trạng thái.
                            Ca đáng lo nhất chính là ca đã quyết xong: "Đã từ chối" / "Đã hẹn phỏng
                            vấn" mà thư không tới nơi thì dòng trạng thái đó đang nói dối, và nếu
                            giấu nhãn đi vì hồ sơ "đã xong" thì không ai phát hiện ra nữa. */}
                        {a.email_bounced && <Tag tone="danger">⚠ Email không gửi được</Tag>}
```

Dùng đúng `Tag`/`tone` sẵn có của `components/ui`; KHÔNG thêm thư viện UI.

- [ ] **Bước 5: Banner ở trang chi tiết**

`apps/dashboard/app/(hr)/applications/[id]/page.tsx` — đặt banner **TRÊN** khối lịch phỏng vấn (đây
là thứ HR cần đọc trước khi làm bất cứ gì khác với hồ sơ này), theo đúng khuôn banner "Hết khung
giờ" đang có ở dòng ~257:

```tsx
{/* EMAIL-1: thư gửi ra không tới được ứng viên. Đặt TRÊN mọi khối khác vì nó phủ định giá trị của
    chúng — "Đã hẹn phỏng vấn" mà thư mời bounce thì buổi phỏng vấn đó không tồn tại với ứng viên. */}
{app.email_bounced && (
  <div className="mt-4 rounded-xl border-2 border-red-300 bg-red-50 px-4 py-3">
    <p className="font-heading text-[13px] font-bold text-red-900">
      ⚠ Email không gửi được — cần liên hệ thủ công
    </p>
    <p className="mt-1.5 text-[13px] text-red-900">
      Nhà cung cấp email báo thư gửi tới <strong>{app.applicant_email}</strong> không tới nơi. Hãy
      liên hệ ứng viên bằng kênh khác (điện thoại trong CV) hoặc xác nhận lại địa chỉ.
      {app.email_bounce_reason ? <> Lý do: <code>{app.email_bounce_reason}</code></> : null}
    </p>
  </div>
)}
```

- [ ] **Bước 6: Nhãn trong `ReviewCard`**

`apps/dashboard/components/ReviewCard.tsx` — thêm ngay **trên** khối "Vì sao vào review" (dòng ~73):

```tsx
{/* EMAIL-1: HR phải thấy điều này TRƯỚC khi bấm nút — cả hai nút bên dưới đều gửi email thật, và
    gửi vào một địa chỉ đã bounce chỉ tạo thêm một lượt bounce nữa. */}
{app.email_bounced && (
  <p className="mt-3 rounded-r-lg border-l-[3px] border-red-500 bg-red-50 px-3 py-2.5 text-[13px] text-red-900">
    <strong className="font-bold">⚠ Email không gửi được: </strong>
    Thư trước đó không tới được {app.applicant_email}
    {app.email_bounce_reason ? ` (${app.email_bounce_reason})` : ""}. Hãy liên hệ thủ công —
    bấm nút bên dưới sẽ gửi thêm một thư nữa vào cùng địa chỉ đó.
  </p>
)}
```

- [ ] **Bước 7: Typecheck + build (PowerShell)**

```powershell
pnpm --filter @ars/shared-types build
pnpm --filter dashboard typecheck
pnpm --filter dashboard build
```
Expected: cả ba PASS.

- [ ] **Bước 8: `make test` + commit**

```bash
cd d:/Web/Project/DATN && make test
git -C d:/Web/Project/DATN add -A
git -C d:/Web/Project/DATN commit -m "feat(ui): nhãn cảnh báo email bounce ở danh sách, chi tiết và ReviewCard"
```

---

## Task 10: Env mẫu · docs · index · verify thật · adversarial review

**Files:**
- Modify: `.env.example`
- Modify: `docs/AI_GUIDE.md`
- Modify: `CLAUDE.md`
- Delete: `plan.md` (one-shot, xong thì bỏ — CLAUDE.md)

- [ ] **Bước 1: `.env.example`**

Trong mục "Email Service (Resend)", thêm:

```bash
# Địa chỉ nhận thư TRẢ LỜI. Vừa là UX (ứng viên bấm Reply là tới HR thật) vừa là tín hiệu
# deliverability — địa chỉ gửi kiểu noreply@ không có hòm thư bị nhà cung cấp trừ điểm.
EMAIL_REPLY_TO=
# Secret ký webhook, lấy khi tạo webhook trên Resend (Settings → Webhooks). CHƯA đặt → endpoint
# /api/webhooks/resend trả 503 (KHÔNG âm thầm nhận sự kiện không ký).
RESEND_WEBHOOK_SECRET=
RESEND_WEBHOOK_TOLERANCE_SECONDS=300
# Resend giới hạn 2 req/s. Lượt gửi được nối tiếp hoá và cách nhau ít nhất ngần này (ms).
EMAIL_MIN_INTERVAL_MS=550
# Số lần thử lại tối đa cho lỗi TẠM THỜI (429 bùng nổ / 5xx / mạng). KHÔNG áp cho 400/422 và
# KHÔNG áp cho cạn quota ngày.
EMAIL_MAX_RETRIES=3
```

Và bổ sung 5 biến này vào **CHECKLIST env prod** (mục "LLM + email", dòng ~247), kèm ghi chú:
webhook trên Resend phải trỏ `https://<backend>/api/webhooks/resend`.

- [ ] **Bước 2: `docs/AI_GUIDE.md` — thêm boundary + gotcha**

Thêm vào *Current boundaries*:

```markdown
- **Email boundary (EMAIL-1):** `scheduler._dispatch` là chỗ DUY NHẤT gọi `email_service.send_email`
  và cũng là chỗ DUY NHẤT ghi `email_delivery` — thêm đường gửi mới thì đi qua một hàm `notify_*`,
  đừng gọi thẳng `send_email` (mất luôn khả năng phát hiện bounce của lá thư đó). `kind` của
  `email_delivery` PHẢI trùng chuỗi `mode` (audit đã ghi `email_sent:{mode}` từ lát 04 — hai từ vựng
  là không đối soát được nữa). Webhook `/api/webhooks/resend` là endpoint CÔNG KHAI CÓ MUTATION:
  chốt chặn là CHỮ KÝ, không phải `require_hr`; nó phải nằm NGOÀI mọi xô rate-limit (Resend gọi từ
  vài IP cố định — siết theo IP là mất sự kiện bounce trong im lặng). Mọi lượt hạ trạng thái do
  bounce phải CÓ ĐIỀU KIỆN + hỏi BẢNG, và **KHÔNG BAO GIỜ auto-reject**.
```

Thêm vào *Gotchas*:

```markdown
- **`html_to_text` BỎ href — bản text của email mất link nếu template không in URL thô (EMAIL-1).**
  Bốn template có liên kết vốn in cả URL thô ra thân thư nên bản text sống sót; `interview_reminder_email`
  thì không, và bản text của nó mất nút huỷ đúng lúc ứng viên cần nhất. Thêm template có link mới →
  in cả URL thô, và có test `html_to_text(html)` chứa URL.
- **Verify webhook phải dùng BYTES THÔ (EMAIL-1).** Parse JSON rồi serialize lại là đổi khoảng
  trắng/thứ tự khoá ⇒ HMAC không bao giờ khớp. Đọc `await request.body()` TRƯỚC mọi thứ khác. Kèm
  theo: chữ ký đúng mà không kiểm `svix-timestamp` thì một request hợp lệ bị chặn lại phát lại được
  mãi mãi — cửa sổ thời gian là chốt chặn thứ hai, không phải trang trí.
- **Retry email làm dài lượt gửi tới ~8s (EMAIL-1) — Load boundary siết lại một bậc.** Trước đây giữ
  connection qua `send_email` là tệ; nay là tệ gấp mấy lần. Mọi caller `notify_*` phải đã `commit()`
  trước đó (hôm nay đúng, và `test_email_delivery.py` có test khoá `_dispatch` không chạm DB trước
  lượt gửi). Khoá `_send_lock` được giữ QUA CẢ vòng retry là CÓ CHỦ Ý: 429 nghĩa là "chậm lại".
- **429 của Resend là HAI chuyện khác nhau (EMAIL-1).** `rate_limit_exceeded` = bùng nổ, lùi một
  nhịp là qua. `daily_quota_exceeded`/`monthly_quota_exceeded` = tài nguyên DÙNG CHUNG đã cạn ⇒ thư
  của MỌI ứng viên khác cũng câm, và thử lại chỉ làm chậm hàng đợi. Phân loại theo `error_type`,
  KHÔNG theo mã 429.
```

- [ ] **Bước 3: `CLAUDE.md` — cập nhật trạng thái (giữ GỌN)**

Cập nhật dòng `scheduler` trong bảng node và thêm một đoạn ngắn (≤ 6 dòng) mô tả EMAIL-1: bảng
`email_delivery` + webhook verify chữ ký + retry/giữ nhịp + `reply_to`/text + nhãn bounce cho HR.
**Trỏ sang `docs/AI_GUIDE.md`** cho chi tiết; KHÔNG nhồi gotcha vào đây.

- [ ] **Bước 4: Index lại GitNexus + impact**

```bash
cd d:/Web/Project/DATN && node .gitnexus/run.cjs analyze
```
Rồi chạy `detect_changes({repo: "Agentic-Recruitment-System", scope: "compare", base_ref: "main"})`
và `impact({repo: "Agentic-Recruitment-System", target: "send_email", direction: "upstream"})`.
⚠ **LUÔN truyền `repo`** — thiếu nó `impact`/`detect_changes` trả kết quả XANH GIẢ (xem CLAUDE.md).
Kỳ vọng: chỉ `email_service`, `scheduler`, `email_templates`, `schemas/application`,
`routes/{applications,webhooks}`, `main`, và các file mới. **Bất kỳ symbol nào của
graph/ranker/parser/screener/booking xuất hiện = vượt ranh giới → dừng lại xem.**

- [ ] **Bước 5: VERIFY chạy thật**

1. **Có vết giao hàng:** đặt `RESEND_API_KEY` thật + `EMAIL_REPLY_TO`, chạy backend, cho một hồ sơ
   đi tới nhánh gửi thư → `SELECT resend_email_id, kind, status FROM email_delivery ORDER BY id DESC LIMIT 1;`
   → so `resend_email_id` với ID trên dashboard Resend. **Phải khớp.**
2. **Reply + text:** mở thư nhận được → bấm **Reply** ra đúng `EMAIL_REPLY_TO`; xem source thư có
   phần `text/plain` và **link nằm trong đó**.
3. **Webhook thật:** tạo webhook trên Resend trỏ vào backend (dev: ngrok/tunnel; hoặc dùng
   `sign_svix_payload` dựng một request hợp lệ với secret thật rồi `curl`), gửi tới một địa chỉ chắc
   chắn bounce → sự kiện tới → `email_delivery.status = BOUNCED`, hồ sơ có cờ `email_bounced`,
   dashboard hiện nhãn ⚠ + lý do.
4. **Giả mạo:** cùng payload nhưng đổi một byte chữ ký → **401**, và `SELECT status FROM email_delivery`
   **không đổi**.
5. **Nới/siết email:** `APP_ENV=local` nộp CV với `a@b.local` → **201**; `APP_ENV=production` cùng
   địa chỉ → **422**, không có hàng `application` mới, không có dòng LLM nào trong log.
6. `make test` xanh · `RUN_EMAIL_IT=1 … pytest tests/test_email_delivery_db.py` xanh ·
   `pnpm --filter dashboard build` PASS.

- [ ] **Bước 6: Adversarial review độc lập**

Bắt buộc trước khi merge (lát này có **endpoint công khai mới + đổi trạng thái**). Dùng
`superpowers:requesting-code-review` hoặc `agent-skills:code-reviewer`. Nhắc reviewer soi đúng bốn
mặt: (a) đường đi của chữ ký + replay; (b) mọi nhánh hạ trạng thái có ĐÚNG điều kiện + hỏi bảng
không; (c) có chỗ nào giữ connection qua lượt gửi/retry không (ĐO bằng `event.listens_for(engine.sync_engine, "checkout"/"checkin")`,
đừng suy luận); (d) cờ `email_bounced` có đường GỠ và có bị kẹt vĩnh viễn ở ca nào không.

- [ ] **Bước 7: Dọn + commit cuối**

```bash
git -C d:/Web/Project/DATN rm plan.md
git -C d:/Web/Project/DATN add -A
git -C d:/Web/Project/DATN commit -m "docs: EMAIL-1 xong — email boundary + 4 gotcha mới; env prod checklist"
```

---

## Ghi chú cho người thi công

- **Task 6 và Task 7 nên chạy liên tiếp** — Task 6 cần một `handle_event` tồn tại để test route
  chạy được (xem ghi chú trong Task 6 Bước 4).
- **Đừng sửa 10 nơi gọi `notify_*`.** Nếu thấy mình đang sửa `booking_flow`, `booking_lifecycle`,
  `review`, `screening_timeout` hay `background`, dừng lại — đó là dấu hiệu đã đi chệch khỏi seam.
- **Vướng → DỪNG, hỏi.** Đặc biệt nếu một nhánh nào đó có vẻ cần auto-reject, hoặc nếu điều kiện hạ
  trạng thái trở nên phức tạp hơn "status khớp + hỏi một bảng".
