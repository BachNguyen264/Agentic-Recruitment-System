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
from app.models.audit_log import AuditLog
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


def _failed_event(email_id: str, reason: str = "reached_daily_quota") -> dict:
    """Payload THẬT của `email.failed` — nguyên nhân nằm ở `data.failed.reason`, KHÔNG phải
    `data.bounce.*` (đã đối chiếu tài liệu Resend). Chép `_event` rồi đổi mỗi `type` sẽ cho một test
    XANH nhưng vô nghĩa: `bounce_reason` im lặng thành None và không assert nào phát hiện."""
    return {"type": "email.failed", "data": {"email_id": email_id, "failed": {"reason": reason}}}


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
    bằng cách hạ trạng thái. CHỈ gắn cờ + audit, GIỮ NGUYÊN AWAITING_BOOKING.

    Fix vòng 3: complaint gắn ĐÚNG `EMAIL_COMPLAINED_FLAG` — KHÔNG dùng chung `EMAIL_BOUNCED_FLAG`
    (dùng chung sẽ khiến `_clear_bounce` xoá nhầm dấu vết "đã báo spam" khi có thư sau tới cùng
    địa chỉ — xem định nghĩa `EMAIL_COMPLAINED_FLAG`)."""
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_cmp_1")
    async with Session() as s:
        await svc.handle_event(s, _event("complained", "e_cmp_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_BOOKING.value  # KHÔNG hạ
        assert svc.EMAIL_COMPLAINED_FLAG in row.uncertainty_flags
        assert svc.EMAIL_BOUNCED_FLAG not in row.uncertainty_flags  # KHÔNG dùng chung cờ
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_cmp_1")
        )).scalar_one()
        assert d.status == DeliveryStatus.COMPLAINED.value  # thứ bậc vẫn ghi nhận đúng
        # F3 (final review): dòng audit của MỘT COMPLAINT phải ghi ĐÚNG loại — trước fix,
        # `_process` gắn cứng `EMAIL_BOUNCED_FLAG` cho cả bounce lẫn complaint, nên bản ghi pháp y
        # (PRD §16, NFR-3) của complaint nói dối là "email_bounced".
        audit = (await s.execute(
            select(AuditLog)
            .where(AuditLog.application_id == app_id, AuditLog.action == "email_complained")
            .order_by(AuditLog.id.desc())
            .limit(1)
        )).scalar_one()
        assert audit.escalation_reason == svc.EMAIL_COMPLAINED_FLAG


async def test_later_delivery_does_not_clear_complained_flag(Session, app_id) -> None:  # noqa: N803
    """Fix vòng 3: `EMAIL_COMPLAINED_FLAG` KHÔNG được gỡ bởi bất kỳ `delivered` nào sau đó — một
    lượt giao hàng thành công chứng minh địa chỉ đang hoạt động, nhưng KHÔNG hề phủ nhận việc ứng
    viên đã từng bấm "đây là spam". Khác hẳn cờ bounce (có đường gỡ — xem
    `test_later_delivery_to_same_address_clears_the_flag`).

    **Dựng CẢ HAI cờ cùng lúc** (bounce THẬT + complain) trước khi gửi `delivered`: nếu hồ sơ chỉ
    mang MỘT MÌNH cờ complained, guard đầu của `_clear_bounce` (`EMAIL_BOUNCED_FLAG not in flags`)
    return SỚM và không bao giờ chạm tới dòng gỡ cờ — bài test sẽ xanh dù logic gỡ có sai (tự bắt
    được đúng lỗ hổng này bằng mutation lúc viết test — xem task-7-report.md)."""
    await _delivery(Session, app_id, EmailKind.BOOKING_CONFIRMED.value, "e_cmp_flag_bounce")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_cmp_flag_bounce"))  # cờ BOUNCE thật
    await _delivery(Session, app_id, EmailKind.INTERVIEW_REMINDER.value, "e_cmp_flag_complain")
    async with Session() as s:
        await svc.handle_event(s, _event("complained", "e_cmp_flag_complain"))  # + cờ COMPLAINED
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags
        assert svc.EMAIL_COMPLAINED_FLAG in row.uncertainty_flags  # cả hai cờ đang CÙNG tồn tại

    await _delivery(Session, app_id, EmailKind.BOOKING_REMINDER.value, "e_cmp_flag_delivered")
    async with Session() as s:
        await svc.handle_event(
            s, {"type": "email.delivered", "data": {"email_id": "e_cmp_flag_delivered"}}
        )
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert svc.EMAIL_BOUNCED_FLAG not in row.uncertainty_flags  # bounce ĐƯỢC gỡ như thường lệ
        assert svc.EMAIL_COMPLAINED_FLAG in row.uncertainty_flags  # complained KHÔNG BAO GIỜ bị gỡ


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


async def test_application_detail_exposes_separate_bounce_and_complaint_reasons(
    Session, app_id  # noqa: N803
) -> None:
    """Task 9: HR phải thấy LÝ DO bounce/complaint ở endpoint chi tiết — hai cột RIÊNG cho hai loại
    sự kiện, KHÔNG trộn lẫn (gộp `status.in_([BOUNCED, COMPLAINED])` vào MỘT truy vấn sẽ khiến lý do
    của loại này lấn qua nhãn của loại kia). Dựng hai message KHÁC NHAU cho bounce/complaint rồi xác
    nhận `get_application` gắn đúng lý do vào đúng cột — không chỉ "có giá trị" mà phải "đúng giá
    trị của đúng sự kiện"."""
    from app.api.routes.applications import get_application

    bounce_event = {
        "type": "email.bounced",
        "data": {
            "email_id": "e_reason_bounce",
            "bounce": {"type": "Permanent", "message": "LY-DO-BOUNCE-RIENG"},
        },
    }
    complain_event = {
        "type": "email.complained",
        "data": {
            "email_id": "e_reason_complain",
            "bounce": {"type": "Complaint", "message": "LY-DO-COMPLAIN-RIENG"},
        },
    }
    await _delivery(Session, app_id, EmailKind.BOOKING_CONFIRMED.value, "e_reason_bounce")
    await _delivery(Session, app_id, EmailKind.INTERVIEW_REMINDER.value, "e_reason_complain")
    async with Session() as s:
        await svc.handle_event(s, bounce_event)
    async with Session() as s:
        await svc.handle_event(s, complain_event)

    async with Session() as s:
        result = await get_application(app_id, s)
        assert result.email_bounced is True
        assert result.email_complained is True
        assert result.email_bounce_reason is not None
        assert "LY-DO-BOUNCE-RIENG" in result.email_bounce_reason
        assert "LY-DO-COMPLAIN-RIENG" not in result.email_bounce_reason
        assert result.email_complaint_reason is not None
        assert "LY-DO-COMPLAIN-RIENG" in result.email_complaint_reason
        assert "LY-DO-BOUNCE-RIENG" not in result.email_complaint_reason


