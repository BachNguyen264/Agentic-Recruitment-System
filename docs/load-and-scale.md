# Tải & Scale — số đo thật và hướng mở rộng

> **Mục đích:** trả lời dứt khoát hai câu hỏi *"nhiều CV nộp cùng lúc thì thế nào?"* và *"nhiều người
> đặt lịch cùng lúc thì sao?"* bằng **số đo**, không phải bằng ước lượng. Kèm hành vi khi VƯỢT trần và
> các nấc mở rộng tiếp theo.
>
> Đo ngày **2026-08-29**. Công cụ: `scripts/loadtest_apply.py`, `scripts/loadtest_booking.py`,
> `scripts/mock_openai.py`, `GET /api/health/metrics`.
> Ranh giới kiến trúc + bẫy → `docs/AI_GUIDE.md`. Sự cố vận hành → `docs/deploy-live-issues.md`.

---

## 0. Trả lời ngắn (đọc cái này trước)

| Câu hỏi | Trả lời |
|---|---|
| Nhiều CV nộp cùng lúc? | **≤ 80 CV cùng lúc: xử lý trọn vẹn, không mất hồ sơ nào.** Vượt ngưỡng thì hệ **xếp hàng**, không sập. |
| Bao nhiêu thì hỏng? | Trước khi vá: **200 CV cùng lúc** → 6 CV mất ở cửa nhận, 107 hồ sơ phải chuyển HR. Sau khi vá: **200/200 xử lý sạch**. |
| Nhiều người đặt lịch cùng lúc? | **~15 người xem lịch cùng lúc.** Người thứ 19 thấy danh sách rỗng. Giới hạn đến từ **cấu hình**, không phải database. |
| Có bao giờ đặt trùng giờ không? | **Không.** 12 người cùng chốt một khung → 1 thắng, 11 nhận 409, 0 lỗi máy chủ. Kiểm chứng bằng SQL toàn bảng. |
| Quá tải thì có mất ứng viên không? | **Không, trừ đúng một đường đã vá.** Mọi lỗi kỹ thuật đều đẩy hồ sơ về `PENDING_REVIEW` cho người xem — không bao giờ tự từ chối. |

---

## 1. Phương pháp — vì sao số này đáng tin

**Vấn đề:** `ENABLE_LLM=false` (cách đo "miễn phí" hiển nhiên) **stub cả parser lẫn ranker**, tức xoá
đúng cái nút thắt cần đo. Đo kiểu đó là đo một hệ thống khác.

**Cách giải:** dựng `scripts/mock_openai.py` đứng thay OpenAI **tại chỗ**, trỏ vào bằng biến môi trường
`OPENAI_API_BASE`. Đã kiểm chứng: biến này chuyển hướng **cả** `ChatOpenAI` lẫn `OpenAIEmbeddings`,
nên **không sửa một dòng code sản phẩm nào** mà đường code thật vẫn chạy nguyên vẹn —
`parse_cv` vẫn gọi `client.invoke()` **đồng bộ** → `asyncio.to_thread` → thread pool dùng chung.
Độ trễ giả lập đặt đúng số đã đo thật: **parser 9.4s · ranker 24.7s · embedding 0.3s**.

**Chi phí: 0 đồng, 0 email.** JD dùng để đo có gate tắt + không câu hỏi screener ⇒ hồ sơ đi
`parser → ranker → (screener bỏ qua) → human_review` mà không phát ra lá thư nào.

**Đã loại trừ mock là nút thắt:** mock đạt đỉnh **96 request đồng thời**, 0 lỗi.

**Điều kiện đo:** 1 tiến trình uvicorn (đúng như prod), `APP_ENV=production` (tắt reload),
`RATE_LIMIT_ENABLED=false` (nếu không, chính limiter chặn phép đo — xem §5).

---

## 2. Nhiều CV nộp cùng lúc

### 2.1 Đường cong tải (trước khi vá)

