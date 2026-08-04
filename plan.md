# SLICE SCH-2 — Nối đặt lịch vào luồng: thư mời + link · trang chọn giờ · xác nhận + .ics · plan one-shot

> **Bản chất:** plan ONE-SHOT. Nguồn chân lý: **`PRD.md` §10b, §12.4 (FR-BOOK-1..2), §13**.
> **Mục tiêu:** biến nền SCH-1 thành luồng chạy thật: quyết định **mời** → thư mời **kèm link đặt lịch** →
> `AWAITING_BOOKING`; ứng viên mở link → **5 slot** (sinh lười) → chọn → `INTERVIEW_SCHEDULED` + email xác
> nhận kèm `.ics`. Tuân thủ `CLAUDE.md` / `docs/AI_GUIDE.md`.
>
> **⚠️ LÁT NHẠY CẢM** — chạm `scheduler_node` + trạng thái cuối + email thật. **KHÔNG thêm `interrupt()`**
> (đặt lịch nằm NGOÀI graph — B2). Giữ nguyên bất biến 08d. Nhắc/hết hạn/hủy/HR-dời-lịch = **SCH-3**.

---

## 1. In scope / Out of scope

**In scope:**

- `scheduler_node` (nhánh **MỜI**): tạo `BookingSession` (token, TTL 72h) → gửi **thư mời + link đặt lịch** → status **`AWAITING_BOOKING`**.
- Endpoint công khai: `GET /api/public/booking/{token}` (→ `generate_slots`) · `POST /api/public/booking/{token}/confirm` (→ `confirm_booking`, thua race → **409**).
- Trang công khai `/booking/{token}`: 5 slot (giờ VN), **đồng hồ đếm ngược hold**, chọn → xác nhận; 409 → tự làm mới danh sách; **`AlreadyBooked` → hiện "bạn đã đặt lúc X"** (KHÔNG render danh sách chọn).
- Email **xác nhận lịch** kèm `.ics` (qua `CalendarProvider` của SCH-1) → `INTERVIEW_SCHEDULED`.
- `AWAITING_BOOKING` vào rổ "đang xử lý" của dashboard + nhãn HR.

**Out of scope (SCH-3):** nhắc trước PV · link hết hạn → `booking_no_response` · hủy · HR dời/hủy lịch.
**KHÔNG:** thêm interrupt/đổi định tuyến graph · đụng ranker/parser/screener/gate logic · Google Calendar.

---

## 2. Prerequisites

- SCH-1 xong (`generate_slots`/`confirm_booking`/`SlotTaken`/`AlreadyBooked`/`IcsProvider`).
- Nhánh **TỪ CHỐI** của scheduler **giữ nguyên** (→ `REJECTED`). Chỉ nhánh MỜI đổi.

## 3. Việc cần làm

### 3.1 `scheduler_node` — nhánh MỜI · `app/agents/nodes/scheduler.py`

- Tạo `BookingSession` (token urlsafe crypto-random như 08b, `expires_at = now + BOOKING_LINK_TTL_HOURS`).
- Soạn **thư mời có link** `{FRONTEND_BASE_URL}/booking/{token}` (nêu rõ hạn 72h) → gửi qua đường email hiện có (`notify_decision` vẫn là **điểm gửi email DUY NHẤT**).
- **THỨ TỰ BẤT BIẾN (08d):** email gửi THÀNH CÔNG rồi mới đặt `AWAITING_BOOKING`. Dispatch **CÔ LẬP** khỏi error handler (đừng để lỗi kỹ thuật sau đó reset trạng thái — lớp "trạng thái nói dối").
- Áp cho **CẢ HAI** đường tới quyết định mời: gate `auto_invite` và HR duyệt ở `/review`.
- `INTERVIEW_SCHEDULED` **KHÔNG còn** đặt ở đây (chuyển sang lúc xác nhận lịch — §3.3).

### 3.2 Endpoint công khai · `app/api/public.py`

- `GET /api/public/booking/{token}`: token hợp lệ + chưa hết hạn → `generate_slots` → trả **projection AN TOÀN**: tiêu đề JD + tên ứng viên + danh sách slot (id, giờ bắt đầu/kết thúc) + `hold_expires_at`. **TUYỆT ĐỐI KHÔNG** rubric/điểm/gate/parsed_data/trạng thái nội bộ (kỷ luật 08b).
  - `AlreadyBooked` → **200** với payload `{already_booked: true, start_at}` (KHÔNG phải lỗi — để UI hiện thông báo).
  - Token sai → 404; hết hạn → 410 (thông báo êm).
