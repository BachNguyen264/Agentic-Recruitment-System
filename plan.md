# SLICE JD-2b — Screener tùy chọn: JD không câu hỏi → BỎ QUA bước screener · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** CV đạt + JD **KHÔNG có câu hỏi sàng lọc** → pipeline **BỎ QUA bước screener** (không suspend), đi
> thẳng tới quyết định post-screener (gate auto-mời / human_review). CV đạt + JD **CÓ câu hỏi** → GIỮ NGUYÊN đường
> screener bất đồng bộ (08a-d). Tham chiếu: PRD §7.3 (FR-SCR-0), §8.3, §10. Tuân thủ `CLAUDE.md`.
>
> **⚠️ LÁT ĐỤNG GRAPH/POLICY** — đúng vùng đã dày công làm bền (08a-d). Scope HẸP: CHỈ _thêm_ nhánh bỏ-qua khi
> rỗng; đường có-câu-hỏi phải BẤT BIẾN. **Adversarial review bắt buộc.** Vướng → DỪNG, hỏi.

---

## 1. In scope / Out of scope

**In scope:**

- **Screener node interrupt CÓ ĐIỀU KIỆN:** interrupt (suspend + gửi email câu hỏi) **CHỈ khi JD có câu hỏi sàng lọc**. JD rỗng câu hỏi → node **pass-through** (KHÔNG suspend, KHÔNG gửi email), đi tiếp.
- **route_after_screener xử ca pass-through:** CV bỏ-qua-screener (đạt, không cờ, KHÔNG `no_response`) = "sạch" → áp gate auto-mời (BẬT → thư mời; TẮT → human_review), **giống hệt** ca đã trả lời sạch.
- Đọc "JD có câu hỏi?" từ config JD tại thời điểm pipeline chạy (config-as-of-entry, như gate — checkpointed JD).
- Test CẢ HAI đường + đối chứng an toàn.

**Out of scope (KHÔNG làm):**

- KHÔNG đổi đường screener CÓ câu hỏi (08a suspend/resume · 08b magic-link · 08c timeout/nhắc · 08d gate mời) — BẤT BIẾN.
- KHÔNG đụng route_after_ranker (uncertain/low giữ nguyên — chúng không tới bước screener). KHÔNG đụng ranker-scoring/parser.
- KHÔNG AI gợi ý rubric (JD-3). KHÔNG soft-delete (JD-4).

---

## 2. Prerequisites

- JD-2a xong (screener câu hỏi tùy chọn ở UI — JD có thể lưu không câu hỏi). 08a-d (screener async đầy đủ). Checkpointer (08a).
- Nắm: chỉ CV **confident + đạt** mới tới bước screener (uncertain/low đã rẽ ở route_after_ranker) — nên nhánh bỏ-qua CHỈ áp ca đạt.

## 3. Việc cần làm

### 3.1 Screener node: interrupt có điều kiện · `app/agents/nodes/screener.py`

- Đọc `screener_questions` của JD (qua job_id của application). **Có câu hỏi** → giữ nguyên hành vi: `interrupt()` suspend + (đường 08b) tạo session/token + email câu hỏi. **Không câu hỏi (rỗng/null)** → **KHÔNG interrupt**: pass-through, set state sao cho route_after_screener coi là "sạch" (KHÔNG gắn `no_response`, KHÔNG cờ), tiếp tục.
- Đây là guard cục bộ quanh interrupt — KHÔNG viết lại logic suspend/resume/timeout.

### 3.2 route_after_screener xử ca bỏ-qua · `app/agents/policy.py`

- Đảm bảo định nghĩa "sạch" của route_after_screener = **confident + đạt + không cờ + không `no_response`** (KHÔNG đòi _phải có answers_). Ca bỏ-qua (no questions → no answers, no no_response) rơi đúng nhánh sạch:
  - auto_invite BẬT → scheduler thư mời → INTERVIEW_SCHEDULED.
  - auto_invite TẮT → human_review.
- Nếu code hiện đòi "có answers mới sạch" → nới để ca no-questions vẫn sạch (vì không có gì để trả lời). Giữ nguyên: `no_response`/cờ/low-conf → human_review ("cờ thắng gate").

### 3.3 (Vá kèm) case suspend-form-rỗng

- Xác nhận: sau JD-2b, KHÔNG còn đường nào suspend + gửi email khi JD rỗng câu hỏi (guard 3.1 chặn). Đây vốn là bug tiềm ẩn — JD-2b vá luôn.

### 3.4 Test · `app/tests/`

