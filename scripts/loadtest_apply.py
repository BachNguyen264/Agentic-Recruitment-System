"""Load test — nhiều CV nộp CÙNG LÚC vào `/api/public/applications` (NFR-1, NFR-7).

Đo hai thứ TÁCH BẠCH nhau, vì chúng gãy ở hai chỗ khác nhau:
  1) TẦNG NHẬN (đồng bộ): backend trả 201 nhanh cỡ nào, bao nhiêu lượt dính 429/413/503.
  2) TẦNG XỬ LÝ (BackgroundTasks, bất đồng bộ): trong số hồ sơ ĐÃ NHẬN, bao nhiêu thật sự
     chạy xong pipeline — và bao nhiêu KẸT ở `SUBMITTED` (pipeline không chạy tới nơi mà cũng
     không được cứu về PENDING_REVIEW[error] ⇒ không audit, không ai biết). 201 KHÔNG có nghĩa
     là hồ sơ được xử lý.

BỐN CÁI BẪY ĐÃ VẤP — đọc trước khi tin bất kỳ con số nào script này in ra:

  (a) RATE-LIMIT TỰ ĐÁNH BẠI PHÉP ĐO. `/api/public/applications` nằm sau xô ghi công khai
      (`RATE_LIMIT_PUBLIC_MAX` lượt / `RATE_LIMIT_PUBLIC_WINDOW_SECONDS`, mặc định 20/giờ mỗi IP).
      Bắn 60 lượt từ một máy = 20 lượt được nhận + 40 lượt 429, và "40 lượt bị chặn trong 0.3s" nhìn
      hệt như "backend nhận rất nhanh". Đây KHÔNG phải phép đo thông lượng. Có 429 ⇒ script in băng
      rôn RUN INVALID và **thoát mã khác 0**. Muốn đo thật: khởi động lại đích với
      `RATE_LIMIT_ENABLED=false`. Cửa sổ TRƯỢT 1 giờ nên lần chạy THỨ HAI trong cùng giờ cũng dính.

  (b) CỬA SỔ THEO DÕI CHỈ 100 DÒNG. `GET /api/applications` gọi
      `list_applications(session, limit=100)` sắp `created_at DESC`, KHÔNG phân trang. Chạy >100 CV
      (hoặc DB đã có sẵn hồ sơ khác) là có id script tạo ra mà nó KHÔNG BAO GIỜ nhìn thấy — bản cũ
      lặng lẽ bỏ qua rồi vẫn in "không có hồ sơ kẹt". Nay đối soát theo TẬP ID đã tạo, TÍCH LUỸ qua
      mọi lượt hỏi (thấy dừng một lần là kết luận được, vì trạng thái không quay ngược), và ba xô in
      RIÊNG: chứng kiến dừng / rớt khỏi cửa sổ khi chưa dừng / chưa bao giờ thấy. Hai xô sau là
      KHÔNG BIẾT, không phải "ổn".

  (c) CV 1.5KB KHÔNG chạm tới trần RAM. Hạn CV là 10MB (`cv_storage.MAX_BYTES`); CV mặc định của
      script nặng ~1.5KB nên "nút thắt kế tiếp là RAM" (CLAUDE.md) không đời nào lộ ra. `--cv-kb N`
      đệm PDF lên cỡ thật.

  (d) "CHƯA CHẠM TRẦN" ≠ "CÒN DƯ SỨC". Hai chỗ từng in ra số trấn an nhưng sai:
      · Đích có HAI thread pool và HAI pool Postgres, tắc độc lập nhau. Chỉ đọc `executor.*` +
        `db_pool.*` là bỏ sót đúng cái pool mà đường NHẬN CV dùng (anyio) và pool mà LangGraph ghi
        checkpoint (psycopg) — xem `METRICS_KEYS`.
      · Bắn 2 CV/s vào hệ chịu được 10 CV/s thì đo ra 2 CV/s. Đó là nhịp do CHÍNH script đặt, không
        phải trần. Script chỉ gọi một con số là "TRẦN BỀN VỮNG" khi có ít nhất một ràng buộc chạm
        đáy; không có thì nó nói thẳng "CHƯA ĐO ĐƯỢC, đây là cận dưới".

CẢNH BÁO CHI PHÍ / TÁC DỤNG PHỤ — chạy với `ENABLE_LLM=true` là:
  - tốn tiền OpenAI thật (mỗi CV = 1 lượt parser + 1 embedding + 1 lượt ranker),
  - GỬI EMAIL THẬT qua Resend nếu JD bật gate auto-từ-chối/auto-mời hoặc có câu hỏi screener,
  - ghi hàng loạt dòng thật vào Neon.
Vì vậy script BẮT BUỘC `--confirm`, và từ chối chạy vào host không phải localhost trừ khi
có `--allow-remote`. Muốn đo riêng trần hạ tầng (pool/RAM/rate-limit) mà KHÔNG tốn tiền:
đặt `ENABLE_LLM=false` và dùng JD KHÔNG có câu hỏi screener, gate TẮT.

⚠ `ENABLE_LLM=false` STUB CẢ parser LẪN ranker ⇒ xoá sạch chỗ chiếm thread pool cần quan sát (parser
gọi OpenAI ĐỒNG BỘ qua `asyncio.to_thread`). Muốn giữ ĐÚNG đường code mà không tốn tiền thì đừng tắt
LLM, hãy ĐỔI ĐÍCH của nó sang `scripts/mock_openai.py`:

    uv run --directory apps/backend python ../../scripts/mock_openai.py --confirm
    OPENAI_API_BASE=http://127.0.0.1:9099/v1 make dev-backend

`ChatOpenAI` lẫn `OpenAIEmbeddings` đều đọc biến đó ⇒ KHÔNG phải sửa dòng code nào của app.

HAI CHẾ ĐỘ BẮN — trả lời hai câu hỏi KHÁC nhau:
  - MẶC ĐỊNH (đợt): `--total N --concurrency K` — N lượt ập vào cùng lúc. Đo sức HẤP THỤ một đợt.
  - `--ramp R` (nhịp đến): mỗi 1/R giây một CV, mở vòng — `--concurrency` KHÔNG gác cổng nữa. Đây mới
    là thứ phân biệt "đợt được hàng đợi nuốt gọn" với "nhịp bền vượt sức chứa": nếu hệ thống chậm hơn
    nhịp đến thì số việc đang bay PHÌNH liên tục thay vì đứng yên. Trần bền vững là con số cần.

Chạy:
    # 1) đo tầng nhận (nhớ tắt rate-limit ở đích, xem bẫy (a))
    uv run --directory apps/backend python ../../scripts/loadtest_apply.py \
        --job-id 1 --total 60 --concurrency 60 --confirm
    # 2) nhịp bền + soi tài nguyên nào bão hoà trước (cần tài khoản HR)
    ... --total 120 --ramp 2 --metrics-poll --watch 300 \
        --hr-email hr@example.com --hr-password '...'
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import statistics
import string
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:  # `fitz` chỉ nạp khi thật sự sinh PDF — giữ script khởi động nhanh.
    import fitz

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("Thiếu httpx: chạy qua `uv run --directory apps/backend python ...`")

# Console Windows mặc định cp1252 → MỌI dòng tiếng Việt (và khung `─`, băng rôn `!`) làm cả script
# nổ `UnicodeEncodeError`. Ở đây nó tệ hơn hẳn `--help` chết ngay: báo cáo chỉ in ra SAU khi đã bắn
# xong tải, nên một lần chạy có LLM thật (tốn tiền + gửi email thật) sẽ mất TRẮNG kết quả ở đúng
# dòng `print` đầu tiên. `errors="replace"` để terminal cổ vẫn in được thứ gì đó thay vì chết.
# Cùng idiom với `scripts/loadtest_booking.py` / `reset_demo_data.py`.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


# `application_service.list_applications` có `limit=100` CỐ ĐỊNH và KHÔNG phân trang. Hằng số này
# phải khớp con số đó: nó là lý do phép đối soát ở TẦNG XỬ LÝ tồn tại (xem bẫy (b) ở docstring).
WINDOW_LIMIT = 100

# Trạng thái pipeline CÒN ĐANG CHẠY (chưa dừng lại chờ người/chờ ứng viên). Mọi trạng thái KHÁC đều
# tính là "đã dừng" — kể cả `AWAITING_SCREENER`/`AWAITING_BOOKING`: lúc đó pipeline đã suspend và
# email đã ra khỏi hệ thống, tức phần việc mà load test đo ĐÃ XONG. Bản cũ thiếu `AWAITING_BOOKING`
# (thêm ở SCH-2) nên một hồ sơ được auto-mời không bao giờ đếm là xong ⇒ vòng lặp chạy hết `--watch`
# rồi báo sai.
RUNNING_STATUSES = frozenset({"SUBMITTED", "PARSING", "RANKING", "SCREENING", "SCHEDULING"})

# Bằng đúng `models/application.py::IN_FLIGHT_STATUSES` — hồ sơ đứng ở đây quá lâu là KẸT CÂM:
# pipeline không chạy tới nơi mà cũng KHÔNG được cứu về PENDING_REVIEW[error], nên không audit,
# không ai biết. Đây là thứ script tồn tại để bắt.
STUCK_STATUSES = frozenset({"SUBMITTED", "PARSING", "RANKING"})

# Đồng hồ đo bão hoà trong tiến trình (HR-only). Có thể CHƯA tồn tại trên đích → 404 là chuyện bình
# thường, không phải lỗi: khi đó chỉ mất phần "tài nguyên nào cạn trước", phần còn lại vẫn đo được.
METRICS_PATH = "/api/health/metrics"

# (đường đọc, nhãn tiếng Việt, các đường có thể chứa TRẦN của chỉ số đó). Trần lấy được thì mới nói
# được "đã chạm nóc"; không có thì chỉ in đỉnh thô — KHÔNG bịa ngưỡng.
#
# ⚠ PHẢI ĐỦ **HAI** THREAD POOL VÀ **HAI** POOL POSTGRES — đây là cái bẫy xanh-giả tệ nhất của công
# cụ này. `executor.*` là default executor của asyncio (parser gọi LLM đồng bộ, R2, Resend), nhưng
# đường NHẬN CV lại KHÔNG đi qua nó: `await file.read()` trên `SpooledTemporaryFile` đã tràn đĩa
# (>1MB ⇒ mọi CV thật) chạy qua thread pool của **anyio**. Tương tự, `db_pool` chỉ là pool asyncpg
# của SQLAlchemy; LangGraph ghi checkpoint sau MỖI node qua pool psycopg RIÊNG. Chỉ đọc hai ô đầu
# rồi kết luận "chưa chạm trần gì cả" là in ra con số TRẤN AN nhưng nói về pool khác — đã tái hiện
# được: mock trả `anyio_threads.borrowed = 40/40` và `checkpointer_pool.waiting = 4` mà bản trước
# vẫn kết luận "Không thấy chỉ số nào chạm trần".
METRICS_KEYS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    # KHÔNG lấy `db_pool.size` làm trần: đó là `pool_size` (5), còn trần THẬT là
    # `pool_size + max_overflow` (15). Nhận nhầm 5 làm trần thì 8 connection đang mượn hiện ra thành
    # "160% trần" — một cảnh báo CHẠM TRẦN sai, tệ hơn hẳn việc không có trần để so.
    ("db_pool.checked_out", "connection pool SQLAlchemy", ("db_pool.limit", "db_pool.max")),
    ("checkpointer_pool.checked_out", "connection pool checkpointer",
     ("checkpointer_pool.limit", "checkpointer_pool.max")),
    ("checkpointer_pool.waiting", "lượt CHỜ pool checkpointer", ()),
    ("executor.queue_depth", "việc xếp hàng ở executor asyncio", ()),
    ("anyio_threads.borrowed", "token thread pool anyio (đường NHẬN CV)", ("anyio_threads.total_tokens",)),
    ("anyio_threads.waiting", "lượt CHỜ thread pool anyio", ()),
    ("pipelines.in_flight", "pipeline đang bay", ("pipelines.limit", "pipelines.max")),
)

# Chỉ số dạng HÀNG ĐỢI: >0 ĐÃ LÀ bằng chứng bão hoà, không cần biết trần (có ai đó phải CHỜ thì tài
# nguyên đó đã hết). Ba hàng đợi này tắc ĐỘC LẬP với nhau — nhìn một cái rồi kết luận là sai.
QUEUE_PATHS: dict[str, str] = {
    "executor.queue_depth": "parser gọi OpenAI ĐỒNG BỘ qua asyncio.to_thread, dùng CHUNG executor "
                            "mặc định với R2 + Resend + checkpointer",
    "anyio_threads.waiting": "đường NHẬN CV (`await file.read()` trên file đã tràn đĩa) xếp hàng ở "
                             "thread pool anyio — KHÁC executor ở trên",
    "checkpointer_pool.waiting": "LangGraph ghi checkpoint sau MỖI node; pool psycopg này cạn thì "
                                 "pipeline treo trong khi db_pool vẫn báo rảnh",
}

# Sinh PDF đệm: chữ NGẪU NHIÊN (gần như không nén được) nên cỡ file ≈ cỡ text ⇒ ước lượng số trang
# đáng tin. Seed CỐ ĐỊNH để hai lần chạy ra file cùng cỡ — phép đo mới so sánh được với nhau.
_FILLER_SEED = 20260829
_FILLER_ALPHABET = string.ascii_letters + string.digits
_FILLER_FONTSIZE = 3  # chữ càng nhỏ càng nhiều dòng lọt vào một trang ⇒ ít trang ⇒ sinh nhanh.
_FILLER_LINE_CHARS = 190
_FILLER_LINES = 210  # `insert_text` CẮT ở đáy trang (~202 dòng ở cỡ chữ 3) — xin dư một chút.

# Tài liệu đệm được xây MỘT LẦN cho mỗi cỡ rồi ghép lại bằng `insert_pdf` (chép object, ~11ms) thay
# vì vẽ lại chữ cho từng CV (~1.6s/MB). Không cache thì riêng việc sinh CV đã chặn event loop lâu
# hơn cả phép đo — và một load test bị chính client làm nghẽn thì đo ra số của client.
_FILLER_CACHE: dict[int, fitz.Document] = {}


# ────────────────────────────────────────────────────────────────────────────────
# Sinh CV
# ────────────────────────────────────────────────────────────────────────────────


def _add_filler_page(doc: fitz.Document, rnd: random.Random, lines: int = _FILLER_LINES) -> int:
    """Một trang chữ ngẫu nhiên. KHÔNG phải nội dung CV — chỉ để file đạt cỡ thật.

    `lines` nhỏ hơn mặc định = trang VƠI, dùng cho trang cuối để bám sát chỉ tiêu: một trang đầy nặng
    ~37KB, nên nếu chỉ ghép trang đầy thì `--cv-kb` bị làm tròn theo bước 37KB (xin 1KB nhận 38KB).

    Trả về SỐ DÒNG THỰC SỰ vẽ được — `insert_text` CẮT ở đáy trang, nên xin 210 dòng chỉ nhận ~202.
    Con số này là cái chia đúng để quy ra "byte mỗi dòng"; lấy 210 là lệch 4% ngay từ đầu.
    """
    page = doc.new_page()
    body = "\n".join(
        "".join(rnd.choices(_FILLER_ALPHABET, k=_FILLER_LINE_CHARS)) for _ in range(max(1, lines))
    )
    return int(page.insert_text((10, 10), body, fontsize=_FILLER_FONTSIZE))


def _filler_doc(target_bytes: int) -> fitz.Document:
    """Tài liệu đệm ≲ `target_bytes`. Đo cỡ MỘT trang thật rồi mới nhân lên — không hằng số phép màu.

    Vì sao đo thay vì hằng số: cỡ một trang phụ thuộc phiên bản PyMuPDF, font nhúng và mức nén; ghim
    cứng "37KB/trang" là vài bản nữa `--cv-kb 10240` lặng lẽ sinh ra file 6MB và phép đo RAM sai mà
    không ai biết.

    LÀM TRÒN XUỐNG, không lên: `--cv-kb 10240` là đúng `cv_storage.MAX_BYTES`, nên dôi ra dù chỉ một
    trang là MỌI lượt nộp ăn 400 "CV không hợp lệ" — và bảng mã HTTP sẽ trông như backend hỏng chứ
    không như công cụ đo sinh sai file. Thà thiếu ~1 trang còn hơn hỏng cả lần chạy.
    """
    import fitz

    # THĂM DÒ trên tài liệu vứt đi: đo tại mốc 1 TRANG rồi 2 TRANG (KHÔNG phải mốc rỗng — `tobytes()`
    # trên tài liệu 0 trang ném `ValueError: cannot save with zero pages`). Hiệu hai mốc = chi phí
    # một trang; phần dôi ở mốc 1 trang = phần đầu tệp, hằng số theo số trang.
    probe = fitz.open()
    rnd = random.Random(_FILLER_SEED)
    full_lines = max(1, _add_filler_page(probe, rnd))
    one_page = len(probe.tobytes())
    _add_filler_page(probe, rnd)
    per_page = max(1, len(probe.tobytes()) - one_page)
    per_line = per_page / full_lines
    header = max(0, one_page - per_page)
    probe.close()

    # Dựng THUẦN CỘNG THÊM theo mô hình vừa đo, KHÔNG bao giờ gỡ trang: `delete_page()` chỉ tháo
    # trang khỏi cây trang, các object nội dung mồ côi VẪN nằm lại trong tệp, nên `tobytes()` sau
    # khi xoá KHÔNG hề nhỏ đi. Mọi cách "ghép dư rồi cắt bớt" vì thế đều đứng im ở cỡ đã vượt —
    # đúng cái bẫy làm `--cv-kb 64` cho ra file 38KB.
    doc = fitz.open()
    rnd = random.Random(_FILLER_SEED)
    # Chừa BIÊN AN TOÀN rồi mới chia trang. Mô hình tuyến tính ở trên bỏ qua phần bảng xref phình
    # theo số trang (~+0.04% ở mốc 10MB), mà `--cv-kb 10240` là ĐÚNG `cv_storage.MAX_BYTES`: dôi ra
    # vài KB là mọi lượt nộp ăn 400. Thà thiếu 0.5% còn hơn hỏng cả lần chạy.
    budget = target_bytes - header - max(per_line, target_bytes / 200)
    full_pages = max(0, int(budget // per_page))
    for _ in range(full_pages):
        _add_filler_page(doc, rnd)
    tail_lines = int((budget - full_pages * per_page) / per_line)
    if tail_lines >= 1:
        _add_filler_page(doc, rnd, lines=tail_lines)
    if doc.page_count == 0:
        # Chỉ tiêu nhỏ hơn cả một dòng (kể cả âm, khi riêng trang bìa đã vượt `--cv-kb`).
        _add_filler_page(doc, rnd, lines=1)
    return doc


def make_cv_pdf(index: int, cv_kb: int = 0) -> bytes:
    """PDF CV tổng hợp CÓ TEXT trích xuất được (không phải file rác) — để parser chạy thật.

    Dùng PyMuPDF (đã là dependency của backend). Mỗi CV khác nhau đôi chút để LLM không
    hưởng lợi từ cache và để phân biệt được trong dashboard.

    `cv_kb > 0` ghép thêm các trang đệm cho tới khi file đạt ~`cv_kb` KB, LUÔN LÀM TRÒN XUỐNG (hạn
    của hệ thống là 10MB = `cv_storage.MAX_BYTES`, nên `--cv-kb 10240` phải nằm DƯỚI mốc đó chứ
    không được chạm). ⚠ Phần đệm là TEXT TRÍCH XUẤT ĐƯỢC: `cv_reader._extract_pdf` đọc MỌI trang và
    `parser` KHÔNG cắt bớt, nên với `ENABLE_LLM=true` mỗi KB đệm đi thẳng vào prompt và thành tiền.
    Đệm chỉ dành cho lần chạy có LLM stub hoặc trỏ vào mock cục bộ.
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
    if cv_kb > 0:
        target = cv_kb * 1024
        if target not in _FILLER_CACHE:
            # Trừ đi cỡ TRANG BÌA trước khi đặt chỉ tiêu cho phần đệm — nếu không thì file cuối
            # cùng luôn nhỉnh hơn `--cv-kb` đúng bằng trang bìa, và ở mốc 10240 chừng đó là đủ vượt
            # `cv_storage.MAX_BYTES`.
            _FILLER_CACHE[target] = _filler_doc(target - len(doc.tobytes()))
        doc.insert_pdf(_FILLER_CACHE[target])
    data: bytes = doc.tobytes()
    doc.close()
    return data


