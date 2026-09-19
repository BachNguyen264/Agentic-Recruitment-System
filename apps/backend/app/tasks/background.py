"""Xử lý bất đồng bộ bằng FastAPI BackgroundTasks (PRD §8.3, NFR-1).

CLAUDE.md: KHÔNG worker polling — dùng BackgroundTasks. Thêm một hàng đợi ngoài nghĩa là thêm một
hạ tầng phải nuôi + một vòng polling chạy liên tục kể cả lúc không có việc, đổi lại không giải quyết
thêm được gì ở quy mô này.

Ghi audit_log từng node + quyết định cuối, cập nhật Application. Screener suspend/resume chạy THẬT
qua `interrupt()` + AsyncPostgresSaver (08a-08d).
"""

from __future__ import annotations

import asyncio

from app.agents.nodes import scheduler
from app.agents.runner import resume_with_trace, run_with_trace
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.models.application import IN_FLIGHT_STATUSES, Application, ApplicationStatus
from app.models.job_posting import JobPosting
from app.services import audit_service, booking_flow, job_service
# F1 (final review, hardening email): chỉ hai TÊN cờ — dùng để giữ lại cờ email khi resume ghi đè
# uncertainty_flags (graph không biết webhook Resend, xem resume_screener). KHÔNG vòng import: email_
# delivery chỉ kéo app.models/app.services.audit_service/app.services.booking_flow — không module nào
# trong đó import app.tasks.background ngược lại.
from app.services.email_delivery import (
    EMAIL_BOUNCED_FLAG,
    EMAIL_COMPLAINED_FLAG,
    EMAIL_SEND_FAILED_FLAG,
)

logger = get_logger("app.tasks.background")

# ── ĐỒNG HỒ ĐO PIPELINE (chỉ chẩn đoán — `GET /api/health/metrics` ĐỌC, không ai khác GHI) ─────────
# VÌ SAO cần: `process_application` chạy trong BackgroundTasks nên KHÔNG có gì ở ngoài nhìn thấy nó.
# Load test chỉ đo được "201 trả về nhanh cỡ nào" (tầng NHẬN) chứ mù hoàn toàn về tầng XỬ LÝ — muốn
# biết bao nhiêu pipeline đang bay CÙNG LÚC thì trước đây phải suy từ trạng thái trong DB, tức là
# thêm truy vấn vào đúng cái pool đang muốn đo. Bốn số nguyên trong RAM thì không đụng gì cả.
#
# VÌ SAO KHÔNG khoá: cả bốn biến CHỈ bị đổi trong `process_application`, một coroutine chạy trên
# event loop chính; `+= 1` là thao tác đồng bộ, KHÔNG có `await` xen giữa đọc và ghi ⇒ không có điểm
# nhường lượt nào để hai coroutine giẫm lên nhau. Thêm `Lock` ở đây chỉ tạo ảo giác an toàn.
#
# BẤT BIẾN: `_STARTED == _FINISHED + _IN_FLIGHT` (đúng ở MỌI thời điểm — `finally` chạy cả khi
# coroutine bị cancel). `_FAILED` là TẬP CON của `_FINISHED`, không phải nhánh song song: một pipeline
# hỏng vẫn là một pipeline đã kết thúc. Load test dựa vào bất biến này để phát hiện rò rỉ.
_PIPELINES_IN_FLIGHT = 0
_PIPELINES_STARTED = 0
_PIPELINES_FINISHED = 0
_PIPELINES_FAILED = 0


# ── TRẦN SỐ PIPELINE CHẠY ĐỒNG THỜI (hardening tải, đợt 2) ────────────────────────────────────────
# VÌ SAO có: đo thật 200 CV nộp cùng lúc → 200 pipeline cùng đua vào checkpointer LangGraph, mà
# `AsyncPostgresSaver` chỉ có MỘT `asyncio.Lock` cho cả tiến trình (aio.py:46, giữ ở cả ba nhánh
# `_cursor()`), lại lấy connection TRƯỚC rồi mới xếp hàng vào khoá. Kết quả: 93/200 hồ sơ vỡ
# `PoolTimeout sau 30s` → PENDING_REVIEW[error]. Nâng pool checkpointer 5→25 chỉ kéo 107→93 ⇒ nút
# thắt KHÔNG phải kích thước pool mà là cái khoá. Việc phải làm là chặn ở ĐẦU VÀO: cùng một lượng
# việc, nhưng vào từng đợt có trật tự thay vì tất cả cùng lúc rồi hỏng hàng loạt.
#
# VÌ SAO Semaphore chứ không phải hàng đợi/worker: CLAUDE.md cấm dựng worker queue polling, và
# BackgroundTasks đã là "hàng đợi" sẵn có — chỉ thiếu cái van. Coroutine đang chờ van KHÔNG giữ
# connection, KHÔNG giữ luồng, chỉ tốn vài KB RAM; nó ngủ cho tới lượt.
#
# BẮT BUỘC đi kèm `openai_timeout_seconds`: một lượt gọi LLM treo vô hạn sẽ giữ một suất VĨNH VIỄN
# và biến van thành nút cổ chai chết. Không có timeout thì ĐỪNG bật van này.
_PIPELINE_SEMAPHORE: asyncio.Semaphore | None = None
# Trần ĐANG THỰC SỰ có hiệu lực. `None` = chưa chốt (van chưa dùng lần nào); `<= 0` = van TẮT hẳn.
_PIPELINE_LIMIT: int | None = None


