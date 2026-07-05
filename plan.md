# SLICE 02a — Quản lý JD + embedding vào Qdrant · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát logic. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** HR tạo được tin tuyển dụng (JD) đầy đủ; khi tạo, JD được embedding (text-embedding-3-small)
> và lưu vào Qdrant Cloud. Chứng minh hạ tầng vector chạy: JD vào → embed → tra cứu tương đồng ra được.
> Đây là nền cho Ranker (lát 2b). Backend-only.
> Tham chiếu: PRD §7.2 (Ranker cần JD chuẩn), §9 (gate_config), §16 (mô hình dữ liệu). Tuân thủ `CLAUDE.md`.
>
> **LLM/embedding provider: OpenAI.** Embedding model: `text-embedding-3-small` (1536 chiều).

---

## 1. In scope / Out of scope

**In scope:**

- DTO/schema tạo JD đầy đủ: title, description, requirements, rubric (tiêu chí + trọng số), screener_questions, gate_config.
- Endpoint tạo/đọc JD (POST/GET) — lưu DB (bảng `job_posting` đã có từ scaffold).
- Embedding service (OpenAIEmbeddings `text-embedding-3-small`) + xây text JD để embed.
- Thiết lập Qdrant collection (size 1536, Cosine) + upsert vector JD kèm payload `{job_id, title, type:"jd"}`.
- Endpoint/script tra cứu để VERIFY: embed một đoạn text truy vấn → search Qdrant → trả JD khớp + điểm tương đồng.
- Dọn 2 comment cũ trong `apps/backend/app/main.py` (CORS "dashboard/mobile", "Expo web :19006") → sửa cho khớp PWA/một app web.
- Test (mock embedding cho logic; một kiểm tra tích hợp embedding+Qdrant có thể gate hoặc script riêng).

**Out of scope (KHÔNG làm ở lát này):**

- KHÔNG chấm điểm CV, KHÔNG đối sánh CV–JD, KHÔNG đụng node `ranker` (vẫn stub) — đó là lát 2b.
- KHÔNG embed CV (chỉ embed JD; CV embed ở 2b khi Ranker cần).
- KHÔNG chunk JD (một vector/JD là đủ; chunk để tương lai nếu JD quá dài).
- KHÔNG UI quản lý JD (tạo JD qua `/docs` như parser; UI để lát HR dashboard sau).
- KHÔNG đụng screener/scheduler/human_review; KHÔNG gate logic (chỉ lưu gate_config).

---

## 2. Prerequisites

- `.env`: thêm `EMBEDDING_MODEL=text-embedding-3-small`. `OPENAI_API_KEY` đã có. `QDRANT_URL`/`QDRANT_API_KEY`/
  `QDRANT_COLLECTION` (=`cv_jd_embeddings`) đã có từ scaffold.
- `langchain-openai`, `qdrant-client` đã có (parser + scaffold). Thêm `EMBEDDING_MODEL` vào `core/config.py`.

---

## 3. Việc cần làm

### 3.1 Schema tạo JD — `app/schemas/job_posting.py`

`JobPostingCreate` (Pydantic v2), khớp cột bảng `job_posting`:

- `title: str`, `description: str`
- `requirements: list[str]` (các yêu cầu chính) — hoặc str; chọn list cho có cấu trúc.
- `rubric: list[RubricCriterion]` — `RubricCriterion = {criterion: str, weight: float}` (trọng số 0..1; nên tổng ~1, validate mềm).
- `screener_questions: list[str]` (bộ câu hỏi Screener cho JD này — lưu để dùng ở lát Screener sau).
- `gate_config: GateConfig` — `{auto_reject: bool = False, auto_invite: bool = False}` (mặc định TẮT, PRD §9 FR-GATE-3).
- `JobPostingRead` cho GET (kèm id, status, created_at).

### 3.2 Embedding service — `app/services/embedding_service.py`

- `embed_text(text: str) -> list[float]`: dùng `OpenAIEmbeddings(model=settings.EMBEDDING_MODEL)`; trả vector 1536.
- `build_jd_text(jd) -> str`: ghép `title + "\n" + description + "\n" + "\n".join(requirements)` thành text để embed.
- Bọc try/except: lỗi API embedding → raise lỗi rõ ràng (JD vẫn lưu DB được, nhưng đánh dấu chưa embed — xem 3.4).

### 3.3 Qdrant — `app/services/qdrant_service.py` (hoặc mở rộng core/qdrant_client.py)

- `ensure_collection()`: tạo collection `QDRANT_COLLECTION` nếu chưa có (vectors size=1536, distance=Cosine). Gọi idempotent lúc khởi động (lifespan) hoặc lần đầu dùng.
- `upsert_jd(job_id, vector, payload)`: upsert điểm với id ổn định theo job_id, payload `{job_id, title, type:"jd"}`.
- `search(vector, top_k=5, filter_type="jd")`: search trả các điểm + score.

### 3.4 JD service + endpoint — `app/services/job_service.py` + `app/api/routes/jobs.py`

