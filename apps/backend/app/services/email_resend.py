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

THỨ TỰ trong `resend_failed_email` là có chủ ý — mỗi bước chặn một lỗi đã từng cắn ở repo này:
khoá theo hồ sơ → đọc lại dưới khoá → GỠ CỜ + phát phiên mới + audit → COMMIT → gửi → `refresh`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import select, update
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

logger = get_logger("app.services.email_resend")

__all__ = [
    "ResendError",
    "ResendableEmail",
    "latest_send_failure_reason",
    "resend_failed_email",
    "resendable_email",
]

ResendableEmail = Literal["screener", "reject"]

# Trạng thái → loại thư gửi lại được ở trạng thái đó. Chỉ hai ca KHÔNG còn đường cứu nào khác.
_RESENDABLE_BY_STATUS: dict[str, ResendableEmail] = {
    ApplicationStatus.AWAITING_SCREENER.value: "screener",
    ApplicationStatus.REJECTED.value: "reject",
}

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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def resendable_email(status: str, flags: list | None) -> ResendableEmail | None:
    """Loại thư HR gửi lại được cho hồ sơ này, hoặc `None`. Nguồn DUY NHẤT cho cả nút trên UI
    (`ApplicationRead.resendable_email`) lẫn chốt chặn của `resend_failed_email` — hai nơi tự suy
    riêng thì HR thấy nút rồi bấm ra 409.

    - Phải có `email_send_failed`: đây là đường CỨU một lá thư hỏng, không phải kênh nhắc tuỳ ý.
      Bounce KHÔNG tính — địa chỉ chết thì gửi lại vào đúng địa chỉ đó là vô ích.
    - Ứng viên đã báo spam (`email_complained`) → không bao giờ gửi thêm: complaint hại danh tiếng
      gửi email của CẢ hệ thống.
    """
    current = set(flags or [])
    if EMAIL_SEND_FAILED_FLAG not in current or EMAIL_COMPLAINED_FLAG in current:
        return None
    return _RESENDABLE_BY_STATUS.get(status)