async def test_screener_reminder_transient_bounce_only_flags_keeps_link_alive(
    Session, app_id  # noqa: N803
) -> None:
    """F2 (final review): `screener_reminder` chở lại CHÍNH magic-link mà thư `screener` gốc đã giao
    THÀNH CÔNG. Hộp thư đầy (`type: Transient`) lúc thư NHẮC tới KHÔNG chứng minh liên kết đã chết —
    hạ về PENDING_REVIEW rồi đóng phiên (`_abandon_in_flight_session`) là giết một link đang sống
    dưới chân ứng viên, mà HR không có nút "gửi lại link sàng lọc" (chỉ booking mới có). Phải CHỈ
    gắn cờ: status GIỮ AWAITING_SCREENER, `timed_out_at` GIỮ None (phiên vẫn mở, link vẫn dùng được).
    """
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        s.add(ScreeningSession(
            application_id=app_id, token=f"{_MARK}-transient-tok", questions=[],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER_REMINDER.value, "e_scr_transient")
    async with Session() as s:
        await svc.handle_event(s, {
            "type": "email.bounced",
            "data": {
                "email_id": "e_scr_transient",
                "bounce": {"type": "Transient", "message": "mailbox full"},
            },
        })
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_SCREENER.value  # KHÔNG hạ
        assert svc.EMAIL_BOUNCED_FLAG in row.uncertainty_flags  # nhưng HR VẪN thấy cảnh báo
        sess = (await s.execute(
            select(ScreeningSession).where(ScreeningSession.token == f"{_MARK}-transient-tok")
        )).scalar_one()
        assert sess.timed_out_at is None  # link còn sống — sweep/HR có thể vẫn xử lý bình thường
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_scr_transient")
        )).scalar_one()
        assert d.status == DeliveryStatus.BOUNCED.value  # vết giao hàng vẫn ghi ĐÚNG (chỉ status app không hạ)
    async with Session() as s:
        await s.execute(delete(ScreeningSession).where(ScreeningSession.application_id == app_id))
        await s.commit()


