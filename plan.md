# SLICE 03a — Màn HR: danh sách ứng viên + chi tiết điểm (chỉ đọc) · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát UI (chủ yếu frontend). Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** làm pipeline HỮU HÌNH — HR thấy danh sách ứng viên kèm điểm + trạng thái, và màn chi tiết hiện
> breakdown điểm (tái dùng `ParsedCVResult` + thêm phần điểm). CHỈ ĐỌC, chưa có duyệt/từ chối (lát human_review sau).
> Tham chiếu: PRD §11 (breakdown điểm), §13 (trạng thái/ba rổ), §14 (web HR). Tuân thủ `CLAUDE.md` + skill frontend-design.

---

## 1. In scope / Out of scope

**In scope:**

- Backend (TỐI THIỂU): đảm bảo endpoint list + detail trả đủ trường cần (score/status/flags…); CHỈ thêm nếu thiếu.
- shared-types: kiểu `Application` (list + detail) + `ScoreBreakdown`.
- Component `ScoreBreakdown` (thuần presentational, tái dùng sau ở ReviewCard).
- Trang danh sách ứng viên (`/applications`) + bộ lọc theo ba rổ trạng thái (đang xử lý / chờ HR / passed / rejected).
- Trang chi tiết ứng viên (`/applications/[id]`): thông tin + `ParsedCVResult` + `ScoreBreakdown` + ngữ cảnh JD (tiêu chí rubric).
- Link điều hướng từ trang chủ tới `/applications`.

**Out of scope (KHÔNG làm ở lát này):**

- KHÔNG có duyệt/từ chối (mutation) — đó là lát human_review kế tiếp.
- KHÔNG gate, KHÔNG đụng logic agent/pipeline/policy.
- KHÔNG hiển thị timeline agent-trace/audit chi tiết (có thể thêm sau; lát này tập trung danh sách + điểm).
- KHÔNG thêm thư viện UI mới ngoài shadcn/ui đã có.

---

## 2. Prerequisites

- Có dữ liệu để xem: vài application đã chạy parser+ranker (upload CV cho job_id=2). Nếu DB trống → tạo vài cái trước khi verify.
- `NEXT_PUBLIC_API_URL` đã có. Lệnh Node chạy PowerShell.

---

## 3. Việc cần làm

### 3.1 Backend — kiểm tra trước, chỉ sửa nếu thiếu (sửa có phẫu thuật)

- **ĐỌC** `app/api/routes/applications.py` + schema hiện có. Xác nhận:
  - `GET /api/applications` (list) trả mỗi item gồm: `id, applicant_email, job_id, status, score, confidence,
uncertainty_flags, created_at`. (KHÔNG cần trả `parsed_data` đầy đủ trong list — giữ nhẹ.) Thiếu trường nào → thêm vào response schema.
  - `GET /api/applications/{id}` (detail) trả đầy đủ: `parsed_data, score, score_breakdown, semantic_similarity,
confidence, uncertainty_flags, status, job_id, applicant_email, created_at`. Thiếu → thêm.
- Lọc theo trạng thái: làm **client-side** (frontend lọc theo rổ) để khỏi đụng backend. (Tùy chọn: thêm `?status=` nếu muốn, không bắt buộc.)
- KHÔNG đụng logic tạo/chấm; chỉ đảm bảo READ trả đủ.

### 3.2 shared-types — `packages/shared-types/src/index.ts`

- `ApplicationListItem = {id, applicant_email, job_id, status, score, confidence, uncertainty_flags, created_at}`.
- `ApplicationDetail` = list item + `parsed_data (ParsedCV), score_breakdown, semantic_similarity`.
- `ScoreBreakdownData = {overall_score, criteria: [{criterion, weight, score, reasoning}], semantic_similarity, confidence, uncertainty_flags}`.

### 3.3 `lib/api.ts`

- `getApplications(): Promise<ApplicationListItem[]>` → GET /api/applications.
- `getApplication(id): Promise<ApplicationDetail>` → GET /api/applications/{id}.
- `getJob(id)` → GET /api/jobs/{id} (để hiển thị tiêu đề JD + rubric ở trang chi tiết).

### 3.4 Component `ScoreBreakdown` — `components/ScoreBreakdown.tsx`

- **Thuần presentational** (nhận prop `ScoreBreakdownData`), để TÁI DÙNG ở ReviewCard (lát human_review sau).
- Hiển thị: `overall_score` nổi bật; mỗi tiêu chí một dòng (tên + trọng số + điểm + lý do); `semantic_similarity`
  (nhãn "độ tương đồng ngữ nghĩa — tham khảo, không tính điểm"); `confidence`; `uncertainty_flags` dạng badge
  (vd `score_signal_mismatch` → badge cảnh báo). Dùng shadcn (Card/Badge/Progress…).