# ────────────────────────────────────────────────────────────────────────────────
# TẦNG NHẬN
# ────────────────────────────────────────────────────────────────────────────────


@dataclass
class Gauge:
    """Đếm request ĐANG BAY phía client + giữ ĐỈNH.

    Đo ở client vì nó đúng cả khi `/api/health/metrics` vắng mặt, và vì đỉnh này là cách phát hiện
    chính CLIENT mới là nút thắt: chạm trần connection pool của httpx thì con số "thông lượng" đo
    được là của script, không phải của backend.
    """

    now: int = 0
    peak: int = 0

    def enter(self) -> None:
        self.now += 1
        self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        self.now -= 1


async def submit_one(
    client: httpx.AsyncClient,
    api: str,
    job_id: int,
    index: int,
    pdf: bytes,
    sem: asyncio.Semaphore | None,
    gauge: Gauge,
    slip: float = 0.0,
) -> dict[str, Any]:
    """Một lượt nộp. `sem=None` = chế độ mở vòng (`--ramp`): KHÔNG được chặn lượt đến.

    `slip` = lượt này rời bệ phóng TRỄ bao nhiêu so với lịch nhịp đến. Slip phình lên nghĩa là chính
    event loop của script đang bị bỏ đói ⇒ nhịp đến in ra không còn là nhịp đến thật.
    """
    async with sem if sem is not None else contextlib.nullcontext():
        gauge.enter()
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
                "index": index, "status": r.status_code, "latency": dt, "slip": slip,
                "application_id": body.get("application_id"),
                "detail": body.get("detail"),
            }
        except Exception as exc:  # noqa: BLE001 — timeout/connection reset cũng là kết quả tải
            return {"index": index, "status": 0, "latency": time.perf_counter() - t0, "slip": slip,
                    "application_id": None, "detail": f"{type(exc).__name__}: {exc}"}
        finally:
            gauge.leave()


