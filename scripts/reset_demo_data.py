"""reset_demo_data — xóa CÓ KIỂM SOÁT application/job_posting demo/test + dọn vector Qdrant + checkpoint.

Dùng khi cần làm sạch danh sách ứng viên / JD rác sau các lần verify. CHỈ xóa DỮ LIỆU —
KHÔNG đổi schema/bảng.
- Xóa `job_posting` → xóa KÈM vector JD trong Qdrant (point theo `jd_point_id`) — không vector mồ côi.
- Xóa `application` → xóa KÈM các dòng CHECKPOINT LangGraph của pipeline đó (thread_id = `app-<id>`,
  PRD §10 Screener suspend/resume) — không checkpoint mồ côi (đối xứng cách dọn vector Qdrant).
- `audit_log` con của application cascade theo FK (ondelete=CASCADE); application trỏ tới job bị xóa
  sẽ SET NULL (FK) — nên xóa application trước.
- `--threads` (tùy chọn): xóa thẳng các thread checkpoint LẺ (vd thread probe/thử nghiệm KHÔNG gắn
  application nào) để dọn mồ côi còn sót.

Chạy (từ gốc repo; cần venv + .env của backend):
    uv run --directory apps/backend python ../../scripts/reset_demo_data.py \
        --applications 5 6 7 --jobs 1 3 --threads prodpath-08a --commit

BỎ --commit  → DRY-RUN: chỉ in ra SẼ xóa gì, KHÔNG đụng DB/Qdrant.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from qdrant_client import models
from sqlalchemy import bindparam, delete, func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.qdrant_client import qdrant_client
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.job_posting import JobPosting
from app.services.qdrant_service import jd_point_id

# Bảng checkpoint của LangGraph AsyncPostgresSaver (khóa theo thread_id). checkpoint_migrations =
# version schema, KHÔNG đụng. Thứ tự con→cha (không có FK giữa chúng nhưng giữ cho rõ ràng).
_CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


def _app_thread_id(app_id: int) -> str:
    """thread_id pipeline theo application — KHỚP runner._app_thread_config (f"app-{id}")."""
    return f"app-{app_id}"


async def _existing_checkpoint_tables(session) -> list[str]:
    """Bảng checkpoint THỰC SỰ tồn tại (checkpointer có thể chưa từng setup → chưa có bảng)."""
    rows = set(
        (
            await session.execute(
                text(
                    "select table_name from information_schema.tables "
                    "where table_schema='public' and table_name like 'checkpoint%'"
                )
            )
        ).scalars().all()
    )
    return [t for t in _CHECKPOINT_TABLES if t in rows]


async def _count_thread_rows(session, tables: list[str], thread_id: str) -> int:
    total = 0
    for t in tables:  # t từ hằng _CHECKPOINT_TABLES (KHÔNG phải input người dùng) — an toàn nội suy.
        total += (
            await session.execute(
                text(f"select count(*) from {t} where thread_id = :tid"), {"tid": thread_id}
            )
        ).scalar_one()
    return total


async def _delete_thread_rows(session, tables: list[str], thread_ids: list[str]) -> int:
    deleted = 0
    for t in tables:  # t từ hằng cố định; thread_ids bind tham số (expanding IN) — an toàn.
        stmt = text(f"delete from {t} where thread_id in :tids").bindparams(
            bindparam("tids", expanding=True)
        )
        result = await session.execute(stmt, {"tids": thread_ids})
        deleted += result.rowcount or 0
    return deleted


async def reset(
    app_ids: list[int], job_ids: list[int], thread_ids: list[str], *, commit: bool
) -> None:
    async with AsyncSessionLocal() as session:
        apps = (
            (await session.execute(select(Application).where(Application.id.in_(app_ids)))).scalars().all()
            if app_ids
            else []
        )
        jobs = (
            (await session.execute(select(JobPosting).where(JobPosting.id.in_(job_ids)))).scalars().all()
            if job_ids
            else []
        )

        print(f"== Application sẽ xóa ({len(apps)}) — audit_log con cascade theo ==")
        for a in apps:
            n_audit = (
                await session.execute(
                    select(func.count()).select_from(AuditLog).where(AuditLog.application_id == a.id)
                )
            ).scalar_one()
            print(f"  id={a.id} job_id={a.job_id} status={a.status} email={a.applicant_email} audit_children={n_audit}")

        print(f"\n== Job_posting sẽ xóa ({len(jobs)}) — kèm xóa vector Qdrant ==")
        for j in jobs:
            print(f"  id={j.id} title={j.title!r} point_id={jd_point_id(j.id)} embedding_ref={j.embedding_ref}")

        # Checkpoint: thread của các application bị xóa (app-<id>) + thread lẻ chỉ định (--threads).
        target_threads = [_app_thread_id(i) for i in app_ids] + list(thread_ids)
        cp_tables = await _existing_checkpoint_tables(session)
        print(f"\n== Checkpoint threads sẽ xóa ({len(target_threads)}) — bảng {list(cp_tables)} ==")
        if not cp_tables:
            print("  (chưa có bảng checkpoint — bỏ qua)")
        else:
            for tid in target_threads:
                print(f"  thread={tid}: {await _count_thread_rows(session, cp_tables, tid)} dòng")

        missing_apps = sorted(set(app_ids) - {a.id for a in apps})
        missing_jobs = sorted(set(job_ids) - {j.id for j in jobs})
        if missing_apps:
            print(f"\n[chú ý] application id không tồn tại (bỏ qua): {missing_apps}")
        if missing_jobs:
            print(f"[chú ý] job_posting id không tồn tại (bỏ qua): {missing_jobs}")

        if not commit:
            print("\n[DRY-RUN] Chưa xóa gì. Thêm --commit để thực thi.")
            return

        # 1) Qdrant TRƯỚC (external): nếu lỗi -> dừng khi CHƯA commit DB (tránh JD mất, vector mồ côi).
        #    delete idempotent: point không tồn tại (vd JD chưa embed) -> no-op OK.
        for j in jobs:
            await qdrant_client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=models.PointIdsList(points=[jd_point_id(j.id)]),
            )
            print(f"  Qdrant: đã xóa point {jd_point_id(j.id)} (job_id={j.id})")

        # 2) DB (cùng transaction): application (audit_log cascade) + checkpoint threads + job_posting.
        if app_ids:
            await session.execute(delete(Application).where(Application.id.in_(app_ids)))
        if target_threads and cp_tables:
            n_cp = await _delete_thread_rows(session, cp_tables, target_threads)
            print(f"  Checkpoint: đã xóa {n_cp} dòng ({len(cp_tables)} bảng) cho thread {target_threads}")
        if job_ids:
            await session.execute(delete(JobPosting).where(JobPosting.id.in_(job_ids)))
        await session.commit()
        print(
            f"\nĐã xóa {len(apps)} application (+audit_log +checkpoint), {len(jobs)} job_posting "
            f"(+vector Qdrant), {len(thread_ids)} thread checkpoint lẻ."
        )


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # tránh lỗi encode tiếng Việt trên Windows console
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Xóa data demo/test (Neon) + dọn vector Qdrant + checkpoint.")
    parser.add_argument("--applications", type=int, nargs="*", default=[], help="id application cần xóa (kèm checkpoint app-<id>)")
    parser.add_argument("--jobs", type=int, nargs="*", default=[], help="id job_posting cần xóa (kèm vector)")
    parser.add_argument("--threads", type=str, nargs="*", default=[], help="thread_id checkpoint LẺ cần xóa (mồ côi, không gắn application)")
    parser.add_argument("--commit", action="store_true", help="thực thi xóa (mặc định: dry-run)")
    args = parser.parse_args()

    if not args.applications and not args.jobs and not args.threads:
        parser.error("cần ít nhất --applications, --jobs hoặc --threads")

    asyncio.run(reset(args.applications, args.jobs, args.threads, commit=args.commit))


if __name__ == "__main__":
    main()