async def latest_send_failure_reason(session: AsyncSession, application_id: int) -> str | None:
    """Lý do GẦN NHẤT khiến dịch vụ gửi không đẩy được thư đi — cho banner ⛔ của HR.

    Hai nguồn, vì hai đường vào của CÙNG một sự kiện (EMAIL-2) để lại dấu ở hai bảng khác nhau:
    - Resend từ chối NGAY lúc gọi (403 sandbox, cạn hạn mức…) → `_dispatch` KHÔNG tạo hàng
      `email_delivery` nào (không có `resend_email_id` để đối chiếu) — lý do CHỈ nằm ở audit
      `scheduler/email_failed`. Trước bản vá, banner bảo HR "kiểm tra lý do bên dưới" mà bên dưới
      trống trơn đúng ở ca phổ biến nhất này.
    - Resend nhận rồi mới báo hỏng qua webhook → `email_delivery.status = FAILED` + `bounce_reason`.
    Lấy cái MỚI hơn: thứ HR cần đọc là lỗi đang chặn họ bây giờ, không phải lỗi đã qua.
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

    candidates: list[tuple[datetime, str]] = []
    if delivery is not None and delivery.bounce_reason:
        candidates.append((delivery.updated_at, delivery.bounce_reason))
    if audit is not None and (audit.detail or {}).get("error"):
        candidates.append((audit.created_at, str(audit.detail["error"])))
    if not candidates:
        return None
    return max(candidates, key=lambda c: c[0])[1][:_MAX_REASON]


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


async def _reissue_screening_session(session: AsyncSession, app_row: Application) -> ScreeningSession:
    """Đóng phiên sàng lọc đang mở + phát phiên MỚI (FR-SCR-7). KHÔNG commit — caller commit.

    Phiên MỚI chứ không dùng lại token cũ (quyết định của người dùng, cùng nguyên tắc §10b.6 "phát
    phiên MỚI, TTL mới"): ứng viên chưa từng nhận thư, nên hạn 72h và mốc nhắc 24h phải tính từ lúc
    họ THỰC SỰ nhận được — dùng lại phiên cũ thì gửi lại ở giờ thứ 70 chỉ còn 2 giờ để trả lời.

    Phiên cũ PHẢI đóng (`timed_out_at`, đúng cách `email_delivery._abandon_in_flight_session` đóng
    phiên): để nó sống thì lưới sweep vẫn đi nhắc bằng link CŨ, rồi tới hạn CŨ nó resume graph với
    `no_response` và kéo hồ sơ về `PENDING_REVIEW` trong khi phiên mới còn nguyên hạn.

    Bộ câu hỏi lấy từ phiên gần nhất, KHÔNG đọc lại JD: ảnh chụp lúc gửi là thứ ứng viên được hỏi
    (PRD §16), HR sửa JD sau đó không được đổi câu hỏi giữa chừng.
    """
    latest = (
        await session.execute(
            select(ScreeningSession)
            .where(ScreeningSession.application_id == app_row.id)
            .order_by(ScreeningSession.created_at.desc(), ScreeningSession.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        raise ResendError("Không tìm thấy phiên sàng lọc nào của hồ sơ này để gửi lại.", status_code=409)
    questions = list(latest.questions or [])

    await session.execute(
        update(ScreeningSession)
        .where(
            ScreeningSession.application_id == app_row.id,
            ScreeningSession.used_at.is_(None),
            ScreeningSession.timed_out_at.is_(None),
        )
        .values(timed_out_at=_now())
    )
    fresh = screening.create_session(session, app_row.id, questions)
    screening.mark_screener_sent(app_row, fresh)
    return fresh


async def resend_failed_email(session: AsyncSession, application_id: int) -> Application:
    """Gửi lại lá thư đã hỏng của hồ sơ này. Trả hàng đã nạp lại (serialize được ngay).

    `ResendError`: 404 không có hồ sơ · 409 không có gì để gửi lại · 502 dịch vụ gửi VẪN từ chối
    (hồ sơ giữ nguyên trạng thái, `_dispatch` đã gắn lại cờ — HR sửa cấu hình rồi bấm lại).
    """
    # Khoá theo hồ sơ TRƯỚC khi đọc — CÙNG khoá với `booking_flow` và webhook `email_delivery`, nên
    # một lượt webhook hạ trạng thái không chen được vào giữa "đọc cờ" và "gỡ cờ" của ta.
    await booking_service.lock_application(session, application_id)
    app_row = await session.get(Application, application_id)
    if app_row is None:
        await session.rollback()  # nhả khoá + connection
        raise ResendError(f"Application {application_id} không tồn tại.", status_code=404)

    kind = resendable_email(app_row.status, app_row.uncertainty_flags)
    if kind is None:
        message = _refusal(app_row)
        await session.rollback()
        raise ResendError(message, status_code=409)

    # Gom nguyên thuỷ TRƯỚC mọi commit (gotcha expire/refresh — lỗi #3 SCH-2).
    applicant_email = app_row.applicant_email
    job_title = await booking_flow.job_title_of(session, app_row)

    # GỠ CỜ TRƯỚC KHI GỬI (at-most-once, cùng triết lý mốc nhắc của sweep): lượt bấm thứ hai — đúp
    # chuột, hai tab — chờ khoá xong sẽ thấy hết cờ và nhận 409, thay vì phát thêm một link khiến
    # link vừa gửi chết dưới chân ứng viên. Gửi hỏng thì `_dispatch` tự gắn cờ lại.
    app_row.uncertainty_flags = [
        f for f in (app_row.uncertainty_flags or []) if f != EMAIL_SEND_FAILED_FLAG
    ]
    detail: dict = {"to": applicant_email}
    form_url = ""
    if kind == "screener":
        try:
            fresh = await _reissue_screening_session(session, app_row)
        except ResendError:
            await session.rollback()
            raise
        form_url = f"{settings.frontend_base_url.rstrip('/')}/screening/{fresh.token}"
        detail["expires_at"] = fresh.expires_at.isoformat()

    # FR-HR-5: hành động của HR vào audit — kết quả gửi do `_dispatch` ghi riêng (email_sent/failed).
    await audit_service.record(
        session, application_id=application_id, node="human_review",
        action="screener_resent" if kind == "screener" else "rejection_resent",
        detail=detail, commit=True,
    )
    # `record(commit=True)` kết thúc bằng `refresh()`, thứ AUTOBEGIN một transaction mới và giữ
    # connection — đóng nó TRƯỚC khi gọi Resend (Load boundary). `commit()` chứ không `rollback()`:
    # rollback expire mọi object, đọc `app_row` sau đó là nạp lười (gotcha `cancel_by_candidate`).
    await session.commit()

    if kind == "screener":
        result = await scheduler.notify_screener(
            session, application_id=application_id, applicant_email=applicant_email,
            job_title=job_title, form_url=form_url,
            # `:g` — float, tránh "72.0 giờ" trong thư (lỗi #4 verify prod 18/08).
            deadline_text=f"{settings.screener_deadline_hours:g} giờ",
        )
    else:
        result = await scheduler.notify_decision(
            session, "reject", application_id=application_id,
            applicant_email=applicant_email, job_title=job_title,
        )

    if not result.get("email_sent"):
        logger.warning("email_resend: app=%s gửi lại thư %s VẪN thất bại", application_id, kind)
        raise ResendError(
            f"Dịch vụ gửi thư vẫn từ chối: {result.get('error')}. Hồ sơ giữ nguyên — sửa cấu hình "
            "gửi thư rồi bấm lại.",
            status_code=502,
        )

    logger.info("email_resend: app=%s đã gửi lại thư %s", application_id, kind)
    # Ở CUỐI, sau lượt gửi mail: route serialize hàng bằng code ĐỒNG BỘ, `updated_at` đã expired sau
    # UPDATE → thiếu dòng này là HTTP 500 dù thư đã đi (gotcha verify prod 18/08 — hai nút lịch).
    await session.refresh(app_row)
    return app_row
