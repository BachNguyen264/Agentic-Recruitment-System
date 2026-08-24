# SPEC — PWA mobile: tinh gọn màn · thông báo đẩy · giao diện offline

> Nguồn: yêu cầu người dùng ngày **2026-08-24** + đọc code thật (7 mũi khảo sát + 4 mũi phản biện độc lập).
> Nguồn chân lý nghiệp vụ: **`PRD.md` §14, §12.3 (FR-HR-3), §12.4 (FR-NOTI-2), §17, NFR-4**.
> Bản spec này là thứ được chốt; kế hoạch thi công viết riêng cho **từng slice** (xem §9).

---

## 1. Vấn đề

PWA hiện **không phải một bản dựng riêng**. `manifest.ts` có `start_url: "/"` và `sw.js` là một cache
tĩnh 38 dòng, nên cài PWA = bọc **toàn bộ website** vào một cửa sổ standalone. HR trên điện thoại thấy
đủ 5 mục điều hướng, trong đó có bảng điều hành 415 dòng, trình soạn JD và màn kiểm tra CV — những thứ
không dùng được trên màn 390px.

**Điều này lệch chính PRD của dự án.** `PRD.md:454-462` (§14) đã ghi sẵn cột "Điện thoại (PWA, HR)":
Quản lý JD ❌ · Dashboard giám sát agent ❌ · Bật/tắt gate ❌ · Thống kê ❌ · Xem danh sách CV ✅ ·
Chi tiết CV ✅ **rút gọn** · Duyệt/từ chối ✅ **nhanh**. Code mới là cái đi lệch, không phải yêu cầu.

Ba việc cần làm, theo lời người dùng: (1) tinh gọn còn login + màn ứng viên + hàng đợi duyệt nhanh,
(2) thông báo đẩy khi có ca cần review, (3) giao diện offline.

Ngoài ra khảo sát phát hiện **một lỗi có thật đang chạy trên bản live**, không liên quan tới PWA nhưng
chặn đường làm offline — xem §5 (BUG-1).

---

## 2. Quyết định đã chốt (2026-08-24)

| # | Câu hỏi | Chốt | Lý do |
|---|---------|------|-------|
| 1 | Tinh gọn dựa trên gì | **Chỉ khi mở từ icon đã cài** (`display-mode: standalone` \|\| `navigator.standalone`) | Đúng nguyên văn yêu cầu. Mở bằng trình duyệt điện thoại vẫn thấy đủ site — không hồi quy cho ai |
| 2 | Deep-link vào màn đã ẩn | **Chuyển về `/review`** + dòng chữ "Màn này chỉ có trên bản máy tính" | Không bao giờ để giao diện desktop bị bóp trên 390px, cũng không tạo ngõ cụt |
| 3 | "Màn ứng viên" là gì | **Danh sách + chi tiết rút gọn, CHỈ ĐỌC** | Đúng `PRD.md:457-458`. Mọi hành động quyết định dồn về `/review` |
| 4 | Độ sâu push | **Web Push thật (VAPID)** — app đóng vẫn nhận | "Thông báo đẩy" đúng nghĩa. Kéo theo: **phải sửa PRD trước** (§3) |
| 5 | Nội dung push | **CHỈ số đếm** — payload đúng `{c, id}`, không tên, không điểm, không lý do | §4.3 |
| 6 | Độ bền push | **Đối soát bằng predicate trong sweep loop 08c sẵn có** + 1 lời gọi trực tiếp sau commit ở đường CV mới | Chết giữa chừng ⇒ TRỄ (≤ `SCREENER_SWEEP_INTERVAL_SECONDS`), không MẤT. Không dựng cơ chế nền mới (`AI_GUIDE.md:101-102`) |
| 7 | Độ sâu offline | **Chỉ trang "Mất kết nối" có thương hiệu.** Không cache dữ liệu nghiệp vụ | Rủi ro dữ liệu cũ = 0; NFR-4 không bị đụng |
| 8 | Máy demo | **Cả iOS lẫn Android** | ⇒ **bắt buộc** có màn hướng dẫn "Thêm vào Màn hình chính" (§4.5) |
| 9 | FR-BOOK-4 trên điện thoại | **Sửa PRD §14**: thêm dòng `Huỷ / gửi lại link đặt lịch \| ✅ \| ❌ \| —` | Hai nút này GỬI EMAIL THẬT + có xác nhận hai bước; giữ nguyên tinh thần chỉ-đọc |

---

## 3. Sửa PRD & ROADMAP — **làm TRƯỚC khi viết code**

PRD hôm nay **tự mâu thuẫn về push**: `PRD.md:459` (bảng §14) đã hứa "✅ nhanh + push", nhưng
`PRD.md:349` (FR-HR-3) và `PRD.md:406` (FR-NOTI-2) đều đẩy sang §17, còn `PRD.md:511` (§17) liệt kê
"Web push notification xuyên nền tảng cho HR" là **ngoài phạm vi**.

Sửa **tại chỗ, không đẻ ID mới** (FR-NOTI-2 vốn ĐÃ LÀ yêu cầu thông báo cho HR):

