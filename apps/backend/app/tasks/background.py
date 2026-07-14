"""Xử lý bất đồng bộ bằng FastAPI BackgroundTasks (PRD §8.3, NFR-1).

CLAUDE.md: KHÔNG worker polling Redis (phá free-tier Upstash) — dùng BackgroundTasks.
Scaffold: chạy pipeline stub, ghi audit_log từng node + quyết định cuối, cập nhật Application.

TODO (PRD §10): Screener suspend/resume cần Upstash QStash (public URL) + Postgres checkpointer;
hiện chạy thẳng một mạch (chưa suspend).
"""

from __future__ import annotations

from app.agents.nodes import scheduler
from app.agents.runner import resume_with_trace, run_with_trace
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.application import Application, ApplicationStatus
from app.models.job_posting import JobPosting
from app.services import audit_service, job_service

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

            # JD cho ranker (nếu application gắn job_id + JD tồn tại).
            jd = None
            job = None
            if application.job_id is not None:
                job = await session.get(JobPosting, application.job_id)
                if job is not None:
                    jd = job_service.jd_dict(job)

            out = await run_with_trace(
                force_review=force_review,
                applicant_email=application.applicant_email,
                application_id=application_id,
                cv_path=application.cv_file_ref,  # parser đọc CV thật từ đây
                jd=jd,                             # ranker đọc JD thật từ đây
            )
            final = out["final"]

            # Ghi audit cho từng node (parser + ranker đã THẬT; screener/scheduler vẫn stub).
            for step in out["trace"]:
                node = step["node"]
                flags = step.get("uncertainty_flags", []) or []
                if node == "parser":
                    action = "parse_failed" if "parse_failed" in flags else "parsed"
                    detail = {"status": step.get("status"), **_parsed_summary(final.get("parsed_data"))}
                elif node == "ranker":
                    action = "rank_failed" if "rank_failed" in flags else "ranked"
                    detail = {
                        "status": step.get("status"),
                        "score": final.get("score"),
                        "semantic_similarity": final.get("semantic_similarity"),
                    }
                elif node == "gate":  # auto-từ-chối (PRD §9) — thư từ chối gửi ở khối bên dưới.
                    action = "auto_reject"
                    detail = {"status": step.get("status"), "score": final.get("score")}
                else:
                    action = "stub_pass_through"
                    detail = {"status": step.get("status")}
                await audit_service.record(
                    session, application_id=application_id, node=node,
                    action=action, confidence=step.get("confidence"),
                    uncertainty_flags=flags, detail=detail, commit=False,
                )

            # Ca ĐẠT dừng ở screener (interrupt) → AWAITING_SCREENER (chưa quyết, chờ resume — PRD §10).
            # KHÔNG coi là "xong": state đã lưu bền ở checkpointer (thread_id=app-id); email/quyết định
            # chỉ xảy ra SAU khi resume. final.status ở đây là RANKING (screener chưa trả) nên set tường minh.
            suspended = out.get("suspended", False)
            persisted_status = (
                ApplicationStatus.AWAITING_SCREENER.value
                if suspended
                else final.get("status", application.status)
            )
            application.status = persisted_status
            application.parsed_data = final.get("parsed_data") or {}
            application.score = final.get("score")
            application.score_breakdown = {
                "criteria": final.get("score_breakdown") or [],
                "summary": (final.get("scratchpad") or {}).get("rank_summary"),
                "semantic_similarity": final.get("semantic_similarity"),
            }
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

            # Gom dữ liệu email auto-reject vào biến cục bộ để khối gửi (SAU commit) không phụ thuộc
            # ORM object — dữ liệu email tách khỏi vòng đời session.
            auto_reject = out["branch"] == "auto_reject"
            if auto_reject:
                reject_email = application.applicant_email
                reject_name = (final.get("parsed_data") or {}).get("full_name") or "Ứng viên"
                reject_title = job.title if job is not None else "vị trí ứng tuyển"

            await session.commit()
            logger.info(
                "BG: xong application_id=%s -> branch=%s status=%s",
                application_id, out["branch"], persisted_status,
            )

            # Gate auto-từ-chối (PRD §9): quyết định (REJECTED) ĐÃ commit → gửi thư từ chối THẬT qua
            # scheduler (điểm phát email DUY NHẤT), KHÔNG có HR, KHÔNG suspend. CÔ LẬP khỏi handler
            # lỗi kỹ thuật bên dưới: mọi lỗi ở đây (kể cả lỗi commit audit của notify_decision sau khi
            # email đã gửi) KHÔNG được reset REJECTED về PENDING_REVIEW — nuốt + log (như review 03b).
            if auto_reject:
                try:
                    await scheduler.notify_decision(
                        session, "reject", application_id=application_id,
                        applicant_email=reject_email, candidate_name=reject_name,
                        job_title=reject_title,
                    )
                except Exception:  # noqa: BLE001 — REJECTED đã commit; lỗi email/audit KHÔNG làm sập
                    logger.exception(
                        "BG: notify_decision(reject) lỗi SAU khi REJECTED đã commit app=%s",
                        application_id,
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


async def resume_screener(
    session, application_id: int, resume_payload: dict
) -> dict:
    """Resume pipeline TỪ screener (08a: dev/test — 08b sẽ thay trigger = ứng viên nộp form magic-link).

    `Command(resume=payload)` cấp câu trả lời (mock ở 08a) cho `interrupt()` → screener chạy tiếp →
    human_review → PENDING_REVIEW. KHÔNG chạy lại parser/ranker (checkpointer nạp state cũ — PRD §10).
    Persist status/flags + audit các node resume. Chữ ký khớp gọi từ endpoint (đã validate AWAITING_SCREENER).
    """
    logger.info("BG-resume: resume screener application_id=%s", application_id)
    out = await resume_with_trace(application_id=application_id, resume_payload=resume_payload)
    final = out["final"]

    application = await session.get(Application, application_id)
    if application is None:
        logger.warning("BG-resume: application_id=%s không tồn tại — bỏ qua", application_id)
        return {"application_id": application_id, "status": None, "branch": out["branch"]}

    for step in out["trace"]:  # trace resume: screener (+ human_review). parser/ranker KHÔNG chạy lại.
        node = step["node"]
        if node == "screener":
            action = "screener_resumed"
        elif node == "human_review":
            action = "queued_for_human_review"
        else:
            action = "stub_pass_through"
        await audit_service.record(
            session, application_id=application_id, node=node, action=action,
            confidence=step.get("confidence"), uncertainty_flags=step.get("uncertainty_flags", []),
            detail={"status": step.get("status")}, commit=False,
        )

    application.status = final.get("status", application.status)
    application.confidence = final.get("confidence")
    application.uncertainty_flags = final.get("uncertainty_flags", []) or []
    application.escalation_reason = final.get("escalation_reason")

    await audit_service.record(
        session, application_id=application_id, node="system",
        action=f"route:{out['branch']}", escalation_reason=final.get("escalation_reason"),
        detail={"final_status": final.get("status"), "resumed": True}, commit=False,
    )
    await session.commit()
    logger.info(
        "BG-resume: xong application_id=%s -> branch=%s status=%s",
        application_id, out["branch"], final.get("status"),
    )
    return {"application_id": application_id, "status": final.get("status"), "branch": out["branch"]}
