# SLICE 02b — Ranker chấm điểm thật (rubric có suy luận + tín hiệu embedding) · plan one-shot

> **Bản chất:** plan ONE-SHOT cho một lát logic. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** node `ranker` từ stub → THẬT. LLM đọc CV + JD, **suy luận theo từng tiêu chí rubric** rồi cho
> điểm có breakdown + lý do. Embedding/Qdrant đóng vai **tín hiệu phụ** (tương đồng ngữ nghĩa để hiển thị +
> kiểm tra chéo), KHÔNG vào điểm. Là node quyết định; wiring `should_review` theo điểm/confidence thật.
> Tham chiếu: PRD §7.2 (Ranker), §11 (ReviewCard), §13 (trạng thái), §16 (score/score_breakdown). Tuân thủ `CLAUDE.md`.
>
> **Hướng đã chốt (Hướng A):** rubric có suy luận = cơ sở điểm DUY NHẤT. Rubric do HR nhập (đã có ở JD từ 2a).
> KHÔNG chunk JD, KHÔNG truy xuất theo mảnh. LLM provider: OpenAI.
> **Model:** CHỌN SAU KHI BENCHMARK (mục 6) — so sánh một model reasoning (gpt-5-mini) và một non-reasoning
> (gpt-4.1) trên cùng CV rồi mới quyết. Code phải hỗ trợ đổi qua lại bằng env.

---

## 1. In scope / Out of scope

**In scope:**

- Schema `RankResult` (điểm tổng + điểm/lý do từng tiêu chí).
- Node `ranker` THẬT: parsed CV + JD(rubric) → (a) embed CV, lấy cosine với JD qua Qdrant (tín hiệu phụ);
  (b) LLM chấm rubric có suy luận → điểm + breakdown; (c) confidence + uncertainty_flags; (d) lưu
  `score`/`score_breakdown`/`semantic_similarity`; (e) audit_log.
- **Client LLM cấu hình được reasoning/non-reasoning** (xử lý đúng `temperature` vs `reasoning_effort`).
- Mở rộng `RecruitmentState`: `score`, `score_breakdown`, `semantic_similarity`.
- `policy.should_review` theo điểm/confidence/flags THẬT.
- Endpoint `rank-test` đồng bộ (dùng cho cả tinh chỉnh lẫn benchmark model).
- **Benchmark reasoning vs non-reasoning** trên bộ CV cố định → chọn RANKER_MODEL (mục 6).
- Dọn tồn dư 2a: `search-test` lỗi Qdrant → trả message rõ.
- Test (mock LLM + mock embedding).

**Out of scope:**

- KHÔNG gate (auto-từ-chối/auto-mời) — chỉ chấm + route bất định sang human_review. Gate là lát sau.
- KHÔNG đụng logic thật `screener`/`scheduler`/`human_review` (vẫn stub).
- KHÔNG chunk JD, KHÔNG để cosine vào điểm, KHÔNG UI hiển thị điểm, KHÔNG sinh rubric bằng LLM.

---

## 2. Prerequisites

- `.env` (cấu hình model — sẽ chốt sau benchmark):
  - `RANKER_MODEL` — model chấm điểm. Hai ứng viên benchmark: `gpt-5-mini` (reasoning) và `gpt-4.1` (non-reasoning).
  - `RANKER_REASONING_EFFORT` — **để trống nếu model non-reasoning** (code dùng `temperature=0`); **đặt `low`/`medium`
    nếu model reasoning** (code dùng `reasoning_effort`, KHÔNG truyền temperature). Đây là công tắc để đổi qua lại.
  - `SCORE_PASS_THRESHOLD` (vd 60), `SCORE_NEAR_BAND` (vd 10). `CONFIDENCE_THRESHOLD` đã có.
- `EMBEDDING_MODEL`, Qdrant, langchain-openai đã có từ 2a.

---

## 3. Việc cần làm

### 3.1 Schema `RankResult` — `app/schemas/rank.py`

- `overall_score: float` (0..100), `criteria: list[CriterionScore]` với
  `CriterionScore = {criterion, weight, score(0..100), reasoning}`, `summary: str`.
- Code tính lại overall từ criteria×weight để đối chiếu (không tin mù; lệch lớn → log/flag).

### 3.2 Mở rộng State — `app/agents/state.py`

Thêm `score: float | None`, `score_breakdown: list[dict] | None`, `semantic_similarity: float | None`.

### 3.3 Client LLM cấu hình được — `app/agents/nodes/ranker.py` (hoặc helper riêng)