def report_intake(results: list[dict[str, Any]], wall: float, ramp: float) -> tuple[list[int], int]:
    """In TẦNG NHẬN. Trả `(id đã nhận, số lượt bị rate-limit)` — số thứ hai quyết định phép đo có
    giá trị hay không (bẫy (a))."""
    codes = Counter(r["status"] for r in results)
    lats = sorted(r["latency"] for r in results)
    accepted = [r["application_id"] for r in results if r["status"] == 201 and r["application_id"]]
    blocked = codes.get(429, 0)

    print()
    print("── TẦNG NHẬN (đồng bộ) " + "─" * 54)
    print(f"   Tổng {len(results)} lượt nộp trong {wall:.1f}s ⇒ {len(results) / wall:.1f} lượt/giây")
    for code, n in sorted(codes.items()):
        label = {
            201: "NHẬN — đã tạo hồ sơ",
            429: "CHẶN rate-limit (xô ghi công khai: RATE_LIMIT_PUBLIC_MAX mỗi IP)",
            413: "CHẶN body quá lớn", 503: "LỖI lưu storage (hồ sơ đã bị xoá)",
            404: "JD không tồn tại/đã đóng", 400: "CV không hợp lệ", 0: "KHÔNG phản hồi (timeout/reset)",
        }.get(code, "")
        print(f"   HTTP {code or '---'}: {n:4d}  {label}")
    if lats:
        print(f"   Độ trễ nhận: p50 {lats[len(lats) // 2]:.2f}s | "
              f"p95 {lats[int(len(lats) * 0.95) - 1]:.2f}s | max {lats[-1]:.2f}s "
              f"| trung bình {statistics.mean(lats):.2f}s")
    if ramp > 0:
        slips = sorted(r["slip"] for r in results)
        print(f"   Trễ lịch bắn: p50 {slips[len(slips) // 2]:.3f}s | max {slips[-1]:.3f}s "
              f"(>0.5s ⇒ event loop của SCRIPT bị bỏ đói, nhịp đến in ra không còn thật)")
    for r in results:
        if r["status"] not in (201, 429) and r["detail"]:
            print(f"   ↳ ví dụ lỗi #{r['index']}: {r['status']} {r['detail'][:90]}")
            break
    # 201 mà KHÔNG đọc được `application_id` thì hồ sơ đó biến mất khỏi phép đối soát tầng xử lý,
    # và mọi tỉ lệ sau đó tính trên một tử số nhỏ hơn thực tế mà không ai biết. Đây là triệu chứng
    # duy nhất nếu `PublicSubmitResponse` đổi tên trường.
    if codes.get(201, 0) != len(accepted):
        print(f"   [!] {codes[201] - len(accepted)} lượt 201 KHÔNG kèm `application_id` — bị LOẠI khỏi")
        print("       phần đối soát TẦNG XỬ LÝ. Kiểm hình dạng phản hồi của /api/public/applications.")

    if blocked:
        print()
        print("   " + "!" * 72)
        print("   !!  PHÉP ĐO KHÔNG HỢP LỆ — rate-limit đã chặn %d/%d lượt." % (blocked, len(results)))
        print("   !!  Số 'lượt/giây' ở trên phần lớn là tốc độ TỪ CHỐI, không phải tốc độ NHẬN:")
        print("   !!  một lượt 429 bị middleware trả về trước khi chạm handler nên nhanh gấp bội.")
        print("   !!  SỬA: khởi động lại backend đích với RATE_LIMIT_ENABLED=false rồi chạy lại.")
        print("   !!  Cửa sổ là 1 GIỜ TRƯỢT ⇒ chạy lại ngay mà không tắt thì vẫn dính tiếp.")
        print("   " + "!" * 72)
    return accepted, blocked


