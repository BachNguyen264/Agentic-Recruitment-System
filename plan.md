# SLICE 13 — Deploy (backend Render + frontend Vercel, cross-domain) · plan + runbook

> **Bản chất:** plan ONE-SHOT + RUNBOOK. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** đưa hệ thống lên internet — backend (Render), frontend (Vercel), nối cross-domain đúng (cookie auth +
> CORS), env prod đầy đủ, DB prod riêng, seed HR admin. Demo được từ xa.
> Tham chiếu: PRD NFR-4 (dữ liệu cá nhân), §14. Tuân thủ `CLAUDE.md`.
>
> **Lát này 2 phần:** (A) CODE-PREP — Claude Code sửa repo cho deploy. (B) RUNBOOK — BẠN thao tác trên dashboard
> Render/Vercel (Claude Code không click được). Rủi ro #1: **cookie cross-domain**. Backend PHẢI là tiến-trình-bền
> (KHÔNG serverless — vì sweep loop + checkpointer pool + BackgroundTasks).

---

## 0. Vì sao Render (và caveat) · vì sao không serverless

- **Backend = tiến trình bền** (Render Web Service / Railway), KHÔNG serverless/Lambda: sweep loop timeout (08c),
  AsyncPostgresSaver pool (08a), BackgroundTasks đều cần process sống liên tục. Serverless giết chúng.
- **Render free tier NGỦ sau ~15 phút không request** → cold start ~30-60s, VÀ sweep loop dừng khi ngủ (timeout screener
  không chạy lúc ngủ; thức dậy quét bù). Chấp nhận được cho đồ án — **đánh thức backend trước khi demo**. Muốn always-on:
  Railway (trả phí sau trial) hoặc Render trả phí. Chọn Render free + đánh thức là đủ.

---

## 1. In scope / Out of scope

**In scope:**

- (A) Code-prep: CORS đọc từ env (cho phép origin frontend + credentials); config build/start; health check; xác nhận
  entrypoint chạy trên Linux; `.env.example` liệt kê env prod; (khuyến nghị) body-size limit + rate-limit cơ bản cho public endpoints.
- (B) Runbook: DB prod riêng (Neon branch/project) + migration + seed admin; deploy backend Render; deploy frontend Vercel;
  nối cross-domain (CORS + cookie SameSite=None;Secure); verify trên URL live.

**Out of scope (KHÔNG làm):**

- KHÔNG UI redesign (lát sau, trên bản live). KHÔNG đổi nghiệp vụ/agents/pipeline. KHÔNG custom domain/DNS (dùng URL mặc định Render/Vercel là đủ).
- KHÔNG dữ liệu thật người thật trên hệ public (NFR-4 — demo bằng CV ẩn danh).

---

## 2. Prerequisites (BẠN chuẩn bị)

- Tài khoản **Render** + **Vercel** (đăng nhập bằng GitHub, connect repo).
- **DB prod RIÊNG:** tạo Neon branch mới (hoặc project mới) cho prod → lấy connection string prod (TÁCH khỏi dev, tránh lẫn data).
- **Giá trị secret PROD MỚI** (KHÔNG dùng lại giá trị dev đã lộ trong chat): `JWT_SECRET` mới (≥32 ký tự random),
  `HR_ADMIN_PASSWORD` mới mạnh. Các key dịch vụ (OpenAI/Resend/Qdrant/Upstash/R2) dùng lại được.
- (Cân nhắc) `QDRANT_COLLECTION` tên riêng cho prod (tránh lẫn vector dev) — hoặc chấp nhận chung.

---

## 3. (A) CODE-PREP — Claude Code sửa repo

### 3.1 CORS từ env · `app/main.py`

- CORS middleware: `allow_origins` đọc từ env (`CORS_ORIGINS` = URL frontend Vercel), `allow_credentials=True`,
  cho phép method/headers cần. **KHÔNG** `allow_origins=["*"]` khi có credentials (trình duyệt cấm). Public endpoints
  (/apply, /screening) cũng gọi từ origin frontend → CORS phải phủ.

### 3.2 Config build/start · repo root

