# SLICE SCH-1 — Nền đặt lịch: model + sinh slot + giữ chỗ + xác nhận + seam lịch · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md` §10b** (FR-BOOK-1..5), §16.
> **Mục tiêu:** dựng **tầng nghiệp vụ** cho đặt lịch: bảng dữ liệu, cấu hình khả dụng, **sinh slot lười**,
> **giữ chỗ (HELD) 10 phút**, **xác nhận (HELD→BOOKED) chống race**, và **seam `CalendarProvider`** (mặc định
> `.ics`). Tuân thủ `CLAUDE.md`.
>
> **⚠️ Ranh giới:** SCH-1 **KHÔNG đụng pipeline/graph/scheduler_node**, **KHÔNG có UI**, **KHÔNG gửi email**.
> Nối vào pipeline + trang công khai = **SCH-2**. Nhắc/hết hạn/hủy + HR quản lý = **SCH-3**.
> Lát này là _thư viện nghiệp vụ_ — test độc lập được, chưa ai gọi tới.

---

## 1. In scope / Out of scope

**In scope:**

- Model `InterviewBooking` + `BookingSession` (PRD §16) + migration (**partial unique index** chống trùng).
- **Cấu hình khả dụng toàn cục** qua env (§10b.7) + múi giờ `Asia/Ho_Chi_Minh`.
- Service: `generate_slots(application_id)` (sinh lười + giữ chỗ), `confirm_booking(...)` (HELD→BOOKED, chống race), `release_holds(...)`.
- Seam `CalendarProvider` (`create_event`/`cancel_event`) + `IcsProvider` mặc định (sinh `.ics`).
- Test đầy đủ tầng service (gồm test race thật).

**Out of scope (KHÔNG làm — SCH-2/SCH-3):**

- KHÔNG sửa `scheduler_node`/graph/status pipeline · KHÔNG endpoint công khai · KHÔNG trang chọn giờ · KHÔNG gửi email (SCH-2).
- KHÔNG nhắc/hết hạn/`booking_no_response`/hủy/HR dời lịch (SCH-3).
- KHÔNG Google Calendar (chỉ _chừa seam_; §17).

---

## 2. Prerequisites

- Hardening (nhả connection) đã xong. Sweep loop 08c có sẵn (SCH-3 dùng).
- **Env mới** (đề xuất, Claude Code chốt tên): `BOOKING_TIMEZONE=Asia/Ho_Chi_Minh` · `BOOKING_WORK_DAYS=1-5`
  · `BOOKING_WORK_START=08:00` · `BOOKING_WORK_END=17:30` · `BOOKING_LUNCH=12:00-13:30`
  · `BOOKING_DURATION_MINUTES=60` · `BOOKING_BUFFER_MINUTES=15` · `BOOKING_LEAD_TIME_HOURS=24`
  · `BOOKING_MAX_PER_DAY=4` · `BOOKING_WINDOW_DAYS=14` · `BOOKING_SLOTS_OFFERED=5` · `BOOKING_HOLD_MINUTES=10`
  · `BOOKING_LINK_TTL_HOURS=72`. Cập nhật `.env.example`.

## 3. Việc cần làm

### 3.1 Model + migration

- `InterviewBooking`: id · application_id (FK) · start_at · end_at · status (`HELD`/`BOOKED`/`CANCELLED`) · hold_expires_at (nullable) · created_at.
- `BookingSession`: id · application_id (FK) · token (urlsafe, **KHÔNG one-time**) · expires_at · reminded_at · booked_at · cancelled_at.
- **Migration hand-written** (add table; **include_object guard** — đừng drop bảng checkpoint):
  **partial unique index** `UNIQUE (start_at) WHERE status = 'BOOKED'` → chặn đặt trùng ở tầng DB.
- Thời gian lưu **timestamptz (UTC)**; sinh/hiển thị theo `Asia/Ho_Chi_Minh`.

### 3.2 Cấu hình khả dụng · settings

- Đọc env §2 vào Settings (validate: work_start < work_end; lunch nằm trong giờ làm; duration/buffer > 0).