- `create_job(...)`: lưu JD vào DB (`SUBMITTED`/`OPEN` tùy trạng thái mặc định) → `build_jd_text` → `embed_text` →
  `upsert_jd`. Nếu embedding lỗi: vẫn giữ JD trong DB, set cờ/trạng thái `embedding_pending` (hoặc log rõ), KHÔNG sập request; trả cảnh báo.
- `POST /api/jobs` (JobPostingCreate → tạo + embed), `GET /api/jobs` (list), `GET /api/jobs/{id}`.

### 3.5 Endpoint VERIFY tra cứu — `app/api/routes/jobs.py`

- `POST /api/jobs/search-test` (body `{query: str, top_k?: int}`): `embed_text(query)` → `qdrant.search` → trả
  danh sách `{job_id, title, score}`. Dùng để chứng minh embedding + tra cứu tương đồng hoạt động.

### 3.6 Dọn comment cũ — `apps/backend/app/main.py`

- Docstring/dòng nhắc "CORS cho dashboard/mobile" → "CORS cho web dashboard (PWA)".
- Dòng "Expo web :19006" → bỏ (không còn Expo). Giữ origin dashboard (:3000). CHỈ sửa comment/oригин thừa, không đổi logic.

### 3.7 Test — `apps/backend/tests/test_jd_embedding.py`

- **Mock embedding** (không gọi API thật): tạo JD → assert lưu DB đúng + `upsert_jd` được gọi với vector đúng chiều.
- `build_jd_text` ghép đúng định dạng.
- gate_config mặc định TẮT khi không truyền.
- (Tùy chọn, gate bằng biến môi trường) một test tích hợp thật: tạo JD thật → search-test bằng query liên quan → JD đó nằm trong kết quả với score hợp lý.

---

## 4. Verify (chạy thật)

1. `make dev-backend`; tại `/docs` `POST /api/jobs` tạo một JD (vd "Backend Intern (Node.js)") với requirements + rubric + screener_questions + gate_config.
2. `GET /api/jobs/{id}` trả đúng JD đã lưu (kèm rubric/gate_config).
3. Kiểm Qdrant: `POST /api/jobs/search-test` với query "Node.js Express REST API backend" → JD vừa tạo xuất hiện, score tương đồng cao. Query lệch hẳn ("kế toán thuế") → score thấp/không khớp.
4. Tạo JD thứ hai khác lĩnh vực → search-test phân biệt được hai JD theo query.
5. Kiểm embedding lỗi không sập: (nếu tiện) tạm để key sai → JD vẫn vào DB, có cảnh báo, request không 500.
6. `make test` xanh. `main.py` không còn nhắc mobile/Expo.

---

## 5. Definition of Done

- [ ] `POST /api/jobs` tạo JD đầy đủ (title/description/requirements/rubric/screener_questions/gate_config) → lưu DB.
- [ ] Collection Qdrant tồn tại (size 1536, Cosine); JD được upsert kèm payload `{job_id, title, type:"jd"}`.
- [ ] `POST /api/jobs/search-test` trả JD khớp theo tương đồng ngữ nghĩa; query lệch → điểm thấp.
- [ ] gate_config mặc định `auto_reject=false, auto_invite=false`.
- [ ] Embedding lỗi không làm sập tạo JD (JD vẫn lưu + cảnh báo).
- [ ] `main.py` hết comment "dashboard/mobile"/"Expo :19006"; CORS vẫn cho :3000.
- [ ] `make test` xanh (embedding mock).
- [ ] Node `ranker`/screener/scheduler/human_review KHÔNG bị đụng (vẫn stub). KHÔNG embed CV.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào phần JD + embedding + Qdrant + 2 comment main.py. KHÔNG chấm điểm, KHÔNG đụng ranker/các node khác.
- Async-first; cấu hình từ env (EMBEDDING*MODEL, QDRANT*\*); không hardcode.
- Đơn giản trước: một vector/JD (không chunk), một collection dùng chung (payload `type` để phân biệt), không thêm dep ngoài đã có.
- `ensure_collection` phải idempotent (chạy nhiều lần không lỗi).
- Commit nhỏ theo bước (vd `feat(jd): schema + job endpoints`, `feat(embedding): embedding_service + qdrant upsert/search`, `feat(jd): search-test verify endpoint`, `chore(backend): dọn comment mobile/Expo trong main.py`, `test(jd): mocked embedding tests`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§7.2, §9, §16). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify, checklist DoD đã đạt.

---

## 7. Lát kế tiếp (2b — KHÔNG làm bây giờ, chỉ để định hướng)

Ranker chấm điểm THẬT: node `ranker` nhận parsed CV + JD → embed CV, tính tương đồng (tín hiệu phụ) + LLM chấm
theo rubric (điểm chính, có breakdown từng tiêu chí) → `score` + `score_breakdown` + `confidence` +
cờ `weak_match`. Là node quyết định; wiring conditional sau ranker (should_review) chạy theo score/confidence
thật. Có endpoint `rank-test` đồng bộ (parsed CV + job_id → điểm) để tinh chỉnh. Mở rộng State với
`score`/`score_breakdown` nếu cần (PRD §16).
