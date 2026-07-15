# SLICE 08c — Screener timeout: nhắc + hết hạn + trả lời trễ (in-process sweep, có seam) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** xử lý ca ứng viên KHÔNG trả lời screener: quét deadline định kỳ (trong tiến trình), **nhắc một lần**,
> **hết hạn → human_review với cờ `no_response`** (KHÔNG BAO GIỜ auto-từ-chối — im lặng ≠ từ chối), và xử lý
> **trả lời trễ** êm. Chọn Hướng A (in-process sweep, quét Postgres — không đụng Redis) sau một seam mỏng để sau
> đổi QStash không sửa nghiệp vụ.
> Tham chiếu: PRD §10 (FR-SCR-3/4/5), §13. Tuân thủ `CLAUDE.md` (KHÔNG worker polling Redis).

---

## 1. In scope / Out of scope

**In scope:**

- **Seam scheduling:** interface `ScreeningTimeoutScheduler` (mỏng) + implementation `InProcessScheduler` (sweep loop
  trong lifespan). **Handler nghiệp vụ (gửi nhắc / xử lý timeout) tách riêng, KHÔNG phụ thuộc cơ chế.**
- Sweep loop: mỗi N phút quét `screening_session` (Postgres) tìm ca cần nhắc / đã hết hạn → gọi handler tương ứng.
- Nhắc MỘT LẦN qua scheduler (email nhắc). Cột `reminded_at` (once-only).
- Timeout: resume graph với tín hiệu `no_response` → screener node → route **human_review** + cờ `no_response`.
  KHÔNG auto-từ-chối. Đánh dấu session timed-out.
- Trả lời trễ: ứng viên mở link sau hết hạn → thông báo êm ("thời hạn đã qua, hồ sơ đang được xem xét"); (tùy chọn nhẹ: đính câu trả lời trễ cho HR tham khảo). KHÔNG resume lại (đã timeout).
- HR thấy cờ/tình trạng `no_response`.

**Out of scope (KHÔNG làm):**

- KHÔNG QStash / hạ tầng scheduling phân tán (chỉ InProcess sau seam — QStash là bản nâng cấp deploy).
- KHÔNG cổng auto-mời (08d). KHÔNG LLM chuẩn hóa câu trả lời. KHÔNG đụng checkpointer-08a / cơ chế token-08b (chỉ thêm timeout).
- KHÔNG đụng parser/ranker logic.

---

## 2. Prerequisites

- 08b xong (screening_session + token + resume bằng answers). 08a (suspend/resume). 04 (scheduler email).
- Config: `SCREENER_DEADLINE_HOURS` (đã có 08b, vd 72), `SCREENER_REMINDER_HOURS` (vd 24), `SCREENER_SWEEP_INTERVAL_MINUTES` (vd 10).
  **Cho verify:** các giá trị này đọc từ env → khi test đặt NHỎ (deadline 2 phút, reminder 1 phút, sweep 20 giây) để quan sát, không phải chờ 72h.

---

## 3. Việc cần làm

### 3.1 Seam scheduling · `app/services/screening_scheduler.py`

- Interface MỎNG (Protocol/ABC): `ScreeningTimeoutScheduler` với, tối thiểu:
  - `async def start() / stop()` — vòng đời (InProcess: khởi/dừng sweep loop). Gọi ở lifespan.
  - (đủ cho seam QStash sau) `async def on_session_created(session)` — InProcess = no-op (sweep đọc DB); QStash sau = đăng ký callback.
- `InProcessScheduler` implements: `start()` chạy một asyncio background task = **sweep loop** (mỗi
  `SCREENER_SWEEP_INTERVAL_MINUTES`). Sweep loop chạy trong event loop chính của backend → await graph resume +
  AsyncPostgresSaver tự nhiên (KHÔNG dính bẫy asyncio.run per-request của 08a — đây là task bền trong loop chính).
