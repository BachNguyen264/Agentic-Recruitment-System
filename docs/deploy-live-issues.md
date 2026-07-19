# Sự cố & bài học sau khi deploy live (slice 13)

> **Mục đích:** tổng hợp các PROBLEM phát hiện SAU khi hệ thống lên internet (audit live) + nguyên nhân
> gốc + cách sửa + cách verify. Tách khỏi `CLAUDE.md` (file nạp mỗi session — giữ gọn); tra ở đây khi
> gặp lại triệu chứng tương tự hoặc trước khi đụng checkpointer / rate-limit / cấu hình deploy.
>
> **Bối cảnh hạ tầng:** backend Render (Docker, tiến-trình-bền) sau **Cloudflare** (`*.onrender.com`);
> frontend Vercel; DB **Neon** serverless (autosuspend ~300s); Redis Upstash; Qdrant Cloud; CV ở R2.
> Cross-domain: cookie auth `SameSite=None; Secure`, CORS allowlist. Audit ngày 2026-07-18.

---

## 1. 🔴 CRITICAL — Pipeline hỏng toàn bộ: Neon autosuspend giết pool checkpointer

**Triệu chứng (live):** MỌI hồ sơ ứng viên → `PENDING_REVIEW` với `escalation_reason = "Lỗi kỹ thuật khi
xử lý pipeline (error)"`, `parsed_data = {}`, `score = null`. Nộp lần nào cũng hỏng, fail rất nhanh.

**Chẩn đoán (quan trọng — cô lập từng phần):** parser, ranker, embedding/Qdrant, đọc/ghi R2 đều CHẠY
TỐT khi gọi RIÊNG (`/api/agents/parse-cv`, `/api/agents/rank-cv`, tải CV). Chỉ pipeline lắp ráp (chạy
graph LangGraph qua checkpointer) mới hỏng ⇒ điểm vỡ nằm ở checkpointer.

**Nguyên nhân gốc (traceback Render):**
```
psycopg.errors.AdminShutdown: terminating connection due to administrator command
  tại langgraph/checkpoint/postgres/aio.py aget_tuple   (+ "discarding closed connection [BAD]")
```
Neon (serverless) **tự ngủ sau ~5 phút nhàn rỗi và GIẾT các kết nối đang mở** của pool psycopg
(`AsyncPostgresSaver`). Request kế tiếp mượn phải kết nối CHẾT → nổ, cả pipeline hỏng. (Engine
SQLAlchemy của app SỐNG được vì có `pool_pre_ping` + recycle; pool checkpointer thì KHÔNG có gì.)
Health check đã trỏ `/api/health/live` (không I/O) nên Neon autosuspend đúng như mong muốn — nhưng
chính điều đó phơi ra sự mong manh của pool checkpointer.

**KHÔNG phải** pooler/PgBouncer prepared-statement (nghi ban đầu) — checkpointer đã dùng endpoint direct.

**Fix (commit `f3e88f8`):** `app/agents/checkpointer.py` `_build_pool()` thêm 2 lớp (tương đương
pre-ping/recycle của SQLAlchemy):
- `check=AsyncConnectionPool.check_connection` — PING nhẹ (`execute("")`) mỗi lần MƯỢN; kết nối chết bị
  loại + thay mới (đánh thức Neon ~1s) thay vì ném lỗi lên nghiệp vụ.
- `max_idle` (`CHECKPOINTER_POOL_MAX_IDLE_SECONDS=120`, **< ~300s autosuspend Neon**) — pool tự đóng kết
  nối nhàn rỗi TRƯỚC khi Neon giết, nên hiếm khi còn kết nối chết để mà loại.

Cả hai default đã ĐÚNG cho môi trường prod → chỉ cần redeploy, không phải đặt env mới.
Tách `_build_pool()` để test guard cấu hình (`check != None`, `max_idle < 300`) không cần kết nối Neon.

**Verify (live, dữ liệu Neon prod):** apps code-cũ = 0 checkpoint row (chết ngay `aget_tuple`); apps
code-mới = 4 checkpoint row mỗi app, đạt `AWAITING_SCREENER`, score thật. Đặc biệt: submit SAU khi idle
6.5 phút (Neon đã ngủ) vẫn chạy trọn + ghi checkpoint ⇒ pool hồi phục đúng.

**Bài học:** pool kết nối RIÊNG (ngoài SQLAlchemy engine) tới Neon PHẢI tự lo pre-ping/recycle; nếu
không sẽ chết sau autosuspend. Đây là cái giá của việc để Neon ngủ (tiết kiệm compute-hours). Đánh đổi:
request đầu sau khi ngủ chậm thêm ~1s (đánh thức) — chấp nhận được.