async def test_screener_reminder_permanent_bounce_still_demotes(Session, app_id) -> None:  # noqa: N803
    """Đối chứng F2: `Permanent` (địa chỉ chết hẳn) trên CHÍNH `screener_reminder` vẫn phải hạ như cũ
    — chỉ `Transient` mới được miễn."""
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        s.add(ScreeningSession(
            application_id=app_id, token=f"{_MARK}-permanent-tok", questions=[],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER_REMINDER.value, "e_scr_permanent")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_scr_permanent"))  # _event() dùng type Permanent
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value  # HẠ như cũ
        sess = (await s.execute(
            select(ScreeningSession).where(ScreeningSession.token == f"{_MARK}-permanent-tok")
        )).scalar_one()
        assert sess.timed_out_at is not None  # phiên đã đóng
    async with Session() as s:
        await s.execute(delete(ScreeningSession).where(ScreeningSession.application_id == app_id))
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


# ══════════════════════════════════════════════════════════════════════════════════════════
# `email.failed` — Resend KHÔNG đẩy được thư đi (thư chưa hề rời hệ thống)
# ══════════════════════════════════════════════════════════════════════════════════════════


async def test_invite_send_failure_demotes_and_records_its_own_reason(Session, app_id) -> None:  # noqa: N803
    """Thư mời không gửi đi được → hạ về PENDING_REVIEW + cờ RIÊNG + lý do RIÊNG.

    Hạ trạng thái là có chủ ý: ứng viên đang đứng ở `AWAITING_BOOKING` chờ một liên kết KHÔNG BAO
    GIỜ tới. Chỉ gắn cờ mà để nguyên thì lưới sweep SCH-3 sẽ hết hạn rồi dán nhãn
    `booking_no_response` — đổ lỗi cho người chưa từng nhận được gì.
    """
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_fail_1")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_fail_1"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value
        assert svc.EMAIL_SEND_FAILED_FLAG in row.uncertainty_flags
        # KHÔNG mượn cờ của hai loại kia — ba tình huống, ba hành động khác nhau cho HR.
        assert svc.EMAIL_BOUNCED_FLAG not in row.uncertainty_flags
        assert svc.EMAIL_COMPLAINED_FLAG not in row.uncertainty_flags
        assert row.escalation_reason == svc._REASON_INVITE_FAILED
        d = (await s.execute(
            select(EmailDelivery).where(EmailDelivery.resend_email_id == "e_fail_1")
        )).scalar_one()
        assert d.status == DeliveryStatus.FAILED.value
        # Lý do phải đọc được từ `data.failed.reason`; None ở đây = HR thấy cảnh báo đỏ trống rỗng.
        assert d.bounce_reason == "reached_daily_quota"


async def test_send_failure_audit_action_is_distinct_from_dispatch_failure(Session, app_id) -> None:  # noqa: N803
    """Dòng audit của webhook KHÔNG được trùng tên với `email_failed` của `scheduler._dispatch`.

    Hai sự kiện khác hẳn nhau, CÙNG `node="scheduler"`: `_dispatch` ghi `email_failed` khi lượt gọi
    Resend NÉM lỗi tại chỗ (không sinh hàng `email_delivery` nào), còn đây là Resend đã nhận thư rồi
    mới báo hỏng. Trùng tên là mất khả năng truy vết — đúng lớp lỗi đã vá ở commit d4fbfd5.
    """
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_fail_2")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_fail_2", "invalid_recipient"))
    async with Session() as s:
        actions = set((await s.execute(
            select(AuditLog.action).where(AuditLog.application_id == app_id)
        )).scalars().all())
        assert "email_send_failed" in actions
        assert "email_failed" not in actions
        audit = (await s.execute(
            select(AuditLog)
            .where(AuditLog.application_id == app_id, AuditLog.action == "email_send_failed")
            .order_by(AuditLog.id.desc()).limit(1)
        )).scalar_one()
        # F3: cờ trong audit phải là cờ THẬT SỰ được gắn, không phải hằng số đoán lại.
        assert audit.escalation_reason == svc.EMAIL_SEND_FAILED_FLAG
        assert audit.detail.get("reason") == "invalid_recipient"


