"""screening — dịch vụ Screener magic-link (08b · PRD §7.3, §10, §12.2).

Tạo phiên (token an toàn + hạn + ảnh chụp câu hỏi), validate token cho form công khai, và NỘP câu
trả lời → resume pipeline bằng chính câu trả lời (thay endpoint dev 08a).

Bảo mật (plan §6):
- Token crypto-random (`secrets.token_urlsafe`) — KHÔNG tuần tự/đoán được.
- Hết hạn (`expires_at`) + one-time (`used_at`) — mọi thao tác re-check.
- Chỉ resume application đang AWAITING_SCREENER.
- Row-lock (`SELECT … FOR UPDATE`) chống 2 submit đồng thời cùng resume một thread.
- KHÔNG lộ nội bộ: chỉ trả câu hỏi + tiêu đề JD (projection ở schema/route).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.tasks import background  # resume_screener (dùng chung persist + error-handling)

logger = get_logger("app.services.screening")

_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) → ~43 ký tự url-safe (crypto-random)
_MAX_ANSWER_LEN = 5000  # chặn input phình (DoS) — mỗi câu trả lời tối đa


class ScreeningError(Exception):
    """Lỗi Screener mang sẵn HTTP status + message tiếng Việt để route map thẳng (không lộ nội bộ)."""

    status_code = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TokenNotFound(ScreeningError):
    status_code = 404


class TokenExpired(ScreeningError):
    status_code = 410


class TokenUsed(ScreeningError):
    status_code = 409


class NotAwaitingScreener(ScreeningError):
    status_code = 409


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_session(
    session: AsyncSession, application_id: int, questions: list[str]
) -> ScreeningSession:
    """Tạo phiên Screener: token an toàn + hạn (screener_deadline_hours) + ảnh chụp câu hỏi JD.

    KHÔNG commit — caller commit CÙNG lúc đặt AWAITING_SCREENER (nguyên tử). Trả row (chưa có id/token
    đến khi flush/commit; token gán sẵn ở Python nên đọc được ngay để dựng magic-link)."""
    row = ScreeningSession(
        application_id=application_id,
        token=secrets.token_urlsafe(_TOKEN_BYTES),
        questions=list(questions or []),
        expires_at=_now() + timedelta(hours=settings.screener_deadline_hours),
    )
    session.add(row)
    return row


def mark_screener_sent(application: Application, session_row: ScreeningSession) -> None:
    """Ghi mốc screener lên `application` cho HR THẤY (denormalize — PRD §10, §16).

    Nguồn chân lý của nhắc/timeout vẫn là `screening_session` (expires_at/reminded_at/timed_out_at —
    xem screening_timeout). Hai cột `screener_sent_at`/`screener_deadline` CHỈ để hiển thị: trước 08b
    chúng là cột scaffold KHÔNG ai ghi → luôn null (HR thấy "—" dù email đã gửi). Gọi trong CÙNG commit
    với AWAITING_SCREENER + create_session để nguyên tử. `sent_at` = lúc khởi phát screener (email gửi
    ngay sau commit; nếu gửi lỗi thì 08c nhắc lại — cột này phản ánh "đã khởi phát", đủ cho hiển thị)."""
    application.screener_sent_at = _now()
    application.screener_deadline = session_row.expires_at


async def _load_valid(
    session: AsyncSession, token: str, *, for_update: bool
) -> tuple[ScreeningSession, Application]:
    """Tra + validate token: tồn tại, chưa dùng, chưa hết hạn, application đang AWAITING_SCREENER.
    `for_update=True` → khóa hàng (chống double-submit). Raise ScreeningError (status_code) nếu sai."""
    stmt = select(ScreeningSession).where(ScreeningSession.token == token)
    if for_update:
        stmt = stmt.with_for_update()
    sess = (await session.execute(stmt)).scalar_one_or_none()
    if sess is None:
        raise TokenNotFound("Liên kết không hợp lệ.")
    if sess.used_at is not None:
        raise TokenUsed("Bạn đã gửi câu trả lời cho liên kết này rồi.")
    # Trả lời TRỄ (08c · PRD §10 FR-SCR-5): đã timeout hoặc quá hạn → thông báo ÊM (đang xem xét),
    # KHÔNG resume lại (graph đã đi tiếp qua timeout → human_review). timed_out_at check TRƯỚC status
    # để có thông điệp trấn an (410) thay vì 409 "sai trạng thái" khi app đã sang PENDING_REVIEW.
    if sess.timed_out_at is not None or sess.expires_at <= _now():
        raise TokenExpired("Thời hạn trả lời đã qua. Hồ sơ của bạn vẫn đang được bộ phận tuyển dụng xem xét.")
    app_row = await session.get(Application, sess.application_id)
    if app_row is None or app_row.status != ApplicationStatus.AWAITING_SCREENER.value:
        raise NotAwaitingScreener("Hồ sơ không ở trạng thái chờ trả lời sàng lọc.")
    return sess, app_row


async def latest_answers(session: AsyncSession, application_id: int) -> list:
    """Câu trả lời sàng lọc mới nhất (đã nộp) của một application — cho HR xem ở review/chi tiết."""
    stmt = (
        select(ScreeningSession.answers)
        .where(
            ScreeningSession.application_id == application_id,
            ScreeningSession.answers.isnot(None),
        )
        .order_by(ScreeningSession.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none() or []


async def get_form(session: AsyncSession, token: str) -> tuple[str, list[str]]:
    """GET công khai: validate token (đọc, không khóa) → (job_title, questions). CHỈ dữ liệu an toàn
    (KHÔNG rubric/gate/điểm/parsed_data)."""
    sess, app_row = await _load_valid(session, token, for_update=False)
    job = await session.get(JobPosting, app_row.job_id) if app_row.job_id is not None else None
    job_title = job.title if job is not None else "vị trí ứng tuyển"
    return job_title, list(sess.questions or [])


async def submit_answers(session: AsyncSession, token: str, answers: list[str]) -> dict:
    """POST công khai: row-lock → re-validate → resume graph BẰNG câu trả lời → mark used + lưu answers
    (nguyên tử trong 1 commit). One-time + chống double-submit. Lỗi resume → PENDING_REVIEW[error]
    (không kẹt AWAITING_SCREENER) — với ứng viên vẫn báo đã nhận (không lộ lỗi nội bộ)."""
    sess, _app_row = await _load_valid(session, token, for_update=True)  # KHÓA hàng
    application_id = sess.application_id
    # Ghép câu hỏi (ảnh chụp) với câu trả lời theo thứ tự; cắt độ dài chống input phình.
    paired = [
        {
            "question": q,
            "answer": (answers[i].strip()[:_MAX_ANSWER_LEN] if i < len(answers) and answers[i] else ""),
        }
        for i, q in enumerate(sess.questions or [])
    ]

    def _mark_used() -> None:  # chạy TRƯỚC commit (trong lock) → used_at + answers nguyên tử với resume.
        sess.used_at = _now()
        sess.answers = paired

    out = await background.resume_screener(
        session, application_id, {"answers": paired}, pre_commit=_mark_used
    )
    logger.info("screening: app=%s đã nộp câu trả lời → resume branch=%s", application_id, out.get("branch"))
    return {"status": "submitted", "application_id": application_id}
