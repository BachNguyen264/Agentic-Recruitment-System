# SLICE 01 — Parser thật (CV → JSON) · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát cắt logic. Xong + nghiệm thu thì bỏ. Nguồn chân lý vẫn là **`PRD.md`**.
> **Mục tiêu lát này:** biến node `parser` từ stub thành THẬT — đọc CV (PDF/DOCX), gọi LLM, trả JSON có cấu
> trúc, gắn confidence + cờ `parse_failed`, lưu vào DB. Chứng minh phần rủi ro nhất: **LLM có đọc CV đủ tốt không.**
> Tham chiếu: PRD §7.1 (Parser), §13 (trạng thái), §16 (mô hình dữ liệu). Tuân thủ `CLAUDE.md`.
>
> **LLM provider lát này: OpenAI** (không dùng Anthropic). Scaffold đã wiring sẵn `langchain-anthropic`; lát
> này thêm `langchain-openai` + `OPENAI_API_KEY`, dùng `ChatOpenAI` cho parser. Config Anthropic cũ để nguyên
> (không dùng tới). Nhờ LangChain, sau này muốn đổi provider chỉ cần thay class — không phá kiến trúc.

---

## 1. In scope / Out of scope

**In scope:**

- Schema Pydantic `ParsedCV` cho đầu ra có cấu trúc.
- Trích xuất văn bản từ PDF (PyMuPDF) và DOCX (python-docx).
- Node `parser` THẬT: trích text → LLM OpenAI (structured output) → `parsed_data` + `confidence` + `uncertainty_flags`.
- Cờ `parse_failed` cho file không đọc được / rỗng / lỗi LLM.
- Lưu file CV upload (local, dev) + lưu `parsed_data` vào bảng `application`.
- Endpoint upload CV; endpoint `parse-cv` đồng bộ để test nhanh chất lượng.
- Vài CV mẫu tổng hợp (Claude Code tự sinh) làm fixture; test (LLM mock).
- Bật LLM CHO RIÊNG parser.

**Out of scope (KHÔNG đụng — vẫn stub):**

- `ranker`, `screener`, `scheduler`, `human_review` — giữ nguyên stub.
- Gate, Screener async, RAG/Qdrant, email/Calendar, vòng học.
- Object storage (S3/Cloudinary) — lát này lưu file local, để TODO cho production.
- OCR cho CV scan ảnh — ngoài phạm vi; CV không trích được text → `parse_failed`.

---

## 2. Prerequisites

- Thêm dependency: `langchain-openai`, `pymupdf`, `python-docx` (qua `uv add`).
- `.env`: đặt `OPENAI_API_KEY` thật. Thêm `PARSER_MODEL` (khuyến nghị `gpt-4o-mini` — rẻ, đủ tốt cho trích
  xuất; đặt model string hiện hành của OpenAI, kiểm tra docs nếu không chắc).
- Thêm `OPENAI_API_KEY` và `PARSER_MODEL` vào `core/config.py` (pydantic-settings) và `.env.example`.
- `ENABLE_LLM=true` (hoặc cờ riêng `PARSER_ENABLED=true` — chọn một, nhất quán).

---

## 3. Việc cần làm

### 3.1 Schema đầu ra — `app/schemas/parsed_cv.py`

`ParsedCV` (Pydantic v2), giữ ĐƠN GIẢN (đừng over-engineer):

- `full_name: str | None`, `email: str | None`, `phone: str | None`
- `skills: list[str]` (mặc định [])
- `experiences: list[Experience]` — `Experience = {company, title, duration, summary}` (đều str|None)
- `education: list[Education]` — `Education = {school, degree, field, year}` (str|None)
- `total_years_experience: float | None`
- `professional_summary: str | None`

### 3.2 Trích xuất văn bản — `app/tools/cv_reader.py`

- `extract_text(path) -> str`: theo đuôi file → PDF dùng PyMuPDF (`fitz`, gom `page.get_text()`), DOCX dùng
  python-docx (gom paragraph). Đuôi khác → raise lỗi rõ ràng.
- Nếu text sau khi strip < ~50 ký tự → coi như rỗng/CV ảnh scan → ném tín hiệu để node set `parse_failed`
  (lý do: "CV có thể là ảnh scan, không trích được văn bản — OCR ngoài phạm vi").

### 3.3 Node parser THẬT — `app/agents/nodes/parser.py`

Thay logic stub bằng:

1. Lấy đường dẫn file CV từ state/application.
2. `extract_text`. Nếu lỗi đọc / text rỗng → set `uncertainty_flags += ["parse_failed"]`, `confidence = 0.0`,
   `escalation_reason = "<lý do>"`, `parsed_data = None`, return (KHÔNG ném exception làm sập pipeline).
3. Nếu có text: gọi LLM `ChatOpenAI(model=settings.PARSER_MODEL, temperature=0).with_structured_output(ParsedCV)`
   với prompt trích xuất (tiếng Việt + Anh; chỉ trích thông tin có thật, không bịa; trường thiếu để None).
4. Tính `confidence` bằng heuristic xác định (KHÔNG hỏi LLM tự chấm): tỉ lệ trường lõi có dữ liệu trong
   `{full_name, (email or phone), skills≠[], experiences≠[], education≠[]}` (mỗi cái 1 điểm / 5).