- `POST /api/public/booking/{token}/confirm` body `{booking_id}`: → `confirm_booking` → gửi email xác nhận + `.ics` → đặt `INTERVIEW_SCHEDULED` → trả thông tin lịch.
  - `SlotTaken` → **409** (+ danh sách slot mới để UI hiển thị ngay).
  - Hold hết hạn → **409/410** kèm thông báo "phiên giữ chỗ đã hết, mời chọn lại".
- Rate-limit công khai: theo kỷ luật hardening — **không** để một IP khóa cả hệ (đây là trang ứng viên thật).

### 3.3 Thứ tự ghi khi xác nhận (QUYẾT ĐỊNH THIẾT KẾ — đọc kỹ)

1. `confirm_booking` (transaction, DB) — **trước tiên**, vì đây là thứ _thắng race_, phải bền và tức thì.
2. Gửi email xác nhận + `.ics`.
3. Đặt `INTERVIEW_SCHEDULED` + audit.

**Nếu bước 2 lỗi:** booking VẪN giữ (slot đã là sự thật) → vẫn đặt `INTERVIEW_SCHEDULED`, nhưng **ghi audit +
cờ để HR biết cần báo lại thủ công**. Khác 08d một cách có chủ đích: ở 08d email là _kênh thông báo duy nhất_
nên "chưa gửi = chưa mời"; ở đây **ứng viên tự bấm và thấy màn xác nhận trên web** — họ ĐÃ biết. Email chỉ là
biên nhận. Rollback booking chỉ vì email lỗi sẽ _tệ hơn_ (mất slot họ vừa chọn).
→ Nếu Claude Code thấy lập luận này sai, **DỪNG và nêu ý kiến** trước khi làm.

### 3.4 Frontend · trang `/booking/[token]`

- Route **công khai** (ngoài `(hr)` group), không auth. **Code-split** — không kéo bundle HR (bài học JD-1).
- Hiện: tiêu đề JD · 5 slot định dạng giờ VN rõ ràng (vd "09:15 · Thứ Năm 06/08/2026") · **đồng hồ đếm ngược** thời gian giữ chỗ (quyết định SCH-1: không gia hạn) · nút chọn + xác nhận.
- Hết hold giữa chừng → thông báo rõ + nút "Tải danh sách mới" (không đổ lỗi người dùng).
- 409 → thông báo "giờ này vừa có người đặt" + **tự hiện danh sách mới**.
- `already_booked` → màn "Bạn đã đặt lịch lúc X" (KHÔNG render danh sách chọn).
- Hết slot khả dụng → thông báo lịch tạm đầy, HR sẽ liên hệ (không để trang trắng).

### 3.5 Dashboard HR

- `AWAITING_BOOKING` vào rổ **"đang xử lý"** (PRD §13) + nhãn tiếng Việt rõ ("Chờ ứng viên chọn lịch").
- Chi tiết ứng viên: hiện lịch đã đặt (nếu có) — chỉ đọc (dời/hủy = SCH-3).

### 3.6 Test

- `scheduler_node` nhánh mời → tạo session + gửi email (mock) → `AWAITING_BOOKING`; **email lỗi → KHÔNG đặt AWAITING_BOOKING** (bất biến 08d). Nhánh từ chối **không hồi quy** (→ `REJECTED`).
- `GET` projection: **không có** rubric/điểm/gate/parsed_data trong payload (test khẳng định vắng mặt).
- `POST` confirm → BOOKED + email + `INTERVIEW_SCHEDULED`; `SlotTaken` → 409; `AlreadyBooked` → 200 payload đúng; token sai → 404; hết hạn → 410.
- Không hồi quy: parse→rank→screener→gate như cũ (chỉ _đuôi_ nhánh mời đổi).

## 4. Verify (chạy thật — LLM + email thật, dùng email của bạn)

