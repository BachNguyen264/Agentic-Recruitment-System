"""Xử lý bất đồng bộ bằng FastAPI BackgroundTasks (PRD §8.3, NFR-1).

CLAUDE.md: KHÔNG worker polling Redis (phá free-tier Upstash) — dùng BackgroundTasks.
Scaffold: chạy pipeline stub, ghi audit_log từng node + quyết định cuối, cập nhật Application.

TODO (PRD §10): Screener suspend/resume cần Upstash QStash (public URL) + Postgres checkpointer;
hiện chạy thẳng một mạch (chưa suspend).
"""

from __future__ import annotations

from app.agents.runner import run_with_trace
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.services import audit_service

logger = get_logger("app.tasks.background")


def _parsed_summary(parsed: dict | None) -> dict:
    """Tóm tắt parsed_data cho audit detail (PRD §16) — không nhồi cả CV vào log."""
    if not parsed:
        return {"has_parsed_data": False}
    return {
        "has_parsed_data": True,
        "full_name": parsed.get("full_name"),
        "skills_count": len(parsed.get("skills") or []),
        "experiences_count": len(parsed.get("experiences") or []),
        "education_count": len(parsed.get("education") or []),
    }


async def process_application(application_id: int, *, force_review: bool = False) -> None:
    """Mỗi CV một pipeline độc lập (FR-PIPE-1). Ghi audit mọi bước (FR-PIPE-4)."""
    logger.info("BG: bắt đầu xử lý application_id=%s", application_id)
    async with AsyncSessionLocal() as session:
        application = await session.get(Application, application_id)
        if application is None:
            logger.warning("BG: application_id=%s không tồn tại — bỏ qua", application_id)
            return

        try:
            await audit_service.record(
                session, application_id=application_id, node="system",
                action="received", detail={"source": "background_task"}, commit=False,
            )

            out = await run_with_trace(
                force_review=force_review,
                applicant_email=application.applicant_email,
                application_id=application_id,
                cv_path=application.cv_file_ref,  # parser đọc CV thật từ đây
            )
            final = out["final"]

            # Ghi audit cho từng node (parser đã THẬT; ranker/screener/scheduler vẫn stub).
            for step in out["trace"]:
                node = step["node"]
                flags = step.get("uncertainty_flags", []) or []
                if node == "parser":
                    action = "parse_failed" if "parse_failed" in flags else "parsed"
                    detail = {"status": step.get("status"), **_parsed_summary(final.get("parsed_data"))}
                else:
                    action = "stub_pass_through"
                    detail = {"status": step.get("status")}
                await audit_service.record(
                    session, application_id=application_id, node=node,
                    action=action, confidence=step.get("confidence"),
                    uncertainty_flags=flags, detail=detail, commit=False,
                )

            application.status = final.get("status", application.status)
            application.parsed_data = final.get("parsed_data") or {}
            application.confidence = final.get("confidence")
            application.uncertainty_flags = final.get("uncertainty_flags", []) or []
            application.escalation_reason = final.get("escalation_reason")

            await audit_service.record(
                session, application_id=application_id, node="system",
                action=f"route:{out['branch']}", confidence=final.get("confidence"),
                uncertainty_flags=final.get("uncertainty_flags", []),
                escalation_reason=final.get("escalation_reason"),
                detail={"final_status": final.get("status")}, commit=False,
            )
            await session.commit()
            logger.info(
                "BG: xong application_id=%s -> branch=%s status=%s",
                application_id, out["branch"], final.get("status"),
            )
        except Exception:  # noqa: BLE001 — lỗi kỹ thuật -> PENDING_REVIEW[error] (PRD §13)
            logger.exception("BG: lỗi xử lý application_id=%s", application_id)
            await session.rollback()
            application = await session.get(Application, application_id)
            if application is not None:
                application.status = ApplicationStatus.PENDING_REVIEW.value
                application.escalation_reason = "Lỗi kỹ thuật khi xử lý pipeline (error)."
                await audit_service.record(
                    session, application_id=application_id, node="system",
                    action="error", escalation_reason="technical_error", commit=True,
                )