| N cùng lúc | Nhận p50 | Nhận max | Xong sau | Thông lượng | db_pool | ckpt chờ | executor queue | Mất hồ sơ |
|---|---|---|---|---|---|---|---|---|
| 1 | 1.5s | 1.5s | 45s | 0.02/s | 2/15 | 0 | 1 | 0 |
| 10 | 2.5s | 2.5s | 46s | 0.22/s | 10/15 | 9 | 0 | 0 |
| 30 | 3.2s | 4.1s | 60s | 0.50/s | **15/15** | 58 | 8 | 0 |
| 80 | 5.9s | 14.9s | 92s | 0.87/s | **15/15** | 182 | 44 | **0** |
| 200 | — | — | — | — | 15/15 | — | — | **6 mất + 107 chuyển HR** |

**Ba điều bảng này nói:**

1. **Thời gian xong tăng DƯỚI TUYẾN TÍNH.** 80 CV chỉ mất gấp ~2× thời gian của 1 CV (45s → 92s), vì
   phần lớn thời gian là *chờ mạng LLM* — song song được — chứ không phải CPU.
2. **Giá phải trả dồn vào độ trễ lúc NỘP** (1.5s → 5.9s, đuôi 14.9s). Đây là thứ ứng viên cảm thấy.
3. **Tới 80 CV cùng lúc vẫn không mất hồ sơ nào.**

### 2.2 Tài nguyên nào cạn trước — và câu trả lời gây bất ngờ

Đọc code thì ai cũng đoán nút thắt là **thread pool** (parser gọi LLM đồng bộ). **Đo thì sai.**

Thứ tự bão hoà thật:

| Hạng | Tài nguyên | Chạm trần từ | Ghi chú |
|---|---|---|---|
| 1 | **Pool checkpointer LangGraph (5)** | **N = 10** | LangGraph ghi checkpoint sau MỖI node |
| 2 | Pool SQLAlchemy (15) | N = 30 | |
| 3 | Executor asyncio (20) | N = 30 (queue=8) | parser đồng bộ |
| — | Thread pool anyio (40) | **chưa bao giờ** | 0/40 ở mọi mức (xem §6 — local dùng đĩa, prod dùng R2) |

### 2.3 Nút thắt thật KHÔNG phải kích thước pool — mà là một cái KHOÁ

Thí nghiệm đối chứng, chỉ đổi **một** biến `CHECKPOINTER_POOL_MAX_SIZE` 5 → 25 (gấp **5×**):

| N=200 | pool 5 | pool 25 |
|---|---|---|
| Nhận | 194/200 | 200/200 |
| Hồ sơ vào đường cứu hộ `[error]` | 107 | **93** |
| Loại lỗi | `PoolTimeout` | `PoolTimeout` (không đổi) |

Pool gấp 5× chỉ giảm lỗi **13%**. Nếu pool là nút thắt thì phải giảm gần hết. Bằng chứng trong mã
nguồn thư viện `langgraph/checkpoint/postgres/aio.py`:

- dòng **46**: `self.lock = asyncio.Lock()` — một khoá cho mỗi saver
- dòng **344/352/359**: khoá được giữ ở **cả ba** nhánh của `_cursor()`
- dòng **328**: connection được **lấy TRƯỚC**, rồi mới xếp hàng vào khoá
- `app/agents/checkpointer.py:71`: `_saver = AsyncPostgresSaver(_pool)` — **MỘT** saver toàn tiến trình

⇒ **Đồng thời hoá SQL của checkpointer thực tế là 1, bất kể pool bao nhiêu.** Nâng pool chỉ khiến
nhiều coroutine cùng ôm connection **rỗi** trong lúc xếp hàng vào khoá — **dời** chỗ nghẽn, không **gỡ**.

### 2.4 Bản vá và kết quả

Vì nới ở *đầu ra* không cứu được, phải chặn ở **đầu vào**:

- **`MAX_CONCURRENT_PIPELINES`** (mặc định **15**) — semaphore quanh `process_application`, chờ **trước
  khi** chạm bất kỳ tài nguyên nào, nhả trong `finally`.
- **`OPENAI_TIMEOUT_SECONDS`** (mặc định **120**) — langchain vốn truyền `timeout=None` = **chờ vô hạn**.

> **Hai thứ này BẮT BUỘC đi cặp.** Van mà không có timeout thì một request treo giữ một suất **vĩnh
> viễn** và biến van thành nút cổ chai chết.

**Đo lại N=200, pool checkpointer trả về mặc định 5:**

| | Trước | Sau |
|---|---|---|
| HTTP 201 | 194/200 | **200/200** |
| CV mất hẳn ở cửa nhận (500) | 6 | **0** |
| Hồ sơ vào `PENDING_REVIEW[error]` | 107 | **0** |
| Hồ sơ **chấm điểm thành công** | 87 | **200** |
| `psycopg_pool.PoolTimeout` | 106 | **0** |
| `sqlalchemy.exc.TimeoutError` | 7 | **0** |
| db_pool đỉnh | 15/15 (cạn) | **2/15** |
| checkpointer đỉnh | 5/5, 182 chờ | **0/5, 0 chờ** |
| Thời gian tường | 132s | 224s |
| **Thông lượng CÓ ÍCH** | 107/132 = **0.81/s** | 200/224 = **0.89/s** |

**Chậm hơn về đồng hồ nhưng nhanh hơn về việc có ích** — trước đây 107 hồ sơ vẫn tiêu trọn hai lượt
LLM rồi mới hỏng. Quan sát trực tiếp giữa lúc chạy: `in_flight=40 · queued=160 · failed=0`, mọi pool RỖI.

### 2.5 Khi thật sự vỡ thì hệ hành xử ra sao (quan trọng cho câu hỏi "có sập không?")

Ở N=200 **trước khi vá**, 107 hồ sơ trúng `PoolTimeout`. Tất cả đều kết thúc ở
**`PENDING_REVIEW`** kèm `escalation_reason = "Lỗi kỹ thuật khi xử lý pipeline (error)"`.

- **Không** hồ sơ nào bị auto-từ-chối.
- **Không** hồ sơ nào biến mất im lặng.
- Tất cả đều nằm trong hàng đợi của HR để người xem.

Đây đúng trụ cột PRD §13: **máy không chắc thì đẩy cho người**. Quá tải làm *tăng việc cho HR*, chứ
không làm *mất ứng viên*.

**Ngoại lệ duy nhất — và đó là lỗi thật đã vá:** 6 CV bị từ chối ngay ở cửa nhận (HTTP 500 do cạn pool
SQLAlchemy). Ứng viên thấy lỗi, **không có dòng nào trong DB, không audit** — đây mới là mất người
thật sự. Sau khi vá: 0.

---

## 3. Nhiều người đặt lịch cùng lúc

### 3.1 Sức chứa

- Lưới thật: **75 mốc giờ phân biệt** trong cửa sổ 21 ngày.
- 20 người mở link cách nhau 0.5s → **18 nhận được khung giờ, 2 nhận danh sách RỖNG**; người rỗng đầu
  tiên là **#19**.
- ⇒ **Trần ≈ 15 người xem đồng thời.**

**Nút thắt KHÔNG phải database** mà là **cơ chế giữ chỗ**: mỗi người mở link chiếm tạm
`BOOKING_SLOTS_OFFERED` (5) khung trong `BOOKING_HOLD_MINUTES` (5) phút. 15 người × 5 khung = 75 = hết lưới.

> **`BOOKING_MAX_PER_DAY=6` là config chết.** Lưới giờ làm việc (08:00–17:30, nghỉ trưa 12:00–13:30,
> 60′ + đệm 15′) chỉ sinh **5** mốc/ngày, nên guard `counts[day] >= max_per_day` **không bao giờ chạm tới**.
> Nâng 4→6 ở SCH-3 thực tế chỉ nâng được 4→5.