# ────────────────────────────────────────────────────────────────────────────────
# Đồng hồ bão hoà
# ────────────────────────────────────────────────────────────────────────────────


def _dig(payload: object, path: str) -> float | None:
    """Đọc `a.b.c` trong JSON lồng nhau; thiếu khoá / sai kiểu → None (KHÔNG raise).

    Cố ý dễ dãi: `/api/health/metrics` do slice khác thêm và có thể đổi hình dạng. Phép đo mất một
    chỉ số thì chỉ mất chỉ số đó, không được làm hỏng cả lần chạy tải.
    """
    cur: Any = payload
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    if isinstance(cur, bool) or not isinstance(cur, (int, float)):
        return None
    return float(cur)


@dataclass
class MetricsPoller:
    """Bám `/api/health/metrics` suốt lần chạy để bắt ĐỈNH bão hoà.

    Vì sao phải poll dày chứ không đo một phát lúc kết thúc: bão hoà là hiện tượng TỨC THỜI. Pool DB
    cạn trong 2 giây rồi hồi lại — hỏi sau khi xong thì mọi đồng hồ đều về 0 và kết luận sẽ là "chưa
    chạm trần gì cả", đúng loại XANH GIẢ mà công cụ này sinh ra để chống.
    """

    client: httpx.AsyncClient
    api: str
    interval: float
    peaks: dict[str, float] = field(default_factory=dict)
    limits: dict[str, float] = field(default_factory=dict)
    samples: int = 0
    status: str = "chưa chạy"
    _stop: asyncio.Event = field(default_factory=asyncio.Event)

    async def run(self) -> None:
        # Một lớp `try` bao TRỌN vòng lặp: poller là thứ phụ trợ, nó hỏng thì phép đo tải vẫn phải
        # chạy tiếp và vẫn phải in báo cáo. Không có lớp này thì một lỗi lạ trong poller nổ ra ở
        # `await poll_task` trong khối `finally` của main — nuốt mất luôn kết quả đã đo xong.
        try:
            await self._loop()
        except Exception as exc:  # noqa: BLE001
            self.status = f"poller lỗi ({type(exc).__name__}: {exc}) — bỏ qua phần đo tài nguyên"

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                r = await self.client.get(f"{self.api}{METRICS_PATH}")
            except Exception as exc:  # noqa: BLE001 — poller KHÔNG được giết lần chạy tải
                self.status = f"lỗi mạng ({type(exc).__name__}) — dừng theo dõi"
                return
            if r.status_code == 404:
                self.status = f"đích CHƯA CÓ {METRICS_PATH} (404) — bỏ qua phần đo tài nguyên"
                return
            if r.status_code in (401, 403):
                self.status = f"HTTP {r.status_code} — endpoint là HR-only, cần --hr-email/--hr-password đúng"
                return
            if r.status_code != 200:
                self.status = f"HTTP {r.status_code} — bỏ qua phần đo tài nguyên"
                return
            try:
                payload = r.json()
            except ValueError:
                self.status = "phản hồi không phải JSON — bỏ qua phần đo tài nguyên"
                return

            self.samples += 1
            self.status = "ok"
            for path, _label, limit_paths in METRICS_KEYS:
                value = _dig(payload, path)
                if value is not None:
                    self.peaks[path] = max(self.peaks.get(path, 0.0), value)
                for lp in limit_paths:
                    found = _dig(payload, lp)
                    if found is not None:
                        self.limits[path] = found
                        break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), self.interval)

    def stop(self) -> None:
        self._stop.set()

    def report(self) -> None:
        print()
        print("── TÀI NGUYÊN (đỉnh trong lúc chạy) " + "─" * 41)
        if self.status != "ok":
            print(f"   [!] Không đo được: {self.status}")
            return
        print(f"   {self.samples} mẫu, mỗi {self.interval:.2f}s")
        for path, label, _ in METRICS_KEYS:
            if path not in self.peaks:
                print(f"   {path:29s} —      (đích không trả chỉ số này)")
                continue
            limit = self.limits.get(path)
            suffix = f" / {limit:.0f} trần" if limit else ""
            pct = f"  ⇒ {self.peaks[path] / limit * 100:.0f}% trần" if limit else ""
            print(f"   {path:29s} đỉnh {self.peaks[path]:.0f}{suffix}   {label}{pct}")
        print(f"   ⚠ Đây là ĐỈNH LẤY MẪU mỗi {self.interval:.2f}s, không phải đỉnh thật: một cơn "
              "bão hoà ngắn hơn")
        print("     khoảng lấy mẫu lọt qua khe và hiện ra thành 0. Đỉnh 0 = 'không bắt được', "
              "KHÔNG phải 'không có'.")


# ────────────────────────────────────────────────────────────────────────────────
# TẦNG XỬ LÝ
# ────────────────────────────────────────────────────────────────────────────────


@dataclass
class WatchResult:
    """Kết quả đối soát. Ba xô TÁCH BẠCH — gộp lại là tái sinh đúng lỗi XANH GIẢ ở bẫy (b)."""

    verified: dict[int, str] = field(default_factory=dict)  # thấy ở lượt hỏi CUỐI → biết chắc
    dropped: set[int] = field(default_factory=set)          # từng thấy rồi rớt khỏi cửa sổ 100 dòng
    never_seen: set[int] = field(default_factory=set)       # KHÔNG BAO GIỜ lọt vào cửa sổ
    settled: int = 0
    stuck: int = 0
    elapsed: float = 0.0
    ran: bool = False
    # Lượt hỏi trạng thái GÃY (401 vì phiên hết hạn, 500, mất mạng). Phải giữ RIÊNG: không có nó thì
    # mọi id thành "chưa bao giờ thấy" và báo cáo đổ tội cho cửa sổ 100 dòng — chẩn đoán sai hoàn
    # toàn, và người đọc sẽ đi thu nhỏ đợt chạy trong khi thứ hỏng là đăng nhập.
    api_error: str | None = None
    # Vòng lặp kết thúc vì HẾT GIỜ `--watch` chứ không phải vì mọi hồ sơ đã dừng ⇒ nhịp xử lý đo
    # được chỉ là CẬN DƯỚI (hàng đợi chưa rút hết).
    timed_out: bool = False

    @property
    def unverifiable(self) -> int:
        return len(self.dropped) + len(self.never_seen)


