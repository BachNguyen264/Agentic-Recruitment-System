# SLICE SCH-3 — Vòng đời lịch: nhắc · hết hạn · hủy · HR quản lý · báo hết slot · plan one-shot

> **Bản chất:** plan ONE-SHOT — **khép feature đặt lịch**. Nguồn chân lý: **`PRD.md` §10b.6** (FR-BOOK-3..4), §13.
> **Mục tiêu:** lo phần _sau khi link đã gửi_: nhắc trước buổi PV · link hết hạn không phản hồi · ứng viên hủy ·
> HR hủy/gửi lại link · **báo HR khi hết khung giờ**. Tuân thủ `CLAUDE.md` / `docs/AI_GUIDE.md`.
>
> **Ranh giới:** dùng **sweep loop 08c sẵn có** (không cơ chế nền mới). KHÔNG đụng graph/ranker/parser/screener.
> KHÔNG Google Calendar. KHÔNG auto-reject bất kỳ đâu.

---

## 1. In scope / Out of scope

**In scope:**

- **Nhắc trước buổi PV** (mặc định 24h) — email + `.ics`, một lần.
- **Link hết hạn:** nhắc 1 lần trước hạn → hết hạn chưa đặt → `PENDING_REVIEW` + cờ `booking_no_response` (**KHÔNG auto-reject**).
- **Ứng viên hủy:** link hủy trong thư xác nhận → nhả slot → quay lại `AWAITING_BOOKING` (chọn lại được trong hạn cũ) + báo HR.
- **HR:** _Hủy lịch_ (nhả slot + báo ứng viên → `PENDING_REVIEW`) và _Gửi lại link đặt lịch_ (→ `AWAITING_BOOKING`). Hai nút này **ghép lại thành "đổi lịch"** — không làm luồng dời-lịch riêng.
- **Hết khung giờ:** ứng viên mở link mà không còn slot → ghi nhận + **nhãn riêng trên dashboard** ("Hết khung giờ — cần mở thêm lịch"), KHÔNG để nhãn "Chờ ứng viên chọn lịch" đổ lỗi nhầm người.

**Out of scope:** dời-lịch một-chạm (dùng hủy + gửi lại link) · lịch bận theo người phỏng vấn · Google Calendar (§17) · thay đổi thuật toán sinh slot.

---

## 2. Prerequisites

- SCH-1 + SCH-2 xong. Sweep loop 08c đang chạy (nhắc/timeout screener) — SCH-3 **thêm handler vào cùng cơ chế**.
- **Chỉnh config sức chứa TRƯỚC khi verify** (vấn đề Claude Code nêu ở SCH-2): `BOOKING_MAX_PER_DAY=6` ·
  `BOOKING_WINDOW_DAYS=21` · `BOOKING_HOLD_MINUTES=5` → ~90 khung giờ, ~18 người xem đồng thời mới cạn
  (trước: ~36 khung, 7 người). Cập nhật `.env.example` + checklist prod.
- Cột mới (migration hand-written, **include_object guard**): `InterviewBooking.reminder_sent_at` ·
  `BookingSession.no_slots_at` (đánh dấu lần đầu ứng viên gặp trang hết slot).

## 3. Việc cần làm

### 3.1 Nhắc trước buổi phỏng vấn · handler mới trong sweep

- Quét `InterviewBooking` `status=BOOKED`, `reminder_sent_at IS NULL`, `start_at` trong khoảng
  `now + BOOKING_INTERVIEW_REMINDER_HOURS` (mặc định 24h) → gửi email nhắc + `.ics` → set `reminder_sent_at` (**idempotent**).
- Bỏ qua booking đã `CANCELLED` và buổi đã qua.

### 3.2 Link hết hạn · handler mới trong sweep