| # | Chỗ sửa | Nội dung |
|---|---------|----------|
| 3.1 | `PRD.md:511` | **Xoá** dòng "Web push notification xuyên nền tảng cho HR (đặc biệt trên iOS…)" khỏi §17 |
| 3.2 | `PRD.md:349` (FR-HR-3) | Xoá ngoặc "(Web push đẩy thật: xem §17.)"; ghi push thật đã trong phạm vi |
| 3.3 | `PRD.md:406` (FR-NOTI-2) | Sửa tại chỗ: badge **+ web push** tới HR khi có ca cần review. **Ghi rõ: nội dung thông báo chỉ là SỐ ĐẾM, không chứa dữ liệu cá nhân** |
| 3.4 | `PRD.md:464-465` (ghi chú §14) | Câu "cột 'Điện thoại' là ưu tiên hiển thị trên màn hình nhỏ" bị quyết định #1 phủ định — sửa thành: rút gọn **khi chạy ở chế độ đã cài (standalone)**; mở bằng trình duyệt vẫn đủ màn |
| 3.5 | `PRD.md` §14 bảng | **Thêm 2 dòng** để bảng thành đầy đủ (sau slice này bảng §14 là SPEC mà guard thi hành — mọi route không có trong bảng là ca chưa định nghĩa): `Kiểm tra CV \| ✅ \| ❌ \| —` và `Huỷ / gửi lại link đặt lịch \| ✅ \| ❌ \| —` |
| 3.6 | `PRD.md:458` | Dòng "Chi tiết CV (parse, điểm, **trace**)" ghi ✅ rút gọn cho điện thoại ⇒ bản rút gọn **giữ `AgentTrace`** (thu gọn được, không được bỏ) |
| 3.7 | `PRD.md:474` (NFR-4) | Thêm mệnh đề: PWA **không lưu dữ liệu nghiệp vụ xuống đĩa thiết bị**; nội dung push không chứa dữ liệu cá nhân |
| 3.8 | `PRD.md` §12.x | Thêm **FR-PWA-1** (đúng nếp `FR-<AREA>-<n>`): PWA ở chế độ đã cài rút gọn còn login + ứng viên (chỉ đọc) + hàng đợi duyệt; mất mạng hiện trang "Mất kết nối" |
| 3.9 | `ROADMAP.md:248` | **Xoá** "cross-platform web push (iOS)" khỏi PHASE 8 |
| 3.10 | `ROADMAP.md` | Thêm BUG-1 / PWA-1 / NOTI-1a / NOTI-1b theo nếp `PREFIX-n`; nêu rõ NOTI-1 là **thăng cấp một mục Phase-8** |

---

## 4. Đính chính bản nháp ↔ code thật (những chỗ bản nháp nói LỆCH)

Phản biện bắt được các chỗ sau; ghi lại vì mỗi cái đều đổi thiết kế.

### 4.1 — KHÔNG có "chokepoint" để gom, và bản nháp đếm thiếu 2 điểm quan trọng nhất