### 3.2 Đúng đắn: chốt chặn giữ vững

12 người cùng chốt **một** khung giờ:

- **1 × HTTP 200 · 11 × HTTP 409 · 0 × HTTP 500**
- SQL toàn bảng: **không mốc giờ nào có quá một hàng `BOOKED`**
- Độ trễ chốt: p50 2.34s · p95 2.44s

Chốt chặn cuối là **partial unique index** `UNIQUE(start_at) WHERE status='BOOKED'` — đã xác nhận tồn
tại trong `pg_indexes`. Thua race ra **409 sạch**, không phải deadlock-ra-500.

Huỷ nhả khung giờ **tức thì** (không chờ sweep) và **không gia hạn** hạn liên kết.

### 3.3 Hai lỗi phát hiện được (CHƯA vá)

**(a) Cảnh báo GIẢ gửi cho HR.** Khi 15+ người cùng xem lịch, 2 phiên bị đóng dấu `no_slots_at` →
dashboard báo HR *"Hết khung giờ — cần mở thêm lịch"* trong khi **0 buổi phỏng vấn được đặt** và 90
khung chỉ đang **giữ tạm**, tự trả lại sau 302 giây. Hệ đổ lỗi cho lịch công ty về một tình trạng tạm
thời do chính cơ chế giữ chỗ gây ra.

**(b) TOCTOU khi sinh khung giờ** (đo được **3/153 cặp có Jaccard = 1.000**, tức trùng **hệt nhau**).
`generate_slots` ĐỌC `_occupied` rồi mới GHI, còn `lock_application` chỉ khoá theo **từng hồ sơ** nên
không tuần tự hoá hai hồ sơ **khác nhau**; `_pick_mixed` lại **tất định** ⇒ nhiều người nhận y hệt một
bộ khung giờ ⇒ tới bước chốt thì 1 thắng, N−1 ăn 409. **Không phải lỗi đúng-đắn** (HELD chỉ là khuyến
nghị, unique index vẫn giữ) nhưng là **lỗi trải nghiệm**, và nó nặng lên đúng lúc đông người.

---

## 4. Hướng mở rộng — nếu muốn xử lý nhiều hơn thì làm gì

Xếp theo **rẻ → đắt**. Mỗi nấc ghi rõ *nới được cái gì* và *chạm trần mới ở đâu*.

| Nấc | Việc phải làm | Nới được | Trần mới |
|---|---|---|---|
| **0** | *(hiện tại)* | ~15 pipeline đồng thời, hàng đợi không giới hạn | RAM khi hàng đợi quá dài |
| **1** | Nâng `MAX_CONCURRENT_PIPELINES` + `BOOKING_SLOTS_OFFERED`/`HOLD_MINUTES` | Chỉ là **đổi biến môi trường**, không sửa code | RAM (mỗi pipeline giữ trọn bytes CV) |
| **2** | Nâng gói Render (free 512MB → Starter 512MB → Standard 2GB) | RAM + CPU ⇒ nâng được nấc 1 cao hơn | Khoá của checkpointer (§2.3) |
| **3** | Bỏ `asyncio.to_thread` ở parser, dùng `ainvoke` | Trả lại toàn bộ thread pool cho R2/email | Khoá checkpointer |
| **4** | Nhiều `AsyncPostgresSaver` (mỗi cái một khoá) hoặc bỏ checkpointer cho JD **không** có câu hỏi screener | Gỡ đúng nút thắt số 1 | DB / OpenAI TPM |
| **5** | Scale ngang (nhiều instance) | Tuyến tính theo số instance | **Xem cảnh báo dưới** |

### ⚠️ Trước khi thêm instance thứ hai, PHẢI xử lý 4 thứ