async def watch_processing(
    client: httpx.AsyncClient, api: str, ids: list[int], seconds: int, interval: float
) -> WatchResult:
    """Theo dõi trạng thái CHỈ các hồ sơ vừa nộp, ĐỐI SOÁT theo tập id đã tạo (không theo cửa sổ).

    ⚠ CHÍNH VÒNG LẶP NÀY CŨNG LÀ TẢI: `GET /api/applications` chạy `require_hr` (một lượt đọc DB) +
    `list_applications` + `no_slot_application_ids` rồi tuần tự hoá tới 100 dòng KÈM `parsed_data`.
    Tức mỗi lượt hỏi mượn một connection từ ĐÚNG cái pool đang được đo. `interval` nhỏ đi thì `elapsed`
    bớt bị làm tròn (xem KẾT LUẬN) nhưng nhiễu tăng lên — 10s là chỗ đứng giữa, đừng hạ xuống dưới
    vài giây khi đang đo pool.
    """
    out = WatchResult(ran=True)
    wanted = set(ids)
    ever_seen: set[int] = set()
    # Id ĐÃ TỪNG được nhìn thấy ở một trạng thái đã dừng, TÍCH LUỸ qua mọi lượt hỏi. Sạch về mặt
    # nghiệp vụ: `IN_FLIGHT_STATUSES` (SUBMITTED/PARSING/RANKING) là tập DUY NHẤT được phép ghi đè,
    # nên không trạng thái nào quay NGƯỢC lại "đang chạy" — thấy dừng một lần là dừng vĩnh viễn.
    # Không tích luỹ thì một hồ sơ đã xong nhưng bị đẩy khỏi cửa sổ 100 dòng lại rơi vào ô "không
    # kết luận được", và cả lần chạy (tốn tiền LLM thật) bị vứt đi dù dữ liệu đã đủ. Đã tái hiện:
    # 95 CV, mọi hồ sơ đều được CHỨNG KIẾN dừng, mà bản trước vẫn báo "60 hồ sơ không đối soát được".
    settled_ids: set[int] = set()
    latest: dict[int, str] = {}

    print()
    print("── TẦNG XỬ LÝ (BackgroundTasks) " + "─" * 45)
    t0 = time.perf_counter()
    window_saturated = False
    while time.perf_counter() - t0 < seconds:
        try:
            rr = await client.get(f"{api}/api/applications")
        except Exception as exc:  # noqa: BLE001 — mất mạng giữa chừng cũng phải báo cáo được
            out.api_error = f"{type(exc).__name__}: {exc}"
            print(f"   [!] GET /api/applications gãy: {out.api_error}")
            break
        if rr.status_code != 200:
            out.api_error = f"HTTP {rr.status_code}"
            print(f"   [!] GET /api/applications → {rr.status_code}"
                  + ("  (phiên HR hết hạn giữa chừng?)" if rr.status_code in (401, 403) else ""))
            break
        try:
            rows = rr.json()
            latest = {a["id"]: a["status"] for a in rows if a["id"] in wanted}
        except Exception as exc:  # noqa: BLE001 — `ApplicationRead` đổi tên trường là KeyError ở đây
            # Cùng lý do với nhánh mạng ở trên: nổ tại đây là mất TOÀN BỘ báo cáo của một lần chạy
            # đã tốn tiền LLM. Ghi lại rồi in như một lượt hỏi gãy.
            out.api_error = f"phản hồi lạ ({type(exc).__name__}: {exc})"
            print(f"   [!] GET /api/applications trả hình dạng không đọc được: {out.api_error}")
            break
        window_saturated = window_saturated or len(rows) >= WINDOW_LIMIT
        ever_seen |= set(latest)

        settled_ids |= {i for i, s in latest.items() if s not in RUNNING_STATUSES}

        counts = Counter(latest.values())
        missing = len(wanted) - len(latest)
        print(f"   t+{time.perf_counter() - t0:5.0f}s  "
              + "  ".join(f"{s}={n}" for s, n in sorted(counts.items()))
              + f"   [dừng {len(settled_ids)}/{len(wanted)}"
              + (f", ngoài cửa sổ {missing}]" if missing else "]"))
        # Chỉ được coi là xong khi MỌI id đã tạo đều được CHỨNG KIẾN dừng. Bản cũ so `done` với
        # `len(wanted)` trong khi `done` chỉ đếm được các dòng lọt cửa sổ ⇒ id vô hình vừa không
        # chặn được vòng lặp vừa không bao giờ bị báo cáo.
        if len(settled_ids) == len(wanted):
            break
        await asyncio.sleep(interval)
    else:
        # Vòng `while` cạn điều kiện = HẾT `--watch` mà chưa mọi hồ sơ dừng. `for/while ... else`
        # chỉ chạy khi KHÔNG `break`, nên nhánh này phân biệt đúng "hết giờ" với "đã xong".
        out.timed_out = True

    out.elapsed = time.perf_counter() - t0
    out.verified = latest
    out.settled = len(settled_ids)
    out.never_seen = wanted - ever_seen
    # RỚT KHỎI CỬA SỔ KHI CHƯA KỊP THẤY DỪNG — chỉ NHỮNG hồ sơ này mới là không kết luận được. Đã
    # thấy dừng rồi mới rớt thì vẫn kết luận được (trạng thái không quay ngược).
    out.dropped = (ever_seen - set(latest)) - settled_ids
    out.stuck = sum(1 for _i, s in latest.items() if s in STUCK_STATUSES)
    running_now = len(latest) - len(set(latest) & settled_ids)

    print()
    print(f"   Chứng kiến DỪNG: {out.settled:4d}/{len(wanted)}  (ở BẤT KỲ lượt hỏi nào — "
          "trạng thái không quay ngược)")
    print(f"     ↳ còn chạy  : {running_now:4d}  (có mặt ở lượt hỏi cuối, chưa dừng)")
    print(f"     ↳ KẸT CÂM   : {out.stuck:4d}  (SUBMITTED/PARSING/RANKING)")
    print(f"   KHÔNG kết luận: {out.unverifiable:4d}  "
          f"(rớt khỏi cửa sổ khi chưa dừng {len(out.dropped)} · chưa bao giờ thấy "
          f"{len(out.never_seen)})")

    if out.unverifiable:
        print()
        print(f"   [!] {out.unverifiable} hồ sơ KHÔNG KẾT LUẬN ĐƯỢC — chúng KHÔNG phải 'ổn'.")
        if out.api_error:
            # Nguyên nhân là lượt HỎI gãy, KHÔNG phải cửa sổ hẹp. In nhầm nguyên nhân ở đây là đẩy
            # người đọc đi thu nhỏ đợt chạy (tốn thêm một lượt LLM có phí) cho một lỗi đăng nhập.
            print(f"       Nguyên nhân: lượt hỏi trạng thái GÃY ({out.api_error}) — vòng theo dõi")
            print("       dừng sớm, KHÔNG phải do cửa sổ 100 dòng. Kiểm --hr-email/--hr-password và")
            print("       hạn phiên (JWT_EXPIRY_MINUTES) rồi chạy lại.")
        else:
            print(f"       `GET /api/applications` = `list_applications(limit={WINDOW_LIMIT})` sắp theo")
            print("       created_at DESC, KHÔNG phân trang ⇒ chỉ nhìn thấy tối đa "
                  f"{WINDOW_LIMIT} dòng MỚI NHẤT toàn hệ thống.")
            if window_saturated:
                print(f"       Cửa sổ ĐÃ ĐẦY ({WINDOW_LIMIT} dòng) trong lần chạy này — đúng nguyên nhân.")
            print(f"       Cách xử: chạy đợt ≤ {WINDOW_LIMIT} hồ sơ trên DB sạch, hoặc kiểm từng id bằng")
            print("       `GET /api/applications/{id}`, hoặc soi thẳng Postgres.")
    if out.stuck:
        print()
        print(f"   [!] {out.stuck} hồ sơ còn ở trạng thái trung gian sau {out.elapsed:.0f}s.")
        print("       Nghĩa là: pipeline CHƯA chạy xong, hoặc đã chết mà không kịp ghi")
        print("       PENDING_REVIEW[error]. Từ hardening tải, TOÀN BỘ thân `process_application`")
        print("       nằm trong một `try` nên lỗi thường được cứu về PENDING_REVIEW[error]; hồ sơ ĐỨNG")
        print("       YÊN ở đây là dấu hiệu nặng hơn: BackgroundTask chưa tới lượt chạy, tiến trình")
        print("       bị khởi động lại, hoặc chính đường cứu hộ cũng không mượn nổi connection.")
        print("       ⚠ Lưới đối soát `stuck_applications` chỉ quét sau "
              "STUCK_APPLICATION_TIMEOUT_MINUTES (30) —")
        print("       ngắn hơn thế thì 'kẹt' ở đây có thể chỉ là 'chưa xong'. Nâng --watch để phân biệt.")
    elif not out.unverifiable and out.settled == len(wanted):
        print()
        print("   Tất cả hồ sơ ĐÃ ĐỐI SOÁT theo id và đều tới trạng thái dừng — không có hồ sơ kẹt câm.")
    return out


