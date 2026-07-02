# SLICE 01b — UI upload CV + hiển thị kết quả parse · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát UI. Xong + nghiệm thu thì bỏ. Nguồn chân lý vẫn là **`PRD.md`**.
> **Mục tiêu:** màn hình web cho phép upload CV (PDF/DOCX), gọi endpoint `parse-cv` (đã có ở slice 01),
> hiển thị `parsed_data` + `confidence` + `uncertainty_flags` một cách gọn gàng. Vừa để nghiệm thu Parser
> trực quan, vừa là viên gạch UI THẬT đầu tiên. Frontend-only.
> Tham chiếu: PRD §7.1 (Parser), §14 (web). Tuân thủ `CLAUDE.md` + skill frontend-design.

---

## 1. In scope / Out of scope

**In scope:**

- Component tái dùng `CVUpload` (chọn/kéo-thả file) + `ParsedCVResult` (hiển thị parsed_data dạng đẹp).
- Một route mới trong dashboard (`/cv-check`) dùng hai component trên.
- `lib/api.ts`: thêm hàm gọi `POST /api/agents/parse-cv` (multipart FormData).
- Trạng thái loading (parse mất vài giây) + xử lý lỗi + validate phía client (loại file, kích thước).
- Hiển thị confidence, uncertainty_flags (badge), và xử lý gọn trường null / ca `parse_failed`.

**Out of scope (KHÔNG làm ở lát này):**

- KHÔNG lưu file / object storage (endpoint parse-cv xử lý in-memory — để lát storage riêng sau).
- KHÔNG chọn JD, KHÔNG tạo application, KHÔNG luồng async — đó là trang nộp CV công khai thật, lát sau.
- KHÔNG auth/đăng nhập.
- KHÔNG đụng backend (parse-cv đã có từ slice 01) — đây là lát thuần frontend.
- KHÔNG dựng các trang HR khác (danh sách ứng viên, review queue…) — ngoài phạm vi.
- KHÔNG thêm thư viện UI nặng ngoài shadcn/ui đã có (đừng thêm react-dropzone… — dùng native).

---

## 2. Prerequisites

- Backend chạy (`make dev-backend`) với slice 01 đã xong; `POST /api/agents/parse-cv` hoạt động.
- Dashboard: `NEXT_PUBLIC_API_URL` trỏ đúng backend (đã có từ scaffold).
- Lệnh Node chạy trong PowerShell (máy này Git Bash lỗi fnm — đã biết).

---

## 3. Việc cần làm

### 3.1 `lib/api.ts` — hàm gọi parse-cv

- Thêm `parseCv(file: File): Promise<ParseCvResponse>`: tạo `FormData`, append `file`, `POST` tới
  `${NEXT_PUBLIC_API_URL}/api/agents/parse-cv` (multipart, KHÔNG tự set Content-Type — để browser tự thêm boundary).
- Kiểu `ParseCvResponse = { parsed_data: ParsedCV | null; confidence: number; uncertainty_flags: string[] }`.
- Nếu `packages/shared-types` là nơi đặt type dùng chung, thêm `ParsedCV` (và các type con Experience/Education) vào đó để backend-shape và frontend khớp; import từ đó.

### 3.2 Component `CVUpload` — `components/CVUpload.tsx`

- Presentational + có callback: nhận prop `onResult(result)` và `onError(err)`; hoặc tự quản mutation bên trong (chọn một, ưu tiên gọn).
- UI: vùng chọn file (input `accept=".pdf,.docx"`) + hỗ trợ kéo-thả bằng native drag events (không thư viện ngoài). Hiện tên file sau khi chọn; nút "Phân tích CV".
- **Validate client trước khi gửi:** chỉ nhận `.pdf`/`.docx`; chặn > 10MB. Sai → hiện thông báo thân thiện, không gọi API.
- Dùng TanStack Query `useMutation` cho lần upload (đây là action). Khi `isPending`: hiện spinner + disable nút.
- Cho phép upload lại (reset kết quả cũ khi chọn file mới).

### 3.3 Component `ParsedCVResult` — `components/ParsedCVResult.tsx`

- **Thuần presentational**, nhận prop `{ parsed_data, confidence, uncertainty_flags }` — để TÁI DÙNG sau ở
  màn chi tiết ứng viên của HR và trang nộp CV công khai.