Phần **đúng đắn** đã an toàn cho nhiều tiến trình (mọi mutation đặt lịch đều có `SELECT … FOR UPDATE`,
`pg_advisory_xact_lock`, hoặc partial unique index). Nhưng **bốn thứ này sống trong RAM của MỘT tiến trình**:

1. **Bộ giữ nhịp email** (`_send_lock` + `_last_send_at`) — 2 instance sẽ gửi **gấp đôi** nhịp cho phép.
2. **Rate limiter** — mọi hạn mức nhân lên theo số instance.
3. **Vòng quét nền** (sweep 08c) — chạy trên **mọi** instance; các mốc thời gian idempotent bảo vệ được
   phần lớn, nhưng công việc bị làm lặp.
4. **`alembic upgrade head`** chạy trong **mọi** container lúc khởi động, không có advisory lock.

> **Kết luận thực dụng cho đồ án:** hệ này **không cần** scale ngang. Nấc 1–2 (đổi biến + nâng gói) đủ
> phục vụ tải thật của một công ty đơn lẻ. Scale ngang là *hướng mở rộng trong báo cáo*, không phải
> việc cần làm.

---

## 5. Phát hiện ngoài dự kiến: rate limit công khai KHÔNG chạm được người dùng thật

Thí nghiệm (POST `/api/public/applications` với `job_id` không tồn tại → 404, **không ghi dữ liệu**;
middleware đếm **trước** handler nên vẫn tiêu quota):

| Đường đi | Số lượt | Kết quả |
|---|---|---|
| **Thẳng vào Render** (IP cố định) | 26 | **429 từ lượt thứ 21** — đúng `RATE_LIMIT_PUBLIC_MAX=20` |
| **Qua Vercel** (đường ứng viên THẬT đi) | **52** | **0 lượt bị chặn** |

Khoá quota là `CF-Connecting-IP` = IP **edge của Vercel**, mà Vercel **xoay vòng IP egress** ⇒ gần như
mỗi request rơi vào một xô khác nhau. Mà **100% ứng viên thật đi qua domain Vercel** (proxy same-origin
bật từ commit `a6df386`).

**Hai hệ quả ngược nhau:**

- ❌ **Bảo mật/chi phí:** đường nộp CV — thứ kích hoạt **LLM tốn tiền** — thực tế **không có giới hạn**.
  Không có chốt chặn nào chống lạm dụng ngân sách OpenAI. **Nên vá.**
- ✅ **Năng lực:** rate limit **không phải** trần ràng buộc với ứng viên thật, nên trần thật đúng là các
  con số ở §2.

---

## 5b. Số đo TRÊN PROD (Render free + Neon free + R2 + OpenAI THẬT)

### Cấu hình thật của máy prod (đọc từ `GET /api/health/metrics`)

| | Giá trị | Ý nghĩa |
|---|---|---|
| `cpu_count` | **8** | Đây là CPU của **máy chủ host**, KHÔNG phải quota thật của gói free |
| `thread_default_width` | **12** | `min(32, 8+4)` — ít hơn local (20) |
| `rss_bytes` lúc rảnh | **169 MB** | Trên 512 MB ⇒ còn **~343 MB** |
| `rss_bytes` khi 15 pipeline chạy | **324 MB** | 63% của 512 MB (CV nhỏ 1.2KB) |

> **Đây là căn cứ chọn `MAX_CONCURRENT_PIPELINES=15`:** 15 × 11MB (CV 10MB đang bay) = 165MB,
> cộng 169MB nền = **334MB ≈ 65%** của 512MB — an toàn có biên. Nếu để 40 như số đo tốt trên máy dev
> thì 40 × 11MB = 440MB + 169MB ⇒ **OOM chắc chắn**, mà OOM-kill là SIGKILL: lifespan không chạy,
> mọi BackgroundTask đang bay bốc hơi.