- **Handler nghiệp vụ ĐỂ RIÊNG** (vd trong screening service), scheduler chỉ _gọi_ chúng:
  - `async def send_screening_reminder(session)` · `async def handle_screening_timeout(session)`.
  - → đổi InProcess↔QStash sau này KHÔNG đụng 2 handler này.
- Chọn implementation qua config (mặc định InProcess). App phụ thuộc INTERFACE, không phụ thuộc InProcess trực tiếp.

### 3.2 Cột session · migration

- Thêm `reminded_at` (nullable) vào `screening_session` (đánh dấu đã nhắc — once-only). (`expires_at` đã có.)
  Cân nhắc `status`/`timed_out_at` nếu cần phân biệt used vs timed-out. Migration Alembic (nhớ `include_object` guard như 08b để KHÔNG drop bảng checkpoint).

### 3.3 Sweep loop — nội dung mỗi vòng

- **Cần nhắc:** session `used_at IS NULL` + `reminded_at IS NULL` + quá mốc nhắc (created_at + REMINDER_HOURS) + chưa hết hạn →
  `send_screening_reminder`: gửi email nhắc (qua scheduler, template nhắc) + set `reminded_at`. **Row-lock** khi xử lý để không nhắc trùng.
- **Hết hạn:** session `used_at IS NULL` + quá `expires_at` → `handle_screening_timeout`: **resume graph** với payload
  `{"no_response": true}` (thread_id=app-<id>) → screener node → route human_review + cờ `no_response` + escalation_reason
  ("ứng viên không phản hồi sàng lọc"). Đánh dấu session timed-out. **KHÔNG auto-từ-chối.** Row-lock.
- Idempotent + an toàn: lỗi một session không được làm chết cả vòng sweep (try/except từng session + log).

### 3.4 Screener node xử lý resume timeout · `app/agents/nodes/screener.py`

- Node phân biệt hai kiểu resume: câu trả lời thật (08b) vs tín hiệu `no_response` (timeout). Với `no_response`:
  set cờ `no_response` + escalation_reason, KHÔNG lưu answers, tiếp tục → human_review. Nhánh nhỏ, KHÔNG đụng logic khác.

### 3.5 scheduler: template nhắc · `app/agents/nodes/scheduler.py` + templates

- `screener_reminder_email(candidate_name, job_title, link, deadline)` — nhắc lịch sự, cùng magic-link (token cũ còn hạn), nêu hạn. Cố định (không LLM). scheduler vẫn điểm phát email duy nhất.

### 3.6 Trả lời trễ · endpoint public POST screening (08b)

- Nếu session đã timed-out/hết hạn khi ứng viên nộp: trả thông báo êm ("Thời hạn đã qua; hồ sơ của bạn đang được
  xem xét"), KHÔNG resume (graph đã đi tiếp qua timeout). (Tùy chọn nhẹ: lưu câu trả lời trễ vào application cho HR
  xem, đánh dấu "trả lời sau hạn" — không bắt buộc.)

### 3.7 HR thấy no_response · ReviewCard/chi tiết

- Ca timed-out hiện rõ (vd nhãn "Không phản hồi sàng lọc") để HR biết vì sao vào review. Thuần hiển thị.

### 3.8 Test · `app/tests/test_screener_timeout.py`

- Nhắc gửi ĐÚNG MỘT LẦN (reminded_at chặn lần hai). Trả lời trước hạn → không nhắc/không timeout (không hồi quy).
- Timeout → resume `no_response` → human_review + cờ; **KHÔNG auto-từ-chối**; parser/ranker không chạy lại.
- Trả lời trễ → thông báo êm, không resume lại. Sweep idempotent (chạy 2 lần không xử lý đôi).
- (Có thể inject thời gian/hạ ngưỡng để test không phải chờ thật.)

---

## 4. Verify (chạy thật — ĐẶT NGƯỠNG NHỎ để quan sát)