Có **10 điểm ghi `status = PENDING_REVIEW`**, không phải 9. Hai điểm quan trọng nhất
— [background.py:268](../../apps/backend/app/tasks/background.py#L268) và
[background.py:433](../../apps/backend/app/tasks/background.py#L433) — ghi `application.status = persisted_status`,
tức một **biến** lấy từ state của graph. Grep chữ `PENDING_REVIEW` không thấy chúng, mà đó lại là
**đường đi thường gặp nhất** của một CV bình thường (node `human_review` chỉ trả dict, không đụng DB —
`agents/nodes/human_review.py:44-51`).

⇒ **Bỏ hẳn ý tưởng `review_queue.enter_review()` gom 10 chỗ.** Nó không áp được ở đúng hai chỗ đông
nhất, và 10 chỗ đó **bất đồng về `uncertainty_flags`**: ghi đè (`background.py:277`), trộn
(`:448-450`), cộng thêm (`booking_flow.py:493`), đặt từ trước (`email_delivery.py:402`), không đụng
(4 chỗ còn lại). Gom lại là abstraction cho code không cùng ngữ nghĩa — trái nguyên tắc 2 của CLAUDE.md.

**Thay bằng:** một **predicate trên DB** (§4.2). Không sửa 10 chỗ đó dòng nào.

Một dữ kiện then chốt làm việc này khả thi: `get_session` (`core/database.py:31-34`) **chỉ yield rồi
close, không bao giờ commit lúc teardown**. Mọi commit đều là một dòng code tường minh — không có ca
"commit nằm trong dependency không móc được".

### 4.2 — Điều kiện bắn: KHÔNG phải "status đổi", cũng KHÔNG phải so `updated_at`

- `old != PENDING_REVIEW && new == PENDING_REVIEW` **nuốt mất** ca gửi thư mời thất bại:
  [review.py:70-73](../../apps/backend/app/services/review.py#L70-L73) cố tình **giữ nguyên**
  `PENDING_REVIEW` trong lúc thư đang bay, rồi [booking_flow.py:211](../../apps/backend/app/services/booking_flow.py#L211)
  ghi `PENDING_REVIEW` lần nữa. old == new ⇒ im lặng. Mà đó chính là ca `PRD.md:400-402` (FR-BOOK-4)
  bắt buộc phải "báo HR".
- `review_notified_at < updated_at` cũng sai: `TimestampMixin.updated_at` dùng `onupdate=func.now()`
  (`models/base.py:21-22`), Postgres `now()` = **thời điểm mở transaction**, nên chính lượt UPDATE đóng
  dấu cũng bump `updated_at` → hai giá trị bằng nhau. Còn nếu ghi dấu từ Python thì lệch đồng hồ theo
  chiều Python-chậm-hơn làm predicate **luôn đúng ⇒ bắn lại cùng một ca mỗi 10 phút, mãi mãi**.

**Chốt — so LÝ DO:**

```sql
status = 'PENDING_REVIEW'
AND review_notified_reason IS DISTINCT FROM escalation_reason
```

`escalation_reason` được đặt ở **100% cả 10 điểm ghi**, vốn đã là câu tiếng Việt mô tả "vì sao hồ sơ
này đang nằm trong hàng đợi". Miễn nhiễm lệch đồng hồ, miễn nhiễm `onupdate` tự kích. Đã kiểm: đóng
dấu có bump `updated_at` nhưng `PENDING_REVIEW ∉ IN_FLIGHT_STATUSES` (`models/application.py:88-95`)
nên **không** làm nhiễu lưới `stuck_applications` (`stuck_applications.py:114`).

### 4.3 — Payload push: nội dung là dữ liệu cá nhân, không phải "chi tiết cho tiện"

Bản nháp định cho `full_name` + `escalation_reason` vào body. `escalation_reason` là văn xuôi **có
kèm điểm số**: `"Hồ sơ đạt {score}/100 (ngưỡng {threshold})…"` (`agents/nodes/human_review.py:33-36`).

Nội dung thông báo **sau khi giải mã** nằm ở: màn khoá · bản nhân bản iCloud sang Mac/iPad · Wear OS /
Android Auto · **mọi app Android có quyền notification-listener** (quyền rất hay được cấp) ·
`registration.getNotifications()` đọc lại được toàn bộ. `PRD.md:517` ghi hard-delete dữ liệu cá nhân
là **ngoài phạm vi** ⇒ không có đường thu hồi. Và NFR-4 (`PRD.md:474`) yêu cầu **có phương án chạy
local không đẩy dữ liệu ra cloud nước ngoài** — Web Push không có lựa chọn local nào (APNs/FCM/Mozilla
là endpoint duy nhất trình duyệt cấp). Repo này thậm chí đã từ chối cả presigned URL cho CV vì NFR-4
(`AI_GUIDE.md:68`); đưa họ tên vào push là kiểm soát **yếu hơn** cái đã bị bác.

**Chốt — payload đúng thế này, không thêm gì:**

```json
{ "c": 3 }
```

`c` = số ca `PENDING_REVIEW` hiện tại. Số tổng hợp, **không phải dữ liệu cá nhân** — đã có sẵn ở
`counts["PENDING_REVIEW"]` (`schemas/application.py:89-98`). **Không có trường nào khác, kể cả `id`.**

SW dựng chữ: title `"HireFlow"`, body `"N hồ sơ đang chờ duyệt"`. **`tag: "review-queue"` — MỘT tag
duy nhất**, không phải tag theo hồ sơ: một thông báo tồn dư luôn-cập-nhật, vừa ít nhận dạng hơn vừa
xoá luôn bài toán gộp/trùng.

**Đích khi bấm vào: luôn là `/review`.** Không kèm `id`, vì (a) `/review` mới là nơi có nút quyết
định — màn chi tiết trên PWA là **chỉ đọc** (quyết định #3), nên deep-link tới đó là dẫn HR vào ngõ
cụt; (b) body đã là số đếm gộp nên "hồ sơ nào" không có nghĩa; (c) `/review` hiện **không đọc query
param** nào (không có `useSearchParams` trong file), nên `?app=<id>` sẽ là tham số chết.

### 4.4 — CSRF: `OriginCheckMiddleware` đã lo, **đừng dựa vào preflight**

Bản nháp viết "POST có thân JSON ⇒ ép preflight ⇒ an toàn". **Sai ở prod**: `next.config.mjs:25-28`
proxy `/api/*` qua chính origin của frontend, nên request là **same-origin** ⇒ CORS không áp dụng ⇒
**không hề có preflight**. Lý lẽ đó chỉ đúng ở dev (nơi không cần tới nó).

Thứ thực sự bảo vệ là `OriginCheckMiddleware` ([hardening.py:350-362](../../apps/backend/app/core/hardening.py#L350-L362)):
**không lọc path**, chặn theo method (`_STATE_CHANGING` gồm POST và DELETE) ⇒ `/api/push/*` **đã được
bảo vệ sẵn, 0 công**. Và repo đã ghi rõ mình từng bị bỏng vì đúng lý lẽ preflight:
`hardening.py:324-327` — *"Trước SCH-3, mọi mutation HR đều nhận thân JSON nên bị ép preflight và an
toàn một cách TÌNH CỜ… nên sự tình cờ đó hết hiệu lực."*

**Một điểm dư cần GHI LẠI, không phải sửa:** `_ok()` (`hardening.py:343-348`) **cho qua khi thiếu
header `Origin`**, có chủ ý (*"không phải trình duyệt → không có cookie ambient để lợi dụng"*). Nghĩa
là kiểm soát CSRF của `/api/push/*` thực chất là "trình duyệt CÓ gửi `Origin`" **và** "edge của Vercel
CÓ chuyển tiếp nó". Nếu Vercel bao giờ đó cắt header này, kiểm soát suy giảm **âm thầm**.

### 4.5 — Dependency: `pywebpush` là lựa chọn **nhỏ hơn**, và `cryptography` là chi phí thật

Bản nháp ngụ ý phương án "tự viết async" nhẹ hơn. Ngược lại: `py-vapid` **và** `http-ece` đều kéo
`cryptography`, nên tự viết = **cùng bộ dependency, trừ đi một gói wrapper thuần Python, cộng thêm
code ECDH/HKDF/AES-GCM tự tay**. Đồng thời `requests` (pywebpush dùng) **đã có sẵn miễn phí** qua
`resend` (`pyproject.toml:26`), và sống sót qua `uv sync --frozen --no-dev` (`Dockerfile:43,48`).
Cũng không có "httpx async client sẵn có" nào cả — `grep httpx app/` **0 kết quả**; httpx là dep
dev, chỉ vào prod theo đường transitive.

⇒ **Dùng `pywebpush` + `asyncio.to_thread`** (đúng tiền lệ `R2Storage` bọc boto3, `storage/r2.py:111`).
**Bắt buộc truyền `timeout=`** — `requests` **không có timeout mặc định**, mà pool `to_thread` là pool
mặc định dùng chung, chưa cấu hình, và `parser.py:137` đã chiếm nó ~10s mỗi CV.

### 4.6 — Lỗi màn trắng: cơ chế đúng, nhưng ca kích hoạt bản nháp mô tả SAI

`onlineManager` của TanStack **không bao giờ đọc `navigator.onLine`** (khởi tạo cứng `#online = true`,
chỉ gắn listener `online`/`offline`). Nên mở PWA **nguội** lúc đang offline thì query **vẫn chạy thật**
→ `fetch` reject → `retry:false` → rơi vào nhánh `isError` "Không kết nối được máy chủ"
(`(hr)/layout.tsx:153-168`), **không phải màn trắng**. Màn trắng chỉ xảy ra khi app đang chạy rồi mới
rớt mạng và một layout `(hr)` mới mount.

⇒ `onlineManager.setOnline(navigator.onLine)` lúc khởi động là **điều kiện tiên quyết**, không phải
tuỳ chọn. **Và nó phá một tiền đề của PWA-1**: hiện "không nháy menu" dựa vào việc `isLoading` luôn
true ở lần render đầu; sau khi seed, mở nguội lúc offline làm query bị *paused* ⇒ `isLoading` false
⇒ cổng chờ không giữ nữa. **PWA-1 phải tự dựng cổng riêng** (`usePwaMode() !== undefined`), không
mượn cổng của `getMe`.

### 4.7 — Rò rỉ suýt gây ra: `providers.tsx` là provider **GỐC**

`app/layout.tsx:49` bọc `<Providers>` quanh **toàn bộ** app. Đặt `mutations: { networkMode: "always" }`
ở đó sẽ âm thầm đổi hành vi offline của **luồng ứng viên công khai**: nộp CV
(`components/CVUpload.tsx`), đặt lịch (`booking/[token]`), trả lời sàng lọc (`screening/[token]`).
⇒ Đặt option đó **riêng ở mutation của `/review`**, không đặt ở QueryClient gốc.

Cùng loại: `PWARegister` đăng ký SW ở scope `/` (`app/layout.tsx:50`) ⇒ trang `/offline` **cũng phục
vụ khách vãng lai** mất sóng ở `/booking/{token}`. Chữ trên trang đó phải trung tính, không mang giọng
HR.

### 4.8 — Các đính chính nhỏ hơn (đã kiểm bằng đọc file)

| Bản nháp nói | Thực tế |
|---|---|
| `sw.js` có nhánh chặn `/api/*` cần "giữ" | **Không có.** `sw.js:23-27` là **allowlist** cho `/_next/static/`; mọi thứ khác vốn đã rơi qua |
| `install` rỗng | Có `self.skipWaiting()` (`sw.js:8-10`). Nó không **precache**, khác với "rỗng" |
| Chi tiết hồ sơ có 3 nút | **6 phần tử tương tác** (1 Link + 5 button) ở `applications/[id]/page.tsx:83, :124, :283, :291, :301, :337` — kèm 3 khối vỏ sẽ mồ côi nếu chỉ ẩn nút: `:123-151`, `:330-346`, `:348-355` |
| Bảng `/applications` "tràn màn hình" | Nó nằm trong `overflow-x-auto` ⇒ **cuộn ngang trong khung của nó**, không cắt mất gì. Cột "Trạng thái" chỉ **khuất** cho tới khi cuộn |
| `btn()` "dưới mức tối thiểu 44px" | 44px là WCAG **2.5.5 AAA**/Apple HIG. Mức **AA (2.5.8) là 24×24** — ghost 25.5px **đã đạt**. Không phải vi phạm |
| Đổi `start_url` sang `/review` | **Bỏ.** Guard đã tự chuyển `/` → `/review`. Đổi manifest thì Chromium coi là app khác (phải thêm `id: "/"`), còn Safari **không đọc lại manifest** ⇒ máy iOS phải xoá icon cài lại. Không đáng để tiết kiệm một lần redirect |

---

## 5. Slice BUG-1 — sửa hành vi offline của TanStack (**ship TRƯỚC, một mình**)

**Vì sao tách riêng:** đây là lỗi có thật trên bản live **hôm nay**, không PWA, không push, không
offline page. Nếu chôn trong OFF-1 thì `git revert` tính năng sẽ làm lỗi sống lại. Nửa nghiêm trọng
nhất **không phải** màn trắng, mà là: nút Duyệt kẹt ở "Đang xử lý…" rồi **tự phát lại khi có mạng**
(`queryClient` lắng `onlineManager` và gọi `resumePausedMutations()`) — tức phát lại một quyết định
HR có thể đã bỏ dở, mà đó là hành động nghiệp vụ được uỷ quyền theo FR-HR-4 và ghi audit theo FR-HR-5.

**Việc:**
1. `app/providers.tsx`: gọi `onlineManager.setOnline(navigator.onLine)` lúc khởi tạo (bọc `typeof window`).
2. `(hr)/layout.tsx`: thêm nhánh hiển thị riêng cho `fetchStatus === "paused"` — hiện nay rơi thẳng
   vào `if (!me) return null` (`:171`).
3. Mutation duyệt/từ chối ở `(hr)/review/page.tsx`: đặt `networkMode: "always"` **tại chỗ** (§4.7) ⇒
   offline bấm là hỏng ngay, không treo, không tự phát lại. **Dịch lỗi sang tiếng Việt** — mặc định
   nó ném nguyên `TypeError: Failed to fetch` vào giao diện toàn tiếng Việt (`review/page.tsx:57`).
4. Chữ hiển thị dùng **"Mất kết nối máy chủ"**, không dùng "Không có Internet": `navigator.onLine`
   trả `true` cả khi dính captive portal hoặc router mất upstream.

**Out of scope:** hook `useOnline()` + banner thường trực (người dùng chọn "chỉ trang offline").

---

## 6. Slice PWA-1 — tinh gọn + trang offline (frontend, không đụng backend)

### 6.1 Tinh gọn
- `lib/pwa.ts` → `usePwaMode()`: trả `undefined` khi chưa biết. Nhận diện:
  `matchMedia("(display-mode: standalone), (display-mode: minimal-ui), (display-mode: fullscreen)").matches
  || (navigator as Navigator & { standalone?: boolean }).standalone === true`.
  Giải một lần trong effect; **bỏ listener** (display-mode không đổi trong vòng đời một document).
  `navigator.standalone` là API không chuẩn, thiếu trong type của TS ⇒ **phải mở rộng type, KHÔNG dùng `any`**.
- `(hr)/layout.tsx`: **cổng chờ riêng** — chưa có `usePwaMode()` thì chưa vẽ nav (§4.6).
- Lọc `NAV` (`layout.tsx:32`) từ 5 mục còn **2**: `/applications`, `/review`.
- Guard route ẩn: ở chế độ standalone, `/` (khớp chính xác), `/jobs*`, `/cv-check*` → `router.replace("/review")`,
  kèm **một dải chữ inline ở đầu `/review`, tự tắt sau ~6s** (không phải dialog, không phải toast cần
  thư viện): "Màn này chỉ có trên bản máy tính". `/` khớp CHÍNH XÁC — nó là tiền tố của mọi route khác.
- Ở chế độ standalone **bỏ nút hamburger** (`layout.tsx:258-268`) — 2 đích thì không còn gì để mở;
  giữ thanh trên cùng và badge `/review` đang có.
- **KHÔNG đụng `manifest.ts`** (§4.8). **KHÔNG thêm thanh tab dưới cùng** — thanh trên cùng đã có link
  `/review` kèm số đếm (`layout.tsx:272-280`), và `env(safe-area-inset-*)` trong app này **bằng 0**
  (thiếu `viewportFit: "cover"` ở `app/layout.tsx:39-43`) nên mọi padding safe-area sẽ âm thầm vô tác dụng.

### 6.2 Màn ứng viên (chỉ đọc)
- `/applications`: dưới `md` render danh sách **thẻ xếp dọc** thay bảng `min-w-[640px]`; từ `md` trở
  lên giữ nguyên bảng. 4 cột hiện có: Ứng viên (avatar + email) · Vị trí · Điểm · Trạng thái (+ cờ email).
- `/applications/[id]` ở chế độ standalone: ẩn **6 phần tử tương tác + 3 khối vỏ** liệt kê ở §4.8.
  **Giữ** panel `app.interview` và panel `booking_no_slots` (chúng là nội dung, không phải hành động),
  và **giữ `AgentTrace`** (thu gọn) theo §3.6.
- Ghi rõ trong code: chỉ-đọc ở đây là lựa chọn **hiển thị**. Endpoint vẫn mở và trình duyệt trên chính
  máy đó vẫn thấy đủ site — đừng có ai "làm chắc" nó thành thay đổi backend.

### 6.3 Trang offline
- `sw.js` lên `ars-static-v3`. Precache `/offline` lúc install:
  `event.waitUntil(caches.open(CACHE).then(c => c.add(new Request("/offline", {cache:"reload"}))).catch(() => {}))`.
  **`.catch` là bắt buộc**: một lần fetch hỏng làm `install` reject ⇒ SW mới **không bao giờ activate**,
  client kẹt code cũ vĩnh viễn, không có đường cứu ngoài xoá site data.
- Nhánh điều hướng, đặt **sau** guard `method !== "GET"` và ghim origin:
  ```js
  if (event.request.mode === "navigate" && url.origin === self.location.origin) {
    event.respondWith(fetch(event.request).catch(() => caches.match("/offline")));
    return;
  }
  ```
  **TUYỆT ĐỐI không `cache.put`** ở nhánh này. Khoá của CacheStorage là URL đầy đủ, mà `/screening/{token}`
  và `/booking/{token}` mang **token bearer trong đường dẫn** (`models/screening_session.py:34`,
  `models/booking.py:103-104`) — cache lại là **lưu một credential còn sống** trên máy ứng viên,
  sống lâu hơn TTL, sống qua cả lượt vô hiệu one-time. Token đặt lịch còn **không phải one-time**, TTL 72h.
- Nhánh riêng cho RSC — điều hướng client-side của App Router đi qua `?_rsc=` với `mode: "cors"`,
  **không lọt vào nhánh `navigate`**. Không có nhánh này thì người dùng phải ngồi chờ hết timeout:
  ```js
  if (url.searchParams.has("_rsc") || event.request.headers.get("RSC") === "1") {
    event.respondWith(fetch(event.request).catch(() => new Response("", { status: 503 })));
    return;
  }
  ```
  503 ⇒ Next tự hard-nav ⇒ rơi vào nhánh `navigate` ⇒ `/offline`. **Không bao giờ trả HTML `/offline`
  cho request `_rsc`.**
- Fallback kích hoạt bằng **`fetch()` reject**, KHÔNG bằng `!res.ok`: Render ngủ hoặc Cloudflare 502
  thì `fetch` **resolve** với 5xx, gán nhãn "bạn đang offline" cho một sự cố backend là chẩn đoán sai
  — repo đã trả giá cho đúng loại nhầm lẫn này một lần (`docs/deploy-live-issues.md`).
- `/offline`: route tĩnh **ngoài nhóm `(hr)`**, **Server Component, KHÔNG `"use client"`**, nút thử
  lại là thẻ `<a href="/review">` thường. Lý do: `cache.add` chỉ lưu HTML; chunk JS của `/offline`
  chưa từng được ai tải nên **không nằm trong cache** ⇒ trang **sẽ không hydrate**, mọi nút React ở đó
  là nút chết. Chữ trung tính (§4.7 — trang này cũng phục vụ khách vãng lai).
- Sửa luôn comment sai ở `sw.js:3-4` (nói API ở origin khác — sai từ slice 13).

**Out of scope:** sửa `btn()`, đổi badge sang `/pipeline`, banner `useOnline` — cả ba đều không truy
được về yêu cầu (chi tiết ở §4.8 và §5).

---

## 7. Slice NOTI-1a — hạ tầng Web Push (gánh toàn bộ rủi ro deploy)

### 7.1 Bảng + migration
`push_subscription`: `id` · `hr_user_id` FK **`ON DELETE CASCADE`** · `endpoint` (UNIQUE, text) ·
`p256dh` · `auth` · `user_agent` · `created_at` · `last_seen_at`.
Migration **viết tay**, `down_revision = "d1e2f3a4b5c6"` (head hiện tại). Import model vào
`app/models/__init__.py` nếu không `Base.metadata` sẽ không thấy bảng. **Không dùng `--autogenerate`**
— nó sẽ phát `DROP TABLE` cho 4 bảng checkpoint của LangGraph.

### 7.2 Chặn host `endpoint` — **BẮT BUỘC, đây là kiểm soát quan trọng nhất của slice**
`endpoint` là URL **do client gửi lên**, và backend sẽ POST tới đó. Không chặn thì:
- **Rút dữ liệu:** client cung cấp cả URL đích **lẫn** khoá ECDH ⇒ kẻ tấn công đăng ký endpoint của
  mình kèm khoá của mình thì **giải mã được mọi push**. Mã hoá Web Push che payload khỏi Google/Apple,
  **không** che khỏi người tự chọn khoá.
- **SSRF:** backend POST tới URL bất kỳ từ trong mạng Render — `http://169.254.169.254/…`,
  `http://127.0.0.1:8000/api/…`, host Neon/Qdrant nội bộ. `require_hr` không cứu: một JWT 8h bị lộ là đủ.
- **Phản hồi quan sát được** (luật xoá theo status đọc mã trả về) ⇒ oracle SSRF bán mù.

**Chặn ở tầng Pydantic**, không phải trong service: scheme phải `https`; host phải khớp allowlist cứng
(`*.push.services.mozilla.com`, `fcm.googleapis.com`, `*.notify.windows.com`, `web.push.apple.com`);
cấm userinfo (`user:pass@`) và cổng khác mặc định. Sai ⇒ 422. **Kiểm lại mỗi lượt gửi** (hàng trong DB
sống lâu hơn allowlist).

### 7.3 Config + khoá
`VAPID_PUBLIC_KEY` / `VAPID_PRIVATE_KEY` / `VAPID_SUBJECT` / `PUSH_ENABLED` — chèn vào `config.py:261`
(sau khối Resend/webhook, trước Langfuse). Secret kiểu `str | None = None`, không mặc định
(nếp `jwt_secret`, `config.py:154`). Kiểm "có cả cặp hay không có gì" bằng **`@property` raise
`ValueError`, đánh giá sớm ở `main.py`** cạnh `_CORS_ORIGINS` (`main.py:65`) — `Settings` trong repo
này **không có validator nào**, đó là quy ước.

`scripts/generate_vapid_keys.py` — chỉ in ra stdout, không ghi file, không log khoá riêng.

⚠ **`make test` sẽ đỏ** nếu thêm 4 biến vào checklist prod của `.env.example` mà chưa có đủ 4 field
trong `Settings`: `tests/test_deploy_config.py:224` quét **mọi `KEY=`** trong file, **kể cả trong khối
comment**, và đối chiếu với `Settings.model_fields`. Phải cùng một commit.

Khối `.env.example` theo nếp `RESEND_WEBHOOK_SECRET`, ghi rõ: **đổi cặp khoá = vô hiệu TOÀN BỘ
`push_subscription`** (push service trả **403 `VapidPkHashMismatch`, KHÔNG phải 410** ⇒ hàng không tự
dọn), nên rotate phải kèm `DELETE FROM push_subscription;`. **Rotate `JWT_SECRET` để thu hồi phiên
cũng PHẢI kèm câu xoá đó** — nếu không, đòn "đăng xuất tất cả" để lại kênh push còn sống. Ghi vào
`docs/deploy-live-issues.md`. `VAPID_SUBJECT` dùng **địa chỉ vai trò**, không phải email cá nhân: nó
được gửi tới Google/Apple/Mozilla ở **mọi** lượt push.

### 7.4 `services/push_service.py`
`send_push(sub, payload) -> Outcome`, **không bao giờ raise**. Bọc `asyncio.to_thread`.
`webpush(..., ttl=86400, headers={"Urgency": "high"}, timeout=(3.05, 10))` — `ttl` phải đặt tường minh
(TTL 0 thì push service **vứt** thay vì xếp hàng khi máy không với tới được, trái thẳng quyết định #4);
`timeout` bắt buộc (§4.5).

Bảng mã trả về:

| Mã | Nghĩa | Xử lý |
|---|---|---|
| 404 / 410 | Subscription chết | **Xoá hàng** |
| 403 / 400 `VapidPkHashMismatch` | Ai đó đã xoay khoá VAPID | **Xoá hàng + log RIÊNG** (khác hẳn "máy đã gỡ") |
| 429 / 5xx | Tạm thời | **Giữ hàng**, để vòng sweep sau thử lại |
| khác | — | Giữ hàng, log |

**Đừng "xoá khi 4xx"** — một lỗi gõ nhầm VAPID sẽ hoá thành mất sạch dữ liệu không cứu được.

Vòng đời session: **ĐỌC (mượn ngắn) → GỬI (không giữ session) → GHI (mượn ngắn)** — hai lượt mượn,
không phải một (`AI_GUIDE.md:95-106`).

### 7.5 Router `api/routes/push.py`
`GET /api/push/public-key` · `POST /api/push/subscribe` · `DELETE /api/push/subscribe`.
Import ở `main.py:16`, mount **sau `main.py:126`** với `dependencies=_HR_ONLY`.
**Phải mở rộng tuple prefix ở `tests/test_auth.py:218`** — không thì lưới kiểm cấu trúc **im lặng bỏ qua**
`/api/push`. CSRF: không cần làm gì, `OriginCheckMiddleware` đã phủ (§4.4). Rate-limit: **cố ý không
thêm** — `_bucket()` chỉ dành cho endpoint **công khai** (`AI_GUIDE.md:92-94`), đây là route sau `require_hr`.
Ghi câu này vào code như một quyết định, không để nó trông như sót.

### 7.6 Đăng xuất phải huỷ subscription
`auth.py:80-83` hiện **không nhận `DBSession` lẫn `CurrentHr`** — nó không biết ai vừa đăng xuất. Kết
quả: máy đó **tiếp tục nhận push vô thời hạn** sau khi đăng xuất. Đây là kiểu khác hẳn điểm yếu JWT
stateless sẵn có: trước giờ không có gì **từ phía server** với tới được một máy đã đăng xuất; push đảo
ngược điều đó.
1. Frontend: `getSubscription()` → `unsubscribe()` **trước** khi gọi `POST /api/auth/logout`, gửi kèm `{endpoint}`.
2. Backend `logout` nhận `{endpoint}` tuỳ chọn, xoá hàng **theo endpoint**, best-effort — **không** thêm
   `CurrentHr` (sẽ làm logout trả 401 khi cookie đã hết hạn, hỏng đúng những phiên cần nó nhất).
   Bản thân endpoint đã là capability entropy cao, biết nó là đủ quyền thu hồi nó.

### 7.7 Service worker + client
- `push`: **luôn `showNotification` trên MỌI nhánh**, kể cả khi parse hỏng hoặc `event.data` rỗng.
  `userVisibleOnly: true` là bắt buộc; WebKit **thu hồi subscription** sau vài lần push không hiện gì,
  Chrome thì tự chèn thông báo "trang này đã cập nhật nền".
  ```js
  self.addEventListener("push", (event) => {
    let d = {}; try { d = event.data ? event.data.json() : {}; } catch {}
    event.waitUntil(self.registration.showNotification("HireFlow", { /* … */ }));
  });
  ```
- **Không bao giờ truyền URL trong payload.** SW tự dựng đích, ghim origin, và đích là **hằng số**:
  `new URL("/review", self.location.origin)` (§4.3). Nhận `data.url` từ server = mở cửa cho
  redirect/lừa đảo (kèm §7.3, khoá lộ ⇒ thông báo giả mang đúng icon và tên app của mình).
- `notificationclick`: `matchAll({type:"window", includeUncontrolled:true})` → `client.navigate(url)`
  (bọc `try`, iOS chưa chắc hỗ trợ) rồi `focus()`; không có client thì `openWindow`. Chỉ `focus()`
  không thôi sẽ để HR đứng nguyên ở màn đang mở.
- `pushsubscriptionchange`: **Chrome CÓ bắn** sự kiện này — thiếu handler thì endpoint chết âm thầm.
  Safari không có ⇒ **thêm** bước kiểm lại mỗi lần mở app, **so `subscription.options.applicationServerKey`
  với `GET /api/push/public-key`** (không chỉ kiểm có/không); lệch thì `unsubscribe()` rồi đăng ký lại.
  Gọi `subscribe()` với `applicationServerKey` khác cái đang có sẽ ném `InvalidStateError`.
- Icon: `icon: "/hireflow-192.png"` (đã có) + **badge PNG 96×96 đơn sắc, chỉ alpha** (asset mới —
  Android mask nó, PNG có màu sẽ ra một vệt xám).
- Android/FCM: **không cần gì thêm** — VAPID không cần sender ID, không cần Firebase project, và
  thêm `gcm_sender_id` vào manifest là có hại. Chỉ cần Render gọi ra được `https://fcm.googleapis.com`.
  Ghi câu này vào code kẻo có người "sửa" nó lúc hoảng trước buổi demo.

### 7.8 Giao diện xin quyền + hướng dẫn iOS
- Một predicate dùng chung mọi nơi:
  `"serviceWorker" in navigator && "PushManager" in window && "Notification" in window`.
  Trong **tab Safari trên iOS, `Notification` và `PushManager` KHÔNG tồn tại** ⇒ đọc
  `Notification.permission` không có guard là `ReferenceError`. Kiểm `"serviceWorker" in navigator`
  **không đủ** (iOS tab vẫn có).
- **Ba trạng thái, không phải một.** `default` → nút, `onClick` gọi `Notification.requestPermission()`
  **đồng bộ ngay trong handler** (iOS đòi transient user activation) rồi mới `subscribe()`.
  `granted` → toggle. `denied` → **hướng dẫn tiếng Việt**: Android = Cài đặt trang trong Chrome;
  iOS = xoá icon rồi thêm lại. `denied` là **chung cuộc** — không banner nào hỏi lại được, và đó lại
  là trạng thái hỏng phổ biến nhất; chỉ xử lý `default` thì nó hiện ra như "mọi thứ vẫn ổn mà chẳng
  bao giờ có thông báo".
- Màn hướng dẫn iOS khi `!pushCapable && isIOS`. Nhận diện iPadOS 13+ bằng
  `navigator.maxTouchPoints > 1 && /Macintosh/` (nó khai báo là Mac).
- **Phải nói rõ trên màn đó:** app trên Màn hình chính của iOS có **kho cookie/storage RIÊNG** với
  Safari ⇒ đăng nhập trong Safari **không** theo sang. Đây là kiểu hỏng dễ gặp nhất hôm demo. Thứ tự
  đúng: **cài icon → mở icon → đăng nhập → cấp quyền thông báo** (cấp quyền trước khi đăng nhập thì
  `POST /api/push/subscribe` trả 401 và subscription không bao giờ được lưu).

---

## 8. Slice NOTI-1b — móc trigger (gánh toàn bộ rủi ro nghiệp vụ)

1. Cột `review_notified_reason: Mapped[str | None]` trên `application` + migration.
2. `services/review_notify.py` — module nghiệp vụ riêng: quét predicate ở §4.2, gửi, đóng dấu
   `review_notified_reason = escalation_reason`. **Không bao giờ raise.**
3. Ghép làm **lưới thứ TƯ** vào `screening_scheduler.py:76`, trong cùng `try` (`AI_GUIDE.md:101-102`
   cấm dựng cơ chế nền thứ hai). Đây vừa là lưới bền vừa là chính sách retry.
4. **Đúng MỘT** lời gọi trực tiếp sau commit, ở `background.py:321` (ngay sau `await session.commit()`),
   có điều kiện `persisted_status == PENDING_REVIEW` — chỉ để lấy độ kịp thời ở đường CV mới, vì sweep
   mặc định 600s. **Bọc `try/except` riêng**, theo đúng nếp 3 khối after-commit đang có
   (`background.py:329-339, 348-361, 364-381`, đều ghi chú *"CÔ LẬP khỏi handler lỗi"*). Không bọc thì
   nó rơi vào `_escalate_technical_error` và đốt thêm một lượt mượn pool + log gây hiểu nhầm.
5. **KHÔNG** gọi trực tiếp trong `_escalate_technical_error` — `background.py:33-37` nói rõ lỗi đưa
   ta tới đó **thường là lỗi của chính session** (pool cạn, connection Neon chết); mở session mới để
   đọc subscription từ đúng cái pool vừa hỏng là thời điểm tệ nhất có thể. Để lưới sweep bắt.
6. **Giới hạn 10 subscription / tài khoản HR** (chống khuếch đại fan-out — mỗi ca cần duyệt nhân lên
   thành N lượt HTTP đi ra, trên pool `to_thread` dùng chung): vượt ngưỡng thì xoá hàng `last_seen_at`
   cũ nhất. Cộng thêm: sweep xoá hàng `last_seen_at` **quá 90 ngày** — backstop duy nhất cho máy bị
   *mất* chứ không phải *đăng xuất*.

**Giới hạn phải ghi vào tài liệu, không phải sửa:** Render gói free ngủ sau ~15 phút ⇒ vòng sweep
không chạy ⇒ push cho hết-hạn-sàng-lọc / hết-hạn-đặt-lịch / hồ sơ-kẹt **trễ tới khi có ai đó đánh
thức máy** (bất kỳ request nào cũng đánh thức; HR mở dashboard là backlog được xả trong một chu kỳ).
Push cho CV mới **luôn kịp** vì chính request `POST /api/public/applications` đã đánh thức máy.
**KHÔNG thêm keep-alive pinger.**

---

## 9. Thứ tự ship & Definition of Done

| Slice | Nội dung | Xong khi |
|---|---|---|
| **BUG-1** | §5 | Ngắt mạng ở DevTools: `/review` hiện lỗi tiếng Việt tử tế; bấm Duyệt hỏng NGAY, không treo; nối mạng lại **không** tự phát lại. Seed `onlineManager` ở `providers.tsx` là **toàn cục và đúng ý**; riêng `networkMode` thì **không** được đặt toàn cục (§4.7) — kiểm bằng cách nộp CV ở `/apply` lúc offline, hành vi phải y như trước slice này |
| **PRD** | §3 | 10 mục sửa xong, commit riêng, **trước** mọi code của NOTI |
| **PWA-1** | §6 | `next build && next start`, cài lên máy thật: chỉ thấy 2 mục nav; gõ tay `/jobs` bị đưa về `/review`; mở cùng URL bằng trình duyệt vẫn đủ site; `/applications` ở 390px là thẻ dọc, không cuộn ngang; chi tiết không còn nút hành động nào; bật máy bay → hiện trang "Mất kết nối" (không phải màn lỗi trình duyệt), cả khi mở nguội lẫn khi điều hướng trong app |
| **NOTI-1a** | §7 | `make test` xanh (gồm `test_auth` prefix mới + parity `.env.example`); một lượt gửi thử tay tới máy thật kêu trên **cả Android lẫn iOS**; endpoint bịa → 422; test pytest cho **timeout** (trỏ vào endpoint cố tình treo, khẳng định hàm trả về đúng hạn và **không** xoá hàng) |
| **NOTI-1b** | §8 | Nộp CV thật → push tới trong vài giây, nội dung **chỉ có số đếm**; giết tiến trình giữa commit và push → vòng sweep sau vẫn bắn; một hồ sơ **không** bị bắn hai lần cho cùng một lý do; ca gửi thư mời thất bại (old == new == `PENDING_REVIEW`) **vẫn** bắn |

**Không có test runner cho frontend** — kiểm bằng trình duyệt thật ở 390px + Chrome DevTools MCP.
**Push không test được bằng `next dev`**: `PWARegister.tsx:9-13` chủ động gỡ SW ở dev.

---

## 10. Out of scope

Thanh tab dưới cùng · sửa `btn()` toàn app · đổi badge sang `/pipeline` · banner `useOnline` thường
trực · gom 10 chỗ `PENDING_REVIEW` · đổi `start_url`/`manifest.ts` · cache dữ liệu nghiệp vụ để xem
offline · duyệt offline rồi gửi sau (Background Sync **không có trên iPhone**) · `navigator.setAppBadge`
(cơ hội tốt, nhưng chưa ai yêu cầu) · audit_log cho push (**cố ý bất đối xứng với email** —
`scheduler.py:118-120` có ghi `email_sent:{mode}`; push là cú hích best-effort, không phải hành động
nghiệp vụ. Ghi rõ là lựa chọn, kẻo bị đọc thành sót).
