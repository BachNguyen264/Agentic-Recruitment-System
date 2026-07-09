# SLICE 01c — Bổ sung certificates/languages/awards/other cho Parser + benchmark lại · plan one-shot

> **Bản chất:** plan ONE-SHOT, lát nhỏ sửa lỗi dữ liệu. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Bối cảnh:** benchmark end-to-end lộ ra parser bỏ sót chứng chỉ (TOEIC 945/990) vì schema `ParsedCV`
> thiếu trường certificates → ranker chấm tiêu chí "Tiếng Anh" trên dữ liệu khuyết → benchmark model bị méo.
> **Mục tiêu:** thêm `certificates`, `languages`, `awards` (có cấu trúc) + `other` (lưới an toàn hứng khối
> lạ) vào ParsedCV; parser trích được chúng — ƯU TIÊN trường có cấu trúc, `other` chỉ hứng phần còn lại; rồi
> **benchmark lại** (gpt-4.1 vs gpt-5-mini) end-to-end trên CV thật CÓ TOEIC để chọn model trên dữ liệu sạch.
> Tham chiếu: PRD §7.1 (Parser). Tuân thủ `CLAUDE.md`. LLM parser: gpt-4.1-mini (giữ nguyên, không đổi).

---

## 1. In scope / Out of scope

**In scope:**

- Mở rộng schema `ParsedCV`: `certificates`, `languages`, `awards` (có cấu trúc) + `other` (lưới an toàn), mặc định [].
- Cập nhật prompt parser để trích các khối này (chỉ khi CÓ, KHÔNG bịa) — ƯU TIÊN xếp vào trường có cấu trúc, chỉ cái không thuộc trường nào mới cho vào `other`.
- Cập nhật `ParsedCVResult` (UI slice 01b) hiển thị các khối mới (gồm `other`) nếu có (nhẹ).
- Fixture có chứng chỉ + test (mock LLM).
- **Benchmark lại** end-to-end trên CV thật có TOEIC → in bảng so sánh 2 model → chờ người dùng chọn.

**Out of scope (KHÔNG làm):**

- KHÔNG đụng logic `ranker` — ranker đã đúng: nó ĐỌC TOÀN BỘ parsed_data theo dẫn dắt của rubric, nên các trường
  mới (certificates/languages/awards/other) TỰ ĐỘNG thành bằng chứng khi một tiêu chí rubric cần. Lát này chỉ sửa _dữ liệu đầu vào_.
- KHÔNG đổi công thức confidence (các khối mới GỒM `other` KHÔNG vào mẫu số — xem 3.3).
- KHÔNG migration DB (parsed_data là JSONB, thêm trường không cần Alembic).
- KHÔNG đụng gate/screener/scheduler/human_review; KHÔNG đổi model parser.

---

## 2. Prerequisites

- Không thêm dependency. `.env` giữ nguyên (parser dùng gpt-4.1-mini như slice 01).
- Có CV thật của bạn (có TOEIC) để benchmark — cung cấp lại file cho Claude Code nếu cần.

---

## 3. Việc cần làm

### 3.1 Mở rộng schema — `app/schemas/parsed_cv.py`

Thêm (giữ NHẸ, mặc định [] để tương thích ngược):

- `certificates: list[Certificate]` — `Certificate = {name: str, detail: str | None, year: str | None}`
  (detail = điểm/cấp độ, vd "945/990"; ví dụ: name="TOEIC", detail="945/990", year="2023").
- `languages: list[Language]` — `Language = {name: str, proficiency: str | None}`
  (vd name="English", proficiency="Professional working").
- `awards: list[str]` — mỗi phần tử một mô tả ngắn.
- `other: list[OtherItem]` — LƯỚI AN TOÀN cho khối CV không thuộc trường nào. `OtherItem = {label: str, content: str}`
  (vd label="Sở thích", content="đọc sách, cờ vua"; label="Người tham chiếu", content="..."). Mục đích: KHÔNG mất
  thông tin CV. KHÔNG phải thùng rác — xem ràng buộc ưu tiên ở 3.2.

### 3.2 Cập nhật prompt parser — `app/agents/nodes/parser.py`

- Thêm hướng dẫn trích certificates (tên + điểm/chi tiết + năm), languages (tên + trình độ), awards, và `other`.
- **RÀNG BUỘC ƯU TIÊN (quan trọng — để `other` không thành thùng rác):** nêu rõ trong prompt thứ tự xếp thông tin:
  1. LUÔN ưu tiên xếp vào đúng trường có cấu trúc (name, contact, skills, experiences, education, certificates,
     languages, awards). 2) CHỈ cho vào `other` những khối KHÔNG thuộc bất kỳ trường nào ở trên. 3) TUYỆT ĐỐI
     không đẩy chứng chỉ/ngôn ngữ/giải thưởng vào `other` — chúng đã có trường riêng.
- GIỮ nguyên tắc: chỉ trích thông tin CÓ THẬT trong CV, KHÔNG bịa; thiếu → để [] / None.
- KHÔNG làm giảm chất lượng trích các trường cũ (name/skills/experiences/education). Chỉ thêm, không phá.

### 3.3 Confidence — GIỮ NGUYÊN