async def test_send_failure_on_receipt_mail_only_flags(Session, app_id) -> None:  # noqa: N803
    """Thư BIÊN NHẬN (xác nhận lịch) không gửi được → CHỈ gắn cờ, KHÔNG hạ trạng thái.

    Cùng chính sách per-kind với bounce: ứng viên đã tự bấm chọn giờ và đã thấy màn xác nhận trên
    web, nên lá thư chỉ là biên nhận — huỷ lịch của họ vì một biên nhận không gửi được mới là cái
    sai lớn. `_SINGLE_CHANNEL` cố ý không chứa các loại thư này.
    """
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.INTERVIEW_SCHEDULED.value
        await s.commit()
    await _delivery(Session, app_id, EmailKind.BOOKING_CONFIRMED.value, "e_fail_3")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_fail_3"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.INTERVIEW_SCHEDULED.value  # KHÔNG hạ
        assert svc.EMAIL_SEND_FAILED_FLAG in row.uncertainty_flags  # nhưng HR vẫn phải BIẾT


async def test_later_delivery_clears_send_failed_flag(Session, app_id) -> None:  # noqa: N803
    """Một lá thư sau giao THÀNH CÔNG tới cùng địa chỉ thì gỡ được cờ này — khác complaint.

    Lý do: `email.failed` nói về phía TA (hạn mức/domain/khoá API). Thư sau đi được nghĩa là sự cố
    đó đã hết, nên cảnh báo phải tự tắt; cảnh báo không bao giờ tắt là cảnh báo sẽ bị phớt lờ.
    """
    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_fail_4")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_fail_4"))
    async with Session() as s:
        assert svc.EMAIL_SEND_FAILED_FLAG in (await s.get(Application, app_id)).uncertainty_flags

    await _delivery(Session, app_id, EmailKind.SCREENER.value, "e_fail_5")
    async with Session() as s:
        await svc.handle_event(s, _event("delivered", "e_fail_5"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert svc.EMAIL_SEND_FAILED_FLAG not in row.uncertainty_flags
        assert row.escalation_reason is None  # câu escalation của chính nó cũng được dọn


async def test_application_detail_exposes_send_failure_reason_separately(Session, app_id) -> None:  # noqa: N803
    """Ba loại sự kiện xấu → BA cột lý do riêng ở endpoint chi tiết, không rò sang nhau.

    Trộn chung thì HR đọc "hạn mức gửi đã cạn" ở ô dành cho bounce và đi làm đúng việc vô ích (tìm
    số điện thoại của ứng viên) trong khi thứ cần sửa là cấu hình gửi.

    Đi QUA `get_application` chứ không gọi thẳng `_latest_reason`: thứ dễ quên nhất không phải câu
    truy vấn mà là DÒNG NỐI nó vào `model_copy(update=...)` của route. Gọi thẳng helper thì xoá hẳn
    dòng nối đó test vẫn xanh, còn HR thì nhận banner ⛔ trống trơn — đúng cái "cảnh báo đỏ không kèm
    lý do" mà docstring của `failure_reason_of` gọi là hỏng-câm tệ nhất.
    """
    from app.api.routes.applications import get_application

    await _delivery(Session, app_id, EmailKind.INVITE.value, "e_mix_f")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_mix_f", "domain_not_verified"))
    await _delivery(Session, app_id, EmailKind.REJECT.value, "e_mix_b")
    async with Session() as s:
        await svc.handle_event(s, _event("bounced", "e_mix_b"))

    async with Session() as s:
        result = await get_application(app_id, s)
        assert result.email_send_failed is True
        assert result.email_send_failure_reason == "domain_not_verified"
        assert "mailbox not found" in (result.email_bounce_reason or "")
        # Ba cột RIÊNG, không rò sang nhau — HR phải biết mình đang đọc chuyện gì.
        assert result.email_send_failure_reason != result.email_bounce_reason
        assert result.email_complaint_reason is None


async def test_screener_reminder_send_failure_keeps_the_live_link(Session, app_id) -> None:  # noqa: N803
    """Thư NHẮC sàng lọc không gửi đi được → CHỈ gắn cờ, KHÔNG được giết liên kết đang sống.

    Bắt được nhờ adversarial review khi bật `email.failed`: thư nhắc chở lại CHÍNH token mà thư
    `screener` gốc đã giao THÀNH CÔNG, nên "không gửi được thư nhắc" không nói gì về liên kết. Nếu
    hạ trạng thái, `_abandon_in_flight_session` đóng phiên → `screening._load_valid` trả "quá hạn"
    cho ứng viên đang cầm liên kết CÒN HẠN; `reminded_at` đã tiêu nên không có lời nhắc thứ hai, và
    HR KHÔNG có nút gửi lại link sàng lọc ⇒ mất bài dự tuyển, không đường cứu.

    Sinh đôi của `test_screener_reminder_transient_bounce_only_flags_keeps_link_alive` (ngoại lệ F2
    của bounce Transient) — hai chốt chặn RIÊNG cho cùng một bất biến, nên phải test RIÊNG từng cái.
    """
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        s.add(ScreeningSession(
            application_id=app_id, token=f"{_MARK}-failtok", questions=[],
            expires_at=datetime.now(timezone.utc) + timedelta(hours=48),
        ))
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER_REMINDER.value, "e_rem_fail")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_rem_fail"))

    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.AWAITING_SCREENER.value  # KHÔNG hạ
        assert svc.EMAIL_SEND_FAILED_FLAG in row.uncertainty_flags  # nhưng HR vẫn BIẾT
        sess = (await s.execute(
            select(ScreeningSession).where(ScreeningSession.token == f"{_MARK}-failtok")
        )).scalar_one()
        assert sess.timed_out_at is None  # liên kết VẪN SỐNG — đây là điều đang bảo vệ
    async with Session() as s:
        await s.execute(delete(ScreeningSession).where(ScreeningSession.application_id == app_id))
        await s.commit()


async def test_screener_first_send_failure_still_demotes(Session, app_id) -> None:  # noqa: N803
    """Đối trọng của test trên: thư sàng lọc GỐC không gửi được thì VẪN hạ về tay HR.

    Không có test này thì ngoại lệ vừa thêm có thể bị nới rộng ra cả `screener` mà không ai biết —
    và khi đó ứng viên chưa hề nhận được liên kết nào lại nằm im ở `AWAITING_SCREENER` cho tới lúc
    hết hạn rồi bị dán nhãn "không phản hồi".
    """
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.status = ApplicationStatus.AWAITING_SCREENER.value
        await s.commit()
    await _delivery(Session, app_id, EmailKind.SCREENER.value, "e_scr_fail")
    async with Session() as s:
        await svc.handle_event(s, _failed_event("e_scr_fail"))
    async with Session() as s:
        row = await s.get(Application, app_id)
        assert row.status == ApplicationStatus.PENDING_REVIEW.value
        assert row.escalation_reason == svc._REASON_SCREENER_FAILED
