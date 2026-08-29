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

from sqlalchemy import bindparam, delete, func, select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.booking import BookingSession, InterviewBooking
from app.models.email_delivery import EmailDelivery
from app.models.job_posting import JobPosting
from app.models.screening_session import ScreeningSession
from app.services.qdrant_service import delete_jd_vector, jd_point_id
from app.services.storage import StorageError, get_storage

# MỌI bảng có FK `application_id ... ondelete=CASCADE` — tức mọi thứ biến mất KÈM một application.
# Giữ danh sách này ĐẦY ĐỦ là điều kiện để bản kiểm kê trước khi xoá nói đúng sự thật; thiếu một
# bảng thì dry-run im lặng về đúng phần dữ liệu mà người đọc cần biết nhất.
_CASCADE_CHILDREN = {
    "audit_log": AuditLog,
    "screening_session": ScreeningSession,
    "booking_session": BookingSession,
    "interview_booking": InterviewBooking,
    "email_delivery": EmailDelivery,
}

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


async def _count_thread_rows(session, tables: list[str], thread_ids: list[str]) -> dict[str, int]:
    """{thread_id: tổng dòng} — MỘT câu `GROUP BY` mỗi bảng, KHÔNG phải một câu mỗi thread.

    Bản trước hỏi từng thread một. Với 756 hồ sơ × 3 bảng = 2.268 lượt khứ hồi tới Neon, đủ để một
    lần DRY-RUN (thao tác được cho là an toàn và nhanh) chạy quá 2 phút rồi bị giết giữa chừng —
    đúng thứ khiến người ta bỏ qua dry-run và gõ thẳng `--commit`.
    """
    totals: dict[str, int] = dict.fromkeys(thread_ids, 0)
    if not thread_ids:
        return totals
    for t in tables:  # t từ hằng _CHECKPOINT_TABLES (KHÔNG phải input người dùng) — an toàn nội suy.
        stmt = text(
            f"select thread_id, count(*) from {t} where thread_id in :tids group by thread_id"
        ).bindparams(bindparam("tids", expanding=True))
        for tid, n in await session.execute(stmt, {"tids": thread_ids}):
            totals[tid] = totals.get(tid, 0) + int(n)
    return totals


async def _count_children(session, model, app_ids: list[int]) -> dict[int, int]:
    """{application_id: số bản ghi con} — MỘT câu `GROUP BY` cho CẢ danh sách (xem lý do ở trên)."""
    if not app_ids:
        return {}
    rows = await session.execute(
        select(model.application_id, func.count())
        .where(model.application_id.in_(app_ids))
        .group_by(model.application_id)
    )
    return {app_id: int(n) for app_id, n in rows}


def _db_host() -> str:
    """Host của DATABASE_URL, KHÔNG kèm user/mật khẩu — đủ để phân biệt dev với prod, đủ an toàn để in."""
    url = settings.database_url or ""
    tail = url.rsplit("@", 1)[-1]  # bỏ scheme + credential
    return tail.split("/", 1)[0] or "(không rõ)"


