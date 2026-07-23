"""Load test — nhiều CV nộp CÙNG LÚC vào `/api/public/applications` (NFR-1, NFR-7).

Đo hai thứ TÁCH BẠCH nhau, vì chúng gãy ở hai chỗ khác nhau:
  1) TẦNG NHẬN (đồng bộ): backend trả 201 nhanh cỡ nào, bao nhiêu lượt dính 429/413/503.
  2) TẦNG XỬ LÝ (BackgroundTasks, bất đồng bộ): trong số hồ sơ ĐÃ NHẬN, bao nhiêu thật sự
     chạy xong pipeline — và bao nhiêu KẸT ở `SUBMITTED` (pool DB cạn → lỗi thoát khỏi
     BackgroundTask, không audit, không ai biết). 201 KHÔNG có nghĩa là hồ sơ được xử lý.

CẢNH BÁO CHI PHÍ / TÁC DỤNG PHỤ — chạy với `ENABLE_LLM=true` là:
  - tốn tiền OpenAI thật (mỗi CV = 1 lượt parser + 1 embedding + 1 lượt ranker),
  - GỬI EMAIL THẬT qua Resend nếu JD bật gate auto-từ-chối/auto-mời hoặc có câu hỏi screener,
  - ghi hàng loạt dòng thật vào Neon.
Vì vậy script BẮT BUỘC `--confirm`, và từ chối chạy vào host không phải localhost trừ khi
có `--allow-remote`. Muốn đo riêng trần hạ tầng (pool/RAM/rate-limit) mà KHÔNG tốn tiền:
đặt `ENABLE_LLM=false` và dùng JD KHÔNG có câu hỏi screener, gate TẮT.

Chạy:
    uv run --directory apps/backend python ../../scripts/loadtest_apply.py \
        --job-id 1 --total 60 --concurrency 60 --confirm
    # rồi đo tầng xử lý (cần tài khoản HR):
    ... --hr-email hr@example.com --hr-password '...' --watch 180
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections import Counter
from urllib.parse import urlsplit

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("Thiếu httpx: chạy qua `uv run --directory apps/backend python ...`")


def make_cv_pdf(index: int) -> bytes:
    """PDF CV tổng hợp CÓ TEXT trích xuất được (không phải file rác) — để parser chạy thật.

    Dùng PyMuPDF (đã là dependency của backend). Mỗi CV khác nhau đôi chút để LLM không
    hưởng lợi từ cache và để phân biệt được trong dashboard.
    """
    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (60, 80),
        "\n".join(
            [
                f"Nguyen Van Loadtest {index:03d}",
                f"Email: loadtest+{index:03d}@example.com | Phone: 09{index:08d}",
                "",
                "MUC TIEU: Backend Engineer, 3 nam kinh nghiem Python/FastAPI.",
                "",
                "KY NANG: Python, FastAPI, PostgreSQL, Docker, SQLAlchemy, Redis",
                "",
                "KINH NGHIEM:",
                "- Backend Engineer, Cong ty ABC (2022-2025):",
                "  xay REST API, toi uu truy van Postgres, trien khai Docker.",
                "- Intern Backend, Cong ty XYZ (2021-2022): viet script ETL.",
                "",
                "HOC VAN: Dai hoc Bach Khoa, Ky thuat Phan mem, 2021. GPA 3.2/4.",
            ]
        ),
        fontsize=10,
    )
    data: bytes = doc.tobytes()
    doc.close()
    return data


async def submit_one(
    client: httpx.AsyncClient, api: str, job_id: int, index: int, sem: asyncio.Semaphore
) -> dict:
    pdf = make_cv_pdf(index)
    async with sem:
        t0 = time.perf_counter()
        try:
            r = await client.post(
                f"{api}/api/public/applications",
                data={"job_id": str(job_id), "applicant_email": f"loadtest+{index:03d}@example.com"},
                files={"file": (f"cv_loadtest_{index:03d}.pdf", pdf, "application/pdf")},
            )
            dt = time.perf_counter() - t0
            body = {}
            try:
                body = r.json()
            except Exception:  # noqa: BLE001
                pass
            return {
                "index": index, "status": r.status_code, "latency": dt,
                "application_id": body.get("application_id"),
                "detail": body.get("detail"),
            }
        except Exception as exc:  # noqa: BLE001 — timeout/connection reset cũng là kết quả tải
            return {"index": index, "status": 0, "latency": time.perf_counter() - t0,
                    "application_id": None, "detail": f"{type(exc).__name__}: {exc}"}


def report_intake(results: list[dict], wall: float) -> list[int]:
    codes = Counter(r["status"] for r in results)
    lats = sorted(r["latency"] for r in results)
    accepted = [r["application_id"] for r in results if r["status"] == 201 and r["application_id"]]

    print()
    print("── TẦNG NHẬN (đồng bộ) " + "─" * 54)
    print(f"   Tổng {len(results)} lượt nộp trong {wall:.1f}s ⇒ {len(results) / wall:.1f} lượt/giây")
    for code, n in sorted(codes.items()):
        label = {
            201: "NHẬN — đã tạo hồ sơ", 429: "CHẶN rate-limit (20 lượt/giờ/IP)",
            413: "CHẶN body quá lớn", 503: "LỖI lưu storage (hồ sơ đã bị xoá)",
            404: "JD không tồn tại/đã đóng", 400: "CV không hợp lệ", 0: "KHÔNG phản hồi (timeout/reset)",
        }.get(code, "")
        print(f"   HTTP {code or '---'}: {n:4d}  {label}")
    if lats:
        print(f"   Độ trễ nhận: p50 {lats[len(lats) // 2]:.2f}s | "
              f"p95 {lats[int(len(lats) * 0.95) - 1]:.2f}s | max {lats[-1]:.2f}s "
              f"| trung bình {statistics.mean(lats):.2f}s")
    for r in results:
        if r["status"] not in (201, 429) and r["detail"]:
            print(f"   ↳ ví dụ lỗi #{r['index']}: {r['status']} {r['detail'][:90]}")
            break
    return accepted


async def watch_processing(
    api: str, ids: list[int], hr_email: str, hr_password: str, seconds: int
) -> None:
    """Đăng nhập HR rồi theo dõi trạng thái CHỈ các hồ sơ vừa nộp cho tới khi ổn định."""
    terminal = {"REJECTED", "INTERVIEW_SCHEDULED", "PENDING_REVIEW", "AWAITING_SCREENER"}
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(f"{api}/api/auth/login", json={"email": hr_email, "password": hr_password})
        if r.status_code != 200:
            print(f"\n   [!] Đăng nhập HR thất bại ({r.status_code}) — bỏ qua tầng xử lý.")
            return

        print()
        print("── TẦNG XỬ LÝ (BackgroundTasks) " + "─" * 45)
        wanted = set(ids)
        t0 = time.perf_counter()
        last: Counter[str] = Counter()
        while time.perf_counter() - t0 < seconds:
            rr = await c.get(f"{api}/api/applications")
            if rr.status_code != 200:
                print(f"   [!] GET /api/applications → {rr.status_code}")
                return
            rows = [a for a in rr.json() if a["id"] in wanted]
            last = Counter(a["status"] for a in rows)
            done = sum(n for s, n in last.items() if s in terminal)
            print(f"   t+{time.perf_counter() - t0:5.0f}s  "
                  + "  ".join(f"{s}={n}" for s, n in sorted(last.items()))
                  + f"   [xong {done}/{len(wanted)}]")
            if done == len(wanted):
                break
            await asyncio.sleep(10)

        stuck = last.get("SUBMITTED", 0) + last.get("PARSING", 0) + last.get("RANKING", 0)
        print()
        if stuck:
            print(f"   [!] {stuck} hồ sơ KẸT ở trạng thái trung gian sau {seconds}s.")
            print("       SUBMITTED kẹt = pool DB cạn, lỗi thoát khỏi BackgroundTask ")
            print("       (process_application dòng 41 nằm NGOÀI try) → không audit, không ai biết.")
        else:
            print("   Tất cả hồ sơ đã tới trạng thái cuối — không có hồ sơ kẹt câm.")


async def main() -> None:
    p = argparse.ArgumentParser(description="Load test nộp CV đồng thời (NFR-1).")
    p.add_argument("--api", default="http://127.0.0.1:8000", help="Gốc API backend")
    p.add_argument("--job-id", type=int, required=True, help="ID của JD đang OPEN")
    p.add_argument("--total", type=int, default=60, help="Tổng số CV nộp")
    p.add_argument("--concurrency", type=int, default=60, help="Số lượt nộp song song")
    p.add_argument("--timeout", type=float, default=60.0, help="Timeout mỗi request (giây)")
    p.add_argument("--hr-email", default="", help="Email HR (để theo dõi tầng xử lý)")
    p.add_argument("--hr-password", default="", help="Mật khẩu HR")
    p.add_argument("--watch", type=int, default=0, help="Theo dõi tầng xử lý trong N giây")
    p.add_argument("--allow-remote", action="store_true", help="Cho phép bắn vào host không phải localhost")
    p.add_argument("--confirm", action="store_true", help="BẮT BUỘC — xác nhận đã hiểu chi phí/email thật")
    args = p.parse_args()

    host = urlsplit(args.api).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        sys.exit(f"Từ chối bắn tải vào {host!r} — thêm --allow-remote nếu CHỦ ĐÍCH muốn vậy.")
    if not args.confirm:
        sys.exit(
            "Cần --confirm. Script này tạo hồ sơ THẬT, tốn tiền OpenAI THẬT và có thể GỬI EMAIL THẬT\n"
            "(gate auto-từ-chối/auto-mời, email screener). Đọc docstring đầu file trước khi chạy."
        )

    print("=" * 78)
    print(f"LOAD TEST — {args.total} CV vào JD #{args.job_id}, {args.concurrency} lượt song song")
    print(f"Đích: {args.api}")
    print("=" * 78)

    sem = asyncio.Semaphore(args.concurrency)
    limits = httpx.Limits(max_connections=args.concurrency + 10)
    async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as c:
        t0 = time.perf_counter()
        results = await asyncio.gather(
            *(submit_one(c, args.api, args.job_id, i, sem) for i in range(args.total))
        )
        wall = time.perf_counter() - t0

    accepted = report_intake(list(results), wall)

    if args.watch and accepted:
        if not (args.hr_email and args.hr_password):
            print("\n   [!] Cần --hr-email/--hr-password để đo tầng xử lý.")
        else:
            await watch_processing(args.api, accepted, args.hr_email, args.hr_password, args.watch)


if __name__ == "__main__":
    asyncio.run(main())
