# SLICE JD-3 — AI gợi ý rubric (đề xuất tiêu chí + trọng số từ JD) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`** (FR-HR-RUBRIC-1, trụ cột 4 §5).
> **Mục tiêu:** ở màn "Cấu hình sàng lọc" (JD đã lưu), HR bấm **"AI gợi ý rubric"** → LLM đọc JD → đề xuất
> **tiêu chí + trọng số** → HR chỉnh/lưu. Xóa nỗi "tê liệt ô rubric". **AI TĂNG CƯỜNG năng lực người** (bắc cầu
> khoảng trống chuyên môn HR) — khác auto-hóa ở chỗ khác. Tham chiếu: PRD §12.1 (FR-HR-RUBRIC-1), §16, §5.
>
> **Điểm nhấn:** lần dùng LLM thứ 3 (parser=trích xuất · ranker=chấm · rubric-suggester=đề xuất — reasoning).
> **KHÔNG đụng pipeline/graph/ranker-scoring** — chỉ thêm 1 endpoint LLM auth-gated + nút điền-sẵn ở màn cấu hình.

---

## 1. In scope / Out of scope

**In scope:**

- Endpoint HR (`require_hr`) **gợi ý rubric**: đọc JD đã lưu (tiêu đề + mô tả + yêu cầu, **cấp bậc làm ngữ cảnh**) →
  LLM **structured output** → list `{criterion, weight}` (tiêu chí + trọng số) → trả cho frontend.
- **Model:** `gpt-5-mini` reasoning (**effort qua env** — benchmark low vs medium, xem §5). **reasoning_effort, KHÔNG temperature.**
- **Cap 3 retry/JD:** cột `rubric_suggestion_count` (đã ghi §16); **reset khi nội dung JD (tiêu đề/mô tả/yêu cầu) đổi** — tái dùng phép so sánh re-embed của 05. Hết cap → chặn + báo rõ.
- Frontend màn cấu hình sàng lọc: nút "AI gợi ý rubric" → gọi endpoint → **điền sẵn** UI rubric (tiêu chí + trọng số) để HR **chỉnh trước khi lưu** (KHÔNG tự lưu/tự áp). Hiện số lần còn lại.
- Benchmark low vs medium (§5) — chọn effort bằng dữ liệu.

**Out of scope (KHÔNG làm):**

- KHÔNG tự lưu rubric (HR phải xem+chỉnh+lưu). KHÔNG gợi ý mô tả/quyền lợi (chỉ rubric — nếu muốn để lát riêng sau).
- KHÔNG đụng ranker-scoring/parser/graph/pipeline/screener. KHÔNG dùng LLM chuẩn hóa câu trả lời screener (vẫn hoãn).
- KHÔNG áp rubric mới lên CV đã chấm (giữ stance: chỉ ảnh hưởng CV chấm SAU).

---

## 2. Prerequisites

- JD-2a xong (màn cấu hình sàng lọc trên JD đã lưu — nút gợi ý gắn ở đây; JD-id để neo `rubric_suggestion_count`).
- JD-1 xong (mô tả/yêu cầu văn bản định dạng — **đưa PLAIN-TEXT vào LLM**, bóc HTML như JD-1 đã làm).
- Config env: `RUBRIC_SUGGEST_MODEL=gpt-5-mini`, `RUBRIC_SUGGEST_REASONING_EFFORT` (low/medium — benchmark), `RUBRIC_SUGGEST_MAX_RETRIES=3`. langchain-openai (đã có).

## 3. Việc cần làm

### 3.1 Service gợi ý rubric · `app/services/` (LLM, structured output)

- Hàm nhận JD (tiêu đề + mô tả plain-text + yêu cầu plain-text + cấp bậc) → gọi `gpt-5-mini` (reasoning_effort từ env, **KHÔNG temperature**) với **structured output** ràng buộc schema: `[{criterion: str, weight: float}]`.
- Prompt: yêu cầu suy ra các trục năng lực cốt lõi từ JD, **cân trọng số theo mức quan trọng** (ngữ cảnh cấp bậc: senior → kinh nghiệm/leadership nặng hơn); trọng số dương, tổng ~1 (gợi ý mềm — code có thể chuẩn hóa lại). Literal `{}` trong prompt → `{{}}` (gotcha str.format).
- Trả về list tiêu chí+trọng số + (tùy) tóm tắt ngắn lý do mỗi tiêu chí (hiển thị cho HR tham khảo).

### 3.2 Cap retry + reset · model/migration + endpoint

- Cột `rubric_suggestion_count` (int, default 0) trên JobPosting — migration hand-written add_column (**include_object guard**, như JD-1).
- **Reset về 0 khi nội dung JD (tiêu đề/mô tả/yêu cầu) đổi** — móc vào đúng chỗ đã kiểm-đổi-để-re-embed của 05 (một phép so sánh, quyết cả re-embed lẫn reset count).
- Endpoint `POST /api/jobs/{id}/suggest-rubric` (`require_hr`): nếu `count >= MAX_RETRIES` → **429/409 báo hết lượt** (rõ); else gọi service, `count += 1`, trả đề xuất. Auth-gated → "farm LLM call" không phải mối lo (chỉ HR đăng nhập gọi).

### 3.3 Frontend màn cấu hình sàng lọc

- Nút **"AI gợi ý rubric"** (cạnh UI rubric) → gọi endpoint → **điền sẵn** list tiêu chí+trọng số vào UI rubric hiện có (05) → HR chỉnh (sửa/thêm/xóa/đổi trọng số) → **Lưu** (đường lưu rubric của JD-2a). Hiện "còn N/3 lần".
- Trạng thái: loading khi gọi; hết lượt → nút disable + tooltip; lỗi LLM → báo êm, không mất rubric HR đang có.
- Rõ ràng "đây là AI gợi ý, bạn đang chỉnh" (không gây hiểu là hệ tự quyết).