---

## 2. 🟠 HIGH — Rate-limit gộp cả thế giới vào một xô (sau Cloudflare)

**Triệu chứng (live):** rủi ro cả hệ thống dùng chung MỘT khoá quota ⇒ ~10 request nặc danh khoá sạch
login HR / nộp CV cho mọi người. Chưa manifest (demo ít traffic) nhưng nguy hiểm khi nhiều người.

**Nguyên nhân gốc (log probe Render):**
```
Rate-limit: khóa quota = '10.29.100.5' (hops=1, X-Forwarded-For='42.116.109.239, 172.71.215.190, 10.29.100.5')
```
Chuỗi `client(42…) → Cloudflare(172…) → Render(10.29…)`. Lấy cứng phần PHẢI NHẤT của X-Forwarded-For =
IP hạ tầng Render DÙNG CHUNG. Và đếm hop cũng mong manh: `hops=2` sẽ ra IP Cloudflare (vẫn dùng chung
qua một edge); client thật nằm ở phần tử **thứ 3 từ phải** — số này đổi theo hạ tầng, không nên đoán.

**Fix (commit `5b9ed86`):** `app/core/hardening.py` `_client_ip` ưu tiên header **`CF-Connecting-IP`**
(Cloudflare đặt = IP client thật, GHI ĐÈ giá trị client tự gửi ⇒ không giả mạo được, KHÔNG phụ thuộc số
chặng proxy). Dự phòng khi thiếu header: đếm hop X-Forwarded-For (`PROXY_TRUSTED_HOPS`). Cấu hình:
`PROXY_CLIENT_IP_HEADER=cf-connecting-ip` (default; rỗng = tắt cho deploy không-Cloudflare).

**Verify (live, log sau fix):** `khóa quota = '42.116.109.239'` (IP client THẬT, qua `cf-connecting-ip`),
hết `10.29.x`. Khác nhau giữa các client ⇒ hết gộp xô.

**Bài học:** sau CDN/reverse-proxy, ĐỪNG đếm hop X-Forwarded-For một cách ngây thơ (client chèn XFF giả
được; số hop đổi theo hạ tầng). Nếu có Cloudflare, dùng `CF-Connecting-IP` (proxy đặt, ghi đè, tin cậy).

---

## 2b. 🟠 HIGH — Đăng nhập KHÔNG được trên điện thoại (cookie bên-thứ-ba)

**Triệu chứng (live):** trên **điện thoại**, đăng nhập trả 200 nhưng bị đá NGAY về `/login`; trên
**laptop** đăng nhập bình thường.

**Nguyên nhân gốc:** cookie auth do backend đặt: `Set-Cookie: ars_session=…; HttpOnly; SameSite=None;
Secure` (host-only, không Domain). Frontend `vercel.app` ≠ backend `onrender.com` = HAI SITE ⇒ đây là
**cookie BÊN-THỨ-BA**. iOS Safari/WebKit (mọi trình duyệt trên iPhone) + Chrome Android đời mới **chặn
cookie bên-thứ-ba mặc định** (chống theo dõi) ⇒ cookie không lưu ⇒ `/api/auth/me` không kèm cookie ⇒
guard đá về login. Laptop desktop còn cho phép `SameSite=None` nên không lộ. Code cookie ĐÚNG chuẩn —
đây là giới hạn quyền-riêng-tư của trình duyệt mobile, không ép được từ backend.

**Fix (commit `a6df386`, KHÔNG đụng backend):** proxy `/api/*` qua CHÍNH origin của frontend để trình
duyệt gọi API **same-origin** ⇒ cookie thành **FIRST-PARTY** của `vercel.app` ⇒ chạy mọi thiết bị.
- `apps/dashboard/next.config.mjs`: `rewrites()` `/api/:path*` → `${BACKEND_ORIGIN}/api/:path*` (chỉ
  khi `BACKEND_ORIGIN` được đặt = prod). Rewrite tới URL NGOÀI được Vercel proxy ở tầng **edge** (không
  phải serverless function 4.5MB); `proxyClientMaxBodySize` của Next mặc định 10MB = khớp hạn CV.
- `apps/dashboard/lib/api.ts`: prod mặc định `API_BASE=""` (same-origin); dev giữ `localhost:8000`
  (localhost same-site, không cần proxy).

