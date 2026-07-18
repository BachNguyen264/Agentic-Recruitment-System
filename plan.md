# SLICE 06 — Object storage (lưu CV lên cloud sau seam) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** chuyển lưu file CV từ đĩa LOCAL → cloud (Cloudflare R2, S3-compatible) SAU một interface storage —
> local cho dev, R2 cho prod, đổi bằng config. File CV BỀN qua restart/redeploy (điều kiện tiên quyết deploy).
> Tham chiếu: PRD §16 (cv_file_ref), NFR-4. Tuân thủ `CLAUDE.md`.
>
> **Seam:** interface `FileStorage` (`save/get/url/delete`) + `LocalStorage` (dev, hành vi hiện tại) + `R2Storage`
> (prod, S3 API). Nghiệp vụ đi qua interface, KHÔNG đọc/ghi path trực tiếp. Đổi impl = đổi config, không sửa nghiệp vụ.

---

## 1. In scope / Out of scope

**In scope:**

- Interface `FileStorage` + `LocalStorage` (bọc hành vi đĩa hiện tại) + `R2Storage` (Cloudflare R2 qua S3 API, boto3).
- Config chọn backend (`STORAGE_BACKEND=local|r2`) + credentials R2 (từ env).
- **Refactor:** mọi chỗ lưu/đọc file CV đi qua interface — upload (/cv-check + nộp công khai 07) lưu qua `save()` → `cv_file_ref` = KEY; parser (và mọi chỗ đọc CV) đọc qua `get(key)` thay vì mở path.
- `delete()` + cập nhật `reset_demo_data.py` xóa file qua storage khi xóa application (tránh file mồ côi).
- **HR tải CV gốc (IN-SCOPE):** endpoint trong khu HR (bảo vệ `require_hr` từ 09) **STREAM** file qua `get()`; nút "Tải CV gốc" ở trang chi tiết ứng viên. Bucket PRIVATE, KHÔNG public URL.

**Out of scope (KHÔNG làm):**

- KHÔNG đổi pipeline/agents logic (chỉ đổi _cách lấy bytes CV_). KHÔNG đổi luồng nộp (chỉ đổi _nơi file nằm_).
- KHÔNG migrate file cũ (dev đang dọn data — không cần). KHÔNG public-bucket cho CV (dữ liệu cá nhân — private + presigned/stream).
- KHÔNG đụng auth/screener/gate logic. KHÔNG deploy (đó là 13 — nhưng chuẩn bị cho nó).

---

## 2. Prerequisites