### 20 CV nộp cùng lúc trên prod, LLM THẬT

- **20/20 xử lý trọn vẹn, 0 mất, 0 lỗi.** Van giữ đúng: `in_flight=15 · queued=5`.
- Pipeline THẬT nhanh hơn số local giả lập: **20 CV xong trong ~41s** (giả lập đặt 34.1s/CV).
- Nhịp xử lý: **0.36 hồ sơ/s**.
- `checkpointer` vẫn chạm trần **5/5 với 35 lượt chờ** — kể cả khi chỉ có 15 pipeline.

### Độ trễ NHẬN trên prod là LƯỠNG CỰC — và KHÔNG phải do đồng thời

| Điều kiện | p50 |
|---|---|
| Tiến trình + connection đã ấm (kể cả khi 15 pipeline đang chạy) | **0,22 – 0,33s** |
| Cụm đầu tiên sau một quãng rỗi / ngay sau deploy | **6 – 19s** |

**Đây là câu chuyện dài nhất của lát này, và bài học phương pháp đáng giá hơn bản vá.**

Ban đầu tôi đo được "13,4s ở 20 CV đồng thời" và kết luận đó là trần đồng thời. **Sai.** Kiểm chứng
chéo bằng **20 tiến trình `curl` độc lập** cùng thời điểm cho **0,22s**; và chạy lại đúng công cụ đó
vài phút sau cho **0,33s** — cùng một bản code, chênh **54 lần**.

Dấu hiệu nhận ra: mọi lượt **dồn cục** quanh cùng một mốc (min 16,9 · p50 18,7 · max 19,2). Đó là
"tất cả cùng chờ MỘT sự kiện rồi được nhả ra cùng lúc", **không phải** xếp hàng tuyến tính (xếp hàng
thì độ trễ phải trải đều).

**Bốn giả thuyết đã bị BÁC BẰNG THỰC NGHIỆM** (mỗi cái một phép đo, không phải suy luận):

| Giả thuyết | Cách bác | Kết quả |
|---|---|---|
| Giữ connection DB qua lượt upload | bỏ `refresh()` thừa rồi đo lại | số KHÔNG đổi |
| Tranh chấp thread pool với parser | cho storage executor riêng | số KHÔNG đổi |
| Neon autosuspend | để hệ nghỉ 6 phút rồi bắn 20 CV | **0,24s** — không tái hiện |
| Nhập lười `langchain_openai` | nạp trước ở lifespan | vẫn 18,7s |

**Hai thứ THẬT SỰ có tác dụng** (đo được):
- Làm ấm **client boto3/R2** lúc khởi động: 18,7s → **9,6s**. Client tạo lười **dưới một `Lock`**, nên
  20 lượt nộp cùng xếp hàng sau lượt đầu (`import boto3` + nạp service model botocore + TLS) rồi được
  nhả ra cùng lúc — khớp chính xác dấu hiệu dồn cục.
- Làm ấm **pool DB** lúc khởi động (bắt tay TLS đầu tới Neon).

**Phần còn lại (~6–10s ở cụm đầu tiên) CHƯA chốt được nguyên nhân.** Ghi đúng như vậy thay vì đoán
tiếp. Ứng viên còn lại: tái lập connection sau khi rỗi (Neon/Render gói free đóng kết nối nhàn rỗi),
và chi phí CPU đường-lạnh trên quota ~0,1 CPU.

> **Điều QUAN TRỌNG cho kết luận năng lực:** cú chậm này là **chi phí đường-lạnh**, KHÔNG phải trần
> đồng thời. Ở trạng thái ổn định, 20 CV nộp cùng lúc mất **0,22s** — kể cả khi 15 pipeline đang chạy.
> Đừng trích số 13–18s như "trần chịu tải của hệ thống": đó là số của lần chạm đầu tiên.

