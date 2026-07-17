# SLICE 09 — Auth HR (tự làm, một vai, seed sẵn) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** bảo vệ toàn bộ khu vực HR bằng đăng nhập — HR admin login → truy cập dashboard/JD/review/gate;
> chưa đăng nhập → chặn. Ứng viên VẪN guest (public /apply, /screening mở). Một vai (HR-admin), tài khoản SEED sẵn.
> Điều kiện tiên quyết để deploy. Tham chiếu: PRD §4 (vai trò), §14. Tuân thủ `CLAUDE.md`.
>
> **Cách làm:** tự làm — **JWT trong cookie httpOnly + băm mật khẩu bcrypt** (dùng thư viện cho crypto, KHÔNG tự chế).
> KHÔNG Clerk/Neon Auth, KHÔNG OAuth. Một vai HR (KHÔNG Super Admin/RBAC). KHÔNG flow quên/reset/quản-lý tài khoản.

---

## 1. In scope / Out of scope

**In scope:**

- Model `hr_user` + migration (nhớ `include_object` guard — đừng drop bảng checkpoint).
- Seed tài khoản HR admin ban đầu từ env (idempotent). Băm mật khẩu bcrypt (passlib).
- JWT (ký/verify) + config (JWT_SECRET, hạn, cookie settings **đọc từ env** để deploy cross-domain OK).
- Endpoints: `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`.
- Auth dependency → **bảo vệ mọi endpoint HR**; endpoint CÔNG KHAI giữ MỞ.
- Frontend: trang `/login` + bảo vệ mọi trang HR (chưa auth → redirect /login) + nút logout + xử lý 401 + trạng thái auth.

**Out of scope (KHÔNG làm):**

- KHÔNG đăng ký/quên mật khẩu/reset/UI quản lý tài khoản. (Endpoint-bí-mật-có-key tạo/xóa/reset = TÙY CHỌN, chỉ nếu dư thời gian — KHÔNG làm trong lát này.)
- KHÔNG Super Admin / RBAC / nhiều vai. KHÔNG OAuth/social login/SSO. KHÔNG Clerk/Neon Auth.
- KHÔNG đụng pipeline/agents logic. KHÔNG khóa luồng ứng viên (guest).

---

## 2. Prerequisites

- Deps: `passlib[bcrypt]` + `python-jose` (hoặc `pyjwt`) cho JWT. Thêm qua `uv add`.
- Config env: `JWT_SECRET` (mạnh, random), `JWT_EXPIRY_MINUTES`, `HR_ADMIN_EMAIL`, `HR_ADMIN_PASSWORD` (seed),
  cookie settings (`COOKIE_SECURE`, `COOKIE_SAMESITE`, `COOKIE_DOMAIN` — để dev vs prod khác nhau). Cập nhật `.env.example` (giá trị mẫu, KHÔNG commit mật khẩu thật).

---

## 3. Việc cần làm

### 3.1 Model + seed · `app/models/hr_user.py` + `scripts/seed_hr_admin.py`

- `hr_user`: `id`, `email` (unique), `password_hash`, `created_at`. Migration Alembic (**include_object guard**).
- Seed script: đọc `HR_ADMIN_EMAIL`/`HR_ADMIN_PASSWORD` từ env → tạo hr_user nếu CHƯA tồn tại (băm bcrypt), idempotent. (Dùng lúc setup/deploy.)
- **`reset_demo_data.py` KHÔNG xóa hr_user** (tài khoản không phải demo data).

### 3.2 Crypto + JWT · `app/core/security.py`

- `hash_password` / `verify_password` bằng **passlib bcrypt** (KHÔNG tự chế băm).
- `create_access_token(sub)` / `decode_token` bằng JWT ký `JWT_SECRET`, hạn `JWT_EXPIRY_MINUTES`.

### 3.3 Endpoints auth · `app/api/routes/auth.py`

- `POST /api/auth/login` (body: email + password): verify → tạo JWT → set **cookie httpOnly** (Secure/SameSite theo env).
  Sai → 401 **thông báo chung** ("email hoặc mật khẩu không đúng" — KHÔNG tiết lộ email có tồn tại không).
- `POST /api/auth/logout`: xóa cookie.
- `GET /api/auth/me`: đọc cookie → trả HR user hiện tại (id/email); không auth → 401. (Frontend dùng để biết đã đăng nhập chưa.)

### 3.4 Bảo vệ endpoint HR · dependency

- `require_hr` (FastAPI dependency): đọc cookie JWT → verify → nạp hr_user; thiếu/sai/hết hạn → 401.
- **Áp `require_hr` cho MỌI router HR:** `/api/jobs/*` (tạo/sửa/list/detail/đóng/gate), `/api/applications/*` (list/detail/review), `/api/agents/*` (parse-cv/rank-cv — công cụ HR/dev).
- **GIỮ MỞ (KHÔNG áp auth):** `/api/public/*` (JD công khai, nộp CV), `/api/public/screening/*` (GET+POST), `/api/auth/login`, `/api/auth/logout`, health check. → **Ứng viên guest không bị chặn.**
- CORS: cho phép credentials (cookie) từ origin frontend.

### 3.5 Frontend · trang login + bảo vệ trang HR