5. Lưu `parsed_data` (dict) + confidence + flags vào state. Ghi `audit_log` qua `audit_service` (node="parser",
   action, confidence, uncertainty_flags, detail).
6. Bọc lời gọi LLM trong try/except: lỗi API → `parse_failed` + confidence 0.0 + escalation_reason, KHÔNG sập.

- Nếu `ENABLE_LLM=false` → giữ hành vi stub cũ (để không phá các test/flow khác).

### 3.4 Lưu file + cập nhật API

- Thư mục lưu dev: `apps/backend/data/uploads/` (gitignore). Tên file theo `application_id` + đuôi gốc.
  Ghi `# TODO (production): chuyển sang object storage S3/Cloudinary` (xem PRD bàn deploy).
- Mở rộng tạo application thành multipart: `file` (PDF/DOCX) + `applicant_email` + `job_id`. Lưu file, set
  `cv_file_ref`, tạo application `SUBMITTED`, kích BackgroundTask chạy graph (parser THẬT, phần sau vẫn stub).
- `GET /api/applications/{id}` trả `parsed_data`, `confidence`, `uncertainty_flags`, `status`.

### 3.5 Endpoint test nhanh (đồng bộ) — `app/api/routes/agents.py`

- `POST /api/agents/parse-cv` (multipart `file`): chạy NGAY logic parser (không qua DB/queue), trả JSON
  `{parsed_data, confidence, uncertainty_flags}`. Đây là công cụ chính để bạn iterate prompt + kiểm tra chất lượng.

### 3.6 CV mẫu (fixture) — `apps/backend/tests/fixtures/`

Claude Code tự sinh tối thiểu:

- `good_cv.docx` (CV đầy đủ, dữ liệu giả thực tế: tên, email, kỹ năng, 2 kinh nghiệm, học vấn).
- `good_cv.pdf` (tương tự, định dạng PDF — sinh bằng reportlab/fpdf hoặc PyMuPDF).
- `sparse_cv.pdf` (chỉ tên + 1-2 dòng — để thử confidence thấp).
- `not_a_cv.pdf` (văn bản ngẫu nhiên không phải CV — xem hệ thống xử lý sao).
  Bạn (người dùng) có thể tự thả CV thật vào thư mục này để thử thêm.

### 3.7 Test — `apps/backend/tests/test_parser.py`

- **Mock LLM** (không gọi API thật trong test — giữ `make test` nhanh, không tốn credit):
  - parse `good_cv.docx`/`good_cv.pdf` (mock LLM trả ParsedCV đầy đủ) → assert lưu đúng + confidence cao.
  - extract_text trên file rỗng/đuôi lạ → `parse_failed`, confidence 0.0.
  - LLM ném exception → `parse_failed`, không sập.
- Test trích text THẬT (không mock) trên fixture PDF/DOCX → assert text không rỗng (kiểm extractor thật).

---

## 4. Verify (chạy thật)

1. `make migrate` (nếu có thay đổi schema/cột) → OK.
2. `make dev-backend`; tại `/docs` gọi `POST /api/agents/parse-cv` upload `good_cv.pdf` → nhận JSON đúng
   tên/kỹ năng/kinh nghiệm; confidence cao.
3. Upload `sparse_cv.pdf` → confidence thấp; `not_a_cv.pdf` → quan sát đầu ra (nhiều None / flag).
4. Upload một file rỗng hoặc ảnh-scan giả → `uncertainty_flags` chứa `parse_failed`.
5. Tạo application qua endpoint upload → `GET /api/applications/{id}` thấy `parsed_data` đã lưu + audit_log có dòng parser.
6. `make test` xanh.

---

## 5. Definition of Done

- [ ] `POST /api/agents/parse-cv` trả JSON có cấu trúc đúng cho CV mẫu (PDF + DOCX) — dùng OpenAI.
- [ ] confidence phản ánh độ đầy đủ; CV sparse lỗi/rỗng → `parse_failed` + confidence 0.0 + escalation_reason.
- [ ] Tạo application kèm file → `parsed_data` lưu vào bảng `application`; audit_log có dòng node="parser".
- [ ] LLM lỗi không làm sập pipeline (try/except → parse_failed).
- [ ] `make test` xanh (LLM mock); test trích text thật trên fixture pass.
- [ ] `ENABLE_LLM=false` vẫn giữ hành vi stub (không phá flow cũ).
- [ ] `ranker/screener/scheduler/human_review` KHÔNG bị đụng (vẫn stub).
- [ ] File lưu local có `# TODO (production): object storage`.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào parser + những gì mục 3 liệt kê. KHÔNG refactor/đụng các node khác.
- Async-first; cấu hình từ env (OPENAI_API_KEY, PARSER_MODEL, ENABLE_LLM); không hardcode model string/secret.
- Đơn giản trước: schema vừa đủ, không thêm trường suy đoán. confidence bằng heuristic xác định, không hỏi LLM tự chấm.
- Commit nhỏ theo bước (vd `feat(parser): cv_reader + ParsedCV schema`, `feat(parser): real parser node (OpenAI) + flags`, `test(parser): fixtures + mocked tests`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§7.1). PRD chưa đủ → DỪNG, hỏi, đừng suy diễn.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD đã đạt.
