"""screening_timeout — nghiệp vụ timeout Screener (08c · PRD §10 FR-SCR-3/4/5).

TÁCH khỏi cơ chế lập lịch (`screening_scheduler.py`): handler nhắc/timeout + `sweep_once` ở đây
KHÔNG phụ thuộc InProcess hay QStash — chỉ nhận AsyncSession + thao tác DB/graph. Đổi cơ chế lập
lịch sau này (QStash) KHÔNG sửa file này (chỉ gọi lại các handler / sweep_once).

Sweep quét Postgres (`screening_session`) — KHÔNG Redis polling (CLAUDE.md). Chạy trong event loop
CHÍNH (asyncio task ở lifespan) nên await graph resume + AsyncPostgresSaver tự nhiên (KHÔNG
`asyncio.run` per-item — tránh bẫy 08a). Mỗi session xử lý trong transaction RIÊNG + row-lock; lỗi
một session KHÔNG làm chết cả vòng (try/except từng cái). Idempotent qua `reminded_at`/`timed_out_at`
+ lọc `AWAITING_SCREENER`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.nodes import scheduler
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.services import audit_service
from app.tasks import background  # resume_screener (dùng chung persist/error-handling 08a/08b)

logger = get_logger("app.services.screening_timeout")

_TIMEOUT_REASON = "Ứng viên không phản hồi bộ câu hỏi sàng lọc trong thời hạn."


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _remaining_text(expires_at: datetime, now: datetime) -> str:
    """Chuỗi thời gian CÒN LẠI cho email nhắc — đọc được kể cả khi verify đặt ngưỡng nhỏ (phút)."""
    secs = max(0, int((expires_at - now).total_seconds()))
    if secs >= 3600:
        return f"{secs // 3600} giờ"
    if secs >= 60:
        return f"{secs // 60} phút"
    return "ít phút tới"


# ── Truy vấn ứng viên đến hạn (đọc, KHÔNG khóa) ──────────────────────────────────────────


async def _due_reminder_ids(session: AsyncSession, now: datetime) -> list[int]:
    """id session cần NHẮC: chưa dùng/chưa nhắc/chưa timeout, app còn AWAITING_SCREENER, CHƯA hết hạn,
    đã quá mốc nhắc (created_at + reminder_hours <= now)."""
    reminder_cutoff = now - timedelta(hours=settings.screener_reminder_hours)
    stmt = (
        select(ScreeningSession.id)
        .join(Application, Application.id == ScreeningSession.application_id)
        .where(
            ScreeningSession.used_at.is_(None),
            ScreeningSession.reminded_at.is_(None),
            ScreeningSession.timed_out_at.is_(None),
            ScreeningSession.expires_at > now,
            ScreeningSession.created_at <= reminder_cutoff,
            Application.status == ApplicationStatus.AWAITING_SCREENER.value,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _due_timeout_ids(session: AsyncSession, now: datetime) -> list[int]:
    """id session HẾT HẠN: chưa dùng/chưa timeout, app còn AWAITING_SCREENER, quá expires_at."""
    stmt = (
        select(ScreeningSession.id)
        .join(Application, Application.id == ScreeningSession.application_id)
        .where(
            ScreeningSession.used_at.is_(None),
            ScreeningSession.timed_out_at.is_(None),
            ScreeningSession.expires_at <= now,
            Application.status == ApplicationStatus.AWAITING_SCREENER.value,
        )
    )
    return list((await session.execute(stmt)).scalars().all())


async def _lock_session(session: AsyncSession, session_id: int) -> ScreeningSession | None:
    """SELECT … FOR UPDATE theo id — khóa hàng để re-check chống double-process (đua với submit)."""
    stmt = select(ScreeningSession).where(ScreeningSession.id == session_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


# ── Handler nghiệp vụ (mechanism-agnostic — scheduler chỉ GỌI, không chứa logic này) ─────


async def send_screening_reminder(session: AsyncSession, sess: ScreeningSession) -> None:
    """NHẮC một lần (PRD §10 FR-SCR-3). Set `reminded_at` + commit TRƯỚC khi gửi → at-most-once
    (email lỗi cũng KHÔNG nhắc lại; timeout sau vẫn xử). Gửi qua scheduler (điểm phát email DUY NHẤT),
    DÙNG LẠI magic-link cũ (token còn hạn). Caller đã row-lock + re-check."""
    app_row = await session.get(Application, sess.application_id)
    if app_row is None:  # application đã bị xóa — bỏ qua an toàn
        return
    job = await session.get(JobPosting, app_row.job_id) if app_row.job_id is not None else None
    job_title = job.title if job is not None else "vị trí ứng tuyển"
    name = (app_row.parsed_data or {}).get("full_name") or "Ứng viên"
    form_url = f"{settings.frontend_base_url.rstrip('/')}/screening/{sess.token}"

    sess.reminded_at = _now()  # once-only: chốt TRƯỚC khi gửi (idempotent kể cả email lỗi)
    await session.commit()

    await scheduler.notify_screener(
        session, application_id=sess.application_id, applicant_email=app_row.applicant_email,
        candidate_name=name, job_title=job_title, form_url=form_url,
        deadline_text=_remaining_text(sess.expires_at, _now()), reminder=True,
    )


async def handle_screening_timeout(session: AsyncSession, sess: ScreeningSession) -> None:
    """TIMEOUT (PRD §10 FR-SCR-4). Resume graph với `{"no_response": True}` → screener node gắn cờ
    no_response → human_review. **Im lặng ≠ từ chối — KHÔNG auto-reject.** Đánh dấu `timed_out_at`
    NGUYÊN TỬ với resume (pre_commit) → idempotent. Caller đã row-lock + re-check used_at/timed_out_at.

    Dùng lại `background.resume_screener` (cùng persist + audit + error-handling 08a/08b): resume lỗi
    kỹ thuật → PENDING_REVIEW[error] (không kẹt câm ở AWAITING_SCREENER)."""
    await audit_service.record(
        session, application_id=sess.application_id, node="screener", action="screener_timeout",
        uncertainty_flags=["no_response"], escalation_reason=_TIMEOUT_REASON,
        detail={"reason": "no_response", "expires_at": sess.expires_at.isoformat()}, commit=False,
    )

    def _mark_timed_out() -> None:  # chạy TRƯỚC commit trong resume_screener (nguyên tử, idempotent)
        sess.timed_out_at = _now()

    await background.resume_screener(
        session, sess.application_id, {"no_response": True}, pre_commit=_mark_timed_out
    )


# ── Một vòng quét (gọi bởi scheduler — cơ chế nào cũng gọi được) ─────────────────────────


async def sweep_once(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """MỘT vòng quét deadline: tìm session cần nhắc + hết hạn → xử lý TỪNG cái trong transaction
    RIÊNG (row-lock, re-check trong lock chống double-process). Lỗi một session KHÔNG chết cả vòng.
    Trả {reminded, timed_out, errors} cho log/observability."""
    now = _now()
    async with session_factory() as read_sess:
        reminder_ids = await _due_reminder_ids(read_sess, now)
        timeout_ids = await _due_timeout_ids(read_sess, now)

    counts = {"reminded": 0, "timed_out": 0, "errors": 0}

    for sid in reminder_ids:
        try:
            async with session_factory() as s:
                sess = await _lock_session(s, sid)
                # re-check trong lock: đua với submit (used_at) / timeout / sweep khác.
                if sess is None or sess.used_at is not None or sess.reminded_at is not None \
                        or sess.timed_out_at is not None:
                    continue
                await send_screening_reminder(s, sess)
                counts["reminded"] += 1
        except Exception:  # noqa: BLE001 — một session lỗi KHÔNG làm chết cả vòng sweep
            counts["errors"] += 1
            logger.exception("sweep: lỗi khi NHẮC session id=%s", sid)

    for sid in timeout_ids:
        try:
            async with session_factory() as s:
                sess = await _lock_session(s, sid)
                # re-check trong lock: đua với submit (used_at) → nếu vừa trả lời thì KHÔNG timeout.
                if sess is None or sess.used_at is not None or sess.timed_out_at is not None:
                    continue
                await handle_screening_timeout(s, sess)
                counts["timed_out"] += 1
        except Exception:  # noqa: BLE001
            counts["errors"] += 1
            logger.exception("sweep: lỗi khi TIMEOUT session id=%s", sid)

    if any(counts.values()):
        logger.info(
            "sweep: reminded=%s timed_out=%s errors=%s",
            counts["reminded"], counts["timed_out"], counts["errors"],
        )
    return counts