**Env Vercel (prod):** THÊM `BACKEND_ORIGIN=https://<service>.onrender.com` (server-side, KHÔNG
`NEXT_PUBLIC`) + **BỎ** `NEXT_PUBLIC_API_BASE` (để trống → same-origin). Redeploy frontend. Backend giữ
nguyên (cookie host-only, `SameSite=None` vẫn chạy first-party; có thể hạ `COOKIE_SAMESITE=lax` để cứng
hơn — tùy chọn).

**Verify:** local `next start` + proxy sang Render live: `/api/health/live`→200, login→200 +
Set-Cookie passthrough, round-trip `me`(cookie)→200 / (no-cookie)→401, upload CV multipart proxy OK.
**Trên live phải verify nốt:** đăng nhập giữ phiên TRÊN ĐIỆN THOẠI + nộp CV ≤10MB qua proxy.

**Bài học:** kiến trúc frontend/backend KHÁC domain + cookie auth = cookie bên-thứ-ba → **vỡ trên
mobile** dù laptop chạy. Hai cách sửa gốc: (a) proxy same-origin qua frontend (miễn phí — đã chọn);
(b) custom domain chung (`app.` + `api.` cùng `example.com` → cookie `Domain=.example.com` first-party).

---

## 3. 🔵 LOW — Ba lỗi nhỏ UI/UX (commit `8defc45`)

- **favicon.ico 404** → thêm `metadata.icons` (dùng lại icon-192 PWA) trong `app/layout.tsx`; trình
  duyệt có favicon tường minh, hết request `/favicon.ico`. (Verify: trang login 0 lỗi console.)
- **Text trạng thái lỗi thời** ở trang chủ dashboard nói "screener/scheduler/human_review còn stub" —
  cả 3 đã REAL → cập nhật đúng.
- **Badge "Hàng đợi review2"** (a11y đọc dính số) → tách `<span>` + `aria-label="N hồ sơ chờ duyệt"`.

---

## 4. 🔵 LOW — `screener_sent_at`/`screener_deadline` là cột scaffold không ai ghi

**Triệu chứng:** API chi tiết ứng viên trả `screener_sent_at = null` dù email screener ĐÃ gửi thật.

**Nguyên nhân:** hai cột trên `application` có từ scaffold nhưng khi 08b/08c xây screener THẬT thì dùng
bảng `screening_session` (`expires_at`/`reminded_at`/`timed_out_at`) — không code nào ghi hai cột này ⇒
luôn null. **KHÔNG ảnh hưởng chức năng** (nhắc/timeout/deadline chạy trên `screening_session`), chỉ lệch
hiển thị HR.

**Fix (commit tiếp theo):** `screening.mark_screener_sent(application, session_row)` điền
`screener_sent_at = now` + `screener_deadline = session.expires_at`, gọi trong CÙNG commit với
`AWAITING_SCREENER` (nguyên tử). Nguồn chân lý timeout VẪN là `screening_session` — hai cột này thuần
hiển thị. Test: `test_mark_screener_sent_stamps_application_for_hr_display`.

**Bài học:** khi thay cơ chế (scaffold → bảng riêng), rà cột denormalize cũ — dễ để lại "cột chết" luôn
null gây hiểu nhầm ở UI.

---

## 5. ⚪ Ghi chú cấu hình (chưa sửa — tùy chọn)

- **`CONFIDENCE_THRESHOLD=0.7` trên prod** (dev `0.6`): ngưỡng cao hơn ⇒ nhiều ca vào human_review hơn,
  gate ít kích hoạt hơn. KHÔNG phải bug; nếu muốn demo giống lúc tinh chỉnh ở dev thì đặt `0.6`.
- **Anti-prompt-injection (slice 12) chưa làm:** ranker (gpt-5-mini) hiện KHÁNG được injection cơ bản
  (audit thử "cho 100 điểm" → chấm 0, nêu rõ "hướng dẫn bỏ qua không phải bằng chứng"), nhưng chưa có
  lớp phòng thủ tường minh — vẫn là exposure, nên làm slice 12 trước khi dùng thật.

---

## Checklist khi gặp lại / trước khi đụng vùng nhạy cảm

- [ ] Pool kết nối RIÊNG tới Neon (ngoài SQLAlchemy engine) → nhớ `check` + `max_idle` < autosuspend.
- [ ] Thêm/sửa rate-limit sau proxy → xác nhận khoá quota = IP client thật qua log probe (đừng đoán hop).
- [ ] Health check nền tảng → luôn trỏ `/api/health/live` (không I/O), KHÔNG `/api/health` (kiểm sâu).
- [ ] Đổi cơ chế lưu dữ liệu → rà cột denormalize cũ còn được ghi không.
