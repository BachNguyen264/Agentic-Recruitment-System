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
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
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


# ── Vòng sửa sau adversarial review (opus, "Not approved" — 1 Critical + 5 Important) ───────
#
# C1 (Critical) đã khoá bằng 2 test THUẦN ở test_webhook_resend.py (email_id_of/bounce_reason_of
# không ném với data/bounce sai kiểu) — không cần lặp lại trên DB thật vì hai hàm đó không chạm DB.
# I3/I4 dưới đây cần DB thật vì đang kiểm hành vi ĐỌC-GHI thật (bảng InterviewBooking/BookingSession/
# ScreeningSession) — đúng lý do file này tồn tại.


async def test_complained_only_flags_never_demotes(Session, app_id) -> None:  # noqa: N803
    """I3 (chốt của người dùng): complaint là bằng chứng thư ĐÃ TỚI TAY — không có gì "hỏng" để cứu
    bằng cách hạ trạng thái. CHỈ gắn cờ + audit, GIỮ NGUYÊN AWAITING_BOOKING."""
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_cmp_1")
    async with Session() as s:
        await svc.handle_event(s, _event("complained", "e_cmp_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_BOOKING.value  # KHÔNG hạ
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_cmp_1")
        )).scalar_one()
        assert d.status == DeliveryStatus.COMPLAINED.value  # thứ bậc vẫn ghi nhận đúng


async def test_invite_bounce_demotion_cancels_booking_session(Session, app_id) -> None:  # noqa: N803
    """I4 (chốt của người dùng): hạ vì invite bounce phải HUỶ liên kết đặt lịch còn sống — không thì
    ứng viên vẫn mở được một link mà hồ sơ đã rời AWAITING_BOOKING (confirm_and_notify sẽ ghi đè
    PENDING_REVIEW thành INTERVIEW_SCHEDULED sau lưng HR)."""
    async with Session() as s:
        s.add(BookingSession(
            application_id=app_id, token=f"{_MARK}-book-tok",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=72),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_inv_close")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_inv_close"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value
        sess = (await s.execute(
            select(BookingSession).where(BookingSession.token == f"{_MARK}-book-tok")
        )).scalar_one()
        assert sess.cancelled_at is not None  # I4: liên kết đã bị huỷ, KHÔNG còn mở được
    async with Session() as s:
        await s.execute(delete(BookingSession).where(BookingSession.application_id == app_id))
        await s.commit()


async def test_screener_bounce_demotion_closes_screening_session(Session, app_id) -> None:  # noqa: N803
    """I4 (chốt của người dùng): hạ vì screener bounce phải ĐÓNG phiên sàng lọc đang mở
    (`timed_out_at`) — không thì hàng screening_session sống mãi MẬP MỜ (không dùng, không hết hạn)
    trong khi hồ sơ đã rời AWAITING_SCREENER. KHÔNG resume graph (giới hạn đã biết, xem docstring
    `_abandon_in_flight_session`)."""
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        s.add(ScreeningSession(
            application_id=app_id, token=f"{_MARK}-close-tok", questions=[],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER.value, "e_scr_close")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_scr_close"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value
        sess = (await s.execute(
            select(ScreeningSession).where(ScreeningSession.token == f"{_MARK}-close-tok")
        )).scalar_one()
        assert sess.timed_out_at is not None  # I4: phiên đã đóng, sweep KHÔNG còn săn nó
        assert sess.used_at is None  # đóng vì bounce, KHÔNG phải vì ứng viên đã trả lời
    async with Session() as s:
        await s.execute(delete(ScreeningSession).where(ScreeningSession.application_id == app_id))
        await s.commit()
