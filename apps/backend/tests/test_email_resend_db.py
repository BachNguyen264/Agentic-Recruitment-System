"""Gửi lại thư khi dịch vụ gửi TỪ CHỐI (PRD FR-SCR-7, FR-NOTI-3) — trên Postgres THẬT.

**Gated `RUN_EMAIL_IT=1`** (đúng lệ repo với RUN_BOOKING_IT/RUN_EMBED_IT):

    RUN_EMAIL_IT=1 uv run --directory apps/backend pytest tests/test_email_resend_db.py -q

Cần DB thật vì thứ đang kiểm là hành vi mà mock không chứng minh được: hàng `screening_session` mới/cũ,
khoá tư vấn theo hồ sơ, cờ JSONB được gỡ TRƯỚC khi gửi rồi `_dispatch` gắn lại khi gửi hỏng, và hàng trả
về phải serialize được ngay (lỗi `MissingGreenlet` → HTTP 500 từng cắn hai nút lịch của HR trên prod).

Chỉ giả lập đúng lớp gọi RA NGOÀI (`email_service.send_email` — Resend); `scheduler._dispatch` chạy thật
nên cờ, `email_delivery` và audit đều là thật. Dữ liệu test tự dọn (mọi bảng con CASCADE theo hồ sơ).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.routes import applications as routes
from app.core.config import settings
from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.email_delivery import DeliveryStatus, EmailDelivery
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.schemas.application import ApplicationRead
from app.services import email_resend, email_service

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_EMAIL_IT"), reason="cần RUN_EMAIL_IT=1 + Postgres thật"
)

_MARK = "resend-it"
_QUESTIONS = ["Mức lương kỳ vọng của bạn?", "Khi nào bạn có thể nhận việc?"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.fixture
async def Session():  # noqa: N802
    """Engine RIÊNG + NullPool mỗi test (gotcha SCH-1: pool toàn cục giữ connection của loop cũ)."""
    engine = create_async_engine(
        settings.database_url, connect_args=settings.db_connect_args, poolclass=NullPool
    )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


class _FakeResend:
    """Thay `email_service.send_email` (lượt gọi Resend). Ghi lại từng lá thư; `fail_with` → ném
    `EmailError` y như Resend từ chối ngay lúc gọi (403 sandbox, cạn hạn mức…)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_with: str | None = None
        # Chạy ĐÚNG lúc thư "rời hệ thống" — để test nhìn DB từ một connection KHÁC tại thời điểm đó.
        self.before_send = None

    async def __call__(self, *, to, subject, html, text=None, attachments=None):  # noqa: ANN001
        if self.before_send is not None:
            await self.before_send()
        self.calls.append({"to": to, "subject": subject, "html": html})
        if self.fail_with is not None:
            raise email_service.EmailError(self.fail_with)
        return f"e-{_MARK}-{uuid.uuid4().hex}"


@pytest.fixture
def resend(monkeypatch: pytest.MonkeyPatch) -> _FakeResend:
    fake = _FakeResend()
    monkeypatch.setattr(email_service, "send_email", fake)
    return fake


async def _make_app(Session, *, status: str, flags: list[str]) -> tuple[int, int]:  # noqa: N803
    async with Session() as s:
        job = JobPosting(title=f"[{_MARK}] Backend Engineer", status="OPEN")
        s.add(job)
        await s.flush()
        row = Application(
            job_id=job.id, applicant_email=f"{_MARK}+{uuid.uuid4().hex[:8]}@example.com",
            status=status, uncertainty_flags=flags,
        )
        s.add(row)
        await s.flush()
        ids = (row.id, job.id)
        await s.commit()
    return ids


async def _drop(Session, app_id: int, job_id: int) -> None:  # noqa: N803
    async with Session() as s:
        await s.execute(delete(Application).where(Application.id == app_id))
        await s.execute(delete(JobPosting).where(JobPosting.id == job_id))
        await s.commit()


@pytest.fixture
async def screening_app(Session):  # noqa: N803
    """Đúng hình dạng prod 06/10: chờ sàng lọc, thư đầu bị từ chối (cờ), phiên đầu đã chạy 30h và lượt
    nhắc cũng đã tiêu (`reminded_at`). Trả (app_id, token cũ)."""
    app_id, job_id = await _make_app(
        Session, status=ApplicationStatus.AWAITING_SCREENER.value, flags=["email_send_failed"]
    )
    old_token = f"old-{uuid.uuid4().hex}"
    async with Session() as s:
        s.add(ScreeningSession(
            application_id=app_id, token=old_token, questions=list(_QUESTIONS),
            created_at=_now() - timedelta(hours=30), expires_at=_now() + timedelta(hours=42),
            reminded_at=_now() - timedelta(hours=6),
        ))
        await s.commit()
    try:
        yield app_id, old_token
    finally:
        await _drop(Session, app_id, job_id)


@pytest.fixture
async def rejected_app(Session):  # noqa: N803
    app_id, job_id = await _make_app(
        Session, status=ApplicationStatus.REJECTED.value, flags=["email_send_failed"]
    )
    try:
        yield app_id
    finally:
        await _drop(Session, app_id, job_id)