- Mẫu số confidence vẫn là 5 khối lõi cũ `{full_name, (email or phone), skills, experiences, education}`.
- Các khối mới (certificates/languages/awards/`other`) KHÔNG vào công thức (là bổ sung, không phải lõi — CV không có chứng chỉ/other không phải parse kém).

### 3.4 UI hiển thị — `components/ParsedCVResult.tsx` (nhẹ)

- Thêm mục hiển thị certificates / languages / awards / `other` (label + content) NẾU có (rỗng thì ẩn, không vỡ layout).
- Giữ style nhất quán; đây là component thuần presentational (không tự fetch).

### 3.5 Fixture + test

- Thêm/cập nhật một fixture CV có chứng chỉ (vd TOEIC) + mục ngôn ngữ + một khối lạ (vd "Sở thích") để thử `other`.
- Test (mock LLM): parse CV có chứng chỉ → `certificates` không rỗng, đúng tên+điểm; languages/awards đúng.
- Test ƯU TIÊN: mock đầu ra sao cho chứng chỉ nằm ở `certificates` (KHÔNG ở `other`); khối lạ ("Sở thích") nằm ở `other`.
- Test tương thích ngược: CV không có các khối → chúng = []; confidence KHÔNG đổi (vẫn theo 5 khối lõi).

---

## 4. Benchmark lại (Claude Code chạy, in kết quả cho người dùng chọn)

> Giờ parser trích được TOEIC nên tiêu chí "Tiếng Anh" có bằng chứng — benchmark model mới công bằng.

1. Chạy `parse-cv` trên CV thật (có TOEIC) → **xác nhận** parsed_data giờ CHỨA certificates (TOEIC 945/990).
2. Chạy end-to-end (parser thật → `rank-cv`) trên CV đó với JD id=2, cho CẢ HAI model, mỗi model 2 lần:
   - M1 non-reasoning: `RANKER_MODEL=gpt-4.1`, `RANKER_REASONING_EFFORT=` (trống).
   - M2 reasoning: `RANKER_MODEL=gpt-5-mini`, `RANKER_REASONING_EFFORT=low`.
3. In **bảng so sánh song song**: overall + breakdown từng tiêu chí (đặc biệt tiêu chí Tiếng Anh — giờ phải phản ánh TOEIC) + similarity + flags + độ trễ + độ nhất quán 2 lần.
4. So với benchmark cũ (CV khuyết TOEIC): chỉ ra English của cả hai model giờ thay đổi ra sao khi có bằng chứng.
5. **Không tự chọn model** — trình bày để người dùng quyết. Sau khi chọn: ghi `RANKER_MODEL` (+ effort) vào `.env`/`.env.example` + 1–2 dòng lý do cho báo cáo Chương 4.

---

## 5. Verify

1. `make dev-backend`; `parse-cv` một CV có chứng chỉ → JSON có `certificates`/`languages`/`awards` đúng.
2. CV không có ba khối → chúng = [], confidence không đổi.
3. `/cv-check` (UI) hiển thị ba khối khi có, ẩn khi rỗng, layout không vỡ.
4. `make test` xanh (gồm test mới + test cũ vẫn pass).
5. Benchmark mục 4 chạy xong, có bảng so sánh trên CV có TOEIC.

---

## 6. Definition of Done

- [ ] `ParsedCV` có `certificates`/`languages`/`awards`/`other` (mặc định []); parser trích đúng khi CV có.
- [ ] ƯU TIÊN đúng: chứng chỉ/ngôn ngữ/giải thưởng vào trường riêng, KHÔNG lọt `other`; `other` chỉ hứng khối thật sự lạ.
- [ ] Parser không bịa (thiếu → []); chất lượng trích các trường cũ không giảm.
- [ ] Confidence GIỮ NGUYÊN công thức (5 khối lõi); các khối mới (gồm `other`) không vào mẫu số.
- [ ] Không migration DB (JSONB); test cũ vẫn pass (tương thích ngược).
- [ ] `ParsedCVResult` hiển thị ba khối mới khi có; `make test` xanh.
- [ ] Benchmark lại trên CV có TOEIC xong, có bảng so sánh gpt-4.1 vs gpt-5-mini — chờ người dùng chọn.
- [ ] `ranker` KHÔNG bị đụng logic; gate/screener/scheduler/human_review KHÔNG bị đụng.

---

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: schema ParsedCV + prompt parser + ParsedCVResult (hiển thị) + fixture/test + chạy benchmark.
- KHÔNG đụng ranker/policy/graph logic (ranker đã đúng — nó đọc toàn bộ parsed_data theo rubric; các trường mới tự thành bằng chứng khi tiêu chí cần). Lát này sửa DỮ LIỆU đầu vào, không sửa cách chấm.
- Đơn giản trước: các khối giữ nhẹ; `other` là lưới an toàn có ràng buộc ưu tiên, KHÔNG phải thùng rác; không thêm dep.
- Commit nhỏ (vd `feat(parser): thêm certificates/languages/awards/other vào ParsedCV + prompt (ưu tiên có cấu trúc)`, `feat(ui): hiển thị các khối mới`, `test(parser): fixture chứng chỉ + other + backward-compat`).
- Nghiệp vụ chưa rõ → tra **PRD.md** §7.1. PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, verify, bảng benchmark, checklist DoD.