# ────────────────────────────────────────────────────────────────────────────────
# KẾT LUẬN
# ────────────────────────────────────────────────────────────────────────────────


def collect_constraints(
    args: argparse.Namespace, watch: WatchResult, poller: MetricsPoller | None, slip_max: float,
) -> list[str]:
    """Các RÀNG BUỘC ĐÃ CHẠM, mỗi cái một dòng. RỖNG = không thấy gì bão hoà.

    Tách khỏi phần in vì cái danh sách này quyết định được phép GỌI con số thông lượng là "TRẦN" hay
    chỉ là "cận dưới": bắn 2 CV/s vào một hệ chịu được 10 CV/s thì đo ra 2 CV/s — gọi đó là trần là
    chép nhịp bắn của chính mình vào báo cáo rồi đặt tên khác. Chỉ khi có ÍT NHẤT một ràng buộc chạm
    đáy thì con số mới là trần.
    """
    out: list[str] = []
    # Client tự làm nút thắt: KHÔNG kiểm bằng trần connection nữa. `httpx.Limits` được đặt RỘNG HƠN
    # số lượt tối đa có thể đồng thời (`ceiling + 10`), nên "chạm trần connection" là điều kiện KHÔNG
    # BAO GIỜ xảy ra — bản trước so `gauge.peak >= ceiling` với `ceiling` là `--total`, tức nó thật ra
    # kêu lên khi BACKEND chậm (mọi lượt cùng bay), rồi đổ tội cho công cụ. Dấu hiệu ĐÚNG của client
    # bị bỏ đói là TRỄ LỊCH BẮN: event loop không kịp phóng lượt tiếp theo đúng nhịp.
    if args.ramp > 0 and slip_max > 0.5:
        out.append(f"     · CHÍNH SCRIPT bị bỏ đói — trễ lịch bắn tới {slip_max:.2f}s, nhịp đến THẬT "
                   f"thấp hơn {args.ramp:g} CV/s đã đặt. Bắn từ máy khác / giảm --cv-kb rồi đo lại.")
    if poller is not None and poller.status == "ok":
        for path, label, _ in METRICS_KEYS:
            peak = poller.peaks.get(path)
            if peak is None:
                continue
            limit = poller.limits.get(path)
            if limit and peak >= limit:
                out.append(f"     · CHẠM TRẦN — {label}: {peak:.0f}/{limit:.0f} ({path}).")
            elif path in QUEUE_PATHS and peak > 0:
                out.append(f"     · CÓ XẾP HÀNG — {label}: đỉnh {peak:.0f} ({path})\n"
                           f"       ↳ {QUEUE_PATHS[path]}.")
    if watch.stuck:
        out.append(f"     · {watch.stuck} hồ sơ còn đứng ở trạng thái trung gian — đọc cảnh báo ở\n"
                   "       TẦNG XỬ LÝ trước khi kết luận là đã vượt sức chứa.")
    return out


def report_conclusion(
    args: argparse.Namespace, accepted: int, blocked: int, wall: float,
    watch: WatchResult, poller: MetricsPoller | None, gauge: Gauge, slip_max: float,
    first_error: str | None,
) -> None:
    """Phát biểu THÔNG LƯỢNG BỀN + ràng buộc quan sát được. Chỉ nói những gì ĐO ĐƯỢC."""
    print()
    print("── KẾT LUẬN " + "─" * 65)

    if accepted == 0 and not blocked:
        # Không một hồ sơ nào vào được hệ thống ⇒ chẳng có gì để kết luận. Nói thẳng thay vì in
        # "0.00 CV/s" kèm một mục "ràng buộc quan sát được" — con số 0 đó trông y như một phép đo.
        print("   KHÔNG hồ sơ nào được nhận (0 lượt 201) ⇒ KHÔNG có phép đo nào ở đây.")
        if first_error:
            print(f"   Lỗi đầu tiên: {first_error}")
        print("   Kiểm: backend đã chạy chưa · --api đúng host/cổng chưa · --job-id có phải JD đang")
        print("   OPEN không (JD đóng/sai id ⇒ 404 cho MỌI lượt).")
        return

    if blocked:
        print("   THÔNG LƯỢNG: KHÔNG ĐO ĐƯỢC — rate-limit đã làm hỏng lần chạy (xem băng rôn trên).")
        print("   Ràng buộc quan sát được: RATE_LIMIT_PUBLIC_MAX, tức một tham số cấu hình, KHÔNG")
        print("   phải trần hạ tầng. Tắt nó rồi chạy lại thì mới bắt đầu đo được thứ cần đo.")
        return

    # Danh sách ràng buộc phải có TRƯỚC khi in thông lượng: nó quyết định được gọi con số đó là
    # "trần" hay chỉ là "cận dưới".
    constraints = collect_constraints(args, watch, poller, slip_max)

    if args.ramp > 0:
        print(f"   Nhịp đến ĐẶT     : {args.ramp:.2f} CV/s trong {args.total / args.ramp:.0f}s "
              f"({args.total} CV, mở vòng)")
    print(f"   Nhịp NHẬN đo được: {accepted / wall:.2f} CV/s  ({accepted} lượt 201 / {wall:.1f}s, "
          f"đỉnh {gauge.peak} lượt cùng bay)")

    if not watch.ran:
        print("   Nhịp XỬ LÝ       : không đo (thiếu --watch + tài khoản HR)")
        print("   ⇒ Chưa kết luận được trần bền vững: 201 chỉ nghĩa là ĐÃ NHẬN, không phải ĐÃ XỬ LÝ.")
    elif watch.unverifiable:
        # Mẫu số là số hồ sơ ĐƯỢC NHẬN, không phải `--total`: lượt nộp hỏng chưa bao giờ vào hệ
        # thống nên không nằm trong phép đối soát.
        print(f"   Nhịp XỬ LÝ       : KHÔNG ĐO ĐƯỢC — {watch.unverifiable}/{accepted} hồ sơ không")
        print("                      đối soát được (xem TẦNG XỬ LÝ). Không chia trên một tử số thiếu.")
    else:
        # MẪU SỐ TÍNH TỪ LƯỢT NỘP ĐẦU TIÊN, không phải từ lúc bắt đầu theo dõi. Pipeline chạy NGAY
        # khi hồ sơ đầu vào, tức phần lớn việc đã xong trước khi vòng theo dõi mở mắt — chia cho
        # riêng `watch.elapsed` là chia một tử số ĐẦY ĐỦ cho một mẫu số CỤT. Đã tái hiện: bắn 20 CV
        # ở nhịp 4/s vào đích xử lý 3s/CV, bản trước in "2.00 hồ sơ/s" rồi gọi đó là TRẦN BỀN VỮNG,
        # trong khi đích chưa hề bão hoà; cực đoan hơn, nếu mọi hồ sơ dừng xong trước lượt hỏi đầu
        # tiên thì `elapsed ≈ 0.05s` và con số in ra là hàng nghìn hồ sơ/s.
        span = wall + watch.elapsed
        rate = watch.settled / span if span > 0 else 0.0
        if watch.settled == 0:
            # "0.00 hồ sơ/s" TRÔNG như một phép đo ("hệ thống xử lý được 0 CV mỗi giây") trong khi
            # nó chỉ có nghĩa "chưa ai kịp xong". Một CV thật mất ~34s (parser ~9s + ranker ~25s),
            # nên --watch ngắn hơn thế thì con số 0 là tất yếu, không phải kết quả.
            print(f"   Nhịp XỬ LÝ       : KHÔNG ĐO ĐƯỢC — 0 hồ sơ kịp dừng trong {span:.0f}s.")
            print("                      Một CV thật mất ~34s (parser ~9s + ranker ~25s) ⇒ đặt")
            print("                      --watch rộng hơn NHIỀU lần con số đó rồi đo lại.")
        else:
            print(f"   Nhịp XỬ LÝ đo được: {rate:.2f} hồ sơ/s  ({watch.settled} hồ sơ tới trạng thái "
                  "dừng")
            print(f"                       trong {span:.0f}s kể từ lượt nộp ĐẦU TIÊN; sai số ±"
                  f"{args.watch_interval:g}s do nhịp hỏi)")
            if watch.timed_out:
                print(f"   ⚠ Hết {args.watch} giây --watch mà hàng đợi CHƯA rút xong ⇒ con số trên là "
                      "CẬN")
                print("     DƯỚI của nhịp xử lý, không phải nhịp ổn định. Nâng --watch rồi đo lại.")
            if constraints:
                print(f"   ⇒ TRẦN BỀN VỮNG quan sát được: ~{min(rate, accepted / wall):.2f} hồ sơ/s "
                      "(khâu chậm hơn quyết định).")
            else:
                # KHÔNG được gọi là trần: không tài nguyên nào chạm đáy nghĩa là hệ thống chưa hề bị
                # ép tới giới hạn, và ở chế độ --ramp con số này chính là nhịp do script tự đặt.
                print(f"   ⇒ TRẦN BỀN VỮNG: CHƯA ĐO ĐƯỢC. Hệ thống nuốt trọn "
                      f"{min(rate, accepted / wall):.2f} hồ sơ/s mà")
                print("     KHÔNG ràng buộc nào chạm đáy ⇒ đây là CẬN DƯỚI (≥), KHÔNG phải trần.")

    print()
    print("   Ràng buộc quan sát được:")
    for line in constraints:
        print(line)
    if poller is None and args.metrics_poll:
        print("     · (ĐÃ bật --metrics-poll nhưng không đăng nhập được HR ⇒ không đo được tài nguyên)")
    elif poller is None:
        print("     · (chưa bật --metrics-poll ⇒ không biết tài nguyên nào cạn trước)")
    elif poller.status != "ok":
        print(f"     · (không đo được tài nguyên: {poller.status})")
    if not constraints:
        print("     · Không thấy chỉ số nào chạm trần ⇒ nhịp này CHƯA phải điểm bão hoà. Tăng")
        print("       --ramp cho tới khi một dòng cảnh báo ở trên xuất hiện.")