async def _sessions(Session, app_id: int) -> list[ScreeningSession]:  # noqa: N803
    async with Session() as s:
        rows = await s.execute(
            select(ScreeningSession)
            .where(ScreeningSession.application_id == app_id)
            .order_by(ScreeningSession.id)
        )
        return list(rows.scalars().all())


async def _app(Session, app_id: int) -> Application:  # noqa: N803
    async with Session() as s:
        return await s.get(Application, app_id)


async def _actions(Session, app_id: int) -> list[tuple[str, str]]:  # noqa: N803
    async with Session() as s:
        rows = await s.execute(
            select(AuditLog.node, AuditLog.action)
            .where(AuditLog.application_id == app_id)
            .order_by(AuditLog.id)
        )
        return [(n, a) for n, a in rows.all()]


# ── Thư sàng lọc ─────────────────────────────────────────────────────────────


async def test_screener_resend_issues_fresh_session_and_retires_old(
    Session, screening_app, resend  # noqa: N803
) -> None:
    app_id, old_token = screening_app
    before = _now()

    async with Session() as s:
        row = await email_resend.resend_failed_email(s, app_id)
        out = ApplicationRead.model_validate(row)  # ĐÚNG dòng của route — nổ MissingGreenlet nếu quên refresh

    assert out.status == ApplicationStatus.AWAITING_SCREENER.value
    assert "email_send_failed" not in out.uncertainty_flags

    old, new = await _sessions(Session, app_id)
    assert old.token == old_token
    assert old.timed_out_at is not None, "link cũ phải ngừng hoạt động"
    assert new.token != old_token
    assert new.questions == _QUESTIONS, "giữ nguyên bộ câu hỏi đã chụp, không đọc lại JD"
    assert (new.used_at, new.reminded_at, new.timed_out_at) == (None, None, None)
    # Hạn tính lại TỪ LÚC GỬI LẠI, không kế thừa 42h còn lại của phiên cũ.
    full = timedelta(hours=settings.screener_deadline_hours)
    assert before + full - timedelta(minutes=1) <= new.expires_at <= _now() + full

    app_row = await _app(Session, app_id)
    assert app_row.screener_deadline == new.expires_at

    assert len(resend.calls) == 1
    assert resend.calls[0]["to"] == app_row.applicant_email
    assert f"/screening/{new.token}" in resend.calls[0]["html"]
    assert old_token not in resend.calls[0]["html"]

    assert ("human_review", "screener_resent") in await _actions(Session, app_id)


async def test_screener_resend_failure_reports_502_and_keeps_flag(
    Session, screening_app, resend  # noqa: N803
) -> None:
    """Dịch vụ gửi VẪN từ chối → HR phải biết ngay (502 kèm lý do), cờ quay lại, hồ sơ vẫn chờ."""
    app_id, _ = screening_app
    resend.fail_with = "Resend gửi email thất bại: You can only send testing emails"

    async with Session() as s:
        with pytest.raises(email_resend.ResendError) as caught:
            await email_resend.resend_failed_email(s, app_id)

    assert caught.value.status_code == 502
    assert "You can only send testing emails" in caught.value.message
    app_row = await _app(Session, app_id)
    assert app_row.status == ApplicationStatus.AWAITING_SCREENER.value
    assert "email_send_failed" in app_row.uncertainty_flags


async def test_second_resend_after_success_is_refused(
    Session, screening_app, resend  # noqa: N803
) -> None:
    """Bấm đúp / hai tab: lượt thứ hai không được phát thêm link (link vừa gửi sẽ chết dưới chân
    ứng viên) và không được gửi thêm thư."""
    app_id, _ = screening_app
    async with Session() as s:
        await email_resend.resend_failed_email(s, app_id)

    async with Session() as s:
        with pytest.raises(email_resend.ResendError) as caught:
            await email_resend.resend_failed_email(s, app_id)

    assert caught.value.status_code == 409
    assert len(resend.calls) == 1
    assert len(await _sessions(Session, app_id)) == 2


async def test_claim_is_committed_before_the_email_leaves(
    Session, screening_app, resend  # noqa: N803
) -> None:
    """Gỡ cờ + phát phiên mới phải COMMIT trước lượt gọi Resend. Đây là thứ khiến lượt bấm thứ hai
    nhận 409 thay vì phát thêm một link (at-most-once), và cũng là bằng chứng không ôm transaction
    xuyên lượt gửi mail (Load boundary). Một connection KHÁC chỉ thấy được dữ liệu ĐÃ commit."""
    app_id, old_token = screening_app
    seen: dict = {}

    async def peek() -> None:
        async with Session() as other:
            row = await other.get(Application, app_id)
            seen["flags"] = list(row.uncertainty_flags or [])
            open_rows = await other.execute(
                select(ScreeningSession.token).where(
                    ScreeningSession.application_id == app_id,
                    ScreeningSession.timed_out_at.is_(None),
                )
            )
            seen["open_tokens"] = [t for (t,) in open_rows.all()]

    resend.before_send = peek
    async with Session() as s:
        await email_resend.resend_failed_email(s, app_id)

    assert "email_send_failed" not in seen["flags"]
    assert len(seen["open_tokens"]) == 1 and seen["open_tokens"][0] != old_token