- `build_ranker_llm()`:
  - Nếu `settings.RANKER_REASONING_EFFORT` rỗng → `ChatOpenAI(model=RANKER_MODEL, temperature=0)` (non-reasoning).
  - Nếu có giá trị → `ChatOpenAI(model=RANKER_MODEL, reasoning_effort=settings.RANKER_REASONING_EFFORT)` — **KHÔNG
    truyền temperature** (reasoning model bỏ qua/không nhận temperature).
  - `.with_structured_output(RankResult)` cho cả hai.
- Mục đích: đổi giữa reasoning/non-reasoning chỉ bằng .env, không sửa code — phục vụ benchmark mục 6.

### 3.4 Node `ranker` THẬT

1. Lấy `parsed_data` + JD (rubric/requirements/description) theo `job_id`.
2. **Tín hiệu embedding (phụ):** embed text CV (skills + experiences summary) → Qdrant search lọc
   `{job_id, type:"jd"}` → `semantic_similarity` (cosine). Lỗi Qdrant → `None` + không sập.
3. **Chấm rubric có suy luận (điểm chính):** `build_ranker_llm()`; prompt đưa CV + JD + rubric; chấm TỪNG tiêu
   chí kèm lý do dựa trên bằng chứng CV, KHÔNG bịa, chỉ theo đúng tiêu chí rubric (không tự thêm).
4. **confidence + uncertainty_flags (heuristic xác định, KHÔNG hỏi LLM tự chấm):**
   - `near_threshold`: |overall_score − SCORE_PASS_THRESHOLD| < SCORE_NEAR_BAND.
   - `weak_match`: similarity != None và < ngưỡng thấp (vd 0.2).
   - `score_signal_mismatch`: rubric cao nhưng similarity rất thấp (hoặc ngược lại).
   - confidence bắt đầu 1.0, giảm theo cờ; có cờ hoặc < CONFIDENCE_THRESHOLD → vào review.
5. Lưu score/breakdown/similarity/confidence/flags vào state; ghi audit_log (node="ranker", score, confidence, flags).
6. LLM try/except: lỗi → cờ + escalation_reason, KHÔNG sập. `ENABLE_LLM=false` → giữ stub.

### 3.5 `policy.should_review`

- Route `"review"` nếu `confidence < CONFIDENCE_THRESHOLD` HOẶC `uncertainty_flags` khác rỗng HOẶC `require_human_review`.
- Graph: `parser → ranker → [should_review] → (screener[stub] | human_review[stub])`. Không đụng screener/scheduler.

### 3.6 Endpoint `rank-test` — `app/api/routes/agents.py`

- `POST /api/agents/rank-cv` (body `{application_id}` HOẶC `{parsed_data, job_id}`) → trả
  `{score, score_breakdown, semantic_similarity, confidence, uncertainty_flags, model_used}`.
  (Thêm `model_used` = RANKER_MODEL + reasoning_effort để phân biệt khi benchmark.)

### 3.7 Dọn tồn dư 2a

- `search-test`: lỗi Qdrant → mã lỗi có message rõ (đồng bộ embedding 502), không 500 chung chung.

### 3.8 Test — `app/tests/test_ranker.py`

- Mock LLM + mock embedding: CV khớp → điểm cao/flags rỗng/đi tiếp; sát ngưỡng → `near_threshold` → review;
  rubric cao + sim thấp → `score_signal_mismatch` → review; lỗi LLM → cờ/không sập; lỗi Qdrant → sim=None + vẫn chấm.
- Kiểm overall tính lại từ criteria×weight.
- Kiểm `build_ranker_llm`: reasoning_effort rỗng → có temperature; có giá trị → có reasoning_effort, không temperature.

---

## 4. Verify chức năng (chạy thật, model bất kỳ trong hai ứng viên)

1. `make dev-backend`. Có JD từ 2a (id=2). Chuẩn bị `parsed_data` (chạy `parse-cv` một CV backend, copy JSON).
2. `POST /api/agents/rank-cv` (parsed_data + job_id=2) → điểm hợp lý, breakdown từng tiêu chí có lý do, similarity cao, confidence cao, flags rỗng.
3. CV lệch ngành (kế toán) + job_id=2 → điểm thấp, sim thấp, cờ `weak_match`/`score_signal_mismatch` → review.
4. CV tàm tạm → điểm quanh ngưỡng → cờ `near_threshold` → review.
5. Pipeline đầy đủ (application kèm CV cho job_id=2) → parser thật → ranker thật → should_review route đúng; audit_log có dòng ranker.
6. `make test` xanh. `search-test` lỗi Qdrant trả message rõ.

---

## 5. (đã gộp vào 6)

## 6. BENCHMARK & CHỌN MODEL (reasoning vs non-reasoning) — mục bạn yêu cầu

> Mục tiêu: quyết `RANKER_MODEL` dựa trên OUTPUT THẬT, không đoán. Chất lượng chấm là thứ hội đồng soi nhất.

