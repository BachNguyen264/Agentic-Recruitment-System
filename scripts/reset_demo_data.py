"""reset_demo_data — xóa CÓ KIỂM SOÁT application/job_posting demo/test + dọn vector Qdrant.

Dùng khi cần làm sạch danh sách ứng viên / JD rác sau các lần verify. CHỈ xóa DỮ LIỆU —
KHÔNG đổi schema/bảng. Xóa `job_posting` thì xóa KÈM vector JD trong Qdrant (point theo
`jd_point_id`) để không còn vector mồ côi. `audit_log` con của application cascade theo FK
(ondelete=CASCADE); application trỏ tới job bị xóa sẽ SET NULL (FK) — nên xóa application trước.

Chạy (từ gốc repo; cần venv + .env của backend):
    uv run --directory apps/backend python ../../scripts/reset_demo_data.py \
        --applications 5 6 7 --jobs 1 3 --commit

BỎ --commit  → DRY-RUN: chỉ in ra SẼ xóa gì, KHÔNG đụng DB/Qdrant.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from qdrant_client import models
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.qdrant_client import qdrant_client
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.job_posting import JobPosting
from app.services.qdrant_service import jd_point_id


async def reset(app_ids: list[int], job_ids: list[int], *, commit: bool) -> None:
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

        missing_apps = sorted(set(app_ids) - {a.id for a in apps})
        missing_jobs = sorted(set(job_ids) - {j.id for j in jobs})
        if missing_apps:
            print(f"\n[chú ý] application id không tồn tại (bỏ qua): {missing_apps}")
        if missing_jobs:
            print(f"[chú ý] job_posting id không tồn tại (bỏ qua): {missing_jobs}")

        if not commit:
            print("\n[DRY-RUN] Chưa xóa gì. Thêm --commit để thực thi.")
            return

        # 1) Qdrant TRƯỚC: nếu lỗi -> dừng khi CHƯA commit DB (tránh JD mất, vector mồ côi).
        #    delete idempotent: point không tồn tại (vd JD chưa embed) -> no-op OK.
        for j in jobs:
            await qdrant_client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=models.PointIdsList(points=[jd_point_id(j.id)]),
            )
            print(f"  Qdrant: đã xóa point {jd_point_id(j.id)} (job_id={j.id})")

        # 2) DB: application trước (audit_log cascade) rồi job_posting.
        if app_ids:
            await session.execute(delete(Application).where(Application.id.in_(app_ids)))
        if job_ids:
            await session.execute(delete(JobPosting).where(JobPosting.id.in_(job_ids)))
        await session.commit()
        print(f"\nĐã xóa {len(apps)} application (+audit_log) và {len(jobs)} job_posting (+vector Qdrant).")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # tránh lỗi encode tiếng Việt trên Windows console
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Xóa data demo/test (Neon) + dọn vector Qdrant.")
    parser.add_argument("--applications", type=int, nargs="*", default=[], help="id application cần xóa")
    parser.add_argument("--jobs", type=int, nargs="*", default=[], help="id job_posting cần xóa (kèm vector)")
    parser.add_argument("--commit", action="store_true", help="thực thi xóa (mặc định: dry-run)")
    args = parser.parse_args()

    if not args.applications and not args.jobs:
        parser.error("cần ít nhất --applications hoặc --jobs")

    asyncio.run(reset(args.applications, args.jobs, commit=args.commit))


if __name__ == "__main__":
    main()
