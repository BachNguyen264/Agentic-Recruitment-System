# SLICE 05 — UI quản lý JD (tạo/sửa/đóng) + toggle gate · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** HR quản lý tin tuyển dụng (JD) qua giao diện web — tạo, xem danh sách, sửa, đóng/mở — thay cho
> gọi API tay. Toggle gate auto-reject (hoãn từ 03c) nằm trong form này. Mở đường cho lát 07 (nộp CV công khai).
> Tham chiếu: PRD §12.1 (FR-HR-JD), §9 (gate_config), §7.2 (rubric). Tuân thủ `CLAUDE.md` + skill frontend-design.
>
> **Rubric = HR NHẬP TAY** (LLM gợi ý rubric ở §17 — KHÔNG làm ở đây). Bắt đầu GĐ2.

---

## 1. In scope / Out of scope

**In scope:**

- Backend (bổ sung, có phẫu thuật): sửa JD (`PUT/PATCH /api/jobs/{id}`) — **re-embed CHỈ khi title/description/
  requirements đổi**; đóng/mở JD (status). (Tạo/đọc/gate đã có từ 02a/03c — tái dùng.)
- Trang danh sách JD (`/jobs`).
- Form JD dùng chung cho TẠO + SỬA: title, description, requirements (danh sách động), rubric (danh sách động
  {tiêu chí, trọng số} + hiển thị tổng trọng số), screener_questions (danh sách động), gate_config (toggle auto_reject).
- Toggle gate (nợ từ 03c) đặt trong form.

**Out of scope (KHÔNG làm):**

- KHÔNG nộp CV công khai (lát 07). KHÔNG object storage (lát 06). KHÔNG LLM gợi ý rubric (§17).
- KHÔNG re-chấm điểm các application cũ khi sửa rubric (chỉ ảnh hưởng application MỚI — ghi chú §3.1).
- KHÔNG đụng pipeline/agents/ranker logic. KHÔNG auto-invite UI (gate mời — lát sau).
- KHÔNG thêm thư viện UI ngoài shadcn.

---

## 2. Prerequisites

- Endpoint đã có: `POST /api/jobs` (tạo + embed), `GET /api/jobs` (list), `GET /api/jobs/{id}`, `PATCH /api/jobs/{id}/gate`.
- Dịch vụ có sẵn: `embedding_service`, `qdrant_service` (upsert). shadcn/ui, TanStack Query, lib/api.ts. Node chạy PowerShell.

---

## 3. Việc cần làm

### 3.1 Backend — sửa JD + đóng/mở · `app/api/routes/jobs.py` + `job_service.py`

- `PUT /api/jobs/{id}` (hoặc PATCH) nhận các trường JD (title, description, requirements, rubric, screener_questions, gate_config):
  - Cập nhật DB.
  - **Re-embed CÓ ĐIỀU KIỆN:** nếu title/description/requirements THAY ĐỔI → `build_jd_text` → `embed_text` →
    `qdrant.upsert_jd` (ghi đè vector cùng job_id). Nếu CHỈ rubric/screener_questions/gate_config đổi → KHÔNG re-embed.
    (So sánh giá trị cũ/mới để quyết định; tránh gọi embedding thừa.)
  - Lỗi embedding không làm sập cập nhật (giữ pattern 02a: cập nhật DB vẫn xong + cảnh báo).
- Đóng/mở JD: `PATCH /api/jobs/{id}/status` (hoặc field `status` trong PUT) — vd `OPEN`/`CLOSED`. JD `CLOSED` sẽ
  không nhận CV mới (dùng ở lát 07). Không xóa JD.
- **Ghi chú (không code):** sửa rubric CHỈ ảnh hưởng application chấm SAU đó; application cũ giữ điểm cũ (không tự re-chấm).

### 3.2 shared-types · `packages/shared-types`

- `JobPosting` (read: id, title, description, requirements[], rubric[{criterion,weight}], screener_questions[],
  gate_config{auto_reject,auto_invite}, status, created_at); `JobPostingInput` (create/edit payload).

### 3.3 `lib/api.ts`

- `getJobs()`, `getJob(id)`, `createJob(input)`, `updateJob(id, input)`, `setJobStatus(id, status)`,
  `toggleGate(id, {auto_reject})` (đã có PATCH /gate — tái dùng, hoặc gộp vào updateJob). Chọn một, ưu tiên gọn.

### 3.4 Trang danh sách JD · `app/jobs/page.tsx`

- Bảng JD: tiêu đề, trạng thái (OPEN/CLOSED badge), số tiêu chí rubric, gate auto_reject (bật/tắt badge), ngày tạo.
- Nút "Tạo JD mới" → form tạo. Bấm dòng → form sửa. Nút đóng/mở JD (đổi status).
- TanStack Query; loading/empty/error gọn.

### 3.5 Form JD (dùng chung TẠO + SỬA) · `components/JobForm.tsx` (+ trang tạo/sửa)