# ────────────────────────────────────────────────────────────────────────────────


async def _login_hr(api: str, email: str, password: str, timeout: float) -> httpx.AsyncClient | None:
    """Đăng nhập HR, trả client GIỮ COOKIE (dùng chung cho watch + metrics)."""
    client = httpx.AsyncClient(timeout=timeout)
    r = await client.post(f"{api}/api/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        print(f"\n   [!] Đăng nhập HR thất bại ({r.status_code}) — bỏ qua tầng xử lý + đo tài nguyên.")
        await client.aclose()
        return None
    return client


async def _run_burst(
    client: httpx.AsyncClient, args: argparse.Namespace, bodies: list[bytes], gauge: Gauge
) -> list[dict[str, Any]]:
    sem = asyncio.Semaphore(args.concurrency)
    return list(await asyncio.gather(
        *(submit_one(client, args.api, args.job_id, i, bodies[i], sem, gauge)
          for i in range(args.total))
    ))


async def _run_ramp(
    client: httpx.AsyncClient, args: argparse.Namespace, bodies: list[bytes], gauge: Gauge
) -> list[dict[str, Any]]:
    """Bắn theo NHỊP ĐẾN cố định, MỞ VÒNG — không semaphore.

    Semaphore ở đây sẽ biến phép đo thành vòng KÍN: lượt đến bị hoãn cho tới khi có chỗ, nên hệ
    thống quá tải lại hiện ra thành "nhịp đến thấp đi" thay vì "việc đang bay phình lên". Đúng thứ
    cần nhìn thấy lại bị chính công cụ đo giấu đi.
    """
    tasks: list[asyncio.Task[dict[str, Any]]] = []
    t0 = time.perf_counter()
    for i in range(args.total):
        due = t0 + i / args.ramp
        delay = due - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        tasks.append(asyncio.create_task(
            submit_one(client, args.api, args.job_id, i, bodies[i], None, gauge,
                       slip=time.perf_counter() - due)
        ))
    return list(await asyncio.gather(*tasks))


async def main() -> None:
    p = argparse.ArgumentParser(description="Load test nộp CV đồng thời (NFR-1).")
    p.add_argument("--api", default="http://127.0.0.1:8000", help="Gốc API backend")
    p.add_argument("--job-id", type=int, required=True, help="ID của JD đang OPEN")
    p.add_argument("--total", type=int, default=60, help="Tổng số CV nộp")
    p.add_argument("--concurrency", type=int, default=60, help="Số lượt nộp song song (chế độ đợt)")
    p.add_argument("--ramp", type=float, default=0.0,
                   help="Nhịp đến CV/giây (mở vòng). >0 ⇒ bỏ chế độ đợt, --concurrency hết tác dụng")
    p.add_argument("--cv-kb", type=int, default=0,
                   help="Đệm PDF lên ~N KB (0 = không đệm, ~1.5KB). Hạn hệ thống 10MB = 10240")
    p.add_argument("--client-ram-mb", type=int, default=512,
                   help="Trần RAM cho các CV dựng sẵn ở CLIENT; vượt thì từ chối chạy")
    p.add_argument("--timeout", type=float, default=60.0, help="Timeout mỗi request (giây)")
    p.add_argument("--hr-email", default="", help="Email HR (để theo dõi tầng xử lý)")
    p.add_argument("--hr-password", default="", help="Mật khẩu HR")
    p.add_argument("--watch", type=int, default=0, help="Theo dõi tầng xử lý trong N giây")
    p.add_argument("--watch-interval", type=float, default=10.0,
                   help="Nhịp hỏi trạng thái (giây). Nhỏ hơn = mẫu số nhịp xử lý bớt bị làm tròn, "
                        "nhưng MỖI lượt hỏi mượn một connection từ chính pool đang đo")
    p.add_argument("--metrics-poll", action="store_true",
                   help=f"Bám {METRICS_PATH} suốt lần chạy để bắt đỉnh bão hoà (cần tài khoản HR)")
    p.add_argument("--metrics-interval", type=float, default=0.25,
                   help="Nhịp poll đồng hồ bão hoà (giây)")
    p.add_argument("--allow-remote", action="store_true", help="Cho phép bắn vào host không phải localhost")
    p.add_argument("--allow-email", action="store_true",
                   help="Cho phép chạy khi RESEND_API_KEY có giá trị (sẽ gửi email THẬT)")
    p.add_argument("--confirm", action="store_true", help="BẮT BUỘC — xác nhận đã hiểu chi phí/email thật")
    args = p.parse_args()

    host = urlsplit(args.api).hostname or ""
    is_local = host in ("127.0.0.1", "localhost", "::1")
    if not is_local and not args.allow_remote:
        sys.exit(f"Từ chối bắn tải vào {host!r} — thêm --allow-remote nếu CHỦ ĐÍCH muốn vậy.")

    # Chốt host CHỈ nói về nơi nhận HTTP, KHÔNG nói gì về DB/Resend mà BACKEND đang cắm vào —
    # `--api 127.0.0.1` vẫn ghi thẳng vào Neon prod nếu `.env` trỏ vào đó. Đây là cùng lý do
    # `reset_demo_data` phải in header môi trường. In ra để người chạy ĐỌC rồi mới gõ --confirm.
    try:
        from app.core.config import settings as _s

        _tail = (_s.database_url or "").rsplit("@", 1)[-1]
        db_target = _tail.split("?", 1)[0] or "(không rõ)"
        has_email = bool((_s.resend_api_key or "").strip())
    except Exception:  # noqa: BLE001 — chạy ngoài venv backend thì vẫn phải bắn được
        db_target, has_email = "(không đọc được .env)", False

    print("== Đích của lần đo này — ĐỌC TRƯỚC KHI GÕ --confirm ==")
    print(f"  HTTP  : {args.api}")
    if is_local:
        print(f"  DB    : {db_target}   (SUY ĐOÁN từ .env của CHÍNH script — không phải của backend)")
    else:
        # In host local lúc đang bắn vào Render là trấn an GIẢ, tệ hơn không in gì.
        print("  DB    : đích ở XA — .env của script KHÔNG nói gì về DB mà backend đó đang dùng")
    print(f"  Email : RESEND_API_KEY {'CÓ giá trị → sẽ gửi THẬT' if has_email else 'trống'}")
    print()

    if not args.confirm:
        sys.exit(
            "Cần --confirm. Script này tạo hồ sơ THẬT, tốn tiền OpenAI THẬT và có thể GỬI EMAIL THẬT\n"
            "(gate auto-từ-chối/auto-mời, email screener). Đọc docstring đầu file trước khi chạy."
        )
    if has_email and not args.allow_email:
        sys.exit(
            "Từ chối: RESEND_API_KEY có giá trị nên gate auto sẽ GỬI EMAIL THẬT. Địa chỉ sinh ra là\n"
            "`loadtest+NNN@example.com` (RFC 2606 — hard bounce CHẮC CHẮN), và bounce hàng loạt làm\n"
            "hỏng danh tiếng gửi của domain. Bỏ RESEND_API_KEY khỏi .env, hoặc thêm --allow-email."
        )
    if args.total < 1:
        sys.exit("--total phải ≥ 1.")
    if args.ramp < 0:
        sys.exit("--ramp phải ≥ 0 (0 = chế độ đợt).")
    if args.cv_kb < 0:
        sys.exit("--cv-kb phải ≥ 0.")
    if args.concurrency < 1:
        sys.exit("--concurrency phải ≥ 1 (asyncio.Semaphore(0) treo vĩnh viễn).")
    if args.metrics_interval <= 0:
        # `asyncio.wait_for(..., 0)` hết hạn NGAY ⇒ vòng poll quay hết tốc lực, nện hàng nghìn
        # request/giây vào đích. Công cụ đo tự trở thành tải và mọi đỉnh in ra là do chính nó.
        sys.exit("--metrics-interval phải > 0 (0 = vòng poll quay tít, tự làm nhiễu phép đo).")
    if args.watch_interval <= 0:
        sys.exit("--watch-interval phải > 0.")

    mode = (f"nhịp đến {args.ramp:g} CV/s (mở vòng)" if args.ramp > 0
            else f"{args.concurrency} lượt song song (đợt)")
    print("=" * 78)
    print(f"LOAD TEST — {args.total} CV vào JD #{args.job_id}, {mode}")
    print(f"Đích: {args.api}")
    print("Nhắc: đích PHẢI chạy với RATE_LIMIT_ENABLED=false, nếu không xô ghi công khai chặn từ")
    print("      lượt thứ RATE_LIMIT_PUBLIC_MAX trở đi và phép đo thông lượng vô nghĩa.")
    print("=" * 78)

    # Dựng SẴN toàn bộ CV trước khi bấm giờ. Sinh PDF là việc CPU nặng (~11ms/MB) và chạy ngay
    # trên event loop; sinh trong lúc bắn thì nó chen vào giữa các lượt gửi, làm hỏng cả nhịp đến
    # (chế độ --ramp) lẫn tính "cùng lúc" (chế độ đợt).
    sample = make_cv_pdf(0, args.cv_kb)
    need_mb = len(sample) * args.total / (1024 * 1024)
    if need_mb > args.client_ram_mb:
        sys.exit(
            f"Từ chối: {args.total} CV × {len(sample) / 1024:.0f}KB ≈ {need_mb:.0f}MB RAM ở CLIENT "
            f"(trần --client-ram-mb={args.client_ram_mb}).\nGiảm --total/--cv-kb, hoặc nâng trần nếu "
            "máy bắn thật sự đủ RAM."
        )
    t_gen = time.perf_counter()
    bodies = [sample] + [make_cv_pdf(i, args.cv_kb) for i in range(1, args.total)]
    print(f"Đã dựng {args.total} CV × {len(sample) / 1024:.1f}KB (≈{need_mb:.1f}MB RAM client) "
          f"trong {time.perf_counter() - t_gen:.1f}s")
    if args.cv_kb > 0:
        print("⚠ CV đã đệm: phần đệm là TEXT TRÍCH XUẤT ĐƯỢC ⇒ với ENABLE_LLM=true nó đi thẳng vào")
        print("  prompt của parser và thành tiền. Chỉ đệm khi LLM là stub hoặc trỏ vào mock cục bộ.")

    hr: httpx.AsyncClient | None = None
    poller: MetricsPoller | None = None
    poll_task: asyncio.Task[None] | None = None
    if args.watch or args.metrics_poll:
        if not (args.hr_email and args.hr_password):
            print("\n   [!] Cần --hr-email/--hr-password cho --watch/--metrics-poll — bỏ qua cả hai.")
        else:
            hr = await _login_hr(args.api, args.hr_email, args.hr_password, args.timeout)
    if hr is not None and args.metrics_poll:
        poller = MetricsPoller(client=hr, api=args.api, interval=args.metrics_interval)
        poll_task = asyncio.create_task(poller.run())

    # Trần connection phía client, đặt RỘNG HƠN số lượt tối đa có thể đồng thời (+10) để công cụ đo
    # KHÔNG BAO GIỜ là thứ gác cổng. Vì thế "chạm trần connection client" không phải một tín hiệu
    # đọc được ở đây; dấu hiệu client bị bỏ đói là TRỄ LỊCH BẮN (`slip`), xem `collect_constraints`.
    ceiling = args.total if args.ramp > 0 else args.concurrency
    gauge = Gauge()
    try:
        limits = httpx.Limits(max_connections=ceiling + 10)
        async with httpx.AsyncClient(timeout=args.timeout, limits=limits) as c:
            t0 = time.perf_counter()
            results = (await _run_ramp(c, args, bodies, gauge) if args.ramp > 0
                       else await _run_burst(c, args, bodies, gauge))
            wall = time.perf_counter() - t0

        accepted, blocked = report_intake(results, wall, args.ramp)

        watch = WatchResult()
        if args.watch and accepted and hr is not None:
            watch = await watch_processing(
                hr, args.api, accepted, args.watch, args.watch_interval
            )
    finally:
        if poller is not None:
            poller.stop()
        if poll_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await poll_task
        if hr is not None:
            await hr.aclose()

    if poller is not None:
        poller.report()
    first_error = next((r["detail"] for r in results if r["status"] not in (201, 429) and r["detail"]), None)
    slip_max = max((r["slip"] for r in results), default=0.0)
    report_conclusion(args, len(accepted), blocked, wall, watch, poller, gauge, slip_max, first_error)

    if blocked or not accepted:
        # Mã thoát khác 0: lần chạy này KHÔNG dùng làm số liệu được (rate-limit đã bóp méo, hoặc
        # không hồ sơ nào vào nổi hệ thống). Có mã thoát thì vòng lặp đo (hoặc CI) dừng lại thay vì
        # chép một con số vô nghĩa vào báo cáo.
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