- Hiển thị:
  - **confidence**: badge/thanh nhỏ (vd 1.0 → "Đầy đủ", thấp → màu cảnh báo).
  - **uncertainty_flags**: mỗi cờ một badge; nếu chứa `parse_failed` → hiện khối cảnh báo rõ ("Không đọc được
    CV / có thể là ảnh scan"), KHÔNG cố render các trường trống.
  - **Thông tin**: họ tên + email + phone (khối liên hệ). Trường null → hiện "—" hoặc bỏ, không vỡ layout.
  - **skills**: dạng chip/badge.
  - **experiences**: mỗi mục một card: title + (company nếu có, null → nhãn "Dự án cá nhân" hoặc bỏ) +
    (duration nếu có) + summary.
  - **education**: school + field + year + (degree nếu có).
  - **total_years_experience**: hiện nếu khác null.
  - **professional_summary**: khối văn bản.
- Dùng component shadcn/ui sẵn có (Card, Badge, Alert, Skeleton…). Giữ style NHẤT QUÁN với ServiceStatus/
  AgentTracePanel đã có (cùng spacing, cùng "cảm giác").

### 3.4 Route `/cv-check` — `app/cv-check/page.tsx`

- Trang ghép `CVUpload` (trên) + `ParsedCVResult` (hiện khi có kết quả). Tiêu đề rõ ("Kiểm tra bóc tách CV").
- Thêm một link/nav tới trang này từ trang chủ (giữ trang chủ nguyên trạng — service status + Run demo).
- Trạng thái: chưa upload → hướng dẫn ngắn; đang phân tích → Skeleton/spinner; có kết quả → ParsedCVResult;
  lỗi API → Alert lỗi (vd backend chưa chạy).

---

## 4. Verify (chạy thật)

1. `make dev-backend` + `make dev-dashboard`; mở `http://localhost:3000/cv-check`.
2. Upload `good_cv.pdf` (hoặc CV thật) → hiện đúng họ tên, skills (chip), 2 experiences, education,
   confidence 1.0, flags rỗng.
3. Upload `sparse_cv.pdf`/`not_a_cv.pdf` → confidence thấp / trường null hiển thị gọn, không vỡ layout.
4. Upload file `.txt` hoặc file > 10MB → client chặn, hiện thông báo, KHÔNG gọi API.
5. Tắt backend rồi upload → hiện Alert lỗi thân thiện (không crash trắng trang).
6. `pnpm -r build` (hoặc `pnpm --filter dashboard build`) PASS.

---

## 5. Definition of Done

- [ ] `/cv-check` upload được CV và hiển thị parsed_data đẹp (họ tên, skills chip, experiences, education, summary).
- [ ] confidence + uncertainty_flags hiển thị; ca `parse_failed` hiện cảnh báo rõ, không render trường trống.
- [ ] Trường null (company/duration/degree/total_years…) hiển thị gọn, layout không vỡ.
- [ ] Validate client: chặn sai loại file + > 10MB trước khi gọi API.
- [ ] Loading state khi parse; lỗi API hiện Alert (không crash).
- [ ] `ParsedCVResult` là component thuần presentational, tái dùng được (nhận prop, không tự fetch).
- [ ] Trang chủ giữ nguyên; có link tới `/cv-check`.
- [ ] KHÔNG lưu file, KHÔNG JD/application/auth, KHÔNG đụng backend.
- [ ] `pnpm build` PASS; không thêm thư viện UI ngoài shadcn.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md + frontend-design)

- CHỈ động vào dashboard (frontend). KHÔNG sửa backend, KHÔNG đụng các node/agent.
- Đơn giản trước: dùng shadcn sẵn có, native drag-drop, không thêm dependency. Không thêm tính năng ngoài mục 3
  (không filter, không lưu lịch sử, không export… — nếu nảy ra ý, ghi vào PRD §17, đừng làm).
- Component tách bạch: `ParsedCVResult` thuần presentational (tái dùng), `CVUpload` lo upload + trạng thái.
- Giữ style nhất quán với component sẵn có; thiết kế sạch, đủ dùng, không polish quá mức (chức năng > thẩm mỹ).
- Type khớp backend: dùng/khai báo `ParsedCV` ở `shared-types` để frontend và backend cùng một shape.
- Commit nhỏ theo bước (vd `feat(ui): parseCv api + ParsedCV types`, `feat(ui): CVUpload + ParsedCVResult`, `feat(ui): /cv-check page + nav link`).
- Nghiệp vụ/hiển thị chưa rõ → tra **PRD.md** (§7.1, §14). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD đã đạt.
