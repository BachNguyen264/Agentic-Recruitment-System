"""Load test — nhiều ứng viên ĐẶT LỊCH phỏng vấn CÙNG LÚC (SCH-1/2/3 · PRD §10b, FR-BOOK-1/2/5).

Câu hỏi cần trả lời: *"chuyện gì xảy ra khi nhiều người cùng đặt lịch một lúc?"* Nó gãy ở BỐN chỗ
khác nhau, nên script đo bốn thứ TÁCH BẠCH — gộp lại thành một con số là mất hết thông tin:

  1) TRANH GIÀNH LƯỢT XEM (pha 1) — mỗi người mở link là GIỮ `BOOKING_SLOTS_OFFERED` khung giờ trong
     `BOOKING_HOLD_MINUTES`. Kho khung giờ là HỮU HẠN và TOÀN CỤC, nên trần "bao nhiêu người xem
     đồng thời" = sức chứa cửa sổ ÷ số slot mời. Vượt trần thì người tới sau thấy **danh sách rỗng**
     — và tệ hơn: hệ thống đóng dấu `no_slots_at` rồi báo HR "hết khung giờ, cần mở thêm lịch"
     TRONG KHI chưa ai đặt gì cả, lịch chỉ đang bị *giữ tạm* bởi những người còn đang phân vân.
  2) TRANH GIÀNH LƯỢT CHỐT (pha 2) — hai người cùng bấm xác nhận MỘT khung giờ. Chốt chặn cuối là
     partial unique index `UNIQUE(start_at) WHERE status='BOOKED'`. Đúng MỘT người thắng, phần còn
     lại phải nhận **409** (chọn lại được); một cái **500** ở đây là hồi quy thật — SCH-2 từng có
     lỗi deadlock-ra-500 và ứng viên nhìn thấy màn lỗi thô.
  3) HUỶ / ĐẶT LẠI (pha 3) — huỷ phải nhả khung giờ TỨC THÌ, và **KHÔNG được gia hạn TTL** của liên
     kết (PRD §10b.6): gia hạn mỗi lần huỷ là tự tạo vòng đặt-huỷ-đặt không điểm dừng.
  4) HOLD HẾT HẠN (pha 4) — hold quá hạn phải THÔI chiếm chỗ mà không cần cron. Nếu sai, mỗi người
     bấm link rồi bỏ đi sẽ khoá vĩnh viễn 5 khung giờ và lịch công ty cạn dần trong im lặng.

KHÔNG cần LLM và KHÔNG tự gửi email: đặt lịch nằm NGOÀI graph (không parser/ranker/embedding), còn
thư thì do backend phát. NHƯNG pha 2/3 đi qua `confirm_and_notify`/`cancel_by_candidate` — hai
đường ĐÓ gọi `scheduler.notify_*` thật. Vì vậy **chạy backend với `RESEND_API_KEY` rỗng**: thiếu
khoá thì `email_service` ném `EmailError`, `scheduler._dispatch` nuốt và trả `email_sent=false` —
lịch vẫn chốt, không lá thư nào bay đi. Script tự kiểm điều kiện này và đòi `--allow-email` nếu
`.env` đang có khoá.

CẢNH BÁO TÁC DỤNG PHỤ:
  - GHI DỮ LIỆU THẬT vào DB mà `.env` đang trỏ tới (thường là Neon dev — **không phải localhost**):
    1 JD + N hồ sơ giả + phiên đặt lịch + hàng `interview_booking`. Mọi hàng đều mang nhãn
    `loadtest-booking`, và `--cleanup` xoá ĐÚNG những hàng đó (cascade theo FK) chứ không xoá gì khác.
  - CHIẾM KHUNG GIỜ THẬT: sức chứa là TOÀN CỤC, nên trong lúc chạy, ứng viên thật mở link đặt lịch
    sẽ thấy ít lựa chọn hơn (hoặc rỗng). Chạy trên DB dev, đừng chạy trên prod giờ hành chính.
  - Pha 2/3 tiêu quota rate-limit của xô `booking` (mặc định 20 POST/giờ/IP). Xem phần tiền kiểm.

Chạy (từ gốc repo):
    uv run --directory apps/backend python ../../scripts/loadtest_booking.py --confirm
    # tìm BỨC TƯỜNG (người thứ mấy nhận danh sách rỗng) — phải chạy NỐI ĐUÔI, xem --stagger:
    uv run --directory apps/backend python ../../scripts/loadtest_booking.py \
        --confirm --phases 0,1 --viewers 20 --stagger 0.4
    uv run --directory apps/backend python ../../scripts/loadtest_booking.py --cleanup

**Pha 1 có HAI chế độ và chúng trả lời hai câu hỏi khác nhau — đừng chỉ chạy một cái:**
`--stagger 0` (mặc định) bắn K request CÙNG LÚC ⇒ đo TOCTOU: mọi người đọc chung một tấm lịch
trống nên `_pick_mixed` (tất định) phát TRÙNG khung giờ, và bức tường KHÔNG hiện ra vì hệ thống
bội-đăng-ký chứ không từ chối ai. `--stagger 0.4` cho mỗi người thấy hold của người trước ⇒ mới
đo được trần thật.

Muốn pha 4 chạy được thì khởi động backend với hold NGẮN (mặc định 5 phút là quá lâu để đứng chờ):
    BOOKING_HOLD_MINUTES=0.25 RATE_LIMIT_ENABLED=false RESEND_API_KEY= make dev-backend

Thoát != 0 khi một BẤT BIẾN sai ⇒ dùng được như cổng hồi quy.
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from itertools import combinations
from urllib.parse import urlsplit

try:
    import httpx
    from sqlalchemy import and_, delete, func, or_, select
    from sqlalchemy.ext.asyncio import AsyncSession
except ImportError:  # pragma: no cover
    sys.exit("Thiếu dependency: chạy qua `uv run --directory apps/backend python ...`")

# Console Windows mặc định cp1252 → MỌI dòng tiếng Việt (và khung `─`, dấu `✔`) làm cả script nổ
# `UnicodeEncodeError` ngay ở `--help`, trước khi đo được gì. Ép UTF-8 tại chỗ, `errors="replace"`
# để terminal cổ vẫn in ra được thứ gì đó thay vì chết. `reconfigure` có từ Python 3.7.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from app.core.config import settings
from app.core.database import AsyncSessionLocal, engine
from app.models.application import Application, ApplicationStatus
from app.models.booking import BookingSession, BookingStatus, InterviewBooking
from app.models.job_posting import JobPosting
from app.services import booking_service
from app.services.booking_config import BookingConfig, load_booking_config

# `_candidate_starts` là hàm nội bộ, và dùng nó ở đây là CÓ CHỦ Ý: nó là NGUỒN DUY NHẤT của lưới
# mốc giờ hợp lệ. Tự dựng lại lưới trong script đo nghĩa là script và sản phẩm có thể lệch nhau —
# lúc đó phép đo "sức chứa" chỉ đo đúng cái script tự nghĩ ra.
from app.services.booking_service import _candidate_starts

# ── Nhãn dữ liệu: mọi hàng script tạo ra đều mang nhãn này để `--cleanup` xoá ĐÚNG chúng ─────
_TAG = "loadtest-booking"
_EMAIL_DOMAIN = "example.invalid"  # TLD dành riêng (RFC 2606): không thể là hộp thư thật của ai
_JOB_TITLE = f"[{_TAG}] Load test đặt lịch"

_ALL_PHASES = (0, 1, 2, 3, 4)

# Số hồ sơ mỗi pha cần RIÊNG, ngoài pha 1 và pha 2 (kích thước do CLI quyết):
_REBOOK_APPS = 1  # pha 3: một người đặt rồi tự huỷ
_HOLD_APPS = 3  # pha 4: A bỏ dở · B xem cùng lúc · C xem SAU khi hold của A hết hạn

# Ý nghĩa từng mã HTTP trên ĐƯỜNG ĐẶT LỊCH — in ra cùng bảng kết quả để đọc số không phải tra code.
_LEGEND = {
    200: "OK",
    404: "token không tồn tại / khung giờ không thuộc hồ sơ này",
    409: "SlotTaken (vừa có người đặt mất) hoặc hold đã hết hạn — ĐÚNG hành vi mong đợi khi thua race",
    410: "liên kết đã huỷ / hết hạn (TokenExpired)",
    413: "body quá lớn",
    422: "payload sai schema",
    429: (f"rate-limit xô `booking` ({settings.rate_limit_public_max} POST/"
          f"{settings.rate_limit_public_window_seconds:g}s/IP theo .env) — KHÔNG phải hành vi nghiệp vụ"),
    500: "LỖI MÁY CHỦ — không được phép xuất hiện ở pha nào",
    0: "KHÔNG phản hồi (timeout/connection reset)",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ict(cfg: BookingConfig, value: datetime) -> str:
    """Mốc UTC → chuỗi giờ Việt Nam. Mọi thứ in ra cho người đọc đều đi qua đây (giờ làm việc là
    khái niệm ĐỊA PHƯƠNG — in UTC là bắt người đọc tự cộng 7 tiếng rồi tự nghi ngờ mình)."""
    return value.astimezone(cfg.tz).strftime("%d/%m %H:%M")


def _p(values: list[float], q: float) -> float:
    """Phân vị đơn giản trên danh sách ĐÃ sắp — cùng idiom với `loadtest_apply.py`."""
    if not values:
        return 0.0
    return values[max(0, min(len(values) - 1, int(len(values) * q) - 1))]


def _banner(title: str) -> None:
    print()
    print(f"── {title} " + "─" * max(4, 74 - len(title)))


def _codes(rows: list[GetResult] | list[PostResult]) -> None:
    """Bảng mã HTTP kèm chú giải. Dùng chung cho mọi pha để một mã luôn đọc ra một nghĩa."""
    counter = Counter(r.status for r in rows)
    for code, n in sorted(counter.items()):
        print(f"   HTTP {code or '---'}: {n:4d}  {_LEGEND.get(code, '')}")


# ══════════════════════════════════════════════════════════════════════════════════════════
# Kết quả một lượt gọi HTTP
# ══════════════════════════════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class GetResult:
    """Một lượt `GET /api/public/booking/{token}`."""

    index: int
    status: int
    latency: float
    finished_at: float  # perf_counter lúc nhận xong — dùng để xếp THỨ TỰ HOÀN TẤT
    starts: frozenset[str] = frozenset()  # tập `start_at` ISO được mời
    already_booked: bool = False
    hold_expires_at: str | None = None
    detail: str = ""


@dataclass(slots=True)
class PostResult:
    """Một lượt POST (`/confirm` hoặc `/cancel`)."""

    index: int
    status: int
    latency: float
    body: dict = field(default_factory=dict)
    detail: str = ""


async def _get_booking(client: httpx.AsyncClient, api: str, index: int, token: str) -> GetResult:
    t0 = time.perf_counter()
    try:
        r = await client.get(f"{api}/api/public/booking/{token}")
        dt = time.perf_counter() - t0
        body: dict = {}
        try:
            body = r.json()
        except Exception:  # noqa: BLE001 — 429/500 trả HTML hoặc rỗng; vẫn là một kết quả tải
            pass
        return GetResult(
            index=index,
            status=r.status_code,
            latency=dt,
            finished_at=time.perf_counter(),
            starts=frozenset(s["start_at"] for s in body.get("slots", []) or []),
            already_booked=bool(body.get("already_booked")),
            hold_expires_at=body.get("hold_expires_at"),
            detail=str(body.get("detail") or ""),
        )
    except Exception as exc:  # noqa: BLE001 — timeout cũng là một phép đo, đừng làm sập cả run
        return GetResult(
            index=index, status=0, latency=time.perf_counter() - t0,
            finished_at=time.perf_counter(), detail=f"{type(exc).__name__}: {exc}",
        )


async def _post(
    client: httpx.AsyncClient, api: str, index: int, path: str, payload: dict | None = None
) -> PostResult:
    t0 = time.perf_counter()
    try:
        r = await client.post(f"{api}{path}", json=payload)
        dt = time.perf_counter() - t0
        body: dict = {}
        try:
            body = r.json()
        except Exception:  # noqa: BLE001
            pass
        return PostResult(
            index=index, status=r.status_code, latency=dt, body=body,
            detail=str(body.get("detail") or ""),
        )
    except Exception as exc:  # noqa: BLE001
        return PostResult(
            index=index, status=0, latency=time.perf_counter() - t0,
            detail=f"{type(exc).__name__}: {exc}",
        )


# ══════════════════════════════════════════════════════════════════════════════════════════
# PHA 0 — GIEO DỮ LIỆU (qua tầng service, KHÔNG qua `dispatch_booking_invite`)
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _delete_tagged(session: AsyncSession) -> tuple[int, int]:
    """Xoá ĐÚNG những hàng script này tạo ra. Trả (số hồ sơ, số JD).

    Xoá `application` TRƯỚC `job_posting`: FK của application là `ondelete=SET NULL`, nên xoá JD
    trước chỉ để lại đám hồ sơ mồ côi mang nhãn cũ. `interview_booking` / `booking_session` /
    `audit_log` / `email_delivery` đều `ondelete=CASCADE` theo application nên DB tự dọn.
    """
    apps = (
        await session.execute(
            delete(Application).where(
                Application.applicant_email.like(f"{_TAG}+%@{_EMAIL_DOMAIN}")
            )
        )
    ).rowcount or 0
    jobs = (
        await session.execute(delete(JobPosting).where(JobPosting.title == _JOB_TITLE))
    ).rowcount or 0
    await session.commit()
    return apps, jobs


async def _seed(session: AsyncSession, total: int) -> list[tuple[int, str]]:
    """Tạo 1 JD + `total` hồ sơ ở `AWAITING_BOOKING`, mỗi hồ sơ MỘT phiên đặt lịch. Trả [(id, token)].

    **Cố ý KHÔNG đi qua `booking_flow.dispatch_booking_invite`.** Hàm đó là đường nghiệp vụ đúng cho
    một lời mời thật, nhưng nó gửi email — `total` lá thư, nối tiếp nhau sau bộ giữ nhịp 2 req/s của
    `email_service` (khoá `asyncio.Lock` dùng chung). Gieo 30 hồ sơ qua đường đó là 30 email thật +
    ~15 giây xếp hàng, để đo một thứ chẳng liên quan gì tới email. Ở đây ta chỉ cần đúng ĐIỀU KIỆN
    ĐẦU VÀO mà lời mời để lại: hồ sơ `AWAITING_BOOKING` + một token còn hạn. `create_booking_session`
    là hàm service thật (token crypto-random + TTL từ `BOOKING_LINK_TTL_HOURS`), không phải bản chép.

    Chạy lại được sạch sẽ: dọn hết hàng mang nhãn cũ TRƯỚC khi gieo. Không cố "tái dùng" seed cũ —
    hồ sơ của lần trước đã bị pha 2/3 đổi trạng thái (INTERVIEW_SCHEDULED, phiên có `booked_at`),
    tái dùng là đo trên đầu vào không xác định.
    """
    removed_apps, removed_jobs = await _delete_tagged(session)
    if removed_apps or removed_jobs:
        print(f"   Dọn seed cũ: {removed_apps} hồ sơ, {removed_jobs} JD.")

    job = JobPosting(title=_JOB_TITLE, description=f"JD giả của {_TAG} — xoá bằng --cleanup.",
                     status="OPEN")
    session.add(job)
    await session.flush()

    rows = [
        Application(
            job_id=job.id,
            applicant_email=f"{_TAG}+{i:03d}@{_EMAIL_DOMAIN}",
            # `booking_view` lấy tên hiển thị từ `parsed_data.full_name`; để trống thì mọi người
            # đều là "Ứng viên" và không phân biệt được ai trong log của backend.
            parsed_data={"full_name": f"Ung Vien Loadtest {i:03d}"},
            # AWAITING_BOOKING = trạng thái THẬT sau khi thư mời đã gửi (bất biến 08d). Để mặc định
            # SUBMITTED thì `confirm_and_notify` từ chối đúng theo thiết kế (`_BOOKABLE_STATUSES`)
            # và pha 2 đo nhầm thứ khác.
            status=ApplicationStatus.AWAITING_BOOKING.value,
        )
        for i in range(total)
    ]
    session.add_all(rows)
    await session.flush()

    seeds: list[tuple[int, str]] = []
    for row in rows:
        s = booking_service.create_booking_session(session, row.id)  # KHÔNG commit — ta commit 1 lần
        seeds.append((row.id, s.token))
    await session.commit()
    return seeds


async def _load_seed(session: AsyncSession) -> list[tuple[int, str]]:
    """Đọc lại seed đang có trong DB (để bỏ qua pha 0 mà vẫn chạy được pha 1–4).

    Sắp theo `application.id` — CÙNG thứ tự lúc gieo, nên vai của từng hồ sơ (người xem / đua / đặt
    lại / hold) ổn định giữa các lần chạy.

    Một hồ sơ có nhiều phiên còn sống thì lấy phiên MỚI NHẤT (`BookingSession.id` giảm dần): HR bấm
    "Gửi lại link" sinh phiên mới, và phiên CŨ tuy `cancelled_at IS NULL` vẫn có thể đã quá TTL —
    dùng nó thì mọi lượt GET trả 410 và pha nào cũng "hỏng" vì một lý do chẳng liên quan.
    """
    stmt = (
        select(Application.id, BookingSession.token)
        .join(BookingSession, BookingSession.application_id == Application.id)
        .where(Application.applicant_email.like(f"{_TAG}+%@{_EMAIL_DOMAIN}"))
        .where(BookingSession.cancelled_at.is_(None))
        .where(BookingSession.expires_at > _now())
        .order_by(Application.id, BookingSession.id.desc())
    )
    seen: dict[int, str] = {}
    for app_id, token in (await session.execute(stmt)).all():
        seen.setdefault(app_id, token)
    return sorted(seen.items())


# ══════════════════════════════════════════════════════════════════════════════════════════
# Sức chứa lịch — tính từ CHÍNH lưới của sản phẩm, không phải từ tài liệu
# ══════════════════════════════════════════════════════════════════════════════════════════


def _capacity(cfg: BookingConfig, now: datetime) -> tuple[int, int, int]:
    """→ (tổng mốc khả dụng trong cửa sổ, số ngày làm việc, số mốc/ngày lớn nhất).

    `max_per_day` chỉ có tác dụng khi nó NHỎ HƠN số mốc lưới sinh ra trong một ngày. Trả về cả hai
    để báo cáo nói được "cấu hình này có ràng buộc gì không" thay vì tin vào con số ghi trong docs.
    """
    starts = _candidate_starts(cfg, now)
    per_day = Counter(s.astimezone(cfg.tz).date() for s in starts)
    if not per_day:
        return 0, 0, 0
    effective = sum(min(n, cfg.max_per_day) for n in per_day.values())
    return effective, len(per_day), max(per_day.values())


def _report_capacity(cfg: BookingConfig) -> int:
    _banner("SỨC CHỨA LỊCH (tính từ lưới thật, không lấy từ tài liệu)")
    total, days, per_day_max = _capacity(cfg, _now())
    lunch = (f"{cfg.lunch[0].strftime('%H:%M')}–{cfg.lunch[1].strftime('%H:%M')}"
             if cfg.lunch else "không")
    print(f"   Giờ làm {cfg.work_start.strftime('%H:%M')}–{cfg.work_end.strftime('%H:%M')} · "
          f"nghỉ trưa {lunch} · buổi {cfg.duration_minutes}′ + đệm {cfg.buffer_minutes}′ "
          f"⇒ bước {cfg.step_minutes}′")
    print(f"   Cửa sổ {cfg.window_days} ngày ⇒ {days} ngày làm việc × tối đa {per_day_max} mốc/ngày "
          f"= {total} khung giờ trên LƯỚI (chưa trừ chỗ đã bị chiếm sẵn trong DB)")
    print(f"   Mỗi người xem giữ {cfg.slots_offered} khung trong {cfg.hold_minutes:g} phút "
          f"⇒ TRẦN người xem đồng thời ≈ {total // max(1, cfg.slots_offered)}")
    # Cả khối này đọc `.env` của SCRIPT. Backend có thể đang chạy cấu hình khác (quy trình pha 4 bảo
    # đặt hold ngắn) — pha 1 đo hold THẬT từ phản hồi và sẽ hô lên nếu hai bên lệch nhau.
    print("   (số trên lấy từ .env của SCRIPT; pha 1 đo lại hold THẬT từ phản hồi của backend)")
    if per_day_max < cfg.max_per_day:
        print(f"   [!] BOOKING_MAX_PER_DAY={cfg.max_per_day} KHÔNG BAO GIỜ chạm tới: lưới chỉ sinh "
              f"nổi {per_day_max} mốc/ngày. Đây là cấu hình CHẾT — nới nó lên không thêm được chỗ nào;")
        print("       muốn tăng sức chứa thì phải nới giờ làm / rút buffer / rút thời lượng buổi PV.")
    return total


# ══════════════════════════════════════════════════════════════════════════════════════════
# PHA 1 — TRANH GIÀNH LƯỢT XEM
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _phase_offers(
    client: httpx.AsyncClient, api: str, cfg: BookingConfig, seeds: list[tuple[int, str]],
    capacity: int, stagger: float, failures: list[str],
) -> float | None:
    """Trả HOLD THẬT (giây) mà backend cấp, đọc từ phản hồi — `None` nếu không ai được mời slot.

    Vì sao phải TRẢ VỀ chứ không dùng `cfg.hold_minutes`: script đọc `.env` của CHÍNH NÓ, còn quy
    trình chạy (docstring đầu file) lại khởi động backend với `BOOKING_HOLD_MINUTES` KHÁC — pha 4
    cần hold ngắn. Mọi câu văn nói "chỗ giữ tự trả lại sau N phút" mà lấy N từ `cfg` là nói về một
    hệ thống KHÔNG PHẢI hệ thống vừa đo.
    """
    k = len(seeds)
    mode = "CÙNG LÚC" if stagger <= 0 else f"cách nhau {stagger:g}s"
    _banner(f"PHA 1 — {k} NGƯỜI MỞ LINK ({mode}; GET không bị rate-limit)")

    async def one(i: int, token: str) -> GetResult:
        # `--stagger` tồn tại vì hai câu hỏi KHÁC NHAU cần hai chế độ khác nhau:
        #   stagger=0 → "cùng lúc": đo TOCTOU (mọi người đọc chung một tấm lịch trống).
        #   stagger>0 → "nối đuôi": mỗi người thấy hold của người trước ⇒ mới tìm được BỨC TƯỜNG
        #               (người thứ mấy nhận danh sách rỗng). Chạy đồng thời thì tường không hiện
        #               ra, vì hệ thống PHÁT TRÙNG chứ không từ chối.
        if stagger > 0:
            await asyncio.sleep(i * stagger)
        return await _get_booking(client, api, i, token)

    wall0 = _now()  # mốc ĐỒNG HỒ TƯỜNG, để so với `hold_expires_at` backend trả về
    t0 = time.perf_counter()
    results = list(await asyncio.gather(*(one(i, tok) for i, (_, tok) in enumerate(seeds))))
    wall = time.perf_counter() - t0

    rate_note = "" if stagger <= 0 else "  (= nhịp --stagger đặt sẵn, KHÔNG phải thông lượng đo được)"
    print(f"   {k} lượt trong {wall:.1f}s ⇒ {k / max(wall, 1e-9):.1f} lượt/giây{rate_note}")
    _codes(results)
    lats = sorted(r.latency for r in results)
    if lats:
        print(f"   Độ trễ: p50 {_p(lats, 0.5):.2f}s | p95 {_p(lats, 0.95):.2f}s | max {lats[-1]:.2f}s "
              f"| trung bình {statistics.mean(lats):.2f}s")
        print("   (GET này giữ MỘT connection của pool suốt lượt sinh slot, mà pool chỉ 15 — nên đuôi")
        print("    p95 dài ở K lớn THƯỜNG là hàng đợi pool chứ không phải Postgres chậm. Chưa loại trừ")
        print("    được client: script không có đồng hồ đo request đang bay như `loadtest_apply.py`.)")

    ok = [r for r in results if r.status == 200]
    empty = [r for r in ok if not r.starts and not r.already_booked]
    served = [r for r in ok if r.starts]
    booked_already = [r for r in ok if r.already_booked]

    # ── HOLD THẬT của backend + kiểm phép đo có còn hợp lệ không ────────────────────────────
    # `hold_expires_at` là do BACKEND cấp, nên nó là số của hệ thống đang đo. `cfg.hold_minutes`
    # chỉ là `.env` của script.
    deadlines = [
        datetime.fromisoformat(r.hold_expires_at) for r in served if r.hold_expires_at
    ]
    hold_seconds = (min(deadlines) - wall0).total_seconds() if deadlines else None
    if hold_seconds is not None:
        env_seconds = cfg.hold_minutes * 60
        print()
        print(f"   Hold THẬT backend cấp: {hold_seconds:.0f}s "
              f"(BOOKING_HOLD_MINUTES trong .env của SCRIPT = {cfg.hold_minutes:g}′ = {env_seconds:.0f}s)")
        if abs(hold_seconds - env_seconds) > max(5.0, 0.2 * env_seconds):
            print("   [!] LỆCH CẤU HÌNH: backend đang chạy BOOKING_HOLD_MINUTES KHÁC .env của script")
            print("       (đúng như quy trình pha 4 yêu cầu). Mọi con số script suy ra từ `cfg` — sức")
            print("       chứa, 'tự trả lại sau N phút' — là của .env, KHÔNG phải của hệ thống vừa đo.")

    # BỨC TƯỜNG chỉ có nghĩa khi CẢ ĐỢT bắn gọn TRONG một vòng đời hold. Dài hơn thì chỗ giữ của
    # những người ĐẦU đã tự nhả trước khi người CUỐI mở link ⇒ sức chứa bị TÁI SỬ DỤNG giữa chừng,
    # và script sẽ báo "chưa ai bị từ chối" cho một đợt vượt trần gấp rưỡi. Đã tái hiện được thật:
    # `--viewers 20 --stagger 1.2` với hold 15s ⇒ 20/20 được mời, trần lý thuyết 15.
    measurable = hold_seconds is None or wall < hold_seconds
    if not measurable:
        print()
        print("   " + "!" * 72)
        print(f"   !!  PHÉP ĐO TRẦN KHÔNG HỢP LỆ: đợt bắn kéo dài {wall:.0f}s nhưng hold chỉ sống")
        print(f"   !!  {hold_seconds:.0f}s ⇒ chỗ giữ của những người ĐẦU đã tự nhả TRƯỚC khi người CUỐI")
        print("   !!  mở link. Sức chứa được tái sử dụng giữa chừng nên 'bức tường' luôn xa hơn thực")
        print("   !!  tế, và 'chưa ai bị từ chối' là kết luận SAI. Cả bội số lẫn Jaccard bên dưới")
        print("   !!  cũng không còn đọc được (trùng nhau có thể chỉ là slot phát LẠI sau khi hết hạn).")
        print(f"   !!  SỬA: giữ --viewers × --stagger < {hold_seconds:.0f}s, hoặc nâng")
        print("   !!  BOOKING_HOLD_MINUTES ở BACKEND rồi chạy lại.")
        print("   " + "!" * 72)
        failures.append(
            f"pha 1: phép đo trần VÔ HIỆU — đợt bắn {wall:.0f}s > hold {hold_seconds:.0f}s "
            "(sức chứa bị tái sử dụng giữa chừng)"
        )

    print()
    print(f"   Được mời khung giờ : {len(served)}/{k}")
    print(f"   Nhận DANH SÁCH RỖNG: {len(empty)}/{k}")
    if booked_already:
        # Không thuộc xô nào ở trên ⇒ nếu không in ra thì hai dòng trên KHÔNG cộng lại thành k và
        # người đọc sẽ tự đi tìm một lỗi không tồn tại.
        print(f"   Đã đặt lịch từ trước: {len(booked_already)}/{k} (seed dùng lại, không tính vào trần)")
    if empty:
        # Ở chế độ nối đuôi, thứ tự có nghĩa là thứ tự XUẤT PHÁT (do `--stagger` áp đặt) — sắp theo
        # `finished_at` là sai, vì độ trễ dao động lớn hơn `--stagger` thì hai người đổi chỗ cho
        # nhau. Ở chế độ đồng thời KHÔNG có thứ tự xuất phát thật, nên thứ tự HOÀN TẤT là thứ duy
        # nhất quan sát được — và phải nói rõ đó chỉ là xấp xỉ.
        if stagger > 0:
            order, label = sorted(ok, key=lambda r: r.index), "thứ tự XUẤT PHÁT"
        else:
            order, label = sorted(ok, key=lambda r: r.finished_at), "thứ tự HOÀN TẤT"
        first_empty = next(
            (n for n, r in enumerate(order, start=1) if not r.starts and not r.already_booked), None
        )
        print(f"   Người RỖNG đầu tiên theo {label}: #{first_empty} "
              f"(trần lý thuyết ≈ {capacity // max(1, cfg.slots_offered)})")
        if stagger <= 0:
            print("   ↳ đây là XẤP XỈ: K request đồng thời không có thứ tự 'người thứ K' thật sự.")
        if len(ok) < k:
            print(f"   ↳ và nó đếm trong {len(ok)}/{k} lượt trả 200 — {k - len(ok)} lượt hỏng đã bị")
            print("     loại khỏi thứ hạng, nên '#N' KHÔNG phải 'người thứ N mở link'.")
    elif measurable:
        print(f"   Chưa ai bị từ chối (trần lý thuyết ≈ {capacity // max(1, cfg.slots_offered)}).")
        if stagger <= 0:
            print("   ↳ Chạy ĐỒNG THỜI thì bức tường KHÔNG hiện ra: hệ thống phát TRÙNG khung giờ")
            print("     chứ không từ chối ai (xem bội số bên dưới). Muốn tìm bức tường thật thì")
            print("     chạy nối đuôi: --stagger 0.5 --viewers "
                  f"{capacity // max(1, cfg.slots_offered) + 5}")

    handed = sum(len(r.starts) for r in served)
    union: set[str] = set()
    for r in served:
        union |= set(r.starts)
    over = handed / len(union) if union else 0.0
    print(f"   Khung giờ đã phát : {handed} lượt trên {len(union)} mốc PHÂN BIỆT "
          f"(trên tổng {capacity} mốc của LƯỚI) ⇒ bội số {over:.1f} người/mốc")
    if union and len(union) < capacity:
        print(f"   ↳ {capacity - len(union)} mốc trên lưới không được mời cho ai — trong đó có thể có")
        print("     mốc đã bị chiếm SẴN từ trước lần chạy này (capacity là sức chứa lưới, chưa trừ).")

    # ── Chồng lấn giữa những người xem ĐỒNG THỜI (Jaccard) ─────────────────────────────────
    pairs = [(a, b) for a, b in combinations(served, 2)]
    if pairs:
        jac = [len(a.starts & b.starts) / len(a.starts | b.starts) for a, b in pairs]
        identical = sum(1 for j in jac if j == 1.0)
        overlapping = sum(1 for j in jac if j > 0)
        print()
        print(f"   Chồng lấn danh sách (Jaccard) trên {len(pairs)} cặp: "
              f"trung bình {statistics.mean(jac):.3f} | lớn nhất {max(jac):.3f} | "
              f"có trùng: {overlapping} cặp | TRÙNG HỆT NHAU: {identical} cặp")
        if overlapping and not measurable:
            # Đợt bắn dài hơn vòng đời hold thì "trùng nhau" có lời giải TẦM THƯỜNG (slot của người
            # trước hết hạn rồi được phát lại cho người sau) — quy nó cho TOCTOU là gán sai nguyên
            # nhân cho một hiện tượng bình thường. Im lặng ở đây, băng rôn VÔ HIỆU ở trên đã nói.
            print("   ↳ KHÔNG kết luận nguyên nhân: đợt bắn dài hơn hold nên trùng nhau có thể chỉ")
            print("     là slot đã hết hạn được phát lại. Chạy lại trong một vòng đời hold rồi đọc.")
        elif overlapping:
            # Đây là phát hiện đáng giá nhất của pha 1 — và nó KHÔNG phải chuyện "hết chỗ": ở lần
            # chạy đo được, 24 người chia nhau đúng 15 mốc trong khi 60 mốc khác trống trơn.
            print("   [!] Chồng lấn CAO trong khi lịch còn rộng KHÔNG phải do cạn chỗ — đó là TOCTOU:")
            print("       `generate_slots` ĐỌC `_occupied` rồi mới GHI, còn `lock_application` chỉ")
            print("       khoá theo TỪNG hồ sơ nên KHÔNG tuần tự hoá hai hồ sơ KHÁC NHAU. Ai đọc")
            print("       trước khi người kia commit đều thấy y hệt một tấm lịch trống, và")
            print("       `_pick_mixed` TẤT ĐỊNH nên tất cả chọn CÙNG một bộ mốc.")
            print("       Hệ quả ở bước chốt: N người cùng nhắm một mốc ⇒ 1 người thắng, N−1 ăn 409.")
            print("       (Không phải lỗi đúng-đắn: HELD là khuyến nghị và partial unique index vẫn")
            print("       giữ vững — nhưng nó là lỗi TRẢI NGHIỆM, và nó nặng lên đúng lúc đông người.)")
        else:
            print("   Không cặp nào trùng: hold của người trước đã loại mốc đó khỏi lượt của người sau.")

    print()
    if any(r.status not in (200,) for r in results):
        failures.append("pha 1: có lượt GET không trả 200 (xem bảng mã ở trên)")
    return hold_seconds


async def _report_false_no_slots(
    session: AsyncSession, cfg: BookingConfig, app_ids: list[int], hold_seconds: float | None,
    failures: list[str],
) -> None:
    """Đếm số phiên bị đóng dấu `no_slots_at` TRONG KHI thực tế chưa có buổi PV nào được chốt.

    Đây là phát hiện đắt nhất của cả script, nên nó có mục riêng: `no_slots_at` là thứ bật nhãn
    dashboard *"Hết khung giờ — cần mở thêm lịch"* (SCH-3 §3.5) và nó nói với HR rằng LỊCH CÔNG TY
    đã kín. Nhưng "chỗ đã chiếm" = `BOOKED` **hoặc** `HELD còn hạn`; nếu số hàng `BOOKED` bằng 0 thì
    lịch KHÔNG hề kín — nó chỉ đang bị giữ tạm bởi những người còn đang phân vân, và toàn bộ số chỗ
    đó sẽ tự trả lại sau `BOOKING_HOLD_MINUTES`. HR bị gọi đi mở thêm lịch cho một vấn đề sẽ tự
    biến mất sau vài phút — và lần nhãn đó hiện lên vì lý do THẬT, không ai còn tin nó nữa.
    """
    now = _now()
    day_start = datetime.combine(
        now.astimezone(cfg.tz).date(), dtime(0, 0), tzinfo=cfg.tz
    ).astimezone(timezone.utc)
    window_end = now + timedelta(days=cfg.window_days)

    flagged = (
        await session.execute(
            select(func.count())
            .select_from(BookingSession)
            .where(
                BookingSession.no_slots_at.is_not(None),
                BookingSession.application_id.in_(app_ids),
            )
        )
    ).scalar_one()
    booked = (
        await session.execute(
            select(func.count())
            .select_from(InterviewBooking)
            .where(
                InterviewBooking.status == BookingStatus.BOOKED.value,
                InterviewBooking.start_at >= day_start,
                InterviewBooking.start_at <= window_end,
            )
        )
    ).scalar_one()
    held = (
        await session.execute(
            select(func.count())
            .select_from(InterviewBooking)
            .where(
                InterviewBooking.status == BookingStatus.HELD.value,
                InterviewBooking.hold_expires_at > now,
                InterviewBooking.start_at >= day_start,
                InterviewBooking.start_at <= window_end,
            )
        )
    ).scalar_one()
    await session.rollback()  # ba câu trên là ĐỌC — đóng transaction, đừng ôm connection để in ấn

    _banner("CẢNH BÁO GIẢ GỬI CHO HR — `no_slots_at`")
    print(f"   Phiên bị đóng dấu no_slots_at : {flagged}")
    print(f"   Hàng BOOKED trong cửa sổ (TOÀN CỤC) : {booked}")
    print(f"   Hàng HELD còn hạn trong cửa sổ      : {held}")
    if flagged and booked == 0:
        print()
        # Thời lượng hold lấy từ PHẢN HỒI của backend (pha 1 đo được), không lấy từ `.env` của
        # script: quy trình chạy khuyến nghị khởi động backend với hold ngắn cho pha 4, nên
        # `cfg.hold_minutes` ở đây thường là con số của một hệ thống khác.
        span = (f"{hold_seconds:.0f} giây" if hold_seconds is not None
                else f"{cfg.hold_minutes:g} phút (theo .env của SCRIPT — chưa đo được từ backend)")
        print("   ██ CẢNH BÁO SAI: hệ thống báo HR \"Hết khung giờ — cần mở thêm lịch\" trong khi")
        print(f"   ██ KHÔNG có buổi phỏng vấn nào được đặt. {held} khung giờ đang bị GIỮ TẠM và sẽ")
        print(f"   ██ tự trả lại sau {span}. Nhãn này đổ lỗi cho lịch của công ty")
        print("   ██ về một tình trạng tạm thời do chính cơ chế giữ chỗ gây ra.")
        print("   ██ (KHÔNG tính là bất biến sai — đây là thiết kế hiện tại, và đó mới là vấn đề.)")
    elif flagged:
        print("   Có đóng dấu, nhưng lịch cũng thật sự có buổi đã chốt — cảnh báo có cơ sở.")
    else:
        print("   Không phiên nào bị đóng dấu.")


# ══════════════════════════════════════════════════════════════════════════════════════════
# PHA 2 — ĐUA CHỐT CÙNG MỘT KHUNG GIỜ
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _pick_contested_start(session: AsyncSession, cfg: BookingConfig) -> datetime | None:
    """Chọn MỘT mốc giờ trên lưới thật, chưa có hàng `BOOKED` nào, nằm CUỐI cửa sổ.

    Cuối cửa sổ là cố ý: `_pick_mixed` ưu tiên mốc sớm, nên mốc cuối gần như chắc chắn không nằm
    trong danh sách mà pha 1 vừa phát ⇒ hai pha không giẫm chân nhau. Bỏ qua mốc đã `BOOKED` để
    lần chạy thứ hai không thua sạch vì kết quả của lần chạy thứ nhất.
    """
    starts = _candidate_starts(cfg, _now())
    if not starts:
        return None
    taken = set(
        (
            await session.execute(
                select(InterviewBooking.start_at).where(
                    InterviewBooking.status == BookingStatus.BOOKED.value
                )
            )
        )
        .scalars()
        .all()
    )
    taken_utc = {t.astimezone(timezone.utc) for t in taken}
    for start in reversed(starts):
        if start not in taken_utc:
            return start
    return None


async def _phase_race(
    client: httpx.AsyncClient, api: str, session: AsyncSession, cfg: BookingConfig,
    seeds: list[tuple[int, str]], failures: list[str],
) -> None:
    r = len(seeds)
    _banner(f"PHA 2 — {r} NGƯỜI CÙNG CHỐT MỘT KHUNG GIỜ (POST /confirm)")

    start = await _pick_contested_start(session, cfg)
    if start is None:
        print("   [!] Không tìm được mốc giờ trống nào trên lưới — bỏ qua pha 2.")
        failures.append("pha 2: không dựng được thế đua (lưới hết mốc trống)")
        return

    # Thế đua phải DỰNG BẰNG TAY. `generate_slots` cố ý loại trừ mốc người khác đang giữ, nên đi
    # đường tự nhiên thì hai người gần như không bao giờ được mời CÙNG một khung — mà đó chính là
    # khe hở mà partial unique index tồn tại để bịt. Đây cũng đúng cách `test_booking_db.py` dựng
    # `test_real_race_exactly_one_winner`; ở đây chỉ khác là chạy qua HTTP thật với R > 2.
    hold_until = _now() + timedelta(minutes=30)  # dài hơn mọi cấu hình hold: đua không được thua vì hết hạn
    rows = [
        InterviewBooking(
            application_id=app_id,
            start_at=start,
            end_at=start + timedelta(minutes=cfg.duration_minutes),
            status=BookingStatus.HELD.value,
            hold_expires_at=hold_until,
        )
        for app_id, _ in seeds
    ]
    session.add_all(rows)
    await session.flush()
    booking_ids = [row.id for row in rows]
    await session.commit()
    print(f"   Khung giờ tranh chấp: {_ict(cfg, start)} (giờ VN) — {r} hàng HELD cùng mốc "
          "(HỢP LỆ: HELD chỉ là khuyến nghị, PRD §10b.5)")

    results = list(
        await asyncio.gather(
            *(
                _post(client, api, i, f"/api/public/booking/{token}/confirm",
                      {"booking_id": booking_ids[i]})
                for i, (_, token) in enumerate(seeds)
            )
        )
    )
    _codes(results)
    lats = sorted(x.latency for x in results)
    if lats:
        print(f"   Độ trễ: p50 {_p(lats, 0.5):.2f}s | p95 {_p(lats, 0.95):.2f}s | max {lats[-1]:.2f}s")

    won = [x for x in results if x.status == 200]
    lost = [x for x in results if x.status == 409]
    crashed = [x for x in results if x.status >= 500 or x.status == 0]
    throttled = [x for x in results if x.status == 429]

    print()
    if throttled:
        print(f"   ██ {len(throttled)} lượt bị 429 — PHÉP ĐO KHÔNG KẾT LUẬN ĐƯỢC.")
        print(f"   ██ Xô `booking` cho phép {settings.rate_limit_public_max} POST / "
              f"{settings.rate_limit_public_window_seconds:g}s / IP, và cả script dùng CHUNG một IP.")
        print("   ██ Chạy lại backend với RATE_LIMIT_ENABLED=false, hoặc giảm --race.")
        failures.append("pha 2: 429 rate-limit làm phép đo vô hiệu")
        return

    if len(won) == 1 and len(lost) == r - 1 and not crashed:
        print(f"   ✔ ĐÚNG 1 người thắng, {len(lost)} người nhận 409, 0 lỗi máy chủ.")
    else:
        print(f"   ✘ BẤT BIẾN SAI: thắng={len(won)} (phải là 1) · 409={len(lost)} (phải là {r - 1}) "
              f"· 5xx/timeout={len(crashed)} (phải là 0)")
        failures.append(
            f"pha 2: thắng={len(won)}/1, 409={len(lost)}/{r - 1}, 5xx={len(crashed)}/0"
        )
    if crashed:
        print("   ↳ 500 ở đây là HỒI QUY: deadlock giữa hai lượt `release_holds` phải được dịch")
        print("     thành 409 ở `confirm_booking` (khối `except DBAPIError`), không được lọt ra route.")
        for x in crashed[:3]:
            print(f"     ví dụ #{x.index}: {x.status} {x.detail[:90]}")
    if won and won[0].body.get("email_sent"):
        print("   [!] Backend ĐÃ GỬI EMAIL THẬT cho người thắng — RESEND_API_KEY đang được cấu hình.")

    # Chốt chặn cuối, hỏi thẳng DB: dù route trả gì thì cũng không được có hai hàng BOOKED một mốc.
    dupes = (
        await session.execute(
            select(InterviewBooking.start_at, func.count())
            .where(InterviewBooking.status == BookingStatus.BOOKED.value)
            .group_by(InterviewBooking.start_at)
            .having(func.count() > 1)
        )
    ).all()
    if dupes:
        print(f"   ✘ DB có {len(dupes)} mốc giờ bị ĐẶT TRÙNG — partial unique index đã thủng:")
        for start_at, n in dupes[:5]:
            print(f"     {_ict(cfg, start_at)}: {n} hàng BOOKED")
        failures.append(f"pha 2: {len(dupes)} mốc giờ có >1 hàng BOOKED")
    else:
        print("   ✔ SQL xác nhận: không mốc giờ nào có quá một hàng BOOKED (toàn bảng).")


# ══════════════════════════════════════════════════════════════════════════════════════════
# PHA 3 — HUỶ RỒI ĐẶT LẠI
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _session_row(session: AsyncSession, token: str) -> BookingSession | None:
    return (
        await session.execute(select(BookingSession).where(BookingSession.token == token))
    ).scalar_one_or_none()


async def _phase_rebook(
    client: httpx.AsyncClient, api: str, session: AsyncSession, cfg: BookingConfig,
    app_id: int, token: str, failures: list[str],
) -> None:
    _banner("PHA 3 — HUỶ RỒI ĐẶT LẠI (khung giờ phải quay lại, TTL không được gia hạn)")

    first = await _get_booking(client, api, 0, token)
    if first.status != 200 or not first.starts:
        print(f"   [!] Không lấy được khung giờ nào (HTTP {first.status}, {len(first.starts)} slot) "
              "— hết sức chứa? Bỏ qua pha 3.")
        failures.append("pha 3: không có khung giờ để đặt (lịch đã cạn)")
        return

    row = await _session_row(session, token)
    if row is None:
        failures.append("pha 3: không tìm thấy booking_session của token")
        return
    ttl_before = row.expires_at
    # Đóng transaction ĐỌC ngay: hai lượt POST bên dưới mất vài giây, và ôm một connection
    # "idle in transaction" xuyên qua đó là đúng thứ *Load boundary* cấm ở phía sản phẩm — công cụ
    # đo cũng không được phép làm gương xấu (và Neon tính giờ compute theo connection đang thức).
    await session.rollback()

    # Chốt khung giờ SỚM NHẤT: sau khi huỷ, nó lại là mốc sớm nhất còn trống, mà `_pick_mixed` bước
    # 1 luôn lấy các mốc sớm nhất ⇒ "quay lại danh sách" là điều kiểm được, không phải may rủi.
    slots = sorted(first.starts)
    target_start = slots[0]
    # Bấm lại link trả ĐÚNG các slot đang giữ (bất biến `generate_slots`), nên lượt GET thứ hai chỉ
    # để lấy `booking_id` — `GetResult` cố tình chỉ giữ tập `start_at`. Truy cập phòng thủ: một lượt
    # 4xx/5xx ở đây mà đọc thẳng `body["slots"]` sẽ ném KeyError và giết cả lần chạy ở PHA 3, làm
    # mất luôn pha 4 vốn chẳng liên quan gì.
    retry = await client.get(f"{api}/api/public/booking/{token}")
    body: dict = retry.json() if retry.status_code == 200 else {}
    booking_id = next(
        (s["booking_id"] for s in body.get("slots", []) or [] if s["start_at"] == target_start), None
    )
    if booking_id is None:
        print(f"   [!] Mở lại link KHÔNG trả về khung giờ vừa được mời (HTTP {retry.status_code}) — "
              "bất biến 'bấm lại trả slot cũ' hỏng, hoặc lượt GET này lỗi. Bỏ qua pha 3.")
        failures.append(f"pha 3: mở lại link không trả lại slot đang giữ (HTTP {retry.status_code})")
        return

    confirmed = await _post(client, api, 0, f"/api/public/booking/{token}/confirm",
                            {"booking_id": booking_id})
    print(f"   Chốt {_ict(cfg, datetime.fromisoformat(target_start))} (giờ VN): "
          f"HTTP {confirmed.status} {_LEGEND.get(confirmed.status, '')}")
    if confirmed.status == 429:
        # 429 KHÔNG phải lỗi nghiệp vụ — đừng ghi vào sổ bất biến như thể sản phẩm sai. Xô `booking`
        # dùng cửa sổ TRƯỢT 1 giờ nên vài lần chạy liên tiếp trong cùng giờ là đủ chạm trần.
        print(f"   ⤼ PHÉP ĐO KHÔNG KẾT LUẬN ĐƯỢC: xô `booking` cho {settings.rate_limit_public_max} "
              f"POST / {settings.rate_limit_public_window_seconds:g}s / IP (cửa sổ TRƯỢT).")
        print("     Khởi động backend với RATE_LIMIT_ENABLED=false rồi chạy lại --phases 0,3.")
        failures.append("pha 3: 429 rate-limit làm phép đo vô hiệu (không phải lỗi nghiệp vụ)")
        return
    if confirmed.status != 200:
        failures.append(f"pha 3: chốt lịch thất bại (HTTP {confirmed.status})")
        return
    if confirmed.body.get("email_sent"):
        print("   [!] Backend ĐÃ GỬI EMAIL THẬT (thư xác nhận) — RESEND_API_KEY đang được cấu hình.")

    cancelled = await _post(client, api, 0, f"/api/public/booking/{token}/cancel")
    print(f"   Huỷ: HTTP {cancelled.status} · cancelled={cancelled.body.get('cancelled')} "
          f"· can_rebook={cancelled.body.get('can_rebook')}")
    if cancelled.status != 200 or not cancelled.body.get("cancelled"):
        failures.append(f"pha 3: huỷ thất bại (HTTP {cancelled.status})")
        return

    again = await _get_booking(client, api, 0, token)
    reappeared = target_start in again.starts
    print(f"   Mở lại link: HTTP {again.status} · {len(again.starts)} khung giờ · "
          f"khung vừa nhả {'CÓ' if reappeared else 'KHÔNG'} quay lại")
    if not reappeared:
        print("   ✘ Khung giờ vừa huỷ KHÔNG được mời lại — `cancel_booked` phải nhả TỨC THÌ và")
        print("     `CANCELLED` không được nằm trong tập 'đang bị chiếm'.")
        if again.status != 200:
            # Mã khác 200 ⇒ nguyên nhân nằm ở LIÊN KẾT (410 = hết hạn/đã huỷ vì chạm hạn mức đổi ý),
            # không phải ở việc nhả khung giờ. Nói đúng chỗ để người đọc không đi sửa nhầm.
            print(f"     ↳ nhưng lượt GET trả HTTP {again.status} ({_LEGEND.get(again.status, '')}) —")
            print("       nguyên nhân là LIÊN KẾT, không phải cơ chế nhả chỗ. Gieo lại seed rồi đo lại.")
        failures.append(f"pha 3: khung giờ đã huỷ không quay lại danh sách (HTTP {again.status})")
    else:
        print("   ✔ Huỷ nhả khung giờ tức thì (không chờ sweep).")

    # `rollback()` chứ không `expunge_all()`: nó vừa đóng transaction đọc cũ, vừa cho hết object
    # hết hạn ⇒ lần đọc sau lấy giá trị THẬT từ DB (backend vừa ghi ở tiến trình khác), không phải
    # bản đã nạp trong bộ nhớ session này. Không có nó thì `expires_at` "không đổi" một cách giả tạo.
    await session.rollback()
    row = await _session_row(session, token)
    if row is None:
        failures.append("pha 3: booking_session biến mất sau khi huỷ")
        return
    ttl_same = row.expires_at == ttl_before
    print(f"   Hạn liên kết: trước {_ict(cfg, ttl_before)} → sau {_ict(cfg, row.expires_at)} "
          f"({'KHÔNG ĐỔI' if ttl_same else 'ĐÃ ĐỔI'}) · rebook_count={row.rebook_count} "
          f"· booked_at={'None' if row.booked_at is None else 'đã đặt'}")
    if not ttl_same:
        print("   ✘ Huỷ đã GIA HẠN hạn liên kết — PRD §10b.6 cấm: đó là vòng đặt-huỷ-đặt vô tận.")
        failures.append("pha 3: huỷ làm đổi expires_at của liên kết")
    else:
        print("   ✔ Hạn gốc vẫn là hạn gốc (`mark_session_reopened` chỉ xoá `booked_at`).")


# ══════════════════════════════════════════════════════════════════════════════════════════
# PHA 4 — HOLD HẾT HẠN THÌ THÔI CHIẾM CHỖ
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _occupied_count(session: AsyncSession, starts: list[datetime]) -> int:
    """Bao nhiêu mốc trong `starts` ĐANG BỊ CHIẾM, theo ĐÚNG định nghĩa của sản phẩm.

    Chiếm chỗ = `BOOKED` **hoặc** (`HELD` và `hold_expires_at > now`) — chép đúng vị từ của
    `booking_service._occupied`. Đây là bất biến CỨNG của pha 4: sau khi hold hết hạn, con số này
    phải về 0 mà KHÔNG cần cron nào chạy.
    """
    now = _now()
    n = (
        await session.execute(
            select(func.count())
            .select_from(InterviewBooking)
            .where(
                InterviewBooking.start_at.in_(starts),
                or_(
                    InterviewBooking.status == BookingStatus.BOOKED.value,
                    and_(
                        InterviewBooking.status == BookingStatus.HELD.value,
                        InterviewBooking.hold_expires_at > now,
                    ),
                ),
            )
        )
    ).scalar_one()
    await session.rollback()
    return int(n)


async def _phase_hold_expiry(
    client: httpx.AsyncClient, api: str, session: AsyncSession, cfg: BookingConfig,
    all_app_ids: list[int], trio: list[tuple[int, str]], max_wait: float, failures: list[str],
) -> None:
    _banner("PHA 4 — HOLD BỎ DỞ PHẢI THÔI CHIẾM CHỖ")
    (_, tok_a), (_, tok_b), (_, tok_c) = trio

    # Lịch phải SẠCH trước khi đo, nếu không phép đo mất tính tất định — và lần chạy đầu tiên của
    # script này đã dính đúng cái bẫy đó: `_pick_mixed` luôn ưu tiên mốc SỚM NHẤT, nên nếu lúc A
    # chọn còn ai đó giữ mấy mốc sớm, thì sau khi hold của A hết hạn, người C tới sau sẽ được mời
    # những mốc CÒN SỚM HƠN (vừa được nhả) chứ không phải mốc của A — và ta kết luận nhầm rằng hold
    # của A không nhả. Dọn trước thì A chắc chắn cầm các mốc sớm nhất, và C phải nhận lại đúng chúng.
    freed = await _release_holds_of(session, all_app_ids)
    print(f"   (công cụ nhả {freed} hold còn sót của các pha trước để lịch SẠCH — pha này cần vậy "
          "mới tất định; xem chú thích trong mã)")

    a = await _get_booking(client, api, 0, tok_a)
    if a.status != 200 or not a.starts or not a.hold_expires_at:
        print(f"   [!] Người A không nhận được khung giờ nào (HTTP {a.status}) — bỏ qua pha 4.")
        failures.append("pha 4: không dựng được hold ban đầu")
        return

    deadline = datetime.fromisoformat(a.hold_expires_at)
    wait = (deadline - _now()).total_seconds() + 2.0
    print(f"   A giữ {len(a.starts)} khung, hết hạn {_ict(cfg, deadline)} "
          f"(còn {max(0.0, wait - 2.0):.0f}s)")

    b = await _get_booking(client, api, 1, tok_b)
    overlap_live = a.starts & b.starts
    print(f"   B mở link NGAY lúc đó: HTTP {b.status} · {len(b.starts)} khung · "
          f"trùng với A: {len(overlap_live)}")
    if overlap_live:
        print("   ✘ Hold CÒN HẠN của A không loại được mốc đó khỏi lượt của B — `_occupied` sai.")
        failures.append("pha 4: hold còn hạn vẫn bị phát lại cho người khác")
    elif b.status != 200 or not b.starts:
        # "Không trùng" vì B KHÔNG NHẬN ĐƯỢC GÌ không chứng minh điều gì cả — tập rỗng thì giao với
        # bất cứ thứ gì cũng rỗng. Nếu không tách nhánh này thì một lượt GET hỏng (hoặc lịch cạn)
        # in ra dấu ✔, và bất biến quan trọng nhất của pha 4 lặng lẽ KHÔNG được kiểm.
        print("   ✘ KHÔNG kiểm được: B không nhận được khung giờ nào (tập rỗng thì đương nhiên không")
        print("     trùng với A). Lịch cạn hoặc request hỏng — không phải bằng chứng hold chiếm chỗ.")
        failures.append(f"pha 4: không kiểm được 'hold còn hạn chiếm chỗ' (B: HTTP {b.status}, 0 khung)")
    else:
        print("   ✔ Hold còn hạn chiếm chỗ đúng như thiết kế.")

    if wait > max_wait:
        print()
        print(f"   ⤼ BỎ QUA phần đo hết hạn: phải chờ {wait:.0f}s > --max-hold-wait {max_wait:.0f}s.")
        print(f"     BOOKING_HOLD_MINUTES đang là {cfg.hold_minutes:g}. Khởi động lại backend với")
        print("     `BOOKING_HOLD_MINUTES=0.25` (15 giây) rồi chạy lại chỉ pha này: --phases 0,4")
        return

    print(f"   … chờ {wait:.0f}s cho hold của A hết hạn (KHÔNG có cron nào dọn — mọi truy vấn")
    print("     'đang bị chiếm' đều lọc `hold_expires_at > now`, nên hàng quá hạn tự thôi chiếm chỗ)")
    await asyncio.sleep(wait)

    # ── Bất biến 1 (hỏi thẳng DB): các mốc của A không còn bị tính là "đang bị chiếm" ──────
    a_starts = [datetime.fromisoformat(s) for s in sorted(a.starts)]
    still = await _occupied_count(session, a_starts)
    print(f"   Mốc của A còn bị tính là 'đang bị chiếm' (BOOKED hoặc HELD còn hạn): {still}/{len(a_starts)}")
    if still:
        print("   ✘ Hold quá hạn VẪN chiếm chỗ — vị từ `hold_expires_at > now` của `_occupied` hỏng,")
        print("     và mỗi người bấm link rồi bỏ đi sẽ khoá vĩnh viễn 5 khung giờ.")
        failures.append(f"pha 4: {still} mốc của A vẫn bị chiếm sau khi hold hết hạn")
    else:
        print("   ✔ Hold quá hạn tự thôi chiếm chỗ — không cần cron dọn (PRD §10b.5).")

    # ── Bất biến 2 (đường công khai): người tới sau THẬT SỰ được mời lại các mốc đó ─────────
    c = await _get_booking(client, api, 2, tok_c)
    recovered = a.starts & c.starts
    print(f"   C mở link SAU khi hết hạn: HTTP {c.status} · {len(c.starts)} khung · "
          f"được mời lại mốc của A: {len(recovered)}/{len(a.starts)}")
    if len(recovered) == len(a.starts):
        print("   ✔ Sức chứa tự hồi phục trên đường công khai, không chỉ trong bảng.")
    elif recovered:
        # Hồi phục MỘT PHẦN vẫn là hồi phục, nhưng in ✔ trơn ở đây là giấu mất phần chưa quay lại.
        print(f"   ~ Hồi phục MỘT PHẦN ({len(a.starts) - len(recovered)} mốc của A chưa được mời lại).")
        print("     Không tính là sai — `_pick_mixed` chỉ phát tối đa slots_offered và có thể ưu")
        print("     tiên mốc khác — nhưng bất biến CỨNG là dòng 'đang bị chiếm' ở trên, không phải dòng này.")
    else:
        print(f"   ✘ DB nói mốc đã trống nhưng `generate_slots` (HTTP {c.status}) không mời lại mốc")
        print("     nào của A — lệch giữa `_occupied` và `_pick_mixed`, hoặc chính lượt GET này hỏng.")
        failures.append(f"pha 4: mốc đã nhả nhưng không được mời lại (C: HTTP {c.status})")


# ══════════════════════════════════════════════════════════════════════════════════════════
# Dọn dẹp giữa chừng + kết luận
# ══════════════════════════════════════════════════════════════════════════════════════════


async def _release_holds_of(session: AsyncSession, app_ids: list[int]) -> int:
    """Nhả mọi chỗ đang giữ của các hồ sơ nêu tên, trả số hàng đã nhả.

    Đây là thao tác CỦA CÔNG CỤ, không phải hành vi hệ thống — báo cáo luôn nói rõ. Cần nó ở hai
    chỗ: sau pha 1 (pha đó cố tình chạy quá trần và ăn sạch lịch, không dọn thì pha 3/4 chỉ đo được
    "hết chỗ") và đầu pha 4 (cần lịch sạch để phép đo tất định). Dùng đúng
    `booking_service.release_holds` chứ không UPDATE thẳng bảng — *Booking boundary* trong AI_GUIDE.
    """
    total = 0
    for app_id in app_ids:
        total += await booking_service.release_holds(session, app_id)
    await session.commit()
    return total


def _not_proven() -> None:
    _banner("SCRIPT NÀY KHÔNG CHỨNG MINH ĐIỀU GÌ")
    for line in (
        "Không đo hệ thống dưới tải THẬT: không có CV/parser/ranker chạy song song. Trần thread "
        "pool + DB pool là việc của `loadtest_apply.py`; ở đây pool chỉ bị chạm qua các GET của pha 1.",
        "Không nói được gì về PROD: `BOOKING_*`, số instance, proxy, Neon autosuspend, và cấu hình "
        "rate-limit đều khác. Số ở đây là số của MỘT máy, MỘT tiến trình, MỘT cấu hình.",
        "Không kiểm nhiều TIẾN TRÌNH: advisory lock + partial unique index vẫn đúng khi scale ngang, "
        "nhưng bộ giữ nhịp email và rate-limiter là theo-tiến-trình nên sẽ KHÔNG còn đúng.",
        "Pha 2 dựng thế đua BẰNG TAY (chèn HELD trùng mốc). Nó chứng minh CHỐT CHẶN DB đúng, KHÔNG "
        "chứng minh tần suất đua ngoài đời — đường tự nhiên `generate_slots` vốn tránh đụng nhau.",
        "Pha 1 chạy MỘT bậc K, không ramp tăng dần. `--stagger` cho ra 'người thứ mấy nhận danh "
        "sách rỗng' đáng tin hơn nhiều so với chế độ đồng thời, nhưng vẫn là một bậc duy nhất.",
        "Pha 4 DỌN SẠCH hold trước khi đo để kết quả tất định. Nó chứng minh 'hold quá hạn thôi "
        "chiếm chỗ', KHÔNG chứng minh điều đó vẫn đúng khi lịch đang đông và các hold gối lên nhau.",
        "Không kiểm sweep SCH-3 (nhắc trước PV / nhắc chọn lịch / hết hạn) — đó là "
        "`tests/test_booking_db.py` với RUN_BOOKING_IT=1.",
        "Không kiểm giao diện `/booking/[token]` (đếm ngược hold, tự làm mới khi 409).",
    ):
        print(f"   • {line}")


# ══════════════════════════════════════════════════════════════════════════════════════════


def _parse_phases(raw: str) -> set[int]:
    if raw.strip().lower() in ("all", ""):
        return set(_ALL_PHASES)
    out: set[int] = set()
    for chunk in raw.split(","):
        part = chunk.strip()
        if not part:
            continue
        if not part.isdigit() or int(part) not in _ALL_PHASES:
            sys.exit(f"--phases: {part!r} không hợp lệ (chọn trong {','.join(map(str, _ALL_PHASES))}).")
        out.add(int(part))
    if not out:
        sys.exit("--phases rỗng.")
    return out


async def main() -> None:
    p = argparse.ArgumentParser(description="Load test đặt lịch phỏng vấn đồng thời (PRD §10b).")
    p.add_argument("--api", default="http://127.0.0.1:8000", help="Gốc API backend")
    p.add_argument("--viewers", type=int, default=20, help="Pha 1: số người CÙNG mở link đặt lịch")
    p.add_argument("--race", type=int, default=8, help="Pha 2: số người CÙNG chốt một khung giờ")
    p.add_argument("--stagger", type=float, default=0.0,
                   help="Pha 1: giãn mỗi người xem cách nhau N giây (0 = cùng lúc). "
                        ">0 để tìm BỨC TƯỜNG 'người thứ mấy nhận danh sách rỗng'")
    p.add_argument("--phases", default="all", help="Pha cần chạy, vd '0,1,2' (mặc định: tất cả)")
    p.add_argument("--max-hold-wait", type=float, default=90.0,
                   help="Pha 4: chờ tối đa bao nhiêu giây cho hold hết hạn (quá thì bỏ qua)")
    p.add_argument("--keep-holds", action="store_true",
                   help="KHÔNG nhả hold của pha 1 sau khi đo (giữ nguyên hiện trường để soi DB)")
    p.add_argument("--timeout", type=float, default=60.0, help="Timeout mỗi request (giây)")
    p.add_argument("--cleanup", action="store_true",
                   help="CHỈ xoá dữ liệu mang nhãn loadtest-booking rồi thoát")
    p.add_argument("--allow-remote", action="store_true",
                   help="Cho phép bắn tải vào host không phải localhost")
    p.add_argument("--allow-email", action="store_true",
                   help="Chấp nhận rằng backend có RESEND_API_KEY và SẼ gửi email thật ở pha 2/3")
    p.add_argument("--confirm", action="store_true",
                   help="BẮT BUỘC — xác nhận đã hiểu script GHI DỮ LIỆU THẬT và CHIẾM khung giờ thật")
    args = p.parse_args()

    # Kiểm HÌNH DẠNG tham số TRƯỚC mọi cổng an toàn: nó không gây hại gì, và gõ nhầm `--phases 9`
    # mà bị mắng về RESEND_API_KEY là kiểu thông báo lỗi khiến người ta đi sửa nhầm chỗ.
    if args.viewers < 1 or args.race < 2:
        sys.exit("--viewers phải >= 1 và --race phải >= 2 (một mình thì không có cuộc đua nào).")
    if args.stagger < 0:
        sys.exit("--stagger không được âm.")
    phases = _parse_phases(args.phases)

    db_host = urlsplit(settings.database_url.replace("postgresql+asyncpg://", "postgresql://")).hostname
    db_name = settings.database_url.rsplit("/", 1)[-1].split("?")[0]

    # `--cleanup` KHÔNG cần `--confirm`: nó chỉ gỡ đi đúng những hàng mang nhãn của script. Bắt xác
    # nhận cho thao tác AN TOÀN nhất chỉ dạy người dùng gõ `--confirm` theo phản xạ.
    if args.cleanup:
        print(f"Dọn dữ liệu nhãn {_TAG!r} trên DB {db_host}/{db_name} …")
        async with AsyncSessionLocal() as session:
            apps, jobs = await _delete_tagged(session)
        print(f"Đã xoá {apps} hồ sơ + {jobs} JD (booking/phiên/audit cascade theo FK).")
        await engine.dispose()
        return

    host = urlsplit(args.api).hostname or ""
    if host not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        sys.exit(f"Từ chối bắn tải vào {host!r} — thêm --allow-remote nếu CHỦ ĐÍCH muốn vậy.")
    if not args.confirm:
        sys.exit(
            "Cần --confirm. Script này GHI DỮ LIỆU THẬT vào DB trong .env (thường là Neon dev, KHÔNG\n"
            "phải localhost) và CHIẾM khung giờ phỏng vấn thật trong lúc chạy — ứng viên thật mở link\n"
            "cùng lúc sẽ thấy ít lựa chọn hơn. Đọc docstring đầu file trước khi chạy.\n"
            f"DB sẽ bị ghi: {db_host}/{db_name}"
        )
    if settings.resend_api_key and not args.allow_email:
        sys.exit(
            "RESEND_API_KEY đang có trong .env. Pha 2/3 đi qua `confirm_and_notify`/`cancel_by_candidate`\n"
            "nên backend SẼ gửi email thật tới các địa chỉ giả @example.invalid (hard bounce → hỏng uy\n"
            "tín người gửi). Chạy backend với RESEND_API_KEY rỗng, hoặc thêm --allow-email nếu CHỦ ĐÍCH.\n"
            "(Lưu ý: script đọc .env của CHÍNH NÓ — nếu backend chạy với env khác thì đây chỉ là suy đoán.)"
        )
    cfg = load_booking_config()
    needed = args.viewers + args.race + _REBOOK_APPS + _HOLD_APPS

    print("=" * 78)
    print(f"LOAD TEST ĐẶT LỊCH — pha {sorted(phases)} · {args.viewers} người xem · "
          f"{args.race} người đua chốt")
    print(f"API: {args.api}")
    print(f"DB : {db_host}/{db_name}   ← dữ liệu giả sẽ nằm ở ĐÂY")
    print("=" * 78)

    # Tiền kiểm hạn mức: chỉ POST mới tính vào xô `booking`, GET của pha 1 thì không (`_bucket`
    # chỉ siết `_BODY_METHODS`). Cộng đúng số POST script sẽ bắn ra.
    planned_posts = (args.race if 2 in phases else 0) + (2 if 3 in phases else 0)
    if settings.rate_limit_enabled and planned_posts > settings.rate_limit_public_max:
        print()
        print(f"   [!] Sẽ bắn {planned_posts} POST nhưng xô `booking` chỉ cho "
              f"{settings.rate_limit_public_max} lượt / "
              f"{settings.rate_limit_public_window_seconds:g}s / IP — pha 2 sẽ dính 429 và")
        print("       phép đo vô nghĩa. Khởi động backend với RATE_LIMIT_ENABLED=false, hoặc giảm --race.")

    failures: list[str] = []
    capacity = _report_capacity(cfg)

    limits = httpx.Limits(max_connections=max(args.viewers, args.race) + 10)
    async with (
        AsyncSessionLocal() as session,
        httpx.AsyncClient(timeout=args.timeout, limits=limits) as client,
    ):
        # ── Pha 0 ──────────────────────────────────────────────────────────────────────────
        if 0 in phases:
            _banner(f"PHA 0 — GIEO {needed} HỒ SƠ AWAITING_BOOKING + PHIÊN ĐẶT LỊCH")
            seeds = await _seed(session, needed)
            print(f"   JD {_JOB_TITLE!r} + {len(seeds)} hồ sơ. Token (dùng lại được cho --phases):")
            for app_id, token in seeds:
                print(f"     app={app_id:<6} {token}")
        else:
            seeds = await _load_seed(session)
            print(f"\n   (bỏ qua pha 0 — dùng lại {len(seeds)} seed đang có trong DB)")
        if len(seeds) < needed:
            sys.exit(
                f"Chỉ có {len(seeds)} seed nhưng cần {needed} "
                f"(--viewers {args.viewers} + --race {args.race} + {_REBOOK_APPS + _HOLD_APPS} cố định).\n"
                "Chạy lại KÈM pha 0, hoặc giảm --viewers/--race cho khớp seed cũ."
            )

        viewers = seeds[: args.viewers]
        racers = seeds[args.viewers : args.viewers + args.race]
        rebook_app, rebook_token = seeds[args.viewers + args.race]
        hold_trio = seeds[args.viewers + args.race + _REBOOK_APPS :][:_HOLD_APPS]

        # ── Pha 1 ──────────────────────────────────────────────────────────────────────────
        if 1 in phases:
            hold_seconds = await _phase_offers(
                client, args.api, cfg, viewers, capacity, args.stagger, failures
            )
            await _report_false_no_slots(session, cfg, [a for a, _ in seeds], hold_seconds, failures)
            if not args.keep_holds:
                freed = await _release_holds_of(session, [a for a, _ in viewers])
                print(f"\n   (công cụ nhả {freed} hold của pha 1 để pha 3/4 còn sức chứa mà đo — "
                      "đây KHÔNG phải hành vi hệ thống; dùng --keep-holds để giữ nguyên hiện trường)")

        # ── Pha 2 ──────────────────────────────────────────────────────────────────────────
        if 2 in phases:
            await _phase_race(client, args.api, session, cfg, racers, failures)

        # ── Pha 3 ──────────────────────────────────────────────────────────────────────────
        if 3 in phases:
            await _phase_rebook(client, args.api, session, cfg, rebook_app, rebook_token, failures)

        # ── Pha 4 ──────────────────────────────────────────────────────────────────────────
        if 4 in phases:
            await _phase_hold_expiry(
                client, args.api, session, cfg, [a for a, _ in seeds], hold_trio,
                args.max_hold_wait, failures,
            )

    _not_proven()

    _banner("KẾT LUẬN")
    if failures:
        print(f"   ✘ {len(failures)} BẤT BIẾN SAI:")
        for f in failures:
            print(f"     - {f}")
        print(f"\n   Dọn dữ liệu: … loadtest_booking.py --cleanup")
        await engine.dispose()
        sys.exit(1)
    print("   ✔ Mọi bất biến đã kiểm đều đúng.")
    print("   Dọn dữ liệu: … loadtest_booking.py --cleanup")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