- Trường: title (text), description (textarea), requirements (**danh sách động**: thêm/bớt dòng text).
- **rubric (danh sách động, phần khó nhất):** mỗi dòng = {tiêu chí (text) + trọng số (số 0..1)} + nút xóa; nút thêm dòng.
  - Hiển thị **TỔNG trọng số** đang chạy + gợi ý "nên bằng 1.0". Validate MỀM: cảnh báo nếu tổng lệch 1.0 nhiều
    (không chặn cứng — backend/ranker vốn tính lại điểm theo trọng số; ưu tiên hướng dẫn HR đặt tổng ≈ 1).
- screener_questions (**danh sách động**: thêm/bớt dòng text) — ghi chú nhỏ "dùng cho vòng Screener (kích hoạt sau)".
- **gate (nợ từ 03c):** toggle `auto_reject` (mặc định TẮT) + ghi chú ngắn "tự động từ chối ca điểm thấp rõ ràng;
  ca bất định vẫn về HR". Có thể hiện toggle `auto_invite` nhưng disable + nhãn "dùng cho vòng Screener — sẽ bật sau".
- Nút Lưu: TẠO → `createJob`; SỬA → `updateJob`. Sau lưu → invalidate query + quay lại danh sách. Chống double-submit.
- Chế độ SỬA: nạp giá trị JD hiện tại vào form.

### 3.6 Điều hướng

- Link `/jobs` từ nav/trang chủ.

---

## 4. Verify (chạy thật)

1. `make dev-backend` + `make dev-dashboard`; mở `/jobs`.
2. **Tạo JD mới** qua form: điền title/description, thêm vài requirements, thêm rubric 3–4 tiêu chí (tổng trọng số ≈ 1), vài câu screener, gate auto_reject TẮT → Lưu → JD xuất hiện trong danh sách; backend embed (kiểm `search-test` khớp JD mới).
3. **Sửa mô tả** JD đó → Lưu → backend RE-EMBED (log/kiểm search-test phản ánh nội dung mới).
4. **Sửa CHỈ rubric/gate** (không đụng mô tả) → Lưu → KHÔNG re-embed (không gọi embedding thừa).
5. **Bật gate auto_reject** trong form → Lưu → `GET /api/jobs/{id}` thấy `gate_config.auto_reject=true` (khớp hành vi 03c).
6. **Đóng JD** → status CLOSED (badge đổi); mở lại → OPEN.
7. Danh sách động: thêm/bớt dòng rubric + requirements hoạt động; tổng trọng số hiển thị đúng.
8. `pnpm --filter dashboard build` PASS; `make test` xanh (nếu có test backend cho edit/status).

---

## 5. Definition of Done

- [ ] `/jobs` liệt kê JD (tiêu đề, trạng thái, số tiêu chí, gate, ngày); tạo/sửa/đóng-mở được qua UI.
- [ ] Form JD dùng chung tạo+sửa; rubric/requirements/screener_questions là danh sách động; tổng trọng số hiển thị.
- [ ] Toggle gate auto_reject trong form → lưu đúng vào gate_config (nợ 03c đã trả).
- [ ] Sửa JD RE-EMBED khi title/description/requirements đổi; KHÔNG re-embed khi chỉ rubric/gate/screener đổi.
- [ ] Lỗi embedding không làm sập cập nhật; đóng JD đổi status (không xóa).
- [ ] KHÔNG nộp CV công khai, KHÔNG storage, KHÔNG LLM-gợi-ý-rubric, KHÔNG đụng pipeline/ranker.
- [ ] shadcn, không thêm lib UI; `pnpm build` PASS; test backend (nếu có) xanh.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md + frontend-design)

- CHỈ động vào: endpoint sửa/đóng JD (+ re-embed có điều kiện) + shared-types/api + trang /jobs + JobForm + nav. KHÔNG đụng pipeline/agents/ranker.
- Backend sửa có phẫu thuật: tái dùng embedding/qdrant service sẵn có; chỉ re-embed khi văn bản đổi.
- Rubric HR nhập tay (KHÔNG LLM). gate mặc định TẮT. Không hardcode.
- Component JobForm dùng chung tạo+sửa (tránh trùng lặp); style nhất quán /applications; validate mềm cho trọng số.
- Commit nhỏ (vd `feat(api): sửa JD + re-embed có điều kiện + đóng/mở`, `feat(ui): trang danh sách /jobs`, `feat(ui): JobForm (rubric/requirements động) + toggle gate`, `feat(ui): trang tạo/sửa JD`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§12.1, §9, §7.2). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD.

---

## 7. Lát kế tiếp (KHÔNG làm bây giờ)

**07 Nộp CV công khai:** trang công khai xem JD đang OPEN → chọn JD → nộp CV (gắn JD) → vào pipeline async. Dùng
`status=OPEN` từ lát này để lọc JD hiển thị. Rồi **06 object storage** (gần lúc deploy). Xem ROADMAP.md.
