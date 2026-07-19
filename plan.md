# SLICE JD-1 — Field mới cho tin tuyển dụng + editor định dạng (bổ sung nội dung) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** làm JD "đầy đủ + đẹp" hơn cho ứng viên và dễ soạn hơn cho HR: thêm field level/salary/benefits/
> employment_type; **mô tả + yêu cầu (+ quyền lợi) → ô văn bản ĐỊNH DẠNG dán-được cả khối** (bỏ nhập-từng-dòng);
> hiển thị các field mới ở trang /apply. Tham chiếu: PRD §12.1 (FR-HR-JD-1), §16 (JobPosting), §8.1. Tuân thủ `CLAUDE.md`.
>
> **Ranh giới lát này (quan trọng):** JD-1 CHỈ _bổ sung nội dung_, KHÔNG tách form 2 màn, KHÔNG đổi status-rule,
> KHÔNG chuyển gate, KHÔNG AI-gợi-ý, KHÔNG đổi định tuyến screener. Tất cả cái đó là JD-2/JD-3/JD-4. Rubric/câu
> hỏi sàng lọc/gate ở form hiện tại GIỮ NGUYÊN hành vi (chỉ để yên, không xóa).

---

## 1. In scope / Out of scope

**In scope:**

- Model JobPosting: thêm `level`, `salary` (min/max/currency/negotiable), `benefits`, `employment_type`; **`requirements` đổi từ list → văn bản định dạng**. Migration (include_object guard).
- Backend: create/edit nhận field mới + validate; **embedding + đầu vào LLM dùng PLAIN-TEXT** (bóc tag khỏi mô tả/yêu cầu — không feed HTML cho embedding/ranker).
- Frontend form JD: thêm input level (dropdown) / salary (từ/đến/thỏa-thuận + tiền tệ) / benefits / employment_type; **editor định dạng (bold/italic/underline/list)** cho mô tả + yêu cầu (+ benefits).
- Public /apply chi tiết JD: hiển thị field mới (level/salary/benefits/employment_type) + render nội dung định dạng (đã sanitize).

**Out of scope (KHÔNG làm — JD-2/3/4):**

- KHÔNG tách form 2 màn / KHÔNG status DRAFT / KHÔNG rubric-bắt-buộc-để-mở / KHÔNG screener-tùy-chọn routing (JD-2).
- KHÔNG chuyển gate ra list (JD-2). KHÔNG AI gợi ý rubric (JD-3). KHÔNG soft-delete/ARCHIVED (JD-4).
- KHÔNG đụng pipeline/ranker-scoring/screener logic (ngoài việc bóc plain-text cho embedding/LLM). KHÔNG xóa/đổi hành vi rubric/screener/gate hiện có.

---

## 2. Prerequisites

- **Chọn thư viện rich-text NHẸ.** Đề xuất **Tiptap** (headless, tree-shakeable, hợp Tailwind, chỉ bật extension cần: bold/italic/underline/bulletList/orderedList). Thay thế đơn giản hơn: react-quill (dễ tích hợp nhưng bundle lớn hơn). **Claude Code chốt theo bundle size** — ưu tiên nhẹ, chỉ cần định dạng cơ bản. KHÔNG kéo cả bộ editor nặng.
- Lưu nội dung định dạng dạng **HTML** (hoặc JSON của editor) — thống nhất một format cho mô tả/yêu cầu/benefits.

## 3. Việc cần làm

### 3.1 Model + migration · `app/models/` + Alembic

- Thêm cột: `level` (string/enum: intern/fresher/junior/mid/senior/lead/manager), `salary` (JSONB hoặc cột rời: min/max nullable + currency default VND + negotiable bool), `benefits` (text định dạng), `employment_type` (string/enum: full_time/part_time/contract/internship).
- **`requirements`: list → text định dạng.** Migration đổi kiểu; nếu row cũ còn dạng list → nối thành text (data hiện đã sạch nên rủi ro thấp; vẫn xử lý an toàn).
- Migration Alembic **NHỚ `include_object` guard** (đừng drop bảng checkpoint — bài học 08b).

### 3.2 Backend create/edit + embedding · schema + jd service

- Schema/endpoint tạo/sửa JD nhận field mới; validate (vd salary min ≤ max; currency hợp lệ; level/employment_type trong tập cho phép).
- **PLAIN-TEXT cho embedding + LLM:** `build_jd_text` (và bất kỳ chỗ nào đưa mô tả/yêu cầu cho embedding hoặc ranker LLM) phải **bóc HTML → plain text** trước (định dạng KHÔNG được lọt vào embedding/prompt). Re-embed khi mô tả/tiêu đề/yêu cầu đổi (đã có từ 05) vẫn đúng.
- shared-types cập nhật field mới.

### 3.3 Frontend form JD · JobForm