1. Đặt env NHỎ: `SCREENER_DEADLINE_HOURS` ~ 2 phút (hoặc thêm cờ giây), `SCREENER_REMINDER_HOURS` ~ 1 phút, `SCREENER_SWEEP_INTERVAL_MINUTES` ~ 20 giây. `make dev-backend`.
2. Nộp CV đạt (email của bạn) qua `/apply` → screener email → **KHÔNG trả lời**, chờ.
3. Tới mốc nhắc → nhận **email nhắc** (một lần; chờ thêm không nhận lần hai).
4. Tới hạn → sweep xử timeout → `/applications` thấy CV vào **PENDING_REVIEW** với nhãn **"Không phản hồi sàng lọc"** (KHÔNG bị từ chối); log: resume no_response, parser/ranker KHÔNG chạy lại.
5. Trả lời trễ: mở lại magic-link sau hạn → thông báo "thời hạn đã qua / đang xem xét".
6. Đối chứng: nộp CV khác + **trả lời trong hạn** → resume bình thường (không nhắc, không timeout).
7. `make test` xanh. (Nhớ trả env về giá trị thật sau verify.)

---

## 5. Definition of Done

- [ ] Seam `ScreeningTimeoutScheduler` + `InProcessScheduler` (sweep loop ở lifespan); handler nghiệp vụ (reminder/timeout) TÁCH riêng, không phụ thuộc cơ chế.
- [ ] Nhắc gửi đúng MỘT LẦN qua scheduler; `reminded_at` chặn lặp.
- [ ] Timeout → resume `no_response` → human_review + cờ, **KHÔNG auto-từ-chối**; parser/ranker không chạy lại.
- [ ] Trả lời trễ xử lý êm (không resume lại, thông báo rõ). HR thấy nhãn no_response.
- [ ] Sweep quét Postgres (KHÔNG Redis), idempotent, lỗi một session không chết cả vòng; chạy trong event loop chính (không dính bẫy asyncio.run).
- [ ] Migration `reminded_at` (+ include_object guard). KHÔNG QStash, KHÔNG auto-mời, KHÔNG LLM chuẩn hóa; checkpointer/token-08b không đổi.
- [ ] `make test` xanh.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: seam scheduler + sweep + handler reminder/timeout + screener node nhánh no_response + template nhắc + trả lời trễ + hiển thị + migration/test. KHÔNG đụng parser/ranker/checkpointer-08a/token-08b logic.
- **Im lặng ≠ từ chối:** timeout LUÔN → human_review, KHÔNG BAO GIỜ auto-reject. scheduler = điểm phát email duy nhất.
- Seam MỎNG: một Protocol + InProcess; handler tách khỏi cơ chế (đổi QStash sau không sửa nghiệp vụ). KHÔNG framework/factory thừa.
- Sweep chạy trong loop chính (asyncio task ở lifespan) — dùng đúng đường async, không asyncio.run per-item.
- Config từ env (deadline/reminder/sweep interval); verify đặt nhỏ rồi TRẢ VỀ giá trị thật. Chạy impact analysis (GitNexus) trước khi sửa screener/policy.
- Commit nhỏ (vd `feat(screener): seam ScreeningTimeoutScheduler + InProcess sweep`, `feat(screener): reminder once + timeout->human_review(no_response)`, `feat(screener): trả lời trễ + hiển thị no_response`, `feat(db): reminded_at migration`, `test(screener): reminder/timeout/late`).
- Nghiệp vụ chưa rõ → **PRD.md** (§10). Vướng kỹ thuật (sweep/resume/loop) → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn: đặt ngưỡng nhỏ rồi trả về), checklist DoD.

## 7. Sau lát này

Screener async ĐẦY ĐỦ (nhận → hỏi → chờ → nhắc → hết hạn/trả lời). Còn **08d** (cổng auto-mời sau screener) là hoàn tất
gate thứ hai + đối xứng auto-reject. Rồi hết GĐ3. Xem ROADMAP.md. (Ghi chú deploy: body-size limit + rate-limit public endpoints; đổi InProcess→QStash — cả hai ở GĐ5.)