- **Nhắc 1 lần** ở `BOOKING_REMINDER_HOURS` trước `expires_at` (session chưa `booked_at`/`cancelled_at`, `reminded_at IS NULL`) → email nhắc "còn X giờ để chọn lịch" → set `reminded_at`.
- **Hết hạn** (`expires_at < now`, chưa đặt) → application → `PENDING_REVIEW` + cờ **`booking_no_response`** + audit + nhả HELD còn sót. **NEVER auto-reject** (đối xứng FR-SCR-3: im lặng ≠ từ chối).
- Idempotent (đã xử lý thì không lặp).

### 3.3 Ứng viên hủy · endpoint công khai

- `POST /api/public/booking/{token}/cancel` → booking `BOOKED → CANCELLED` (slot nhả ngay) → application về **`AWAITING_BOOKING`** (link cũ còn hạn thì chọn lại được) → email xác nhận đã hủy + **báo HR** (audit + nhãn dashboard).
- Link hủy nằm trong **thư xác nhận lịch** (SCH-2). Dùng **chính token đó** (không one-time).
- Nếu link đã hết hạn khi hủy → application → `PENDING_REVIEW` (cờ `booking_cancelled`), HR xử tiếp.
- **Vòng lặp bị chặn tự nhiên** bởi TTL 72h gốc (KHÔNG gia hạn khi hủy) → hết hạn thì §3.2 lo.

### 3.4 HR quản lý lịch · dashboard

- Chi tiết ứng viên (đã `INTERVIEW_SCHEDULED`): hiện lịch + hai nút:
  - **Hủy lịch** → `CANCELLED` + nhả slot + email báo ứng viên + → `PENDING_REVIEW` + audit.
  - **Gửi lại link đặt lịch** → session mới (TTL mới) + email mời chọn lại → `AWAITING_BOOKING` + audit.
- Ghép hai nút = "đổi lịch" (không viết luồng dời riêng). Cả hai **auth-gated** (`require_hr`).

### 3.5 Báo HR khi hết khung giờ

- `GET /api/public/booking/{token}` trả **0 slot** → set `no_slots_at` (lần đầu) + audit.
- Dashboard: nhãn riêng **"Hết khung giờ — cần mở thêm lịch"** (khác "Chờ ứng viên chọn lịch"), để HR biết _hệ thống_ đang chặn chứ không phải ứng viên chậm.
- Trang ứng viên: thông báo lịch tạm đầy + "HR sẽ liên hệ" (đã có ở SCH-2 — nay có thêm vế báo HR).

### 3.6 Test

- Nhắc PV: đúng cửa sổ 24h, gửi một lần, bỏ qua CANCELLED/đã qua.
- Hết hạn: nhắc 1 lần → hết hạn → `PENDING_REVIEW[booking_no_response]`, **KHÔNG auto-reject**, idempotent.
- Hủy (ứng viên): slot nhả → chọn lại được; slot vừa nhả **xuất hiện lại** cho ứng viên khác.
- HR hủy / gửi lại link: đúng trạng thái + email + audit; chưa đăng nhập → 401.
- Hết slot: `no_slots_at` được set + nhãn dashboard đúng.
- Không hồi quy: luồng SCH-2 (mời → chọn → xác nhận) nguyên vẹn.

## 4. Verify (chạy thật — email thật của bạn)

1. Áp config sức chứa mới (§2) + restart. Kiểm `generate_slots` giờ cho nhiều khung hơn.
2. Đặt `BOOKING_INTERVIEW_REMINDER_HOURS` tạm ngắn → tạo booking sắp tới → sweep chạy → **nhận email nhắc + .ics**, chạy lần 2 → **không gửi lại**.
3. Đặt `BOOKING_LINK_TTL_HOURS` tạm ngắn → gửi mời, **không** đặt lịch → nhận **email nhắc** → hết hạn → hồ sơ về `PENDING_REVIEW` nhãn `booking_no_response` (**không** bị từ chối).
4. Đặt lịch → mở **link hủy** trong thư xác nhận → hủy → nhận email xác nhận hủy → hồ sơ về `AWAITING_BOOKING` → mở lại link → **chọn được slot khác**; slot vừa nhả hiện lại cho ứng viên khác.
5. HR: **Hủy lịch** → ứng viên nhận email + hồ sơ `PENDING_REVIEW`. **Gửi lại link** → ứng viên nhận thư chọn lại → `AWAITING_BOOKING`.
6. Ép hết slot (tạm hạ `MAX_PER_DAY`/`WINDOW_DAYS`) → mở link → trang báo lịch đầy + dashboard hiện **"Hết khung giờ"**.
7. `make test` xanh; `pnpm build` PASS; luồng SCH-2 không hồi quy.