1. Restart backend + dashboard. JD có rubric, **gate auto-mời BẬT**, screener rỗng (đi thẳng) → nộp CV tốt.
2. **Nhận thư mời có link đặt lịch** → trạng thái `AWAITING_BOOKING` (dashboard hiện "Chờ ứng viên chọn lịch").
3. Mở link → thấy **5 slot** giờ VN + đồng hồ đếm ngược. **Mở lại link** (tab khác) → **đúng 5 slot cũ** (không phát thêm).
4. Chọn 1 slot → xác nhận → **email xác nhận kèm `.ics`** (mở được bằng ứng dụng lịch, đúng giờ) → `INTERVIEW_SCHEDULED`.
5. **Mở lại link sau khi đã đặt** → hiện "Bạn đã đặt lịch lúc X", KHÔNG hiện danh sách chọn.
6. **Race thật:** hai trình duyệt (2 ứng viên khác nhau) cùng mở, cùng chọn slot trùng → một thành công, một nhận **409 + danh sách mới**, không ai thấy màn lỗi thô.
7. Đường HR: một ứng viên khác → `/review` → **Duyệt** → cũng ra thư mời + link (không chỉ gate mới có).
8. Ẩn danh gọi API HR → 401 (ranh giới còn nguyên). `make test` xanh; `pnpm build` PASS.

## 5. Definition of Done

- [ ] Nhánh mời: tạo `BookingSession` + thư mời có link → `AWAITING_BOOKING`, **chỉ sau khi email gửi thành công**; dispatch cô lập khỏi error handler; áp cho cả gate lẫn HR-duyệt.
- [ ] Endpoint công khai GET/POST đúng mã lỗi (404/410/409) + **projection an toàn** (không lộ rubric/điểm/gate).
- [ ] Xác nhận → BOOKED → email + `.ics` → `INTERVIEW_SCHEDULED` (thứ tự §3.3).
- [ ] Trang `/booking/[token]`: 5 slot giờ VN · đếm ngược · 409 tự làm mới · `already_booked` · hết-slot; code-split khỏi bundle HR.
- [ ] `AWAITING_BOOKING` trong rổ "đang xử lý" + nhãn HR; chi tiết hiện lịch đã đặt (chỉ đọc).
- [ ] **KHÔNG thêm interrupt/đổi định tuyến graph**; nhánh từ chối không hồi quy; `make test` xanh; `pnpm build` PASS.

## 6. Gotchas & quy ước

- **Bất biến 08d:** đổi trạng thái CHỈ SAU khi email gửi thành công; dispatch **cô lập** khỏi technical-error handler (lớp lỗi "trạng thái nói dối" đã bị bắt ở 03b/08d/JD-2b).
- **`AlreadyBooked` KHÔNG phải lỗi** — là một _trạng thái UI_ (200 + payload). Nếu coi là lỗi, ứng viên thấy màn vỡ khi chỉ mở lại link.
- **Projection công khai**: chỉ tiêu đề JD + tên + slot. Test phải khẳng định _sự vắng mặt_ của rubric/điểm/gate (kỷ luật 08b).
- **Không gia hạn hold** (quyết định SCH-1) → UI **phải** có đếm ngược, nếu không người dùng bị bất ngờ.
- Múi giờ hiển thị: luôn `Asia/Ho_Chi_Minh`, ghi rõ thứ + ngày. **Không** để người dùng tự đoán múi giờ.
- Token đặt lịch **KHÔNG one-time** (khác screener 08b) nhưng **có hạn**; đừng vô tình copy logic one-time.
- Code-split trang công khai (đừng kéo bundle HR vào trang ứng viên — bài học JD-1).
- Chạy `npx gitnexus analyze` rồi impact analysis trước khi sửa scheduler. **Adversarial review** (chạm scheduler + email thật + trạng thái cuối).
- Commit nhỏ (vd `feat(booking): scheduler gửi link đặt lịch → AWAITING_BOOKING`, `feat(api): endpoint booking công khai`, `feat(ui): trang chọn giờ`, `feat(booking): email xác nhận + ics`, `test(booking): luồng + projection + race`).
- Nghiệp vụ chưa rõ → **PRD.md §10b**. Vướng (nhất là §3.3) → **DỪNG, hỏi**.

## 7. Sau lát này

**SCH-3:** nhắc trước PV 24h · link hết hạn → nhắc 1 lần → `PENDING_REVIEW[booking_no_response]` (**KHÔNG
auto-reject**, dùng sweep 08c) · link hủy → nhả slot + báo HR · HR xem/dời/hủy lịch. Rồi: **đợt scale**
(semaphore · parser `ainvoke` · rate-limit theo IP+email · nợ giữ-connection lúc upload R2) → **tinh gọn PWA**
→ **đóng băng** → **báo cáo**.