def _pipeline_semaphore() -> asyncio.Semaphore | None:
    """Van giới hạn pipeline đồng thời — `None` nghĩa là TẮT trần (`max_concurrent_pipelines <= 0`).

    Tạo LƯỜI (lần gọi đầu) chứ không phải lúc import: `asyncio.Semaphore()` ở Python 3.10+ không gắn
    event loop lúc dựng, nhưng tạo lười vẫn an toàn hơn cho test (đổi settings rồi gọi lại vẫn đúng
    trong cùng một tiến trình chưa từng dùng van).

    CHỐT MỘT LẦN, cả GIÁ TRỊ lẫn nhánh BẬT/TẮT. Bản trước đọc lại `settings` MỖI lượt gọi nhưng chỉ
    dùng cho nhánh `limit <= 0`, còn `asyncio.Semaphore(limit)` thì chỉ dựng khi biến toàn cục còn
    `None` ⇒ đổi 15→30 lúc chạy KHÔNG có tác dụng nào (vẫn 15), mà đổi 15→0 lại TẮT van NGAY. Đọc
    code thấy "đọc lại mỗi lần gọi" nên rất dễ tin là đổi được — đúng loại bất đối xứng chỉ lộ ra khi
    có sự cố tải và người trực chỉnh số mà không hiểu vì sao chẳng khác gì.

    VÌ SAO chốt chứ không dựng lại van theo trần mới: các coroutine đang cầm suất nhả vào van CŨ, nên
    thay van giữa chừng cho phép đồng thời vọt lên `trần_cũ + trần_mới` — tệ hơn hẳn cái nó định
    sửa. `max_concurrent_pipelines` cũng KHÔNG nằm trong `config_registry` (không chỉnh được lúc
    chạy từ giao diện HR), nên "chốt lúc dùng lần đầu" đúng với cách biến này thực sự được dùng:
    đọc từ env một lần cho cả vòng đời tiến trình. Muốn đổi thật thì đổi env rồi khởi động lại.
    """
    global _PIPELINE_SEMAPHORE, _PIPELINE_LIMIT
    if _PIPELINE_LIMIT is None:
        _PIPELINE_LIMIT = settings.max_concurrent_pipelines
        if _PIPELINE_LIMIT > 0:
            _PIPELINE_SEMAPHORE = asyncio.Semaphore(_PIPELINE_LIMIT)
    return _PIPELINE_SEMAPHORE


def pipeline_gauges() -> dict[str, int | None]:
    """Ảnh chụp bộ đếm pipeline cho endpoint chẩn đoán. Thuần RAM — KHÔNG chạm DB, KHÔNG raise."""
    # Hỏi VAN, không đọc lại `settings`: sau khi van đã chốt, `settings` có đổi cũng không đổi được
    # trần thật, nên báo số của `settings` là để endpoint chẩn đoán nói dối đúng lúc người ta cần nó
    # nói thật nhất. Gọi `_pipeline_semaphore()` để chốt luôn nếu van chưa từng dùng (dựng một
    # `Semaphore` là thao tác thuần RAM, không chạm loop).
    _pipeline_semaphore()
    limit = _PIPELINE_LIMIT or 0
    return {
        "in_flight": _PIPELINES_IN_FLIGHT,
        # SUY RA chứ không đếm riêng: một coroutine bị cancel LÚC ĐANG CHỜ van sẽ không chạy `finally`
        # của thân hàm, nên bộ đếm "queued" riêng sẽ rò. Hiệu số thì luôn tự khớp lại.
        "queued": _PIPELINES_STARTED - _PIPELINES_FINISHED - _PIPELINES_IN_FLIGHT,
        "limit": limit if limit > 0 else None,
        "started_total": _PIPELINES_STARTED,
        "finished_total": _PIPELINES_FINISHED,
        "failed_total": _PIPELINES_FAILED,
    }


