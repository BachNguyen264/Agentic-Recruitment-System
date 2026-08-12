# SPEC — EMAIL-1: Làm chắc tầng gửi email

> Nguồn: `plan.md` (bản nháp một-lát) + đọc code thật ngày **2026-08-10**.
> Nguồn chân lý nghiệp vụ: **`PRD.md` §7.4, §12.4 (FR-NOTI-1)**.
> Bản spec này là thứ được chốt; kế hoạch thi công ở `docs/superpowers/plans/2026-08-10-email-hardening.md`.

---

## 1. Vấn đề

`email_service.send_email()` trả về là hệ thống coi như "đã gửi" và ghi trạng thái ngay. Nhưng
**provider chấp nhận ≠ người nhận nhận được**: bounce xảy ra _bất đồng bộ, vài giây tới vài phút sau_.
Hậu quả: hồ sơ hiển thị "Chờ ứng viên chọn lịch" / "Đã hẹn phỏng vấn" / "Đã từ chối" trong khi ứng
viên **không hề nhận được thư nào**. Đây là lớp *"trạng thái nói dối"* mà các đợt review trước chưa
chạm — chúng kiểm ranh giới **hàm gọi**, không kiểm ranh giới **mạng**.

Kèm theo, ba lỗ nhỏ hơn cùng tầng:

- Resend giới hạn **2 req/s**; sweep loop (08c + SCH-3) có thể bắn nhiều thư trong một vòng → tự đâm
  giới hạn của chính mình, và hiện **không có retry** nên thư đó mất luôn.
- Không có `reply_to`: ứng viên bấm Reply là rơi vào hư không, và `noreply@`-không-hòm-thư bị trừ
  điểm deliverability.
- Chỉ có phần `html`, không có bản `text` → tăng tín hiệu spam.

**Đây là FIX ĐÚNG–SAI, không phải feature mới.** Không phá cam kết đóng băng tính năng.

---

## 2. Quyết định đã chốt (2026-08-10)

| # | Câu hỏi | Chốt |
|---|---------|------|
| 1 | Nền branch | `feature/booking-schedule` **đã merge vào `main`** (commit `c9fa373`). EMAIL-1 tách branch `fix/email-hardening` **trực tiếp từ `main`**. Không còn bài toán rebase 23 commit. |
| 2 | Verify chữ ký webhook | **Tự viết bằng stdlib `hmac`/`hashlib`** — 0 dependency mới, đúng nếp `IcsProvider`/`html_text`. KHÔNG thêm gói `svix`. |
| 3 | `submission_ack` | **Chỉ để dành giá trị `kind`** (+ phân loại bounce sẵn). KHÔNG xây thư xác nhận nộp CV — đó là feature mới, trái `Out of scope` của chính plan và đốt thêm quota Resend cho cả hồ sơ sẽ bị loại. |
| 4 | Bounce thư **`reject`** | **Chỉ gắn cờ, GIỮ `REJECTED`.** KHÔNG hạ về `PENDING_REVIEW`. Lý do: `ReviewCard` chỉ có hai nút — "Duyệt → mời phỏng vấn" (mời một người đã bị từ chối) và "Từ chối → gửi thư từ chối" (bounce vòng hai vào đúng địa chỉ chết). Hạ trạng thái ở đây là lật ngược một quyết định đã ghi mà không mở ra hành động đúng nào. HR thấy nhãn ⚠ và liên hệ thủ công. |

---

## 3. Đối chiếu plan gốc ↔ code thật (những chỗ plan nói LỆCH)

Bốn đính chính bắt buộc, đã kiểm chứng bằng cách đọc code:

**3.1 — `send_email` KHÔNG cần thêm tham số `kind`/`application_id`.**
plan §3.1 viết "thêm tham số `kind` + `application_id`". Nhưng `email_service.send_email` có **đúng
một** nơi gọi: `scheduler._dispatch` ([scheduler.py:69-107](../../apps/backend/app/agents/nodes/scheduler.py#L69-L107)) — và nó **đã sẵn có** cả `mode` (= kind) lẫn
`application_id`, lại đã mở sẵn một `session` để ghi audit. Vậy: `send_email` chỉ cần **trả về**
`resend_email_id`; dòng `email_delivery` do `_dispatch` ghi, **cùng transaction với audit**. Không
một trong 10 nơi gọi `notify_*` phải sửa. Ít code hơn, ít chỗ quên hơn.

**3.2 — Tên `kind` phải lấy đúng chuỗi `mode` đang chạy, KHÔNG bịa tên mới.**
plan §3.1 viết `booking_confirm` / `booking_reminder`. Code thật dùng `mode` = `invite`, `reject`,
`screener`, `screener_reminder`, `booking_confirmed`, `interview_reminder`, `booking_reminder`,
`booking_cancelled`, và các chuỗi này **đã nằm trong `audit_log.action`** dưới dạng
`email_sent:{mode}`. Đặt tên thứ hai là tạo hai từ vựng cho một thứ — đối soát audit ↔ delivery sẽ
không khớp được nữa. **Dùng nguyên chuỗi `mode`.**

**3.3 — plan §3.5 gần như ĐÃ XONG một nửa; phần còn thiếu là "nới ở dev", không phải "siết ở prod".**
`ApplicationCreate.applicant_email` hiện là `EmailStr` — siết ở **CẢ HAI** môi trường, và validate
chạy **trước** `create_application` ở cả hai đường nộp
([public.py:68-71](../../apps/backend/app/api/routes/public.py#L68-L71), [applications.py:47-50](../../apps/backend/app/api/routes/applications.py#L47-L50)) nên "422 trước khi tốn LLM" đã đúng.
Đo thật: `EmailStr` **từ chối** `a@b.local`, `a@localhost`, `hr@company.local`. Vậy delta thực = **cho
phép `.local` khi `APP_ENV=local`** + test hồi quy khoá cả hai chiều.

**3.4 — Miễn trừ rate-limit + Origin cho webhook: ĐÃ ĐÚNG SẴN, chỉ cần khoá bằng test.**
`RateLimitMiddleware._bucket()` ([hardening.py:211-220](../../apps/backend/app/core/hardening.py#L211-L220)) chỉ siết `/api/auth/login`, `/api/health`,
`/api/public/booking*`, `/api/public/applications*`, `/api/public/screening*` — `/api/webhooks/resend`
**không khớp cái nào**. `OriginCheckMiddleware._ok(None) → True` nên request server-to-server không có
header `Origin` **được cho qua**. Cả hai là hành vi ta đang dựa vào mà chưa có test nào giữ; thêm test
để lần sửa `_bucket()` sau không âm thầm nuốt mất sự kiện bounce.

---

## 4. In scope

1. **Bảng `email_delivery`** — lưu vết giao hàng, khoá đối chiếu là `resend_email_id` của Resend.
2. **`send_email` trả `resend_email_id`**; `scheduler._dispatch` ghi một dòng `email_delivery` (kind
   = `mode`, `application_id`, recipient, `SENT`) cùng transaction với audit.
3. **Webhook `POST /api/webhooks/resend`** — verify chữ ký Svix **bắt buộc** (sai → 401, không xử lý
   gì), **idempotent**, cập nhật `status` + `bounce_reason`.
4. **Xử lý bounce theo LOẠI thư** (§5 dưới) — gắn cờ `email_bounced`, hạ trạng thái **có điều kiện**,
   audit. **KHÔNG auto-reject ở bất kỳ nhánh nào.**
5. **Retry + giữ nhịp** — nối tiếp hoá lượt gửi (`asyncio.Lock` + `EMAIL_MIN_INTERVAL_MS`), retry có
   backoff+jitter khi 429-burst/5xx tạm thời, **không** retry lỗi vĩnh viễn, phân biệt **cạn quota ngày**.
6. **`reply_to` + bản `text`** song song `html`.
7. **Validate email: chặt ở prod / nới ở dev** (xem §3.3).
8. **Phơi cho HR** — nhãn ⚠ "Email không gửi được — cần liên hệ thủ công" + lý do bounce rút gọn, ở
   danh sách và trang chi tiết.

## 5. Xử lý bounce — bảng quyết định

Nguyên tắc trên hết (bài học SCH-3 *"hỏi sự thật, đừng hỏi cờ"*): webhook tới **sau vài phút**, HR
hoặc ứng viên có thể đã đi tiếp. Chỉ hạ trạng thái khi hồ sơ **vẫn đang đứng đúng ở trạng thái mà lá
thư đó thiết lập**, và phải hỏi **BẢNG** chứ không chỉ hỏi cờ.

| `kind` | Thư này có phải kênh duy nhất? | Trạng thái thư đó thiết lập | Hành động khi BOUNCED/COMPLAINED |
|---|---|---|---|
| `invite` | **Có** — link đặt lịch chỉ nằm trong thư | `AWAITING_BOOKING` | Cờ `email_bounced` + **nếu** `status == AWAITING_BOOKING` **và** không có hàng `interview_booking` nào `BOOKED` → `PENDING_REVIEW` + `escalation_reason`. Ngược lại: **chỉ cờ**. |
| `screener` · `screener_reminder` | **Có** — magic-link chỉ nằm trong thư | `AWAITING_SCREENER` | Cờ + **nếu** `status == AWAITING_SCREENER` **và** chưa có `screening_session` nào đã nộp câu trả lời → `PENDING_REVIEW` + reason. Ngược lại: chỉ cờ. |
| `reject` | Có, nhưng — xem quyết định #2 §2 | `REJECTED` | **CHỈ gắn cờ** + audit. Giữ nguyên `REJECTED`. |
| `booking_confirmed` · `interview_reminder` · `booking_reminder` · `booking_cancelled` | **Không** — biên nhận (ứng viên đã thấy màn xác nhận trên web / đã tự bấm) | — | **CHỈ gắn cờ** + audit. KHÔNG đổi trạng thái. |
| `submission_ack` | (để dành, chưa có đường phát) | — | Phân loại "kênh duy nhất", nhưng không đường nào tới. |

**Gỡ cờ.** Bài học SCH-3 *"gắn cờ thì phải có đường GỠ cờ"*: khi một sự kiện `email.delivered` tới cho
**cùng application + cùng recipient**, gỡ `email_bounced`. Không có đường gỡ thì hồ sơ mang nhãn báo
động vĩnh viễn và nhãn đó sẽ bị phớt lờ.

**Thứ tự sự kiện không bảo đảm.** Quy tắc chuyển trạng thái giao hàng:
`BOUNCED`/`COMPLAINED` là **cuối** (không bị `delivered`/`sent` tới muộn ghi đè);
`DELIVERED` > `SENT`. Sự kiện trùng ⇒ no-op (Resend gửi lại sự kiện là bình thường).

## 6. Out of scope

Đổi nội dung/thiết kế template (chỉ **thêm** bản text) · đổi luồng nghiệp vụ · đụng
graph/ranker/parser/screener/**booking logic** · thư xác nhận nộp CV (quyết định #3) · DMARC (việc
**DNS**, làm song song — xem §9) · chặn gửi tới địa chỉ đã bounce · UI redesign.

## 7. Env mới

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `EMAIL_REPLY_TO` | `None` | Địa chỉ HR **thật, có hòm thư**. Rỗng = không đặt `reply_to`. |
| `RESEND_WEBHOOK_SECRET` | `None` | `whsec_...` lấy khi tạo webhook trên Resend. Rỗng ⇒ endpoint trả **503** (KHÔNG âm thầm nhận). |
| `RESEND_WEBHOOK_TOLERANCE_SECONDS` | `300` | Cửa sổ chống replay theo `svix-timestamp`. |
| `EMAIL_MIN_INTERVAL_MS` | `550` | Khoảng cách tối thiểu giữa hai lần gọi Resend (giữ dưới 2 req/s). |
| `EMAIL_MAX_RETRIES` | `3` | Số lần thử lại tối đa cho lỗi TẠM THỜI. |

## 8. Definition of Done

- [ ] `email_delivery` + `send_email` trả `resend_email_id`; `_dispatch` ghi dòng có đúng `kind`
      (= `mode`) + `application_id` + recipient.
- [ ] Webhook verify chữ ký (sai/thiếu → **401**, DB không đổi), thiếu secret → 503, quá cửa sổ
      thời gian → 401, **idempotent**.
- [ ] Bounce xử theo đúng bảng §5; **KHÔNG auto-reject**; hạ trạng thái **có điều kiện + hỏi bảng**;
      có đường **gỡ cờ** khi `delivered` về sau.
- [ ] Retry/backoff cho 429-burst + 5xx; **không** retry 400/422/401/403 và **không** retry
      `daily_quota_exceeded`/`monthly_quota_exceeded`; cạn quota log **phân biệt được**; nhiều lượt
      gửi liên tiếp cách nhau ≥ `EMAIL_MIN_INTERVAL_MS`.
- [ ] `reply_to` + bản `text` (dẫn xuất từ `html` nếu caller không truyền).
- [ ] Email sai định dạng ở prod-mode → 422, **pipeline không chạy**; `.local` chạy được ở dev.
- [ ] HR thấy nhãn ⚠ bounce + lý do ở danh sách và chi tiết.
- [ ] Webhook **miễn trừ rate-limit** + qua được `OriginCheckMiddleware` — có test khoá.
- [ ] KHÔNG đụng graph/ranker/parser/screener/booking logic. `make test` xanh; `pnpm build` PASS.

## 9. Việc DNS song song (người làm, không phải code)

- TXT `_dmarc.hireflow.dpdns.org` = `v=DMARC1; p=none; rua=mailto:<email của bạn>` trên Cloudflare.
  (Resend verify domain = SPF + DKIM; **DMARC là bản ghi riêng phải tự thêm** — thiếu nó là nguyên
  nhân hàng đầu khiến Gmail chặn thẳng.) Ổn định rồi có thể siết `p=quarantine`.
- Đo điểm spam bằng **mail-tester.com** (mục tiêu ≥ 8/10); kiểm blocklist bằng MXToolbox.
- Kỳ vọng thực tế: danh tiếng domain mới cần **2–4 tuần**. Với demo đồ án, gửi cho vài người nhận
  đã biết trước là đủ; ghi deliverability là **giới hạn đã biết** trong báo cáo.

## 10. Sau lát này

Merge `fix/email-hardening` → `main` → **đợt scale** (semaphore · parser `ainvoke` · rate-limit
IP+email · nợ connection lúc upload R2 · load test số trước/sau) → **tinh gọn PWA** → **ĐÓNG BĂNG**
→ **báo cáo**.