- **Đường CÓ câu hỏi (không hồi quy):** CV đạt + JD có câu hỏi → suspend AWAITING_SCREENER + email câu hỏi (08a-d nguyên).
- **Đường KHÔNG câu hỏi (mới):** CV đạt + JD không câu hỏi → KHÔNG suspend, KHÔNG email screener → route_after_screener: gate ON→auto-mời / OFF→human_review.
- An toàn: uncertain/low → human_review/auto-reject như cũ (không tới screener). `no_response` (đường có câu hỏi timeout) vẫn → human_review.
- Không có case suspend khi JD rỗng câu hỏi.

## 4. Verify (chạy thật — CẢ HAI đường)

1. `make dev-backend` (restart để nạp code mới — nhớ bài học "process cũ") + dashboard.
2. **Đường CÓ câu hỏi:** JD có câu hỏi sàng lọc + gate mời TẮT → nộp CV đạt (email của bạn) → suspend AWAITING_SCREENER + **email câu hỏi** (đường 08b nguyên vẹn). _(không hồi quy)_
3. **Đường KHÔNG câu hỏi:** JD KHÔNG câu hỏi (JD-2a cho lưu vậy) + gate mời TẮT → nộp CV đạt → **KHÔNG suspend, KHÔNG email screener** → vào PENDING_REVIEW (human_review) thẳng. Log: không có bước screener/không interrupt.
4. **Không câu hỏi + auto_invite BẬT:** JD không câu hỏi + gate mời BẬT → CV đạt sạch → **auto-mời thẳng** (thư mời thật) → INTERVIEW_SCHEDULED.
5. An toàn: CV lệch ngành (bất định) → human_review DÙ gate bật; CV thấp + auto_reject → auto-từ-chối (không đụng).
6. `make test` xanh.

## 5. Definition of Done

- [ ] Screener node interrupt **chỉ khi JD có câu hỏi**; JD rỗng câu hỏi → pass-through (KHÔNG suspend/email).
- [ ] Ca bỏ-qua = "sạch" → route_after_screener áp gate mời đúng (ON→thư mời / OFF→human_review), KHÔNG gắn no_response.
- [ ] Đường CÓ câu hỏi (08a suspend/resume · 08b magic-link · 08c timeout · 08d gate) **BẤT BIẾN** — verify không hồi quy.
- [ ] "Cờ thắng gate" giữ nguyên (uncertain/cờ/no_response → human_review). Không còn case suspend-form-rỗng.
- [ ] KHÔNG đụng route_after_ranker/ranker/parser/scoring. `make test` xanh.
- [ ] **Adversarial review** xác nhận: đường cũ nguyên + đường mới đúng + an toàn giữ.

## 6. Gotchas & quy ước (theo CLAUDE.md)

- **Thay đổi CỤC BỘ:** guard interrupt quanh "JD có câu hỏi?" + đảm bảo route_after_screener coi no-questions là sạch. KHÔNG viết lại suspend/resume/timeout/gate.
- **Ca bỏ-qua KHÔNG phải no_response:** no_response = "có câu hỏi nhưng ứng viên im lặng" (→ human_review). Bỏ-qua = "không có gì để hỏi" (→ sạch). Đừng lẫn hai cái — nếu lẫn, ca no-question sẽ bị đẩy vào review thay vì auto-mời (sai gate ON), hoặc bị coi là ghosting.
- Config-as-of-entry: đọc screener_questions từ JD tại lúc pipeline chạy (nhất quán với gate). Chạy impact analysis trước khi sửa screener/policy (GitNexus). **Adversarial review bắt buộc** (đụng graph).
- Commit nhỏ (vd `feat(screener): interrupt có điều kiện (bỏ qua khi JD rỗng câu hỏi)`, `feat(policy): route_after_screener coi no-questions là sạch`, `test(screener): 2 đường có/không câu hỏi`).
- Nghiệp vụ chưa rõ → **PRD.md** (§7.3 FR-SCR-0, §8.3, §10). Vướng graph → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify (nhấn: CẢ HAI đường + không hồi quy) + checklist DoD + kết quả adversarial review.

## 7. Sau lát này

Screener bây giờ chạy có-điều-kiện (đúng FR-SCR-0). Còn **JD-3** (AI gợi ý rubric — điểm nhấn) và **JD-4** (soft-delete
ARCHIVED + dọn vector Qdrant mồ côi). Xong cụm tối-ưu-tạo-JD → UI redesign → báo cáo. Xem ROADMAP.md.