async def _escalate_technical_error(application_id: int, reason: str) -> None:
    """Đưa hồ sơ về PENDING_REVIEW[error] (PRD §13) bằng session MỚI. KHÔNG BAO GIỜ raise.

    Vì sao session MỚI: lỗi đưa ta tới đây thường LÀ lỗi của chính session cũ (pool timeout, kết nối
    Neon chết, transaction hỏng) — tái dùng nó thì thao tác cứu hộ chết theo. Session mới là lần thử
    trung thực duy nhất.

    CHỈ hạ hồ sơ CÒN ĐANG BAY (`IN_FLIGHT_STATUSES`). Vì `try` nay bao cả `async with`, việc ĐÓNG
    session cũng rơi vào tay handler này — và đóng session KHÔNG hề vô hại: `audit_service.record(
    commit=True)` kết thúc bằng `refresh()`, thao tác này MỞ LẠI một transaction, nên lúc thoát khối
    `async with` còn một ROLLBACK đi qua mạng và nó CÓ THỂ ném. Nếu lúc đó cứ hạ trạng thái thì:
    AWAITING_SCREENER (magic-link ĐÃ gửi) → ứng viên nộp câu trả lời nhận 409, MẤT bài dự tuyển; hoặc
    SCHEDULING (thư mời có thể đã gửi) → HR nhận thẻ [error] rồi từ chối người vừa được mời.

    Nếu ngay cả session mới cũng hỏng (pool cạn SẠCH) thì nuốt + `logger.exception`: hàm này chạy
    trong BackgroundTask, ném ra là biến mất không dấu vết. Khi đó hồ sơ còn kẹt ở SUBMITTED và lưới
    cuối là sweep đối soát (`stuck_applications`) — đó là lý do lưới ấy tồn tại.
    """
    try:
        async with AsyncSessionLocal() as session:
            application = await session.get(Application, application_id)
            if application is None:
                return
            if application.status not in IN_FLIGHT_STATUSES:
                # Hồ sơ đã rời vạch "chưa quyết" — thứ gì đó đã phát ra ngoài (email/magic-link) hoặc
                # đã có lưới riêng lo. Lỗi kỹ thuật sau thời điểm ấy KHÔNG được kéo ngược trạng thái.
                logger.warning(
                    "BG: app=%s đang ở %s (không còn đang bay) — KHÔNG hạ về PENDING_REVIEW[error]",
                    application_id, application.status,
                )
                return
            application.status = ApplicationStatus.PENDING_REVIEW.value
            application.escalation_reason = reason
            await audit_service.record(
                session, application_id=application_id, node="system",
                action="error", escalation_reason="technical_error", commit=True,
            )
    except Exception:  # noqa: BLE001 — lưới cuối: KHÔNG để lỗi thoát khỏi BackgroundTask không dấu vết
        logger.exception(
            "BG: KHÔNG ghi nổi PENDING_REVIEW[error] cho app=%s — hồ sơ còn kẹt, chờ sweep đối soát",
            application_id,
        )


# Pipeline CỐ ĐỊNH, KHÔNG Supervisor (PRD §5 trụ cột 1) ⇒ "node X vừa xong thì đang đứng ở đâu" là
# biết trước, không cần hỏi graph. Chỉ MỘT bước cần ghi: xong parser là sang ranker. Sau ranker,
# quyết định (gate/screener/scheduler) chốt ngay trong khối GHI nên thêm mốc nữa chỉ tốn một lượt
# mượn pool mà không cho HR biết thêm điều gì.
_STATUS_AFTER_NODE = {"parser": ApplicationStatus.RANKING.value}


