# SLICE 07 — Nộp CV công khai (ứng viên guest chọn JD → nộp → pipeline) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** "cửa vào" của ứng viên — trang công khai liệt kê JD đang MỞ → ứng viên (guest, chỉ email) chọn một
> vị trí → nộp CV GẮN với JD đó → vào pipeline async (parser→ranker→...). Khép luồng "HR đăng tin (05) → ứng viên nộp".
> Tham chiếu: PRD §8.2 (luồng nộp), §12.2 (FR-AP), §14 (web). Tuân thủ `CLAUDE.md` + skill frontend-design.
>
> **Guest, chỉ JD OPEN, async, LƯU FILE CỤC BỘ** (object storage = lát 06, hoãn tới gần deploy). UI Tailwind thuần
> (nhất quán component sẵn có; redesign để giai đoạn cuối). KHÔNG auth (đăng nhập HR = GĐ4).

---

## 1. In scope / Out of scope

**In scope:**

- Backend: endpoint CÔNG KHAI liệt kê JD `OPEN` (**projection AN TOÀN** — chỉ trường ứng-viên-thấy); endpoint nộp CV
  công khai (validate JD OPEN + loại/size file → lưu cục bộ → tạo application gắn job_id → chạy pipeline async).
- shared-types: JD công khai (trường an toàn) + payload nộp.
- Trang công khai `/apply` (danh sách JD OPEN) + `/apply/[jobId]` (chi tiết JD + form nộp: email + CVUpload → xác nhận).
- Tái dùng `CVUpload` (đã có từ 01b).

**Out of scope (KHÔNG làm):**

- KHÔNG object storage (lưu cục bộ — lát 06). KHÔNG auth/đăng nhập (GĐ4).
- KHÔNG trang tra cứu trạng thái cho ứng viên (guest không đăng nhập; họ nhận email sau qua scheduler). KHÔNG hiện điểm/trạng thái cho ứng viên.
- KHÔNG lộ rubric/gate_config/screener_questions cho ứng viên (nội bộ — xem §3.1).
- KHÔNG đụng pipeline/agents/ranker logic. KHÔNG redesign UI (giai đoạn cuối).

---

## 2. Prerequisites