- `/login`: form email + mật khẩu → POST login → thành công redirect dashboard; lỗi hiện thông báo chung.
- **Bảo vệ mọi trang HR** (`/`, `/applications`, `/applications/[id]`, `/review`, `/jobs`, `/jobs/*`, `/cv-check`): chưa đăng nhập → redirect `/login` (middleware Next.js hoặc kiểm `GET /api/auth/me` ở layout HR).
- **GIỮ MỞ:** `/apply`, `/apply/[jobId]`, `/screening/[token]`, `/login` — công khai, KHÔNG redirect.
- Nút **Logout** ở nav HR (gọi logout → về /login). Xử lý **401 từ API** → redirect /login. Trạng thái auth qua `/api/auth/me`.
- Gọi API kèm credentials (cookie) — cấu hình fetch/TanStack Query gửi cookie.

### 3.6 Test · `app/tests/test_auth.py`

- login đúng → cookie set + /me trả user; sai mật khẩu → 401 chung.
- Endpoint HR không cookie → 401; có cookie hợp lệ → 200.
- Endpoint public (nộp CV, screening) KHÔNG cookie → VẪN 200 (guest không bị chặn).
- Băm mật khẩu: verify đúng/sai; hash không lưu plaintext.

---

## 4. Verify (chạy thật)

1. Seed admin: chạy `seed_hr_admin.py` (env có HR_ADMIN_EMAIL/PASSWORD). `make dev-backend` + `make dev-dashboard`.
2. **Chưa đăng nhập:** mở `/applications` (hoặc `/jobs`, `/review`) → **redirect `/login`**. Gọi `GET /api/applications` (Postman, không cookie) → **401**.
3. **Guest vẫn chạy:** mở `/apply` → hiện JD OPEN + nộp được CV (KHÔNG bị chặn). Mở magic-link `/screening/{token}` → form vẫn mở. → xác nhận ứng viên không bị khóa.
4. **Đăng nhập:** `/login` với tài khoản seed → vào dashboard; `/applications`, `/jobs`, `/review` truy cập được; thao tác HR (tạo JD, duyệt) chạy.
5. Sai mật khẩu → thông báo chung (không lộ email tồn tại hay không).
6. **Logout** → về /login; truy cập lại trang HR → bị chặn.
7. Luồng end-to-end vẫn nguyên: nộp CV qua /apply (guest) → pipeline chấm → đăng nhập HR thấy hồ sơ trên /applications.
8. `make test` xanh; `pnpm --filter dashboard build` PASS.

---

## 5. Definition of Done

- [ ] `hr_user` + migration (include_object guard); seed admin từ env idempotent; bcrypt băm mật khẩu.
- [ ] login/logout/me hoạt động; JWT trong cookie httpOnly; sai đăng nhập → 401 chung.
- [ ] MỌI endpoint + trang HR được bảo vệ (chưa auth → 401/redirect login).
- [ ] Endpoint + trang CÔNG KHAI (/apply, /screening, login) VẪN mở — ứng viên guest KHÔNG bị chặn (verify).
- [ ] Cookie settings (Secure/SameSite/domain) đọc từ env (sẵn sàng cross-domain khi deploy).
- [ ] KHÔNG đăng ký/quên/reset/quản-lý-tài-khoản; KHÔNG Super Admin/RBAC/OAuth; pipeline/agents không đụng.
- [ ] `reset_demo_data` KHÔNG xóa hr_user; `make test` xanh; `pnpm build` PASS.

---

## 6. 🔒 BẢO MẬT — đọc kỹ

- **Mật khẩu:** bcrypt qua passlib. KHÔNG plaintext, KHÔNG tự chế băm/salt.
- **JWT:** ký bằng `JWT_SECRET` mạnh (từ env, KHÔNG hardcode); hạn hợp lý.
- **Cookie:** `httpOnly` (JS không đọc được → chống XSS lấy token); `Secure` (HTTPS ở prod); `SameSite` (chống CSRF; dev Lax, prod cross-domain None+Secure). Đọc từ env.
- **Không lộ thông tin:** lỗi đăng nhập chung chung (không nói email tồn tại hay không).
- **Không khóa nhầm guest:** public/applicant endpoints + trang PHẢI mở (kiểm kỹ ở verify).
- Rate-limit đăng nhập (chống brute-force): ghi chú deploy-time (proxy) — không bắt buộc code ở lát này; có thể thêm giới hạn đơn giản nếu nhanh.

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: hr_user/seed + security(crypto/JWT) + auth endpoints + require_hr dependency áp lên router HR + frontend login/bảo-vệ-trang + test. KHÔNG đụng pipeline/agents.
- Một vai HR; seed sẵn; KHÔNG account-management/quên-reset (endpoint-key tùy chọn = việc riêng sau nếu dư giờ).
- Public endpoints/trang giữ MỞ tuyệt đối. Cookie settings từ env cho deploy. Crypto dùng thư viện.
- Chạy impact analysis trước khi sửa router (GitNexus nếu có, không thì grep-based). Commit nhỏ (vd `feat(auth): hr_user + seed + bcrypt/JWT`, `feat(auth): login/logout/me + require_hr bảo vệ router HR`, `feat(ui): trang login + bảo vệ trang HR + logout`, `test(auth): login + bảo vệ + guest mở`).
- Nghiệp vụ chưa rõ → **PRD.md** (§4). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn: guest vẫn nộp được + trang HR bị chặn khi chưa login), checklist DoD.

## 8. Sau lát này

HR được bảo vệ, ứng viên vẫn guest → sẵn sàng deploy. Kế tiếp (đường về đích): **06 object storage** → **13 deploy** →
**UI redesign** → (tùy chọn: 10 analytics tí hon, 12 chống prompt injection). Observability đã BỎ. Xem ROADMAP.md.