### 3.3 Sinh slot LƯỜI + giữ chỗ · `booking_service.generate_slots()`

1. **Nếu application này đã có HELD chưa hết hạn → TRẢ VỀ ĐÚNG các slot đó** (KHÔNG giữ thêm).
   ⚠️ Bắt buộc: nếu không, mỗi lần bấm lại link = giữ thêm 5 slot → N lần bấm khóa 5N slot.
2. Sinh slot ứng viên trong cửa sổ `BOOKING_WINDOW_DAYS`: theo ngày làm việc + giờ làm, **trừ nghỉ trưa**,
   bước = duration + buffer, **bỏ slot sớm hơn `LEAD_TIME_HOURS`**.
3. **Loại trừ** slot đã `BOOKED` **hoặc** (`HELD` và `hold_expires_at > now()`), và ngày đã đủ `MAX_PER_DAY`.
4. **Chọn 5 slot trộn** (§10b.4): 2–3 slot **sớm nhất** + 2–3 slot **rải ngày/buổi khác** (sáng lẫn chiều).
5. Ghi 5 dòng `HELD` với `hold_expires_at = now + BOOKING_HOLD_MINUTES`. Trả danh sách.

- Ít hơn 5 slot khả dụng → trả hết những gì có (không lỗi). Không còn slot nào → trả rỗng (SCH-2 xử UI/HR).

### 3.4 Xác nhận · `booking_service.confirm_booking(application_id, booking_id)`

- **Transaction**: khóa dòng (`SELECT … FOR UPDATE`) → kiểm còn `HELD` + chưa hết hạn + đúng application →
  lật `BOOKED` (xóa `hold_expires_at`) → **nhả các HELD anh em** của application đó → commit.
- **Vi phạm partial unique index** (ai đó vừa BOOKED slot này) → bắt `IntegrityError` → trả lỗi rõ để SCH-2 dịch thành **409**.
- HELD đã hết hạn → lỗi "hold hết hạn, xin chọn lại".
- **KHÔNG cần cron dọn hold** (truy vấn đã lọc theo `hold_expires_at`).

### 3.5 Seam `CalendarProvider` + `IcsProvider`

- Interface: `create_event(booking) -> EventRef|bytes`, `cancel_event(ref)`. Chọn qua env (`CALENDAR_PROVIDER=ics`).
- `IcsProvider`: sinh VEVENT hợp lệ (RFC 5545) — **ưu tiên 0-dependency** (tự sinh ~20 dòng) như `html_to_text` của JD-1; nếu cần lib nhẹ thì Claude Code cân nhắc + báo. Đúng múi giờ, có UID + DTSTAMP.
- Chưa gọi ở đâu (SCH-2 đính vào email).

### 3.6 Test

- Sinh slot: tôn trọng giờ làm/nghỉ trưa/lead-time/max-per-day/cửa sổ; loại slot BOOKED và HELD-chưa-hết-hạn; **HELD hết hạn thì slot quay lại khả dụng**.
- **Bấm lại trong lúc còn hold → TRẢ ĐÚNG 5 slot cũ, KHÔNG giữ thêm** (chống rò slot).
- Trộn slot: không phải 5 slot dồn một buổi khi còn ngày khác trống.
- Xác nhận: HELD→BOOKED + nhả anh em; hold hết hạn → lỗi; **race thật** (2 transaction đồng thời cùng slot → đúng 1 thắng, 1 nhận IntegrityError).
- `.ics` sinh ra parse được, đúng giờ theo `Asia/Ho_Chi_Minh`.

## 4. Verify (chạy thật)

1. `make dev-backend` (restart) — migration chạy sạch; **kiểm bảng checkpoint LangGraph còn nguyên**.
2. Script/REPL nhỏ: tạo application giả → `generate_slots()` → in 5 slot (kiểm đúng giờ làm, có trộn ngày/buổi) → gọi lại lần 2 → **ra đúng 5 slot cũ**.
3. `confirm_booking()` một slot → DB: 1 dòng BOOKED, 4 HELD kia đã nhả. Gọi `generate_slots()` cho application khác → **slot vừa BOOKED không xuất hiện**.
4. Thử insert thẳng DB một BOOKED trùng `start_at` → **DB từ chối** (partial unique index hoạt động).
5. Sinh `.ics` → mở bằng ứng dụng lịch (hoặc parse) → đúng ngày/giờ/độ dài.
6. `make test` xanh. Pipeline **không hồi quy** (SCH-1 chưa ai gọi tới — nộp thử 1 CV vẫn chạy như cũ).