async def test_resend_refused_when_no_email_failed(Session, screening_app, resend) -> None:  # noqa: N803
    """Không có thư hỏng thì không có gì để "gửi lại" — và KHÔNG được đụng vào phiên đang sống."""
    app_id, old_token = screening_app
    async with Session() as s:
        row = await s.get(Application, app_id)
        row.uncertainty_flags = []
        await s.commit()

    async with Session() as s:
        with pytest.raises(email_resend.ResendError) as caught:
            await email_resend.resend_failed_email(s, app_id)

    assert caught.value.status_code == 409
    assert resend.calls == []
    (only,) = await _sessions(Session, app_id)
    assert only.token == old_token and only.timed_out_at is None


async def test_resend_unknown_application_is_404(Session, resend) -> None:  # noqa: N803
    async with Session() as s:
        with pytest.raises(email_resend.ResendError) as caught:
            await email_resend.resend_failed_email(s, 2_000_000_000)
    assert caught.value.status_code == 404


# ── Thư từ chối ──────────────────────────────────────────────────────────────


async def test_reject_resend_sends_rejection_and_clears_flag(
    Session, rejected_app, resend  # noqa: N803
) -> None:
    async with Session() as s:
        row = await email_resend.resend_failed_email(s, rejected_app)
        out = ApplicationRead.model_validate(row)

    assert out.status == ApplicationStatus.REJECTED.value
    assert "email_send_failed" not in out.uncertainty_flags
    assert len(resend.calls) == 1
    assert "Kết quả ứng tuyển" in resend.calls[0]["subject"]
    assert ("human_review", "rejection_resent") in await _actions(Session, rejected_app)


async def test_reject_resend_refused_after_candidate_complained(
    Session, rejected_app, resend  # noqa: N803
) -> None:
    async with Session() as s:
        row = await s.get(Application, rejected_app)
        row.uncertainty_flags = ["email_send_failed", "email_complained"]
        await s.commit()

    async with Session() as s:
        with pytest.raises(email_resend.ResendError) as caught:
            await email_resend.resend_failed_email(s, rejected_app)

    assert caught.value.status_code == 409
    assert resend.calls == []


# ── Lý do lỗi hiện cho HR ────────────────────────────────────────────────────


async def test_failure_reason_comes_from_audit_for_sync_failures(Session, rejected_app) -> None:  # noqa: N803
    """Resend từ chối NGAY lúc gọi thì không có hàng `email_delivery` nào — lý do chỉ nằm ở audit.
    Trước bản vá, banner bảo HR "kiểm tra lý do bên dưới" mà bên dưới trống trơn."""
    async with Session() as s:
        s.add(AuditLog(
            application_id=rejected_app, node="scheduler", action="email_failed",
            detail={"mode": "reject", "to": "x@example.com", "error": "Resend gửi email thất bại: 403"},
        ))
        await s.commit()

    async with Session() as s:
        reason = await email_resend.latest_send_failure_reason(s, rejected_app)
    assert reason == "Resend gửi email thất bại: 403"


async def test_failure_reason_prefers_the_newer_failure(Session, rejected_app) -> None:  # noqa: N803
    """Lỗi tại chỗ (audit) CŨ hơn lỗi do webhook báo về (`email_delivery` FAILED) → hiện cái mới."""
    t0 = _now() - timedelta(hours=2)
    async with Session() as s:
        s.add(AuditLog(
            application_id=rejected_app, node="scheduler", action="email_failed",
            detail={"mode": "reject", "error": "lỗi cũ"}, created_at=t0,
        ))
        s.add(EmailDelivery(
            resend_email_id=f"e-{_MARK}-{uuid.uuid4().hex}", application_id=rejected_app,
            kind="reject", recipient="x@example.com", status=DeliveryStatus.FAILED.value,
            bounce_reason="reached_daily_quota",
            created_at=t0 + timedelta(minutes=30), updated_at=t0 + timedelta(hours=1),
        ))
        await s.commit()

    async with Session() as s:
        reason = await email_resend.latest_send_failure_reason(s, rejected_app)
    assert reason == "reached_daily_quota"


async def test_detail_route_exposes_reason_and_resendable_kind(
    Session, screening_app  # noqa: N803
) -> None:
    """Nối dây ở route chi tiết: banner cần lý do, nút cần biết gửi lại được thư nào."""
    app_id, _ = screening_app
    async with Session() as s:
        s.add(AuditLog(
            application_id=app_id, node="scheduler", action="email_failed",
            detail={"mode": "screener", "error": "Resend gửi email thất bại: 403 sandbox"},
        ))
        await s.commit()

    async with Session() as s:
        out = await routes.get_application(app_id, s)

    assert out.email_send_failure_reason == "Resend gửi email thất bại: 403 sandbox"
    assert out.resendable_email == "screener"