- Cách deploy Render: **Dockerfile** (khuyến nghị, kiểm soát rõ) HOẶC build/start command.
  - Build: cài `uv` + deps backend; build frontend riêng ở Vercel (không chung).
  - **Start backend:** chạy migration trước rồi uvicorn: `alembic upgrade head && python -m app` (entrypoint `python -m app`
    đã set Windows loop policy — trên Linux là **no-op**, uvicorn chạy bình thường; xác nhận điều này).
  - Bind `0.0.0.0:$PORT` (Render cấp `$PORT` qua env).
- Health check path `/api/health` (Render dùng để biết service sống).

### 3.3 Xác nhận entrypoint + async trên Linux

- `python -m app`: guard win32 → Linux bỏ qua policy, uvicorn khởi động chuẩn. Sweep loop + checkpointer + BackgroundTasks chạy trong process bền của Render. Xác nhận không có gì Windows-only chặn khởi động.

### 3.4 Hardening public endpoints (khuyến nghị — giờ chúng ra internet)

- **Body-size limit** cho public upload (chặn file khổng lồ) + **rate-limit cơ bản** cho `/api/public/applications`,
  `/api/public/screening`, `/api/auth/login` (chống spam/brute-force). Mức đơn giản (vd slowapi hoặc middleware đếm theo IP). Các món deploy-time đã tích từ 08b — làm ở đây.

### 3.5 `.env.example` + tài liệu env prod

- Liệt kê ĐẦY ĐỦ env prod (mục 4.2) trong `.env.example` (mẫu, không giá trị thật) để bạn điền trên dashboard.

### 3.6 Frontend

- `NEXT_PUBLIC_API_BASE` = URL backend (đặt ở Vercel env). Fetch đã `credentials:"include"` (từ 09) — xác nhận mọi call đều gửi cookie.

---

## 4. (B) RUNBOOK — BẠN thao tác (mình hướng dẫn)

### 4.1 DB prod + migration + seed

- Neon: tạo branch/project prod → connection string prod.
- Migration chạy khi deploy (start command `alembic upgrade head`). Checkpointer `.setup()` tự tạo bảng checkpoint lúc startup (idempotent).
- Seed HR admin trên prod: chạy `seed_hr_admin.py` (Render shell hoặc idempotent startup) với `HR_ADMIN_EMAIL` + `HR_ADMIN_PASSWORD` MỚI mạnh.

### 4.2 Deploy backend (Render Web Service)

- Connect repo → chọn thư mục backend → Docker/командa build+start (mục 3.2). Health check `/api/health`.
- **Đặt ĐẦY ĐỦ env vars:** `DATABASE_URL` (Neon prod), `OPENAI_API_KEY`, `RANKER_MODEL=gpt-5-mini` + `RANKER_REASONING_EFFORT=low`,
  Qdrant (URL/KEY/`QDRANT_COLLECTION`), Upstash Redis, `RESEND_API_KEY` + `EMAIL_FROM`, **`STORAGE_BACKEND=r2`** + `R2_*` (5 biến),
  `JWT_SECRET` (mới), `JWT_EXPIRY_MINUTES`, `HR_ADMIN_EMAIL`/`HR_ADMIN_PASSWORD` (mới), `ENABLE_LLM=true`, `ENABLE_DEV_ENDPOINTS=false`,
  **cookie:** `COOKIE_SECURE=true` `COOKIE_SAMESITE=none` (+ domain nếu cần), `CORS_ORIGINS`=URL Vercel, `FRONTEND_BASE_URL`=URL Vercel (magic-link),
  screener thresholds (72h/24h/sweep). → Deploy, lấy **URL backend**.

### 4.3 Deploy frontend (Vercel)

- Import repo → framework Next.js → root = thư mục dashboard (monorepo: set root directory + build command pnpm nếu cần).
- Env: `NEXT_PUBLIC_API_BASE` = URL backend (từ 4.2). → Deploy, lấy **URL frontend**.

### 4.4 Nối cross-domain (thứ tự gà-trứng)

- Sau khi có URL frontend → **cập nhật `CORS_ORIGINS` + `FRONTEND_BASE_URL` của backend** = URL frontend → redeploy backend.
- Xác nhận: cookie backend đặt với `SameSite=None; Secure` (đã env-driven từ 09); frontend gọi `credentials:"include"`.