async def _mark_progress(application_id: int, new_status: str) -> None:
    """Ghi mốc "hồ sơ đang ở node nào" NGAY LÚC pipeline còn chạy (PRD §13, FR-HR-DASH-1).

    Trước mốc này, `PARSING`/`RANKING` chỉ tồn tại trong graph state (bộ nhớ) và không bao giờ chạm
    DB: hồ sơ nằm ở `SUBMITTED` suốt ~34 giây rồi nhảy thẳng sang trạng thái cuối. Hệ quả là (a)
    dashboard không soi được pipeline đang chạy, và (b) lưới đối soát `stuck_applications` biết hồ sơ
    kẹt nhưng KHÔNG biết kẹt ở đâu — dù nó vốn đã quét cả ba trạng thái đang-bay.

    CHI PHÍ: đúng MỘT lượt mượn pool ngắn cho mỗi CV (mốc `PARSING` đi ghép vào session ĐỌC nên
    không tốn gì). Cố ý KHÔNG dùng lại session của pipeline: giữa hai node KHÔNG có session nào đang
    mở, và mở lại một session dài là quay về đúng cái đã vá ở hardening tải.

    KHÔNG BAO GIỜ raise: đây là dữ liệu hiển thị. Ghi hỏng thì dashboard hiện chậm một nhịp — chấp
    nhận được; để nó ném ra thì giết luôn pipeline của một ứng viên thật vì một con số trang trí.
    Guard `IN_FLIGHT_STATUSES` giữ đúng bất biến của file: mốc tiến độ đến muộn KHÔNG được kéo ngược
    hồ sơ đã rời vạch "chưa quyết" (vd sweep đối soát vừa đẩy về HR, hoặc hồ sơ đã bị xóa).
    """
    try:
        async with AsyncSessionLocal() as session:
            application = await session.get(Application, application_id)
            if application is None or application.status not in IN_FLIGHT_STATUSES:
                return
            application.status = new_status
            await session.commit()
    except Exception:  # noqa: BLE001 — mốc hiển thị KHÔNG được phép giết pipeline
        logger.warning(
            "BG: không ghi được mốc tiến độ %s cho app=%s — pipeline vẫn chạy tiếp",
            new_status, application_id, exc_info=True,
        )


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
    """Mỗi CV một pipeline độc lập (FR-PIPE-1). Ghi audit mọi bước (FR-PIPE-4).

    VÒNG ĐỜI SESSION (hardening tải): ĐỌC (session ngắn) → CHẠY pipeline KHÔNG giữ connection →
    GHI (session MỚI). Trước đây MỘT session mở suốt từ `session.get` tới `commit`, tức giữ một
    connection Neon + một TRANSACTION MỞ trọn cả lượt gọi parser LLM lẫn ranker LLM (hàng chục giây).
    Pool chỉ có `pool_size + max_overflow` connection ⇒ vài chục CV nộp cùng lúc là cạn pool và các
    pipeline sau chết vì `QueuePool ... timed out`. Nay connection chỉ bị giữ vài mili-giây ở hai đầu.

    TOÀN BỘ thân hàm nằm trong MỘT try — thao tác DB ĐẦU TIÊN cũng phải được bắt. Trước đây nó nằm
    NGOÀI try nên pool cạn ngay tại đó ném thẳng ra ngoài BackgroundTasks: Starlette KHÔNG bắt,
    response 201 thì đã trả cho ứng viên, hồ sơ nằm mãi ở SUBMITTED với audit_log TRỐNG — mất im lặng.
    """
    global _PIPELINES_IN_FLIGHT, _PIPELINES_STARTED, _PIPELINES_FINISHED, _PIPELINES_FAILED

    logger.info("BG: bắt đầu xử lý application_id=%s", application_id)
    # Đếm NGOÀI `try` nhưng NGAY TRƯỚC nó: `+= 1` trên int không thể ném, nên không có kẽ hở nào cho
    # một pipeline "đã bắt đầu" mà không bao giờ được trừ. Đặt trong `try` thì đọc dễ nhầm là có thể
    # nhảy vào `finally` khi CHƯA cộng.
    _PIPELINES_STARTED += 1
    # VAN: chờ tới lượt TRƯỚC khi chạm bất cứ tài nguyên nào (chưa mở session, chưa mượn luồng).
    # Chờ ở đây là chờ RẺ; chờ ở trong là chờ trong lúc đang giữ connection/luồng của người khác.
    slot = _pipeline_semaphore()
    if slot is not None:
        await slot.acquire()
    _PIPELINES_IN_FLIGHT += 1
    try:
        # ── 1) ĐỌC: lấy MỌI thứ pipeline cần rồi TRẢ connection ngay. Chụp ra biến cục bộ thay vì
        #    giữ ORM object qua ranh giới session (idiom sẵn có của file: "dữ liệu tách khỏi session").
        async with AsyncSessionLocal() as session:
            application = await session.get(Application, application_id)
            if application is None:
                logger.warning("BG: application_id=%s không tồn tại — bỏ qua", application_id)
                return
            applicant_email = application.applicant_email
            cv_file_ref = application.cv_file_ref
            # JD cho ranker (nếu application gắn job_id + JD tồn tại).
            jd = None
            job_title = "vị trí ứng tuyển"
            screener_questions: list = []
            if application.job_id is not None:
                job = await session.get(JobPosting, application.job_id)
                if job is not None:
                    jd = job_service.jd_dict(job)
                    job_title = job.title
                    screener_questions = list(job.screener_questions or [])
            # Mốc PARSING GHÉP vào chính session ĐỌC này — parser chạy ngay sau khi thoát khối `async
            # with` nên đây là mô tả đúng, không phải dự đoán, và KHÔNG tốn thêm lượt mượn pool nào.
            # Đặt CUỐI khối: mọi thứ pipeline cần đã nằm trong biến cục bộ, không còn đọc ORM object.
            #
            # GÓI TRY RIÊNG: đây là `commit()` DUY NHẤT nằm trong khối ĐỌC, mà khối ĐỌC lại nằm trong
            # `try` lớn — một lỗi ghi thoáng qua (kết nối Neon đứt ngay giữa `get` và `commit`) sẽ rơi
            # xuống `_escalate_technical_error` và giết pipeline TRƯỚC KHI parser kịp chạy: hồ sơ ra
            # PENDING_REVIEW[error] với `parsed_data` rỗng và `score` NULL — HR mở ReviewCard thấy một
            # thẻ trống, tất cả vì một con số trang trí trên dashboard. Cùng CHÍNH SÁCH LỖI với
            # `_mark_progress` (mốc RANKING): mốc hiển thị KHÔNG được phép giết pipeline.
            # KHÔNG rollback trong `except`: thoát `async with` đã `close()` an toàn từ MỌI trạng thái
            # transaction, còn `rollback()` là một lượt đi mạng NỮA — nó ném thì bay thẳng ra `try`
            # lớn, tức quay lại đúng con bug vừa vá.
            try:
                if application.status in IN_FLIGHT_STATUSES:
                    application.status = ApplicationStatus.PARSING.value
                    await session.commit()
            except Exception:  # noqa: BLE001 — mốc hiển thị KHÔNG được phép giết pipeline
                logger.warning(
                    "BG: không ghi được mốc tiến độ %s cho app=%s — pipeline vẫn chạy tiếp",
                    ApplicationStatus.PARSING.value, application_id, exc_info=True,
                )

        # ── 2) CHẠY pipeline — phần TỐN GIÂY (parser LLM + ranker LLM). KHÔNG giữ connection nào ──
        async def _advance(node_name: str) -> None:
            """Node vừa xong → ghi mốc node kế tiếp. Chạy GIỮA hai node, lúc không giữ connection."""
            next_status = _STATUS_AFTER_NODE.get(node_name)
            if next_status is not None:
                await _mark_progress(application_id, next_status)

        out = await run_with_trace(
            force_review=force_review,
            applicant_email=applicant_email,
            application_id=application_id,
            cv_path=cv_file_ref,  # parser đọc CV thật từ đây
            jd=jd,                # ranker đọc JD thật từ đây
            on_node=_advance,
        )
        final = out["final"]

        # ── 3) GHI: session MỚI, đọc LẠI hồ sơ (nguồn chân lý hiện tại) rồi ghi kết quả ──
        async with AsyncSessionLocal() as session:
            application = await session.get(Application, application_id)
            if application is None:  # bị xóa trong lúc chạy (vd reset_demo_data) — KHÔNG gửi email
                logger.warning(
                    "BG: application_id=%s biến mất trong lúc chạy pipeline — bỏ ghi kết quả",
                    application_id,
                )
                return
            if application.status not in IN_FLIGHT_STATUSES:
                # Hồ sơ đã rời vạch "chưa quyết" trong lúc pipeline còn chạy (vd pipeline treo rất
                # lâu → sweep đối soát đẩy về HR → HR quyết, thư đã gửi). Ghi đè ở đây = "từ chối
                # xong lại mời". Kết quả pipeline đến muộn thì BỎ, giữ quyết định đã tới ứng viên.
                logger.warning(
                    "BG: application_id=%s đang ở %s (không còn đang bay) — BỎ kết quả đến muộn",
                    application_id, application.status,
                )
                return
            await audit_service.record(
                session, application_id=application_id, node="system",
                action="received", detail={"source": "background_task"}, commit=False,
            )

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
                elif node == "screener":  # JD-2b: screener CHỈ vào trace lần chạy đầu khi BỎ QUA (có câu
                    action = "screener_skipped"  # hỏi → interrupt, không hoàn tất → không vào trace).
                    detail = {"status": step.get("status")}
                elif node == "scheduler":  # 08d gate auto-mời đạt NGAY lần đầu (JD không câu hỏi + auto_invite ON)
                    action = "auto_invite"
                    detail = {"status": step.get("status")}
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
            # TODO (§10, khi có hàng đợi bền QStash): checkpoint ghi (autocommit) TRƯỚC commit status dưới.
            # Nếu tiến trình chết giữa 2 mốc (BackgroundTasks KHÔNG bền) → checkpoint mồ côi/status lệch;
            # cần job đối soát (quét AWAITING_SCREENER vs checkpoint) — hiện chấp nhận (dev, chưa QStash).
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
                reject_title = job_title

            # JD-2b: ca BỎ-QUA-screener (JD không câu hỏi) + JD auto_invite BẬT → route_after_screener rẽ
            # scheduler NGAY ở lần chạy đầu (branch="auto_invite", KHÔNG suspend). Gom dữ liệu email mời vào
            # locals để gửi SAU commit (cô lập, song song auto_reject). Đường auto_invite khi CÓ câu hỏi vẫn
            # đi qua resume_screener như 08d — BẤT BIẾN (khối này chỉ chạm ca no-questions lần chạy đầu).
            auto_invite = out["branch"] == "auto_invite"
            if auto_invite:
                invite_email_to = application.applicant_email
                invite_title = job_title

            # Screener (08b): dừng ở screener → TẠO screening_session (token + hạn + ảnh chụp câu hỏi)
            # trong CÙNG commit với AWAITING_SCREENER (nguyên tử). Gom dữ liệu email vào locals để gửi
            # magic-link SAU commit (cô lập khỏi handler lỗi, như auto_reject).
            if suspended:
                from app.services import screening  # import trễ: tránh vòng import screening↔background

                screening_row = screening.create_session(session, application_id, screener_questions)
                # Denormalize mốc screener lên application cho HR hiển thị (CÙNG commit — nguyên tử).
                screening.mark_screener_sent(application, screening_row)
                screener_token = screening_row.token
                screener_email_to = application.applicant_email
                screener_title = job_title

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
                        applicant_email=reject_email,
                        job_title=reject_title,
                    )
                except Exception:  # noqa: BLE001 — REJECTED đã commit; lỗi email/audit KHÔNG làm sập
                    logger.exception(
                        "BG: notify_decision(reject) lỗi SAU khi REJECTED đã commit app=%s",
                        application_id,
                    )

            # JD-2b — GATE AUTO-MỜI ở LẦN CHẠY ĐẦU (ca bỏ-qua-screener sạch + auto_invite BẬT). SCHEDULING
            # đã commit → gửi thư MỜI THẬT qua scheduler (điểm phát email DUY NHẤT). Email-first rồi mới đặt
            # INTERVIEW_SCHEDULED (KHÔNG "trạng thái nói dối"); gửi lỗi → PENDING_REVIEW cho HR. CÔ LẬP khỏi
            # handler lỗi kỹ thuật bên dưới: một khi thư mời CÓ THỂ đã tới ứng viên, lỗi sau đó (audit/commit)
            # KHÔNG được reset về error (→ "mời xong lại từ chối"). Logic song song 08d resume_screener —
            # resume_screener GIỮ NGUYÊN (đường CÓ câu hỏi bất biến); đây là bản cho lần-đầu no-questions.
            if auto_invite:
                try:
                    # SCH-2: thư mời nay KÈM LINK tự đặt lịch → AWAITING_BOOKING (KHÔNG còn
                    # INTERVIEW_SCHEDULED ở đây — trạng thái đó chỉ đặt khi ứng viên đã CHỌN xong giờ).
                    # Thứ tự email-trước-trạng-thái-sau nằm trong booking_flow, dùng chung cả 3 đường mời.
                    await booking_flow.dispatch_booking_invite(
                        session, application, applicant_email=invite_email_to,
                        job_title=invite_title, audit_node="gate",
                    )
                except Exception:  # noqa: BLE001 — CÔ LẬP: lỗi sau khi có thể đã gửi thư KHÔNG reset error
                    logger.exception(
                        "BG: auto_invite dispatch (no-questions) lỗi app=%s — giữ trạng thái đã commit",
                        application_id,
                    )

            # Screener (08b): AWAITING_SCREENER + session ĐÃ commit → gửi email magic-link qua scheduler
            # (điểm phát email DUY NHẤT). CÔ LẬP: lỗi gửi KHÔNG reset AWAITING_SCREENER — hồ sơ vẫn chờ,
            # session vẫn còn → 08c (nhắc/timeout) xử lý. magic-link = FRONTEND_BASE_URL/screening/token.
            if suspended:
                try:
                    form_url = f"{settings.frontend_base_url.rstrip('/')}/screening/{screener_token}"
                    await scheduler.notify_screener(
                        session, application_id=application_id,
                        applicant_email=screener_email_to,
                        job_title=screener_title, form_url=form_url,
                        # `:g` — biến này là FLOAT (cố ý, để verify đặt ngưỡng dưới 1 giờ), nên nội
                        # suy thẳng cho ra "72.0 giờ" trong thư gửi ứng viên. `:g` bỏ đuôi .0 mà vẫn
                        # giữ được giá trị nhỏ (0.017 → "0.017"). Cùng ý đồ `booking_flow._deadline_text`.
                        deadline_text=f"{settings.screener_deadline_hours:g} giờ",
                    )
                except Exception:  # noqa: BLE001 — AWAITING_SCREENER đã commit; lỗi email KHÔNG làm sập
                    logger.exception(
                        "BG: notify_screener lỗi SAU khi AWAITING_SCREENER đã commit app=%s",
                        application_id,
                    )
    except Exception:  # noqa: BLE001 — lỗi kỹ thuật -> PENDING_REVIEW[error] (PRD §13)
        # Cộng TRƯỚC phần cứu hộ: `_escalate_technical_error` cam kết KHÔNG BAO GIỜ raise, nhưng bộ
        # đếm không được phụ thuộc vào lời hứa của hàm khác để đếm đúng.
        _PIPELINES_FAILED += 1
        logger.exception("BG: lỗi xử lý application_id=%s", application_id)
        await _escalate_technical_error(
            application_id, "Lỗi kỹ thuật khi xử lý pipeline (error)."
        )
    finally:
        # `finally` mới thêm — nó KHÔNG đổi luồng điều khiển nào: chỉ hai phép cộng/trừ int, không
        # `return`/`raise`/`await`, nên không thể nuốt exception hay chặn `except` ở trên. Chạy cả khi
        # coroutine bị CANCEL (tắt server giữa chừng), nhờ vậy `in_flight` không kẹt ở số dương giả.
        _PIPELINES_IN_FLIGHT -= 1
        _PIPELINES_FINISHED += 1
        # Nhả van CUỐI CÙNG: người kế tiếp chỉ được vào khi hồ sơ này đã buông hết tài nguyên.
        # Nằm trong `finally` nên nhả cả khi pipeline ném lẫn khi coroutine bị cancel lúc tắt server —
        # rò một suất là hàng đợi ngắn dần vĩnh viễn cho tới lần restart.
        if slot is not None:
            slot.release()