- Lát 05 xong: JD có `status` OPEN/CLOSED. Có JD OPEN để test (JD #2; lưu ý JD #4 gate đang BẬT).
- Có sẵn: `CVUpload`, logic tạo application + chạy pipeline (từ scaffold/các lát trước), parser/ranker thật.
- Lưu file cục bộ hiện tại (thư mục uploads). Node chạy PowerShell.

---

## 3. Việc cần làm

### 3.1 Backend — JD công khai + nộp CV · `app/api/routes/` (+ service)

- **Liệt kê JD công khai:** `GET /api/public/jobs` → chỉ JD `status == OPEN`, **projection AN TOÀN**: chỉ
  `id, title, description, requirements` (+ ngày nếu muốn). **TUYỆT ĐỐI KHÔNG trả** `rubric`, `gate_config`,
  `screener_questions` — đây là tiêu chí chấm/cấu hình nội bộ; lộ ra thì ứng viên có thể "nhồi từ khóa" theo rubric.
- **Chi tiết JD công khai:** `GET /api/public/jobs/{id}` → cùng projection an toàn; 404 nếu không OPEN.
- **Nộp CV công khai:** `POST /api/public/applications` (multipart: `job_id`, `applicant_email`, file CV):
  1. **Validate**: JD tồn tại + `OPEN` (không thì 404/409); loại file ∈ {PDF, DOCX} (kiểm magic bytes, không chỉ đuôi); size ≤ ~10MB. Email hợp lệ cơ bản.
  2. Lưu file CV cục bộ (như hiện tại), tạo application gắn `job_id` + `applicant_email`, status `SUBMITTED`.
  3. Kick pipeline async (BackgroundTask — như luồng tạo application hiện có).
  4. Trả xác nhận gọn (vd `{application_id}` hoặc chỉ success) — KHÔNG trả điểm/parsed_data cho ứng viên.
- **Sửa có phẫu thuật:** ĐỌC logic tạo application + chạy pipeline hiện có → TÁI DÙNG; chỉ thêm lớp public
  (projection an toàn + validate OPEN + validate file). Đừng viết lại pipeline.

### 3.2 shared-types · `packages/shared-types`

- `PublicJob = {id, title, description, requirements[], created_at?}` (KHÔNG rubric/gate/screener).
- `SubmitApplicationInput = {job_id, applicant_email, file}` (payload nộp).

### 3.3 `lib/api.ts`

- `getOpenJobs(): Promise<PublicJob[]>` → GET /api/public/jobs.
- `getPublicJob(id)` → GET /api/public/jobs/{id}.
- `submitApplication(job_id, email, file)` → POST /api/public/applications (multipart).

### 3.4 Trang công khai · `app/apply/page.tsx` + `app/apply/[jobId]/page.tsx`

- `/apply`: danh sách JD OPEN (tiêu đề + mô tả ngắn) → bấm một JD → sang chi tiết. Empty ("hiện không có vị trí mở")/loading/error.
- `/apply/[jobId]`: hiện chi tiết JD (title, description, requirements) + **form nộp**: ô email + `CVUpload` (tái dùng)
  → nút "Nộp hồ sơ". Validate client (email + loại/size file). Đang gửi → disable, chống double-submit.
- Sau khi nộp thành công → **màn xác nhận** ("Cảm ơn, hồ sơ của bạn đã được gửi. Chúng tôi sẽ liên hệ qua email.")
  — KHÔNG hiện điểm/trạng thái. Lỗi → thông báo thân thiện.
- **Tách khỏi dashboard HR:** trang công khai KHÔNG dùng nav HR (không lẫn với /jobs, /applications, /review).

### 3.5 (Không bắt buộc) liên kết

- Có thể để một link "Trang tuyển dụng công khai" ở đâu đó cho tiện demo, nhưng public pages là luồng riêng của ứng viên.

---

## 4. Verify (chạy thật)

1. Đảm bảo có JD OPEN (JD #2). Nếu test JD #4 thì tắt gate trước (`PATCH /api/jobs/4/gate {auto_reject:false}`).
2. `make dev-backend` + `make dev-dashboard`; mở `/apply` → thấy danh sách JD OPEN (chỉ JD OPEN; JD CLOSED không hiện).
3. Kiểm projection an toàn: response `GET /api/public/jobs` KHÔNG chứa rubric/gate_config/screener_questions.
4. Chọn JD #2 → `/apply/[id]` hiện title/description/requirements + form. Nhập email của bạn, upload CV backend → Nộp → màn xác nhận (không hiện điểm).
5. Kiểm application đã tạo: sang dashboard HR `/applications` → thấy ứng viên mới (gắn đúng JD #2) đã chạy pipeline (có điểm/trạng thái). Audit có parser+ranker.
6. Thử JD CLOSED / job_id sai → nộp bị từ chối (404/409). Thử file .txt hoặc >10MB → bị chặn (client + server).
7. `pnpm --filter dashboard build` PASS; `make test` xanh (nếu có test backend cho public endpoints).

---

## 5. Definition of Done

- [ ] `/apply` liệt kê JD OPEN; `/apply/[jobId]` hiện JD an toàn + form nộp (email + CVUpload tái dùng).
- [ ] Nộp CV công khai (guest, chỉ email) → tạo application gắn job_id → chạy pipeline async; màn xác nhận (không lộ điểm/trạng thái).
- [ ] JD công khai KHÔNG lộ rubric/gate_config/screener_questions (projection an toàn — verify).
- [ ] Validate: chỉ nhận JD OPEN; loại file PDF/DOCX + size ≤ ~10MB (client + server).
- [ ] Ứng viên mới hiện đúng trên /applications của HR (gắn đúng JD, đã chấm).
- [ ] Lưu file cục bộ (chưa object storage); trang công khai tách khỏi nav HR.
- [ ] KHÔNG auth, KHÔNG storage cloud, KHÔNG tra cứu trạng thái ứng viên, KHÔNG đụng pipeline/ranker.
- [ ] `pnpm build` PASS; test backend (nếu có) xanh.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md + frontend-design)

- CHỈ động vào: public endpoints (list OPEN an toàn + nộp CV) + shared-types/api + trang /apply + form. KHÔNG đụng pipeline/agents/ranker.
- Backend sửa có phẫu thuật: TÁI DÙNG logic tạo application + pipeline hiện có; chỉ thêm lớp public + validate. Đừng viết lại pipeline.
- BẢO MẬT: projection JD công khai chỉ trường an toàn (không rubric/gate/screener); validate loại+size file ở SERVER (không chỉ client).
- Guest, chỉ email; ứng viên không thấy điểm/trạng thái (HR-only). UI Tailwind thuần, nhất quán component sẵn có; tách nav HR.
- Commit nhỏ (vd `feat(api): public JD list an toàn + endpoint nộp CV (validate OPEN + file)`, `feat(ui): trang /apply danh sách JD OPEN`, `feat(ui): trang chi tiết JD + form nộp (CVUpload) + xác nhận`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§8.2, §12.2, §14). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhắc dùng email của người dùng), checklist DoD.

---

## 7. Sau lát này

Cửa vào ứng viên hoàn chỉnh: đăng tin (05) → ứng viên nộp (07) → pipeline → HR xem/duyệt → email ra. Kế tiếp:
**06 object storage** (chuyển lưu file lên cloud, gần lúc deploy) hoặc bước vào **GĐ3 Screener async** (phần khó nhất). Xem ROADMAP.md.