**Bộ CV cố định (3 cái, dùng chung cho cả hai model):**

- CV-A: khớp tốt (CV backend cho JD backend id=2).
- CV-B: lệch ngành (CV kế toán cho JD backend id=2).
- CV-C: tàm tạm / quanh ngưỡng (CV có một phần kỹ năng khớp).

**Hai cấu hình model (đổi bằng .env, không sửa code):**

- M1 non-reasoning: `RANKER_MODEL=gpt-4.1`, `RANKER_REASONING_EFFORT=` (trống).
- M2 reasoning: `RANKER_MODEL=gpt-5-mini`, `RANKER_REASONING_EFFORT=low`.

**Quy trình (Claude Code chạy, in kết quả cho người dùng đọc):**

1. Với MỖI model, chạy `rank-cv` trên CV-A, CV-B, CV-C.
2. Chạy CV-A **hai lần** với mỗi model → kiểm tính nhất quán (điểm/breakdown có ổn định không).
3. Ghi lại cho mỗi lần: `overall_score`, điểm+lý do từng tiêu chí, similarity, flags, và cảm nhận độ trễ.
4. In **bảng so sánh song song**: hàng = CV-A/B/C (+ lần chạy lặp), cột = M1 vs M2 → mỗi ô: overall_score + tóm tắt breakdown.

**Tiêu chí người dùng đánh giá để chọn:**

- Điểm có hợp lý theo trực giác không (A cao, B thấp, C ở giữa)?
- Lý do từng tiêu chí có sâu, đúng bằng chứng trong CV, thuyết phục không?
- Nhất quán giữa 2 lần chạy CV-A (điểm không nhảy lung tung)?
- Độ trễ/chi phí có chấp nhận được không (reasoning thường chậm hơn)?

**Sau khi chọn:** đặt `RANKER_MODEL` (+ `RANKER_REASONING_EFFORT` nếu reasoning) vào `.env` + `.env.example`;
ghi 1–2 dòng lý do chọn (dùng cho báo cáo Chương 4 — "vì sao chọn model này cho chấm điểm").

> Lưu ý: `make test` mock LLM nên KHÔNG phụ thuộc model — benchmark là bước thủ công riêng, không nằm trong test tự động.

---

## 7. Definition of Done

- [ ] `rank-cv` trả điểm + breakdown từng tiêu chí (lý do) + similarity + confidence + flags + `model_used`.
- [ ] Điểm dựa trên rubric có suy luận; cosine KHÔNG vào điểm.
- [ ] `build_ranker_llm` xử lý đúng: non-reasoning → temperature; reasoning → reasoning_effort (không temperature).
- [ ] Cờ đúng (`near_threshold`/`weak_match`/`score_signal_mismatch`); should_review route theo confidence/flags thật.
- [ ] State có score/score_breakdown/semantic_similarity; audit_log ghi dòng ranker.
- [ ] Lỗi LLM/Qdrant không sập pipeline; `ENABLE_LLM=false` giữ stub.
- [ ] **Benchmark M1 (gpt-4.1) vs M2 (gpt-5-mini) chạy xong, có bảng so sánh; RANKER_MODEL được chọn + ghi lý do.**
- [ ] screener/scheduler/human_review KHÔNG bị đụng; KHÔNG gate; KHÔNG chunk JD.
- [ ] `search-test` lỗi Qdrant có message rõ; `make test` xanh (mock).

---

## 8. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào ranker + policy(routing) + rank-test + fix search-test. KHÔNG screener/scheduler/human_review logic, KHÔNG gate.
- Async-first; cấu hình từ env (RANKER*MODEL, RANKER_REASONING_EFFORT, SCORE*\*); không hardcode.
- Đơn giản trước: confidence/flags heuristic xác định; code tính lại overall; không thêm dep.
- Embedding CHỈ tín hiệu phụ (similarity + cờ mismatch), KHÔNG vào điểm, KHÔNG chunk JD.
- Đổi model chỉ qua env (build_ranker_llm) — đừng hardcode tham số riêng cho một model.
- Commit nhỏ (vd `feat(ranker): RankResult + state`, `feat(ranker): build_ranker_llm (reasoning/non-reasoning) + node`, `feat(ranker): should_review + rank-test`, `fix(qdrant): search-test message`, `test(ranker): mocked`).
- Nghiệp vụ chưa rõ → tra **PRD.md**. PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, verify, bảng benchmark, checklist DoD.

---

## 9. Lát kế tiếp (KHÔNG làm bây giờ)

Gate rank (auto-từ-chối dùng score + gate_config, PRD §9), hoặc UI hiển thị điểm cho HR, rồi Screener async (PRD §10).