def _print_environment() -> None:
    """In ĐÍCH THẬT SỰ của lệnh này trước khi liệt kê bất cứ thứ gì — kể cả ở DRY-RUN.

    Đây không phải trang trí. `LocalStorage.delete` là `unlink(missing_ok=True)`: nó KHÔNG BAO GIỜ
    raise. Nên chạy script với `STORAGE_BACKEND=local` (mặc định trong `.env` của máy dev) trong khi
    file CV thật nằm trên R2 sẽ in ra đủ "+206/206 file CV" mà chưa xoá một byte nào trên bucket —
    một báo cáo thành công hoàn hảo cho một việc chưa hề xảy ra. Cách duy nhất để bắt là NHÌN THẤY
    backend và host DB trước khi gõ `--commit`.
    """
    backend = (settings.storage_backend or "").lower()
    target = settings.r2_bucket if backend == "r2" else settings.cv_upload_dir
    print("== Môi trường của lệnh này — ĐỌC TRƯỚC KHI GÕ --commit ==")
    print(f"  app_env = {settings.app_env}")
    print(f"  storage = {backend or '(chưa đặt)'} → {target}")
    print(f"  db host = {_db_host()}")
    print()


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
    _print_environment()
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

        # ĐỦ 5 bảng con cascade từ `application` (ondelete=CASCADE). Bản trước chỉ đếm 2 —
        # interview_booking / booking_session / email_delivery được thêm SAU khi script này ra đời,
        # nên bản kiểm kê trước khi xoá vẫn im lặng về chúng: người đọc dry-run tưởng không có gì.
        found_ids = [a.id for a in apps]
        per_table = {
            name: await _count_children(session, model, found_ids)
            for name, model in _CASCADE_CHILDREN.items()
        }
        totals = {name: sum(d.values()) for name, d in per_table.items()}
        print(f"== Application sẽ xóa ({len(apps)}) — {len(_CASCADE_CHILDREN)} bảng con cascade theo ==")
        for a in apps:
            children = " ".join(
                f"{name}={per_table[name][a.id]}" for name in _CASCADE_CHILDREN if per_table[name].get(a.id)
            )
            print(
                f"  id={a.id} job_id={a.job_id} status={a.status} email={a.applicant_email} "
                f"{children or '(không có bản ghi con)'} cv={a.cv_file_ref or '—'}"
            )
        if apps:
            print("  ── tổng bản ghi con: " + ", ".join(f"{n}={c}" for n, c in totals.items()))

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
            thread_rows = await _count_thread_rows(session, cp_tables, target_threads)
            for tid in target_threads:
                print(f"  thread={tid}: {thread_rows.get(tid, 0)} dòng")
            print(f"  ── tổng dòng checkpoint: {sum(thread_rows.values())}")

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
        #    delete_jd_vector idempotent: point không tồn tại (vd JD chưa embed) -> no-op OK (seam JD-4).
        for j in jobs:
            await delete_jd_vector(j.id)
            print(f"  Qdrant: đã xóa point {jd_point_id(j.id)} (job_id={j.id})")

        # 1b) GHI NHỚ key CV trước khi xóa row (mất row là mất key). File xóa SAU KHI DB commit —
        #     xóa trước mà transaction rollback thì file mất trong khi hồ sơ vẫn còn (HR bấm tải →
        #     hỏng). Ngược lại (commit xong mới xóa) xấu nhất chỉ còn file mồ côi + đã in cảnh báo.
        cv_keys = [(a.id, a.cv_file_ref) for a in apps if a.cv_file_ref]

        # 2) DB (cùng transaction): application (audit_log cascade) + checkpoint threads + job_posting.
        if app_ids:
            await session.execute(delete(Application).where(Application.id.in_(app_ids)))
        if target_threads and cp_tables:
            n_cp = await _delete_thread_rows(session, cp_tables, target_threads)
            print(f"  Checkpoint: đã xóa {n_cp} dòng ({len(cp_tables)} bảng) cho thread {target_threads}")
        if job_ids:
            await session.execute(delete(JobPosting).where(JobPosting.id.in_(job_ids)))
        await session.commit()

        # 3) File CV qua SEAM STORAGE (slice 06) — SAU commit. Không để file mồ côi: CV là dữ liệu
        #    cá nhân, không giữ lại sau khi xóa hồ sơ (NFR-4). Lỗi xóa một file KHÔNG chặn cả lệnh
        #    (file có thể đã bị xóa tay) — chỉ cảnh báo để dọn thủ công.
        n_cv_deleted = 0
        try:
            # `get_storage()` PHẢI nằm trong try: đặt STORAGE_BACKEND=r2 mà thiếu một biến R2_* thì
            # nó ném NGAY — và ở vị trí cũ (ngoài try) traceback đó bay ra SAU `session.commit()`,
            # tức DB đã xoá xong còn file thì chưa, mà người chạy chỉ thấy một stack trace.
            storage = get_storage()
        except Exception as exc:  # noqa: BLE001 — cấu hình storage sai không được che mất việc DB ĐÃ xoá
            print(f"\n  [CHÚ Ý] DB đã xoá xong nhưng KHÔNG mở được storage ({exc}).")
            print(f"  {len(cv_keys)} file CV còn nguyên trên kho — chạy lại phần xoá file sau khi sửa env.")
            cv_keys = []
            storage = None

        for app_id, key in cv_keys:
            try:
                await storage.delete(key)  # type: ignore[union-attr]
                n_cv_deleted += 1
                # "đã gọi xóa" chứ KHÔNG phải "đã xóa": `delete` idempotent theo hợp đồng trên CẢ HAI
                # backend (LocalStorage dùng `unlink(missing_ok=True)`), nên thành công ở đây chỉ có
                # nghĩa "không có lỗi", không hề chứng minh file từng tồn tại hay vừa biến mất.
                print(f"  Storage: đã gọi xóa (idempotent) key={key} (app {app_id})")
            except StorageError as exc:
                # Gồm cv_file_ref ĐỊNH DẠNG CŨ (path tuyệt đối, trước slice 06) — key không hợp lệ.
                print(f"  [chú ý] KHÔNG xóa được CV của app {app_id} ({key}): {exc} — dọn thủ công.")

        # Số LƯỢT XÓA KHÔNG LỖI — KHÔNG phải "số file thực sự biến mất" (xem chú thích idempotent
        # ngay trên). Muốn biết bucket đã sạch chưa thì phải liệt kê prefix `cv/` trên bucket.
        n_failed = len(cv_keys) - n_cv_deleted
        cv_note = f"+{n_cv_deleted}/{len(cv_keys)} lượt xóa file CV không lỗi" + (
            f", {n_failed} lỗi" if n_failed else ""
        )
        print(
            f"\nĐã xóa {len(apps)} application (+audit_log +checkpoint {cv_note}), "
            f"{len(jobs)} job_posting (+vector Qdrant), {len(thread_ids)} thread checkpoint lẻ."
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