## 5. Definition of Done

- [ ] `InterviewBooking` + `BookingSession` + migration (**partial unique index BOOKED**, include_object guard, checkpoint tables nguyên).
- [ ] Cấu hình khả dụng toàn cục qua env + `.env.example`; thời gian UTC trong DB, sinh/hiển thị `Asia/Ho_Chi_Minh`.
- [ ] `generate_slots` sinh **lười** + giữ chỗ 10 phút + **bấm lại trả slot cũ** + trộn 5 slot; loại trừ BOOKED/HELD-còn-hạn/quá-max-ngày/dưới-lead-time.
- [ ] `confirm_booking` transaction HELD→BOOKED + nhả anh em + bắt IntegrityError (cho SCH-2 dịch 409); hold hết hạn → lỗi rõ.
- [ ] Seam `CalendarProvider` + `IcsProvider` (`.ics` hợp lệ, đúng múi giờ), chọn qua env.
- [ ] **KHÔNG đụng pipeline/graph/scheduler_node/UI/email**; `make test` xanh (gồm test race thật).

## 6. Gotchas & quy ước (theo CLAUDE.md)

- **Bấm lại link phải trả slot cũ** — nếu không, N lần bấm khóa 5N slot (rò slot). Đây là bug dễ lọt nhất của lát này.
- **Múi giờ:** lưu timestamptz UTC, sinh/so sánh theo `Asia/Ho_Chi_Minh`. **KHÔNG dùng datetime naive** ở bất kỳ đâu.
- **Partial unique index** là `CREATE UNIQUE INDEX … WHERE status='BOOKED'` — Alembic autogenerate hay bỏ sót/viết sai → **hand-write**; include_object guard.
- **Bẫy `refresh()` (bài học vừa rồi):** `commit=True` kèm `refresh()` **mở lại transaction** → giữ connection qua I/O. Đường confirm là transaction-nặng: commit xong **đừng refresh** nếu không cần.
- Hold hết hạn xử lý **bằng truy vấn lọc**, không cron. `CANCELLED` không chiếm slot (chỉ BOOKED/HELD-còn-hạn mới chiếm).
- Chạy impact analysis trước khi sửa models/migration (**GitNexus — nhớ chạy `npx gitnexus analyze` nếu index chưa có**; không thì grep).
- Commit nhỏ (vd `feat(booking): model + migration partial unique index`, `feat(booking): cấu hình khả dụng + sinh slot lười`, `feat(booking): giữ chỗ + xác nhận chống race`, `feat(booking): seam CalendarProvider + IcsProvider`, `test(booking): slot/hold/race/ics`).
- Nghiệp vụ chưa rõ → **PRD.md §10b**. Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify + checklist DoD.

## 7. Sau lát này

- **SCH-2** (lát dọc, làm hệ thống chạy được): `scheduler_node` gửi **thư mời + link đặt lịch** → `AWAITING_BOOKING`
  (KHÔNG thêm interrupt — đặt lịch ngoài graph); endpoint công khai `GET /api/public/booking/{token}` (gọi
  `generate_slots`) + `POST …/confirm` (409 khi thua race); trang `/booking/{token}`; email xác nhận kèm `.ics`.
  ⚠️ Giữ bất biến 08d: **chỉ đổi trạng thái SAU khi email đã gửi**; dispatch cô lập khỏi error handler.
- **SCH-3** (hoàn thiện): nhắc trước PV 24h · link hết hạn → nhắc 1 lần → `PENDING_REVIEW[booking_no_response]`
  (**KHÔNG auto-reject**) qua sweep 08c · link hủy → nhả slot + báo HR · HR xem/dời/hủy lịch trên dashboard.