### 3.4 Test

- Service: mock LLM → trả đúng list `{criterion, weight}`; plain-text (không HTML) đưa vào prompt.
- Endpoint: count tăng mỗi lần; đạt cap → chặn (429/409); nội dung JD đổi → count reset. Auth: chưa login → 401.
- Frontend: điền-sẵn không tự-lưu; hết lượt disable.

## 4. Verify (chạy thật — LLM thật)

1. `make dev-backend` (restart nạp code mới) + dashboard. Tạo JD Leader Node.js (dán mô tả+yêu cầu thật như bạn khảo sát), cấp bậc "lead".
2. Màn cấu hình sàng lọc → bấm **"AI gợi ý rubric"** → nhận đề xuất tiêu chí + trọng số **bắt nguồn từ JD** (vd: kiến trúc/Node.js/leadership/message-queue... trọng số phản ánh vị trí lead). Chỉnh vài trọng số → Lưu.
3. Bấm lại 2 lần nữa (tổng 3) → lần 4 **bị chặn** ("hết lượt gợi ý"). Sửa mô tả JD + lưu → **count reset** → gợi ý lại được.
4. Chưa login gọi `POST /api/jobs/{id}/suggest-rubric` (Postman) → 401.
5. Lưu rubric AI-gợi-ý → mở JD (OPEN) → nộp CV → ranker chấm theo rubric đó (pipeline không đụng — không hồi quy).
6. `make test` xanh; `pnpm build` PASS.

## 5. ⭐ BENCHMARK effort: low vs medium (chọn bằng dữ liệu)

- Với **2-3 JD thật khác nhau** (vd Leader Node.js · một vị trí junior · một vị trí phi-kỹ-thuật), chạy gợi ý ở **cả `low` và `medium`** (đổi `RUBRIC_SUGGEST_REASONING_EFFORT`), so sánh:
  - **Chất lượng tiêu chí:** có bắt đúng trục cốt lõi của JD không? có bỏ sót/bịa không?
  - **Chất lượng TRỌNG SỐ (điểm mấu chốt):** trọng số có _phản ánh mức quan trọng_ theo vị trí không (senior → kinh nghiệm/leadership nặng), hay đều đều/hời hợt? Đây là chỗ effort tạo khác biệt.
  - Độ trễ + (ước) chi phí mỗi lần (chạy hiếm nên thứ yếu).
- **Chọn effort thấp nhất cho chất lượng chấp nhận được** (nếu low đã cho trọng số hợp lý → dùng low; nếu medium khác biệt rõ ở trọng số → medium). Ghi nhận xét ngắn (2-3 JD × 2 effort) — **tư liệu benchmark cho báo cáo** (giống benchmark ranker). Để effort ở env → tinh chỉnh sau.

## 6. Definition of Done

- [ ] Endpoint `suggest-rubric` (require_hr): đọc JD (plain-text + cấp bậc) → `gpt-5-mini` reasoning (effort env, KHÔNG temperature) → structured output tiêu chí+trọng số.
- [ ] Cap 3 retry/JD (`rubric_suggestion_count`), reset khi nội dung JD đổi (tái dùng check re-embed); hết cap chặn rõ.
- [ ] Frontend: nút gợi ý → điền-sẵn UI rubric để HR **chỉnh trước khi lưu** (KHÔNG tự lưu/áp); hiện số lần còn lại.
- [ ] Plain-text vào LLM (bóc HTML); KHÔNG đụng ranker-scoring/parser/graph/pipeline (không hồi quy).
- [ ] **Benchmark low vs medium** trên 2-3 JD → chọn effort + ghi nhận xét. `make test` xanh; `pnpm build` PASS.

## 7. Gotchas & quy ước (theo CLAUDE.md)

- **`gpt-5-mini` = reasoning → dùng `reasoning_effort`, KHÔNG `temperature`** (bài học ranker — set temperature sẽ lỗi).
- **Plain-text vào LLM** (bóc HTML mô tả/yêu cầu — như JD-1); structured output ràng buộc schema (như parser/ranker).
- **AI đề xuất, HR duyệt** — KHÔNG tự lưu/tự áp rubric (trụ cột 4: "HR duyệt mới áp dụng"). Neo count vào JD-id (đã lưu), reset theo nội dung.
- Auth-gated → threat "farm LLM" moot (chỉ HR gọi). Literal `{}` trong prompt → `{{}}` (str.format). Migration include_object guard.
- Chạy impact analysis trước khi sửa job_service/re-embed-check (GitNexus nếu có, không thì grep). Commit nhỏ (vd `feat(jd): service gợi ý rubric (gpt-5-mini structured)`, `feat(jd): endpoint suggest-rubric + cap retry/reset`, `feat(ui): nút AI gợi ý rubric ở màn cấu hình`, `test(jd): suggest-rubric + cap/reset`).
- Nghiệp vụ chưa rõ → **PRD.md** (§12.1 FR-HR-RUBRIC-1, §16, §5). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify + **kết quả benchmark low vs medium** + checklist DoD.

## 8. Sau lát này

Khâu tạo JD _dùng được thật_ cho HR không-chuyên (xóa nỗi tê-liệt-rubric). Còn **JD-4** (soft-delete ARCHIVED + dọn
vector Qdrant mồ côi + đường submit-không-job_id pre-existing) → xong cụm tối-ưu-tạo-JD → **UI redesign** → viết báo cáo. Xem ROADMAP.md.
