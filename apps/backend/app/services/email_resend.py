"""email_resend — HR gửi lại thư khi dịch vụ gửi TỪ CHỐI (PRD FR-SCR-7, FR-NOTI-3).

Vì sao có module này (quan sát trên PROD 06/10/2026): sender rơi về địa chỉ sandbox của Resend, mọi lượt
gửi tới ứng viên bị trả 403 NGAY lúc gọi. `scheduler._dispatch` nuốt lỗi đúng thiết kế (gắn cờ
`email_send_failed` + audit `email_failed`, KHÔNG đổi trạng thái), nên:

- thư SÀNG LỌC hỏng → hồ sơ đứng ở `AWAITING_SCREENER` tới hết hạn 72h trong khi ứng viên chưa hề có
  link, rồi bị gắn nhãn `no_response` — và HR không có nút nào để cứu (chỉ đặt lịch mới có "Gửi lại
  link");
- thư TỪ CHỐI hỏng → ứng viên không bao giờ được báo kết quả.

Thư MỜI cố ý VẮNG MẶT: nó đã có đường cứu riêng (gửi hỏng → `PENDING_REVIEW`, HR duyệt lại; hoặc nút
"Gửi lại link đặt lịch"). Thêm đường thứ hai ở đây là lặp lại thứ tự email-trước-trạng-thái-sau mà
AI_GUIDE bắt mọi đường mời phải đi chung qua `booking_flow.dispatch_booking_invite`.

BA PHA trong `resend_failed_email`, mỗi pha chặn một lỗi đã tái hiện được trên Postgres thật:
1. CHIẾM (`_claim`): khoá tư vấn → khoá hàng PHIÊN sàng lọc → khoá hàng HỒ SƠ → gỡ cờ + đóng phiên cũ +
   phát phiên mới + audit → COMMIT. Thứ tự khoá TRÙNG với `screening.submit_answers` và sweep hết hạn
   (hàng phiên trước, hàng hồ sơ sau) — ngược thứ tự là deadlock với chính lượt ứng viên nộp câu trả
   lời. Gỡ cờ trước khi gửi là chốt chống bấm đúp (lượt hai thấy hết cờ → 409).
2. GỬI qua `scheduler` (điểm phát DUY NHẤT), KHÔNG giữ connection/khoá nào (Load boundary).
3. CHỐT hoặc HOÀN: gửi được → ghi mốc hiển thị; gửi hỏng → đóng phiên MỚI (chưa tới tay ai) và MỞ LẠI
   phiên cũ — ứng viên có thể đang cầm đúng link đó (ca chỉ thư NHẮC hỏng), đóng nó rồi gửi hỏng là họ
   mất cả hai link.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.nodes import scheduler
from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.audit_log import AuditLog
from app.models.email_delivery import DeliveryStatus, EmailDelivery
from app.models.screening_session import ScreeningSession
from app.services import audit_service, booking_flow, booking_service, screening
from app.services.email_delivery import EMAIL_COMPLAINED_FLAG, EMAIL_SEND_FAILED_FLAG
from app.services.resend_policy import ResendableEmail, resendable_email

logger = get_logger("app.services.email_resend")

__all__ = [
    "ResendError",
    "ResendableEmail",
    "latest_send_failure_reason",
    "resend_failed_email",
    "resendable_email",
]

# Lý do là văn bản do BÊN NGOÀI trả về (Resend) — cắt ngắn trước khi lên UI, cùng trần với
# `email_delivery._MAX_REASON`.
_MAX_REASON = 500


class ResendError(Exception):
    """Gửi lại không làm được (route dịch thẳng ra `status_code`). Người đọc là HR, nên thông điệp
    được phép nói rõ trạng thái nội bộ — đúng nếp `booking_flow.BookingActionError`."""

    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class _Claim:
    """Những gì pha CHIẾM đã cam kết — chỉ giá trị nguyên thuỷ, vì session bị `expunge_all` trước
    lượt gửi (xem `resend_failed_email`)."""

    kind: ResendableEmail
    applicant_email: str
    job_title: str
    new_session_id: int | None = None
    new_token: str | None = None
    retired_session_ids: tuple[int, ...] = ()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def latest_send_failure_reason(session: AsyncSession, application_id: int) -> str | None:
    """Lý do của lần gửi hỏng GẦN NHẤT — cho banner ⛔ của HR.

    Hai nguồn, vì hai đường vào của CÙNG một sự kiện (EMAIL-2) để lại dấu ở hai bảng khác nhau:
    - Resend từ chối NGAY lúc gọi (403 sandbox, cạn hạn mức…) → `_dispatch` KHÔNG tạo hàng
      `email_delivery` nào (không có `resend_email_id` để đối chiếu) — lý do CHỈ nằm ở audit
      `scheduler/email_failed`. Trước bản vá, banner bảo HR "kiểm tra lý do bên dưới" mà bên dưới
      trống trơn đúng ở ca phổ biến nhất này.
    - Resend nhận rồi mới báo hỏng qua webhook → `email_delivery.status = FAILED` + `bounce_reason`.
    Chọn SỰ KIỆN mới hơn rồi mới lấy lý do của nó: sự kiện mới nhất không kèm lý do thì trả `None`,
    KHÔNG mượn lý do của một lần hỏng cũ (có thể đã hết) — đó là trình bày sai nguyên nhân.
    """
    delivery = (
        await session.execute(
            select(EmailDelivery.bounce_reason, EmailDelivery.updated_at)
            .where(
                EmailDelivery.application_id == application_id,
                EmailDelivery.status == DeliveryStatus.FAILED.value,
            )
            .order_by(EmailDelivery.updated_at.desc(), EmailDelivery.id.desc())
            .limit(1)
        )
    ).first()
    audit = (
        await session.execute(
            select(AuditLog.detail, AuditLog.created_at)
            .where(
                AuditLog.application_id == application_id,
                AuditLog.node == "scheduler",
                AuditLog.action == "email_failed",
            )
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        )
    ).first()

    events: list[tuple[datetime, str | None]] = []
    if delivery is not None:
        events.append((delivery.updated_at, delivery.bounce_reason))
    if audit is not None:
        events.append((audit.created_at, (audit.detail or {}).get("error")))
    if not events:
        return None
    reason = max(events, key=lambda e: e[0])[1]
    return str(reason)[:_MAX_REASON] if reason else None


def _refusal(app_row: Application) -> str:
    """Thông điệp 409 nói ĐÚNG vì sao không gửi lại được — HR cần biết bước tiếp theo, không chỉ "không"."""
    flags = set(app_row.uncertainty_flags or [])
    if EMAIL_COMPLAINED_FLAG in flags:
        return "Ứng viên đã báo cáo thư là spam — không gửi thêm thư vào địa chỉ này."
    if EMAIL_SEND_FAILED_FLAG not in flags:
        return "Hồ sơ này không có thư nào gửi hỏng cần gửi lại (có thể vừa được gửi lại xong)."
    return (
        f"Không gửi lại thư từ đây khi hồ sơ đang ở {app_row.status}. Thư mời: duyệt lại ở hàng chờ "
        "hoặc dùng nút Gửi lại link đặt lịch."
    )


async def _lock_screening_sessions(
    session: AsyncSession, application_id: int, *, ids: tuple[int, ...] | None = None
) -> list[ScreeningSession]:
    """Khoá (FOR UPDATE) hàng phiên sàng lọc — LUÔN gọi TRƯỚC khi chạm hàng hồ sơ.

    `ids=None` → các phiên đang MỞ của hồ sơ (pha chiếm); có `ids` → đúng những phiên đó (pha chốt/
    hoàn). Lượt nộp câu trả lời đang resume giữ khoá hàng phiên: ta CHỜ ở đây, mà không giữ khoá hàng
    hồ sơ nào để nó phải chờ lại — nên không thể có deadlock. Sau khi nó commit, Postgres xét lại
    điều kiện WHERE trên bản mới, nên phiên vừa được dùng (`used_at`) tự rơi khỏi kết quả.
    """
    stmt = select(ScreeningSession).where(ScreeningSession.application_id == application_id)
    if ids is None:
        stmt = stmt.where(
            ScreeningSession.used_at.is_(None), ScreeningSession.timed_out_at.is_(None)
        )
    else:
        stmt = stmt.where(ScreeningSession.id.in_(ids))
    rows = await session.execute(stmt.order_by(ScreeningSession.id).with_for_update())
    return list(rows.scalars().all())


async def _locked_application(session: AsyncSession, application_id: int) -> Application | None:
    """Đọc LẠI hồ sơ dưới khoá hàng: `populate_existing` để không tin bản cũ trong identity map."""
    return await session.get(
        Application, application_id, populate_existing=True, with_for_update=True
    )


async def _claim(session: AsyncSession, application_id: int) -> _Claim:
    """Pha CHIẾM — xem docstring module. COMMIT trước khi trả về; không giữ khoá nào sau đó."""
    # Khoá tư vấn: CÙNG khoá với `booking_flow` và webhook `email_delivery`, nên webhook hạ trạng
    # thái không chen được vào giữa "đọc cờ" và "gỡ cờ".
    await booking_service.lock_application(session, application_id)
    open_sessions = await _lock_screening_sessions(session, application_id)
    app_row = await _locked_application(session, application_id)
    if app_row is None:
        await session.rollback()  # nhả khoá + connection
        raise ResendError(f"Application {application_id} không tồn tại.", status_code=404)

    kind = resendable_email(app_row.status, app_row.uncertainty_flags)
    if kind is None:
        message = _refusal(app_row)  # đọc TRƯỚC rollback — rollback expire mọi object
        await session.rollback()
        raise ResendError(message, status_code=409)

    applicant_email = app_row.applicant_email
    job_title = await booking_flow.job_title_of(session, app_row)
    app_row.uncertainty_flags = [
        f for f in (app_row.uncertainty_flags or []) if f != EMAIL_SEND_FAILED_FLAG
    ]

    claim = _Claim(kind=kind, applicant_email=applicant_email, job_title=job_title)
    detail: dict = {"to": applicant_email}
    if kind == "screener":
        # Bộ câu hỏi từ phiên GẦN NHẤT, KHÔNG đọc lại JD: ảnh chụp lúc gửi là thứ ứng viên được hỏi
        # (PRD §16) — HR sửa JD sau đó không được đổi câu hỏi giữa chừng.
        questions = (
            await session.execute(
                select(ScreeningSession.questions)
                .where(ScreeningSession.application_id == application_id)
                .order_by(ScreeningSession.created_at.desc(), ScreeningSession.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if questions is None:
            await session.rollback()
            raise ResendError(
                "Không tìm thấy phiên sàng lọc nào của hồ sơ này để gửi lại.", status_code=409
            )
        # Phiên cũ ĐÓNG ngay (không để hai link sống song song): còn mở thì lưới sweep vẫn nhắc bằng
        # link CŨ, rồi tới hạn CŨ resume `no_response` trong khi phiên mới còn nguyên hạn. Gửi hỏng thì
        # pha HOÀN mở lại đúng những phiên này.
        now = _now()
        for row in open_sessions:
            row.timed_out_at = now
        fresh = screening.create_session(session, application_id, list(questions or []))
        await session.flush()  # có `fresh.id` (dưới đúng các khoá đang giữ)
        claim = _Claim(
            kind=kind, applicant_email=applicant_email, job_title=job_title,
            new_session_id=fresh.id, new_token=fresh.token,
            retired_session_ids=tuple(r.id for r in open_sessions),
        )
        detail["expires_at"] = fresh.expires_at.isoformat()

    # FR-HR-5: hành động của HR vào audit — kết quả gửi do `_dispatch` ghi riêng (email_sent/failed).
    await audit_service.record(
        session, application_id=application_id, node="human_review",
        action="screener_resent" if kind == "screener" else "rejection_resent",
        detail=detail, commit=True,
    )
    # `record(commit=True)` kết thúc bằng `refresh()`, thứ AUTOBEGIN một transaction mới và giữ
    # connection — đóng nó TRƯỚC khi gọi Resend (Load boundary).
    await session.commit()
    return claim


async def _settle_screener(session: AsyncSession, application_id: int, claim: _Claim) -> None:
    """Gửi ĐƯỢC: ghi mốc hiển thị (`screener_sent_at`/`screener_deadline`) theo phiên mới — chỉ khi
    hồ sơ vẫn đang chờ (ứng viên có thể vừa nộp trên phiên mới ngay khi thư tới)."""
    assert claim.new_session_id is not None  # chỉ gọi cho thư sàng lọc — pha chiếm luôn tạo phiên
    await booking_service.lock_application(session, application_id)
    rows = await _lock_screening_sessions(session, application_id, ids=(claim.new_session_id,))
    app_row = await _locked_application(session, application_id)
    if rows and app_row is not None and app_row.status == ApplicationStatus.AWAITING_SCREENER.value:
        screening.mark_screener_sent(app_row, rows[0])
    await session.commit()


async def _undo_screener(session: AsyncSession, application_id: int, claim: _Claim) -> None:
    """Gửi HỎNG: đóng phiên MỚI (chưa tới tay ai), MỞ LẠI phiên cũ — trả hồ sơ về đúng như trước khi
    bấm. Không mở lại nếu hồ sơ đã rời `AWAITING_SCREENER` trong lúc gửi (vd webhook vừa hạ trạng
    thái): một phiên mở cho hồ sơ không còn chờ là phiên mập mờ mà AI_GUIDE cấm để lại."""
    assert claim.new_session_id is not None  # chỉ gọi cho thư sàng lọc — pha chiếm luôn tạo phiên
    ids = (claim.new_session_id, *claim.retired_session_ids)
    await booking_service.lock_application(session, application_id)
    rows = await _lock_screening_sessions(session, application_id, ids=ids)
    app_row = await _locked_application(session, application_id)
    still_waiting = (
        app_row is not None and app_row.status == ApplicationStatus.AWAITING_SCREENER.value
    )
    now = _now()
    for row in rows:
        if row.used_at is not None:
            continue
        if row.id == claim.new_session_id:
            row.timed_out_at = row.timed_out_at or now
        elif still_waiting:
            row.timed_out_at = None
    await session.commit()


async def resend_failed_email(session: AsyncSession, application_id: int) -> Application:
    """Gửi lại lá thư đã hỏng của hồ sơ này. Trả hàng đọc mới (serialize được ngay).

    `ResendError`: 404 không có hồ sơ · 409 không có gì để gửi lại · 502 dịch vụ gửi VẪN từ chối (hồ
    sơ được trả về đúng như trước khi bấm, `_dispatch` đã gắn lại cờ — HR sửa cấu hình rồi bấm lại).

    GIỚI HẠN ĐÃ BIẾT (at-most-once, cùng triết lý mốc nhắc của sweep): tiến trình chết đúng giữa pha
    chiếm và lượt gửi thì cờ đã gỡ mà thư chưa đi. Thư sàng lọc tự lành qua lời nhắc 24h của phiên
    mới; thư từ chối thì không — dấu vết còn lại là audit `*_resent` không có `email_sent:*`/
    `email_failed` theo sau.
    """
    claim = await _claim(session, application_id)

    # `_dispatch` gắn lại cờ khi gửi hỏng bằng `session.get(Application)` — trả bản trong identity
    # map nếu còn, mà bản đó là ảnh chụp lúc chiếm. Webhook complaint tới giữa chừng sẽ bị ghi đè mất
    # (đo được trên DB thật). Tách hết để nó đọc hàng MỚI.
    session.expunge_all()

    if claim.kind == "screener":
        result = await scheduler.notify_screener(
            session, application_id=application_id, applicant_email=claim.applicant_email,
            job_title=claim.job_title,
            form_url=f"{settings.frontend_base_url.rstrip('/')}/screening/{claim.new_token}",
            # `:g` — float, tránh "72.0 giờ" trong thư (lỗi #4 verify prod 18/08).
            deadline_text=f"{settings.screener_deadline_hours:g} giờ",
        )
    else:
        result = await scheduler.notify_decision(
            session, "reject", application_id=application_id,
            applicant_email=claim.applicant_email, job_title=claim.job_title,
        )

    if not result.get("email_sent"):
        logger.warning(
            "email_resend: app=%s gửi lại thư %s VẪN thất bại", application_id, claim.kind
        )
        if claim.kind == "screener":
            await _undo_screener(session, application_id, claim)
        reason = str(result.get("error") or "không rõ lý do").rstrip(". ")  # lỗi Resend tự kết bằng "."
        raise ResendError(
            f"Dịch vụ gửi thư vẫn từ chối: {reason}. Hồ sơ và liên kết cũ được giữ nguyên — sửa cấu "
            "hình gửi thư rồi bấm lại.",
            status_code=502,
        )

    if claim.kind == "screener":
        await _settle_screener(session, application_id, claim)
    logger.info("email_resend: app=%s đã gửi lại thư %s", application_id, claim.kind)
    # Đọc MỚI ở CUỐI: route serialize bằng code ĐỒNG BỘ — một thuộc tính expired ở đây là
    # MissingGreenlet → HTTP 500 dù thư đã đi (gotcha verify prod 18/08 — hai nút lịch).
    reloaded = await session.get(Application, application_id, populate_existing=True)
    if reloaded is None:  # hồ sơ bị xoá giữa chừng — thư đã đi, không còn gì để trả
        raise ResendError(f"Application {application_id} không tồn tại.", status_code=404)
    return reloaded