### 3.5 Trang danh sách — `app/applications/page.tsx`

- Bảng/list ứng viên: applicant_email, JD (job_id — hoặc tiêu đề nếu tiện), score, status (badge màu theo rổ),
  flags, created_at. Bấm dòng → sang chi tiết.
- **Bộ lọc theo ba rổ (PRD §13):** tab/filter: Tất cả / Đang xử lý (SUBMITTED,PARSING,RANKING,SCREENING,AWAITING_SCREENER,SCHEDULING)
  / Chờ HR (PENDING_REVIEW) / Passed (INTERVIEW_SCHEDULED) / Rejected (REJECTED). Map status→rổ ở frontend.
- Dùng TanStack Query `getApplications`. Loading/empty/error state gọn.

### 3.6 Trang chi tiết — `app/applications/[id]/page.tsx`

- Header: applicant_email + status badge + JD (tiêu đề, lấy qua `getJob`).
- `ParsedCVResult` (tái dùng, hiển thị parsed_data — gồm certificates/languages/awards/other đã có từ 01c).
- `ScoreBreakdown` (điểm + từng tiêu chí + lý do + similarity + confidence + flags).
- (Tùy chọn nhẹ) hiển thị rubric của JD cạnh breakdown để thấy "chấm theo tiêu chí nào".
- Loading/error state gọn.

### 3.7 Điều hướng

- Thêm link tới `/applications` từ trang chủ (giữ trang chủ nguyên trạng: ServiceStatus + demo). Đơn giản.

---

## 4. Verify (chạy thật)

1. Đảm bảo có dữ liệu: upload 2–3 CV cho job_id=2 (một khớp, một lệch ngành) → chúng chạy parser+ranker.
2. `make dev-backend` + `make dev-dashboard`; mở `/applications` → thấy danh sách kèm score + status + flags.
3. Bấm bộ lọc: "Chờ HR" hiện đúng các PENDING_REVIEW; "Passed" hiện INTERVIEW_SCHEDULED; v.v.
4. Bấm một ứng viên → chi tiết: thông tin + parsed_data (ParsedCVResult) + breakdown điểm từng tiêu chí (có lý do) + similarity + confidence + flags + tiêu đề JD.
5. Ứng viên có cờ `score_signal_mismatch` → badge cảnh báo hiện rõ ở breakdown.
6. `pnpm --filter dashboard build` PASS.

---

## 5. Definition of Done

- [ ] `GET /api/applications` + `/{id}` trả đủ trường (score/status/flags/breakdown…); chỉ thêm nếu thiếu, không refactor.
- [ ] `/applications` hiển thị danh sách ứng viên kèm điểm + trạng thái; bộ lọc ba rổ (PRD §13) hoạt động.
- [ ] `/applications/[id]` hiển thị parsed_data (ParsedCVResult tái dùng) + ScoreBreakdown (từng tiêu chí + lý do) + JD.
- [ ] `ScoreBreakdown` là component thuần presentational (nhận prop), tái dùng được.
- [ ] similarity hiển thị kèm nhãn "tham khảo, không tính điểm"; flags hiển thị dạng badge.
- [ ] KHÔNG có mutation (duyệt/từ chối); KHÔNG đụng agent/pipeline/gate.
- [ ] Không thêm thư viện UI ngoài shadcn; `pnpm build` PASS.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md + frontend-design)

- CHỈ động vào: read endpoints (nếu thiếu trường) + shared-types + lib/api + ScoreBreakdown + 2 trang + link. KHÔNG đụng logic agent/policy/gate.
- Backend: sửa có phẫu thuật — ĐỌC trước, chỉ thêm trường response còn thiếu, không đổi logic tạo/chấm.
- Component tách bạch, thuần presentational (ScoreBreakdown, và ParsedCVResult đã có) để tái dùng ở human_review.
- Style nhất quán với /cv-check + ServiceStatus; sạch, đủ dùng, không polish quá mức; đừng đẻ tính năng ngoài mục 3.
- Commit nhỏ (vd `feat(api): list/detail trả đủ score+status (nếu thiếu)`, `feat(ui): ScoreBreakdown + shared-types`, `feat(ui): trang /applications danh sách + lọc`, `feat(ui): trang chi tiết ứng viên`).
- Nghiệp vụ/hiển thị chưa rõ → tra **PRD.md** (§11, §13, §14). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD.

---

## 7. Lát kế tiếp (KHÔNG làm bây giờ)

**human_review THẬT:** ReviewCard (tái dùng ScoreBreakdown + tóm tắt + lý do leo thang) + nút Duyệt/Từ chối →
delegate scheduler (PRD §11). Đây là lát biến điểm đến "human_review" từ stub thành khâu thật. Rồi tới gate rank (§9).