---

## 5. Verify (trên URL LIVE — đánh thức backend trước)

1. Mở URL frontend. **Đánh thức backend** (mở /api/health hoặc chờ cold start).
2. **Guest:** `/apply` (URL live) → nộp CV **ẩn danh** (email của bạn) → xác nhận. Pipeline chấm (backend live đọc CV từ R2).
3. **Screener:** nhận email câu hỏi (magic-link trỏ URL frontend live) → mở form → nộp → resume.
4. **HR login (RỦI RO #1):** `/login` (live) bằng tài khoản seed prod → **đăng nhập được VÀ giữ phiên** (cookie cross-domain hoạt động — đây là chỗ hay vỡ). `/applications`, `/review`, `/jobs` truy cập được.
5. **Duyệt** → thư mời thật gửi đi. **Tải CV gốc** (HR live) → nhận file. Gate/auto-reject/auto-invite thử được.
6. **PWA:** cài web app trên điện thoại (HTTPS Vercel) → mở được.
7. Chưa login gọi API HR (live) → 401; endpoint tải CV chưa login → 401 (CV không lộ).

---

## 6. ⚠️ GOTCHAS — đọc kỹ

- **Cookie cross-domain (RỦI RO #1):** frontend (vercel.app) ≠ backend (onrender.com) = cross-site → cookie PHẢI `SameSite=None; Secure`, và CORS `allow_credentials=True` + `allow_origins`=URL frontend (KHÔNG `*`). Sai → login trả 200 nhưng cookie KHÔNG lưu/gửi → HR không giữ được phiên. Kiểm kỹ ở verify #4.
- **Không serverless** cho backend (sweep/checkpointer/BackgroundTasks cần process bền).
- **Free tier ngủ:** đánh thức trước demo; sweep timeout dừng lúc ngủ (quét bù khi thức) — chấp nhận cho đồ án.
- **Secret prod MỚI:** JWT_SECRET + HR_ADMIN_PASSWORD mới (giá trị dev đã lộ trong chat — KHÔNG tái dùng).
- **`STORAGE_BACKEND=r2`** trên prod (dev là local); `ENABLE_DEV_ENDPOINTS=false`.
- **DB prod riêng** (Neon branch) — đừng trỏ prod vào DB dev. Bắt đầu DB sạch (chỉ seed HR admin; rows cũ trước-06 bị validate_key từ chối).
- **NFR-4:** hệ public → CV **ẩn danh** khi demo, không dùng CV người thật.
- Gà-trứng URL: deploy backend → lấy URL → deploy frontend với URL đó → cập nhật CORS backend = URL frontend → redeploy.

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- Code-prep CHỈ động vào: CORS-từ-env + config build/start + health + hardening public + `.env.example` + xác nhận entrypoint Linux. KHÔNG đổi nghiệp vụ/agents/pipeline.
- Cookie/CORS cross-domain đúng chuẩn (credentials + origin cụ thể). Secret từ env, không hardcode. Bucket R2 private.
- Chạy impact analysis trước khi sửa main/config (GitNexus nếu có, không thì grep-based). Commit nhỏ (vd `feat(deploy): CORS từ env + credentials`, `feat(deploy): Dockerfile + start migrate+uvicorn`, `feat(deploy): health + hardening public endpoints`, `docs(deploy): env prod`).
- Nghiệp vụ chưa rõ → **PRD.md**. Vướng cấu hình → DỪNG, hỏi (nhiều bước ở dashboard — mình hướng dẫn).
- Kết thúc code-prep: in tóm tắt + hướng dẫn bạn từng bước runbook; sau runbook cùng chạy verify live.

## 8. Sau lát này

Hệ thống LIVE trên internet, demo từ xa. Kế tiếp: **UI redesign** (đánh bóng trên bản live, từng phần, no-backend-touched) →
(tùy chọn: 10 analytics tí hon, 12 anti-injection nếu chưa gộp vào 3.4, 14 LLM gợi ý rubric). Rồi viết báo cáo. Xem ROADMAP.md.