**Bản vá `refresh()` vẫn GIỮ** dù nó không cải thiện con số này: nó đúng độc lập (`refresh()` thật sự
mở lại transaction và giữ connection qua lượt I/O mạng) và có **test hồi quy hai chiều** khoá lại —
thêm `refresh()` vào thì test ĐỎ, bỏ ra thì XANH.

---

## 6. Local khác prod ở đâu (đọc trước khi trích số)

| | local (máy dev) | prod (Render) |
|---|---|---|
| `STORAGE_BACKEND` | `local` (đĩa, ~0ms) | `r2` (mạng, ~0.2–0.3s) |
| event loop | **WindowsSelectorEventLoop** — `select()` trần **512 socket** | epoll, không có trần này |
| thread pool | `min(32, 16+4)` = **20** | phụ thuộc `os.cpu_count()` trong container |
| CPU đơn luồng | chậm hơn prod ~2.7× (bcrypt 0.272s vs ~0.1s) | nhanh hơn |
| RAM | dư dả | **512MB** (gói free) |

⇒ Local đo đúng **hình dạng** nút thắt; **con số tuyệt đối phải xác nhận trên prod**.
Đặc biệt: `anyio_threads` ở local luôn 0/40 vì storage là đĩa — **trên prod (R2 qua mạng) con số này
sẽ khác**, và đó chính là đường NHẬN CV.

---

## 7. Vòng quét nền KHÔNG phải nút thắt (bác bỏ một lo ngại)

`EXPLAIN ANALYZE` trên truy vấn hết-hạn của screener: **0.043 ms**. Vòng quét chạy mỗi **600 giây**, và
hai bảng liên quan chỉ lớn thêm 1 hàng/ứng viên **đi tới bước đó**. Kể cả 100.000 hàng, seq scan bảng
hẹp ≈ vài chục ms = **~0,005%** chu kỳ.

Vấn đề thật của vòng quét là **đúng đắn**, không phải hiệu năng: ba lưới dùng **chung một `try`** và
không lưới nào có `LIMIT` ⇒ lỗi ở lưới 1 làm **bỏ qua** lưới 2 và 3.

---

## 8. Cách chạy lại các phép đo

```bash
# 1) Mock OpenAI (0 đồng, chạy ĐÚNG đường code thật)
uv run --directory apps/backend python scripts/mock_openai.py \
    --parser-delay 9.4 --ranker-delay 24.7 --confirm

# 2) Backend: 1 tiến trình, tắt rate-limit, trỏ vào mock
APP_ENV=production RATE_LIMIT_ENABLED=false \
OPENAI_API_BASE=http://127.0.0.1:9099/v1 \
    uv run --directory apps/backend python -m app

# 3) Tải CV (JD phải: OPEN + gate TẮT + KHÔNG câu hỏi screener ⇒ 0 email)
uv run --directory apps/backend python scripts/loadtest_apply.py \
    --job-id <ID> --total 80 --concurrency 80 \
    --hr-email <email> --hr-password <pw> --watch 600 --metrics-poll --confirm

# 4) Tải đặt lịch (chạy backend với RESEND_API_KEY rỗng ⇒ 0 email)
uv run --directory apps/backend python scripts/loadtest_booking.py \
    --viewers 20 --stagger 0.5 --race 12 --confirm
uv run --directory apps/backend python scripts/loadtest_booking.py --cleanup
```

**Bẫy đã vấp:** trên Windows, tiến trình python cũ **giữ socket** sau khi bị kill — cổng vẫn bận và
server mới **im lặng không bind được**, khiến phép đo chạy vào server CŨ. Luôn xác nhận cổng đã tự do
trước khi đo (xem `docs/AI_GUIDE.md`).

---

## 9. Đã vá trong lát này