## 5. Definition of Done

- [ ] Nhắc trước PV 24h (email + `.ics`), một lần, idempotent.
- [ ] Link hết hạn: nhắc 1 lần → `PENDING_REVIEW[booking_no_response]`, **KHÔNG auto-reject**; HELD sót được nhả.
- [ ] Ứng viên hủy: nhả slot → `AWAITING_BOOKING` (chọn lại trong hạn cũ) + báo HR; hết hạn → `PENDING_REVIEW`.
- [ ] HR: **Hủy lịch** + **Gửi lại link** (auth-gated, có email + audit) — ghép thành "đổi lịch".
- [ ] Hết khung giờ: `no_slots_at` + **nhãn dashboard riêng** (không đổ lỗi ứng viên).
- [ ] Config sức chứa mới áp dụng + `.env.example`; **KHÔNG đụng graph/ranker/parser/screener**; `make test` xanh; `pnpm build` PASS.

## 6. Gotchas & quy ước

- **KHÔNG auto-reject ở bất kỳ nhánh nào** — hết hạn/hủy đều về người (bất biến xuyên dự án: im lặng ≠ từ chối).
- **Hủy KHÔNG gia hạn TTL** — nếu gia hạn, ứng viên hủy-đặt-hủy vô hạn. TTL gốc chặn vòng lặp tự nhiên.
- **Bẫy ORM sau commit/rollback** (bài học `refresh()` + lỗi #3 SCH-2): trong handler lỗi/log, **đừng chạm thuộc tính object đã expire** (lazy-load → `PendingRollbackError`). Lấy sẵn id/giá trị ra biến cục bộ TRƯỚC khi commit.
- **Idempotent bằng cột mốc thời gian** (`reminder_sent_at`/`reminded_at`/`no_slots_at`), không đếm.
- Sweep là **cơ chế**; handler nghiệp vụ tách riêng (giữ seam 08c để đổi QStash sau không phải sửa nghiệp vụ).
- Nhả slot phải **tức thì** khi hủy (không chờ cron) — slot là tài nguyên tranh chấp.
- Chạy `npx gitnexus analyze` + impact analysis trước khi sửa sweep/booking_service. **Adversarial review** (chạm email thật + trạng thái + tài nguyên tranh chấp).
- Commit nhỏ (vd `feat(booking): nhắc trước buổi PV`, `feat(booking): hết hạn → booking_no_response`, `feat(booking): ứng viên hủy lịch`, `feat(hr): hủy/gửi lại link đặt lịch`, `feat(hr): nhãn hết khung giờ`, `test(booking): vòng đời lịch`).
- Nghiệp vụ chưa rõ → **PRD.md §10b.6**. Vướng → **DỪNG, hỏi**.

## 7. Sau lát này — **HẾT FEATURE ĐẶT LỊCH**

Còn lại theo kế hoạch GVHD giao: **đợt scale** (semaphore · parser `ainvoke` · rate-limit theo IP+email ·
nợ giữ-connection lúc upload R2 · load test có số trước/sau) → **tinh gọn PWA mobile** (chỉ dashboard +
duyệt ứng viên + đăng nhập) → **ĐÓNG BĂNG TÍNH NĂNG** → **viết báo cáo ~60 trang**.
