"""stuck_applications — đối soát hồ sơ KẸT giữa pipeline (hardening tải · PRD §13).

VÌ SAO CẦN: pipeline chạy trong `BackgroundTasks` — KHÔNG bền. Hai đường làm hồ sơ kẹt CÂM ở trạng
thái "đang xử lý" trong khi ứng viên đã nhận 201 "nộp thành công":
  1) Tiến trình backend restart / OOM giữa chừng → task đang chạy biến mất, không ai ghi lại gì.
  2) Pool DB cạn tới mức chính đường xử-lý-lỗi cũng không mở nổi session để hạ hồ sơ về
     PENDING_REVIEW[error] (xem `background._escalate_technical_error`).
Không có lưới này thì hồ sơ nằm mãi ở SUBMITTED, `audit_log` TRỐNG, dashboard hiện "Vừa nộp" — đúng
loại "trạng thái nói dối" mà dự án coi là nghiêm trọng nhất, và ứng viên guest KHÔNG có tài khoản
nào để mà khiếu nại.

TUYỆT ĐỐI KHÔNG auto-reject. Im lặng của HỆ THỐNG lại càng không phải lỗi của ứng viên: mọi hồ sơ
kẹt đều về NGƯỜI (PENDING_REVIEW + nhãn `[error]`), đúng bất biến "cờ thắng gate" (PRD §9) và §13
("lỗi kỹ thuật vào PENDING_REVIEW nhưng gắn nhãn [error]").

Mechanism-agnostic như `screening_timeout`: chỉ nhận `session_factory`, KHÔNG biết ai gọi mình.
`screening_scheduler` quyết khi nào gọi (nay: sweep loop in-process; đổi sang QStash sau KHÔNG phải
sửa file này).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.services import audit_service

logger = get_logger("app.services.stuck_applications")

_STUCK_REASON = "Xử lý bị gián đoạn giữa chừng — cần HR xem lại (error)."

# Trạng thái "ĐANG BAY": pipeline CHƯA ra quyết định và CHƯA có email nào gửi cho ứng viên, nên đưa
# về hàng chờ HR là an toàn tuyệt đối. CỐ Ý bỏ ra ngoài:
#   - SCHEDULING: nghĩa là "đã quyết mời, thư mời CÓ THỂ đã gửi". Kéo nó về hàng chờ HR là mở đúng
#     đường cho "mời xong lại từ chối" — cái mà `background` bỏ công cô lập dispatch để tránh.
#   - AWAITING_SCREENER: đã có deadline + sweep RIÊNG (`screening_timeout`). Hai lưới cùng đụng một
#     hồ sơ thì chúng giẫm chân nhau (timeout resume graph vs đối soát ghi thẳng status).
_STUCK_STATUSES = (
    ApplicationStatus.SUBMITTED.value,
    ApplicationStatus.PARSING.value,
    ApplicationStatus.RANKING.value,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _due_stuck_ids(session: AsyncSession, cutoff: datetime) -> list[int]:
    """id hồ sơ còn ở trạng thái đang-bay mà đã quá lâu KHÔNG được đụng tới (`updated_at <= cutoff`).

    Mốc dùng `updated_at` (TimestampMixin: server_default khi INSERT + onupdate mỗi UPDATE) — pipeline
    chạy xong luôn UPDATE hồ sơ nên hồ sơ khoẻ mạnh tự đẩy mốc này về hiện tại.
    """
    stmt = select(Application.id).where(
        Application.status.in_(_STUCK_STATUSES),
        Application.updated_at <= cutoff,
    )
    return list((await session.execute(stmt)).scalars().all())


async def _lock_application(session: AsyncSession, application_id: int) -> Application | None:
    """SELECT … FOR UPDATE theo id — khóa hàng để re-check chống đua với pipeline đang ghi kết quả."""
    stmt = select(Application).where(Application.id == application_id).with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def reconcile_stuck_application(session: AsyncSession, app_row: Application) -> None:
    """Đưa MỘT hồ sơ kẹt về PENDING_REVIEW[error] + ghi audit (PRD §13, NFR-3). Caller đã row-lock.

    Idempotent tự nhiên: sau khi đổi, `status` không còn nằm trong `_STUCK_STATUSES` nên vòng quét sau
    không nhặt lại. Audit ghi `previous_status` để HR/hậu kiểm biết hồ sơ đã kẹt ở đâu.
    """
    previous_status = app_row.status
    stuck_since = app_row.updated_at
    app_row.status = ApplicationStatus.PENDING_REVIEW.value
    app_row.escalation_reason = _STUCK_REASON
    await audit_service.record(
        session, application_id=app_row.id, node="system", action="stuck_reconciled",
        escalation_reason="stuck_pipeline",
        detail={
            "previous_status": previous_status,
            "stuck_since": stuck_since.isoformat() if stuck_since is not None else None,
        },
        commit=True,  # cùng transaction với UPDATE application ở trên → nguyên tử
    )
    logger.warning(
        "sweep-stuck: app=%s kẹt ở %s quá hạn → PENDING_REVIEW[error]", app_row.id, previous_status
    )


async def sweep_stuck_once(session_factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """MỘT vòng đối soát: tìm hồ sơ kẹt quá hạn → xử lý TỪNG cái trong transaction RIÊNG (row-lock +
    re-check trong lock). Lỗi một hồ sơ KHÔNG làm chết cả vòng. Trả {reconciled, errors}.

    `STUCK_APPLICATION_TIMEOUT_MINUTES <= 0` = TẮT lưới (thoát sớm, không truy vấn gì).
    """
    threshold = settings.stuck_application_timeout_minutes
    if threshold <= 0:
        return {"reconciled": 0, "errors": 0}

    cutoff = _now() - timedelta(minutes=threshold)
    async with session_factory() as read_sess:
        stuck_ids = await _due_stuck_ids(read_sess, cutoff)

    counts = {"reconciled": 0, "errors": 0}
    for aid in stuck_ids:
        try:
            async with session_factory() as s:
                app_row = await _lock_application(s, aid)
                # Re-check TRONG lock: pipeline có thể vừa ghi kết quả xong giữa lúc quét và lúc khóa
                # (khi đó status đã rời _STUCK_STATUSES / updated_at đã mới) — KHÔNG được đè lên nó.
                if app_row is None or app_row.status not in _STUCK_STATUSES:
                    continue
                if app_row.updated_at is not None and app_row.updated_at > cutoff:
                    continue
                await reconcile_stuck_application(s, app_row)
                counts["reconciled"] += 1
        except Exception:  # noqa: BLE001 — một hồ sơ lỗi KHÔNG làm chết cả vòng sweep
            counts["errors"] += 1
            logger.exception("sweep-stuck: lỗi khi đối soát application id=%s", aid)

    if any(counts.values()):
        logger.warning(
            "sweep-stuck: reconciled=%s errors=%s", counts["reconciled"], counts["errors"]
        )
    return counts