| Vá | Hiệu quả ĐO ĐƯỢC |
|---|---|
| `MAX_CONCURRENT_PIPELINES=15` + `OPENAI_TIMEOUT_SECONDS=120` | 200 CV cùng lúc: **107 hồ sơ lỗi → 0**, 6 CV mất → 0 |
| Bỏ `refresh()` thừa ở đường nhận (+ test hồi quy 2 chiều) | Nhả connection trước lượt upload (đúng độc lập; không đổi độ trễ) |
| Thread pool RIÊNG cho storage + gauge | Tách coupling; **đo được executor trên prod** (uvloop làm ta mù) |
| Làm ấm client R2 + pool DB lúc khởi động | Cụm đầu sau deploy **18,7s → ~10s** |

## 10. Việc còn nợ

- [ ] **Chốt nốt ~6–10s còn lại của cụm-đầu-tiên** (§5b) — chưa xác định được nguyên nhân.
- [ ] Vá **cảnh báo `no_slots_at` giả** (§3.3a) và **TOCTOU sinh khung giờ** (§3.3b).
- [x] ~~Vá **rate limit không chạm được người dùng thật** (§5)~~ — XONG (AUDIT-1): đường nộp CV gọi
      THẲNG Render qua `NEXT_PUBLIC_PUBLIC_API_BASE`, kèm trần 60k ký tự khi trích CV (chặn chi phí
      MỖI request, bổ sung cho việc chặn SỐ request). **Cần đặt biến env đó trên Vercel mới có tác dụng.**
- [x] ~~Vá **`list_applications(limit=100)`**~~ — XONG (AUDIT-1): phân trang + `?status=` lọc ở server
      (khoá phụ `id DESC`, trần `limit le=200`), `/review` hỏi đúng `PENDING_REVIEW&limit=20`, badge đọc
      `/pipeline`. Triệu chứng thật quan sát được trên prod: 206 hồ sơ ⇒ cửa sổ 100 dòng rơi TRỌN vào mẻ
      probe, **86 hồ sơ đã chấm điểm sạch không thể chạm tới bằng bất kỳ nút/bộ lọc nào**.
- [ ] Tách `try` cho ba lưới của vòng quét + thêm `LIMIT` (§7).
- [ ] `executor` gauge trả `null` trên prod vì `uvloop` — cân nhắc `set_default_executor` để đo được.
- [x] ~~Dọn dữ liệu test trên prod + **lưu trữ JD 8 `[LOADTEST]`**~~ — XONG 29/08/2026: xoá 206
      application + 1.116 audit_log + **21.068 dòng checkpoint** + 206 file CV trên R2 + chính JD 8
      (kèm vector Qdrant). Snapshot `pre-purge-2026-08-29` giữ đường lùi. Verify bằng SQL + liệt kê
      prefix `cv/` trên bucket, KHÔNG tin dòng "+206/206" của script (xem gotcha `LocalStorage.delete`).
- [ ] **Đổi mật khẩu `admin@ars.prod`** (đã lộ trong chat) — việc THỦ CÔNG còn lại, chưa làm.

---

## 11. Bốn bài học phương pháp (đáng giá hơn các con số)

1. **Đọc code đoán nút thắt là SAI.** Audit 9 chiều đoán thread pool cạn trước; đo ra là pool
   checkpointer (N=10), mà thật ra là **cái khoá** chứ không phải pool.
2. **Nới ở đầu ra ≠ gỡ nghẽn.** Pool checkpointer gấp 5× chỉ giảm lỗi 13%. Phải chặn ở **đầu vào**.
3. **Một con số chậm KHÔNG tự nói nó chậm ở đâu.** Bốn giả thuyết hợp lý về độ trễ nhận đều sai; chỉ
   phép **kiểm chứng chéo** (20 `curl` độc lập vs công cụ) mới lật được vấn đề.
4. **Công cụ đo phải bị nghi ngờ trước tiên.** `loadtest_apply.py` từng báo XANH GIẢ hai chỗ, và có
   lúc chính nó bị nghi là nút thắt. Luôn có ít nhất **hai đường đo độc lập** cho mỗi con số quan trọng.