async def resume_screener(
    session, application_id: int, resume_payload: dict, *, pre_commit=None
) -> dict:
    """Resume pipeline TỪ screener. Dùng chung cho endpoint dev (08a) VÀ nộp form magic-link (08b).

    `Command(resume=payload)` cấp câu trả lời cho `interrupt()` → screener chạy tiếp → human_review →
    PENDING_REVIEW. KHÔNG chạy lại parser/ranker (checkpointer nạp state cũ — PRD §10). Persist
    status/flags + audit các node resume. Chữ ký khớp gọi từ endpoint (đã validate AWAITING_SCREENER).

    `pre_commit` (08b): callback chạy TRƯỚC commit thành công (trong CÙNG transaction) — dùng để đánh
    dấu `screening_session.used_at`/`answers` nguyên tử với việc resume (one-time). KHÔNG chạy khi lỗi.

    LƯU Ý (dual-write): checkpoint chạy autocommit (tiến ĐỘC LẬP với session SQLAlchemy). Nếu persist
    DB lỗi SAU khi checkpoint đã tới END → KHÔNG để hồ sơ kẹt CÂM ở AWAITING_SCREENER: nuốt lỗi kỹ
    thuật → PENDING_REVIEW[error] (HIỆN trong hàng chờ HR), như process_application (PRD §13).
    """
    logger.info("BG-resume: resume screener application_id=%s", application_id)
    try:
        out = await resume_with_trace(application_id=application_id, resume_payload=resume_payload)
        final = out["final"]

        application = await session.get(Application, application_id)
        if application is None:
            logger.warning("BG-resume: application_id=%s không tồn tại — bỏ qua", application_id)
            return {"application_id": application_id, "status": None, "branch": out["branch"]}

        for step in out["trace"]:  # trace resume: screener (+ human_review / scheduler). parser/ranker KHÔNG chạy lại.
            node = step["node"]
            if node == "screener":
                action = "screener_resumed"
            elif node == "scheduler":  # 08d gate auto-mời — quyết định mời (thư mời gửi post-commit dưới)
                action = "auto_invite"
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
        # F1 (final review): KHÔNG ghi đè trần. Webhook Resend gắn email_bounced/email_complained
        # thẳng lên hàng DB (checkpoint LangGraph không biết hai cờ này), nên "final.get(...) or []"
        # trần XOÁ SẠCH chúng ở MỌI lượt resume — một ứng viên vừa báo spam bị resume (vd. hết hạn
        # sàng lọc) là mất cảnh báo, HR có thể mời/gửi tiếp cho đúng người đó. Hợp NHẤT: giữ cờ email
        # cũ nếu graph không tự trả lại chúng, kế thừa lối lọc-chọn-lọc đã dùng ở booking_flow.py
        # (gỡ cờ CŨ theo tên, không ghi đè trần).
        old_email_flags = [
            f for f in (application.uncertainty_flags or [])
            # Thêm cờ email MỚI thì PHẢI thêm vào đây: thiếu một tên là cờ đó bị xoá sạch ở mọi
            # lượt resume (hết hạn sàng lọc, trả lời muộn, nộp form) mà không test nào đỏ.
            if f in (EMAIL_BOUNCED_FLAG, EMAIL_COMPLAINED_FLAG, EMAIL_SEND_FAILED_FLAG)
        ]
        new_flags = final.get("uncertainty_flags", []) or []
        application.uncertainty_flags = new_flags + [
            f for f in old_email_flags if f not in new_flags
        ]
        # escalation_reason: graph không đặt lý do MỚI (None) trong khi hồ sơ đang mang cờ email —
        # đừng để mất lý do "cần liên hệ thủ công" đã ghi lúc bounce hạ trạng thái. Graph CÓ đặt lý do
        # (vd. no_response) thì lý do đó vẫn thắng như cũ — chỉ tránh cái XOÁ VỀ None trần.
        new_reason = final.get("escalation_reason")
        if new_reason is None and old_email_flags:
            new_reason = application.escalation_reason
        application.escalation_reason = new_reason

        await audit_service.record(
            session, application_id=application_id, node="system",
            action=f"route:{out['branch']}", escalation_reason=final.get("escalation_reason"),
            detail={"final_status": final.get("status"), "resumed": True}, commit=False,
        )
        # 08d — GATE AUTO-MỜI: ca sạch + JD auto_invite ON đã route → scheduler (status=SCHEDULING). Gom
        # dữ liệu email vào locals để gửi thư mời SAU commit (cô lập, như auto_reject ở process_application).
        auto_invite = out["branch"] == "auto_invite"
        if auto_invite:
            invite_email_to = application.applicant_email
            invite_title = ((final.get("input") or {}).get("jd") or {}).get("title") or "vị trí ứng tuyển"

        if pre_commit is not None:  # 08b: đánh dấu used_at/answers CÙNG transaction (nguyên tử, one-time).
            pre_commit()
        await session.commit()
        logger.info(
            "BG-resume: xong application_id=%s -> branch=%s status=%s",
            application_id, out["branch"], final.get("status"),
        )

        # Gửi thư MỜI THẬT qua scheduler (điểm phát email DUY NHẤT). INTERVIEW_SCHEDULED CHỈ đặt khi thư
        # mời ĐÃ gửi — KHÔNG "trạng thái nói dối" (plan §3.2): gửi lỗi → PENDING_REVIEW cho HR xử lý.
        # CÔ LẬP khỏi outer handler (CLAUDE.md — như auto_reject 03c): một khi ĐÃ VÀO nhánh gửi mời, thư
        # mời CÓ THỂ đã tới ứng viên; nếu lỗi email/audit/commit sau đó rơi ra outer except → rollback →
        # PENDING_REVIEW[error] rồi HR TỪ CHỐI = "mời xong lại từ chối". Nuốt + log tại đây: case giữ
        # trạng thái đã commit (SCHEDULING = trung gian trung thực, KHÔNG giả "đã hẹn") để đối soát sau.
        if auto_invite:
            try:
                # SCH-2: thư mời KÈM LINK đặt lịch → AWAITING_BOOKING (xem booking_flow — thứ tự
                # email-trước-trạng-thái-sau dùng chung cho cả gate lẫn HR duyệt).
                await booking_flow.dispatch_booking_invite(
                    session, application, applicant_email=invite_email_to,
                    job_title=invite_title, audit_node="gate",
                )
            except Exception:  # noqa: BLE001 — CÔ LẬP: lỗi SAU khi có thể đã gửi thư KHÔNG reset case về error
                logger.exception(
                    "BG-resume: auto_invite dispatch lỗi app=%s — giữ trạng thái đã commit, KHÔNG reset error",
                    application_id,
                )
            return {"application_id": application_id, "status": application.status, "branch": out["branch"]}

        return {"application_id": application_id, "status": final.get("status"), "branch": out["branch"]}
    except Exception:  # noqa: BLE001 — resume lỗi kỹ thuật: KHÔNG để hồ sơ kẹt câm ở AWAITING_SCREENER
        logger.exception("BG-resume: lỗi resume application_id=%s", application_id)
        await session.rollback()
        application = await session.get(Application, application_id)
        if application is not None:
            application.status = ApplicationStatus.PENDING_REVIEW.value
            application.escalation_reason = "Lỗi kỹ thuật khi resume screener (error)."
            await audit_service.record(
                session, application_id=application_id, node="system",
                action="error", escalation_reason="resume_error", commit=True,
            )
        return {
            "application_id": application_id,
            "status": ApplicationStatus.PENDING_REVIEW.value,
            "branch": "error",
        }