- Thêm input: `level` (dropdown), `salary` (từ/đến + tiền tệ + checkbox "thỏa thuận" → ẩn từ/đến khi bật), `employment_type` (dropdown), `benefits` (editor).
- **Editor định dạng** (component tái dùng `RichTextEditor`) cho **mô tả + yêu cầu (+ benefits)** — toolbar bold/italic/underline/bullet/ordered. **Yêu cầu** bỏ UI nhập-từng-dòng-bấm-thêm → thành ô dán-được-cả-khối.
- Giữ nguyên các section rubric/câu hỏi sàng lọc/gate hiện có (KHÔNG đụng).

### 3.4 Public /apply · trang chi tiết JD

- Hiển thị field mới hướng-ứng-viên: level, salary (từ/đến hoặc "Thỏa thuận"), employment_type, benefits.
- **Render nội dung định dạng AN TOÀN:** mô tả/yêu cầu/benefits render HTML đã **sanitize** (DOMPurify) — vì trang công khai; không để HTML thô chưa lọc ra ứng viên. (Nội dung do HR soạn nên rủi ro thấp, nhưng sanitize là chuẩn.)
- Projection công khai vẫn KHÔNG lộ rubric/gate/screener (giữ như 07).

### 3.5 Test

- Create/edit JD với field mới → lưu + đọc lại đúng. Salary validate (min>max báo lỗi; thỏa-thuận bỏ min/max). requirements text lưu/hiện đúng.
- embedding/ranker nhận PLAIN-TEXT (không có tag HTML trong text đưa vào embedding — test build_jd_text bóc tag).
- /apply hiển thị field mới + render định dạng (sanitize); projection không lộ nội bộ.

## 4. Verify (chạy thật)

1. `make dev-backend` + `make dev-dashboard`. Đăng nhập HR → tạo JD mới: điền level/salary/benefits/employment_type; **dán cả khối mô tả + yêu cầu** (có định dạng bold/list) → lưu.
2. Mở lại JD (edit) → field + nội dung định dạng còn nguyên. Sửa mô tả → re-embed chạy (đã có).
3. Mở JD đó (OPEN) trên `/apply` → thấy level/lương/loại việc/quyền lợi + mô tả/yêu cầu render định dạng đẹp; KHÔNG lộ rubric/điểm.
4. Nộp một CV → pipeline chấm bình thường (không hồi quy — embedding dùng plain-text). Kiểm log: text đưa vào embedding KHÔNG chứa tag HTML.
5. `make test` xanh; `pnpm --filter dashboard build` PASS (kiểm bundle editor không phình quá).

## 5. Definition of Done

- [ ] JobPosting có level/salary/benefits/employment_type; requirements = văn bản định dạng; migration (+ include_object guard).
- [ ] Form JD: input field mới + **editor định dạng cho mô tả/yêu cầu/benefits**; yêu cầu dán-được-cả-khối (bỏ nhập-từng-dòng).
- [ ] /apply hiển thị field mới + render nội dung định dạng **đã sanitize**; projection không lộ nội bộ.
- [ ] embedding + LLM nhận **plain-text** (bóc HTML); pipeline không hồi quy; re-embed khi nội dung đổi vẫn đúng.
- [ ] Rubric/câu hỏi sàng lọc/gate hiện có KHÔNG bị đụng. KHÔNG tách form/status/gate-move/AI-suggest.
- [ ] `make test` xanh; `pnpm build` PASS; bundle editor hợp lý.

## 6. Gotchas & quy ước (theo CLAUDE.md)

- **Bóc HTML trước khi vào embedding/LLM** — định dạng chỉ để hiển thị, KHÔNG lọt vào semantic matching/prompt (nếu không, tag làm nhiễu điểm).
- **Sanitize HTML ở trang công khai** (DOMPurify) — /apply render nội dung; không xuất HTML thô.
- Editor NHẸ (Tiptap/tương đương) — chỉ định dạng cơ bản; đừng phình bundle. Lưu một format nhất quán (HTML).
- Migration requirements (list→text) an toàn cho row cũ; include_object guard. CHỈ động content-layer; KHÔNG đụng pipeline/ranker/screener logic.
- Chạy impact analysis trước khi sửa jd service/build_jd_text (GitNexus nếu có, không thì grep). Commit nhỏ (vd `feat(jd): field mới + requirements text (model+migration)`, `feat(jd): plain-text cho embedding/LLM`, `feat(ui): RichTextEditor + field mới form JD`, `feat(ui): /apply hiển thị field + render sanitize`, `test(jd): field mới + plain-text embedding`).
- Nghiệp vụ chưa rõ → **PRD.md** (§12.1, §16, §8.1). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify + checklist DoD.

## 7. Sau lát này

**JD-2** — tách form 2 màn ('Tin tuyển dụng' / 'Cấu hình sàng lọc' trên JD đã lưu) + status DRAFT + rubric-bắt-buộc-để-mở

- screener-tùy-chọn (đổi định tuyến) + gate ra list. Rồi **JD-3** (AI gợi ý rubric), **JD-4** (soft-delete). Xem ROADMAP.md.