- Tài khoản Cloudflare R2: tạo **bucket** (private) + **API token** (Access Key ID + Secret) + endpoint
  `https://<account_id>.r2.cloudflarestorage.com`. Đặt vào env: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT`. `.env.example` có mẫu (KHÔNG commit secret).
- Dep: `boto3` (+ `aioboto3` nếu muốn async thuần) qua `uv add`. `STORAGE_BACKEND` mặc định `local` cho dev.

---

## 3. Việc cần làm

### 3.1 Interface + impls · `app/services/storage/`

- `FileStorage` (Protocol/ABC): `async save(key, data, content_type) -> str` · `async get(key) -> bytes` ·
  `async url(key) -> str` (presigned/stream — để HR tải nếu cần) · `async delete(key) -> None`.
- `LocalStorage`: bọc hành vi đĩa hiện tại (thư mục uploads). `save` ghi file, `get` đọc bytes, `delete` xóa,
  `url` trả đường dẫn nội bộ / qua endpoint stream.
- `R2Storage`: boto3 S3 client (endpoint R2 + credentials). `save`=put_object, `get`=get_object, `delete`=delete_object,
  `url`=presigned URL (hạn ngắn) HOẶC stream qua backend. **Async:** boto3 đồng bộ → bọc `asyncio.to_thread`
  (nhất quán email_service) HOẶC dùng aioboto3. Bucket PRIVATE (không public).
- Factory theo `STORAGE_BACKEND`: trả LocalStorage/R2Storage. App phụ thuộc INTERFACE.

### 3.2 Refactor điểm lưu/đọc file · upload + parser

- **Lưu:** endpoint nộp CV (public 07 + /cv-check) → `storage.save(...)` → lưu KEY vào `cv_file_ref` (thay vì path local).
  Key có cấu trúc rõ (vd `cv/{application_id}/{uuid}.pdf`).
- **Đọc:** parser (và bất kỳ chỗ nào mở file CV) → `storage.get(cv_file_ref)` lấy bytes → xử lý. KHÔNG mở path trực tiếp.
- Rà quét TOÀN BỘ code còn đọc/ghi path CV trực tiếp → chuyển qua interface (đừng sót chỗ nào).

### 3.3 Dọn file khi xóa application · `reset_demo_data.py`

- Xóa application → gọi `storage.delete(cv_file_ref)` (tránh file mồ côi, nhất quán với cascade session/checkpoint).

### 3.4 HR tải CV gốc (IN-SCOPE) · endpoint HR + nút ở chi tiết ứng viên

- Endpoint tải CV gốc **NẰM TRONG khu HR** (áp `require_hr` từ 09 — chưa đăng nhập → 401). **STREAM** file về qua
  `storage.get(cv_file_ref)` (trả bytes + đúng content-type + filename). **KHÔNG** dùng public URL; bucket giữ PRIVATE.
- Ưu tiên stream qua backend (mọi lượt tải đều qua kiểm auth, không rò URL). Nếu dùng presigned `url()` thì hạn RẤT
  ngắn (vài phút) + vẫn sinh sau khi `require_hr` pass — nhưng khuyến nghị stream cho đơn giản/an toàn.
- Frontend: nút "Tải CV gốc" ở trang chi tiết ứng viên (khu HR đã bảo vệ). Gọi kèm credentials (cookie auth).
- **Tuyệt đối:** endpoint này KHÔNG public; CV = dữ liệu cá nhân (NFR-4) — link tải không cần đăng nhập là vi phạm.

### 3.5 Config · `app/core/config.py`

- `STORAGE_BACKEND` + R2 credentials (pydantic-settings). `.env.example` cập nhật.

### 3.6 Test · `app/tests/test_storage.py`

- LocalStorage: save→get roundtrip; delete xóa; url trả cái gì đó hợp lệ.
- R2Storage: mock boto3 client (KHÔNG gọi R2 thật trong test) — save gọi put_object đúng key/bucket; get gọi get_object; delete gọi delete_object.
- Factory chọn đúng impl theo config. Upload→parser đọc qua interface (không path trực tiếp).

---

## 4. Verify (chạy thật — kiểm CẢ hai backend)

1. **Local (mặc định):** `STORAGE_BACKEND=local`, `make dev-backend` + dashboard. Nộp CV qua `/apply` → pipeline chấm bình thường (file trên đĩa, parser đọc được) → không hồi quy.
2. **R2:** đặt `STORAGE_BACKEND=r2` + credentials R2. Restart backend. Nộp CV qua `/apply` → **kiểm R2 dashboard: file xuất hiện trong bucket** → parser đọc từ R2 → pipeline chấm điểm (log không lỗi) → HR thấy hồ sơ.
3. **HR tải CV gốc:** đăng nhập HR → trang chi tiết ứng viên → bấm "Tải CV gốc" → nhận đúng file (stream qua get). **Chưa đăng nhập** gọi endpoint tải (Postman, không cookie) → **401** (CV không lộ ra ngoài). Kiểm với backend R2 (file thật từ bucket private).
4. **Bền:** với R2, restart backend → file vẫn còn (khác local ephemeral) — đây là mục tiêu chính.
5. `reset_demo_data` xóa application → file tương ứng biến mất khỏi storage (local + R2).
6. Đổi lại `STORAGE_BACKEND=local` → vẫn chạy (seam hoạt động hai chiều).
7. `make test` xanh (mock R2); `pnpm build` PASS (nếu đụng UI tải CV).

---

## 5. Definition of Done

- [ ] Interface `FileStorage` + LocalStorage + R2Storage; factory theo `STORAGE_BACKEND`; nghiệp vụ đi qua interface.
- [ ] Nộp CV → `save()` (key vào cv_file_ref); parser đọc qua `get()`; KHÔNG còn đọc/ghi path CV trực tiếp ở đâu.
- [ ] R2 thật: file lên bucket private, parser đọc được, pipeline chấm; file BỀN qua restart (verify R2 dashboard).
- [ ] Local vẫn chạy (mặc định dev); đổi backend bằng config, không sửa nghiệp vụ.
- [ ] **HR tải CV gốc:** nút ở chi tiết ứng viên; endpoint STREAM qua `get()` trong khu HR (`require_hr`); chưa đăng nhập → 401; bucket PRIVATE (verify tải được khi login, chặn khi không).
- [ ] `reset_demo_data` xóa file qua storage (không mồ côi). CV bucket PRIVATE (không public).
- [ ] KHÔNG đụng pipeline/agents/auth logic; credentials từ env; boto3 bọc async.
- [ ] `make test` xanh (mock R2); `pnpm build` PASS.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: storage interface + 2 impls + refactor điểm lưu/đọc CV + reset_demo_data delete + config + endpoint tải CV (khu HR) + nút tải ở chi tiết + test. KHÔNG đụng pipeline/agents/auth-logic/screener.
- **Endpoint tải CV phải trong khu HR (require_hr), stream qua get(), bucket private — KHÔNG public URL/bucket** (CV = dữ liệu cá nhân NFR-4; link không auth = vi phạm).
- Seam MỎNG: interface + 2 impl + factory; KHÔNG framework thừa. Nghiệp vụ đọc/ghi CV CHỈ qua interface (rà hết, đừng sót path trực tiếp).
- Bucket PRIVATE (CV = dữ liệu cá nhân, NFR-4); truy cập qua presigned/stream, không public URL. boto3 bọc async (to_thread/aioboto3). Credentials từ env.
- Chạy impact analysis trước khi sửa parser/upload (GitNexus nếu có, không thì grep-based). Commit nhỏ (vd `feat(storage): interface + LocalStorage`, `feat(storage): R2Storage (S3) + factory/config`, `refactor(cv): upload/parser qua storage interface`, `feat(storage): reset_demo_data xóa file`, `test(storage): local + mock R2`).
- Nghiệp vụ chưa rõ → **PRD.md** (§16, NFR-4). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn: kiểm file trên R2 + bền qua restart), checklist DoD.

## 7. Sau lát này

File CV bền trên cloud → sẵn sàng **13 deploy** (backend Render/Railway, frontend Vercel, cookie cross-domain đã env-driven từ 09, storage R2 từ đây, env secrets, đánh thức managed). Rồi **UI redesign**. Xem ROADMAP.md.
