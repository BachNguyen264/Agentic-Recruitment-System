# SLICE 03c — Gate rank (auto-từ-chối, cấu hình theo JD) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** thêm cổng auto-từ-chối SAU ranker — khi HR bật gate cho một JD, ca điểm thấp RÕ RÀNG (tự tin,
> không cờ bất định) tự động bị từ chối + gửi thư từ chối THẬT (qua scheduler); khi tắt, mọi từ chối vẫn qua
> human_review. Ca BẤT ĐỊNH luôn về human_review bất kể gate. Hoàn thiện Giai đoạn 1 (vòng lặp HITL cốt lõi).
> Tham chiếu: PRD §9 (hai gate + FR-GATE), §8.3 (định tuyến sau ranker), §13 (trạng thái). Tuân thủ `CLAUDE.md`.
>
> **Quyết định phạm vi:** CHỈ auto-từ-chối (sau ranker). KHÔNG làm auto-mời (sau screener — lát 08d). Cấu hình
> **theo từng JD** (`gate_config` đã có trên JD từ 02a — không đổi schema). **UI toggle HOÃN** (đi kèm UI quản lý
> JD, lát 05); lát này bật/tắt qua API. Backend-only.

---

## 1. In scope / Out of scope

**In scope:**

- Định tuyến sau ranker có ý thức về gate: uncertain → human_review (LUÔN); confident + điểm thấp → (gate ON) auto-reject / (OFF) human_review; confident + đạt → tiếp tục (giữ nguyên).
- Nhánh/logic auto-reject: delegate `scheduler.notify_decision(reject)` (gửi thư từ chối THẬT) → REJECTED → audit. Chạy trong pipeline (async), KHÔNG cần HR.
- Endpoint nhỏ bật/tắt `gate_config` trên JD có sẵn (phục vụ test/dùng thật qua API).
- Test (mock scheduler/email) + verify thật (gửi thư từ chối tự động tới email của bạn).

**Out of scope (KHÔNG làm):**

- KHÔNG auto-mời (gate sau screener — lát 08d). KHÔNG đụng nhánh "đạt → tiếp tục".
- KHÔNG UI toggle (hoãn tới UI quản lý JD, lát 05). KHÔNG đổi schema (gate_config đã có).
- KHÔNG đụng logic chấm điểm của ranker; KHÔNG build screener; KHÔNG checkpointer.
- KHÔNG auto-reject ca bất định (an toàn — xem quy tắc §3.1).

---

## 2. Prerequisites

- Lát 04 xong (scheduler gửi email thật) — auto-reject sẽ tái dùng scheduler để gửi thư từ chối thật.
- `SCORE_PASS_THRESHOLD`, `CONFIDENCE_THRESHOLD` đã có. `gate_config` (`auto_reject`, `auto_invite`) đã có trên JD.
- Có JD (id=2) để test. Có email của bạn để nhận thư từ chối tự động khi verify.

---

## 3. Việc cần làm

### 3.1 Định tuyến có gate sau ranker — `app/agents/policy.py` (+ graph)

Thay quyết định 2 nhánh hiện tại bằng quyết định 3 nhánh, **theo đúng thứ tự ưu tiên (an toàn trước)**:

1. **Uncertain trước hết** — nếu `confidence < CONFIDENCE_THRESHOLD` HOẶC `uncertainty_flags` khác rỗng HOẶC
   `require_human_review` → **`human_review`**. (Gate KHÔNG được xét ở đây — ca không chắc LUÔN về người, dù gate bật.)
2. **Nếu confident (không rơi vào (1))**:
   - `score >= SCORE_PASS_THRESHOLD` → **`continue`** (đạt ngưỡng — giữ nguyên luồng hiện tại, KHÔNG đụng).
   - `score < SCORE_PASS_THRESHOLD` (từ chối rõ ràng, confident):
     - JD.`gate_config.auto_reject == True` → **`auto_reject`**.
     - ngược lại → **`human_review`**.

- Hàm đọc `gate_config` của JD theo `job_id`. Log/ghi rõ nhánh đã chọn + lý do (score, gate) để audit.
- **Mặc định gate TẮT** → hành vi mặc định KHÔNG đổi so với hiện tại (mọi điểm thấp vẫn về human_review).

> Lưu ý precedence (quan trọng): ca điểm thấp NHƯNG có cờ (`score_signal_mismatch`…) là _uncertain_ → về
> human_review dù gate bật. CHỈ ca điểm thấp SẠCH (confident, không cờ) mới được auto-reject.

### 3.2 Nhánh auto-reject — node/logic

- Khi route = `auto_reject`: delegate `scheduler.notify_decision(mode="reject")` (điểm phát email DUY NHẤT →
  gửi thư từ chối THẬT) → set status `REJECTED` → ghi audit_log (node="gate", action="auto_reject" +
  scheduler "email_sent:reject"). Chạy đồng bộ trong pipeline (async task), KHÔNG có HR, KHÔNG suspend.
- Lỗi gửi email nuốt có kiểm soát (như lát 04): trạng thái REJECTED vẫn giữ, audit email_failed.

### 3.3 Endpoint bật/tắt gate — `app/api/routes/jobs.py`

- `PATCH /api/jobs/{id}/gate` (hoặc PUT) body `{auto_reject: bool}` (và có thể `auto_invite` để dành) → cập nhật
  `gate_config` của JD. Trả JD đã cập nhật. (Phục vụ bật/tắt nhanh; UI đầy đủ ở lát 05.)

### 3.4 Test — `app/tests/test_gate_rank.py` (mock scheduler/email)

- Gate ON + điểm thấp SẠCH (confident, không cờ) → route `auto_reject`; scheduler.notify_decision(reject) được gọi; status REJECTED.
- Gate OFF + điểm thấp → route `human_review` (như cũ), KHÔNG gọi scheduler.
- Uncertain (có cờ) + gate ON → route `human_review` (gate no-op — an toàn), KHÔNG auto-reject.
- Confident + đạt ngưỡng → route `continue` (không đổi).
- PATCH gate cập nhật gate_config đúng.

---

## 4. Verify (chạy thật — auto-reject gửi thư từ chối THẬT tới email của bạn)

1. `make dev-backend`. Bật gate cho JD #2: `PATCH /api/jobs/2/gate {auto_reject: true}`.
2. Tạo application với `applicant_email` = **email của bạn**, upload CV lệch ngành RÕ (vd kế toán) cho JD #2
   → pipeline chạy: ranker điểm thấp, confident, không cờ → **auto-reject tự động** → status REJECTED, KHÔNG cần vào /review.
3. Kiểm **hòm thư**: nhận thư từ chối THẬT — do hệ thống tự gửi, không có thao tác HR. Audit có dòng gate/auto_reject + email_sent:reject.
4. Tắt gate: `PATCH /api/jobs/2/gate {auto_reject: false}`. Lặp lại với CV lệch ngành → lần này vào `/review` (PENDING_REVIEW), KHÔNG tự từ chối.
5. Ca có cờ (vd CV cho điểm 39 + `score_signal_mismatch`) với gate BẬT → vẫn vào `/review` (an toàn), KHÔNG auto-reject.
6. Ca đạt ngưỡng (CV backend khớp) → tiếp tục như cũ (không bị gate đụng).
7. `make test` xanh (mock).

---

## 5. Definition of Done

- [ ] Định tuyến sau ranker 3 nhánh đúng thứ tự: uncertain→human_review (luôn); confident+thấp→(ON)auto_reject/(OFF)human_review; confident+đạt→continue.
- [ ] Auto-reject delegate scheduler → thư từ chối THẬT gửi đi (verify bằng email của bạn) → REJECTED + audit.
- [ ] Ca bất định (có cờ/low-confidence) KHÔNG bị auto-reject dù gate bật (an toàn — verify).
- [ ] Mặc định gate TẮT → hành vi không đổi so với trước 03c.
- [ ] `PATCH /api/jobs/{id}/gate` bật/tắt được auto_reject (cấu hình theo JD).
- [ ] scheduler là điểm phát email DUY NHẤT; lỗi gửi nuốt có kiểm soát (REJECTED vẫn giữ).
- [ ] KHÔNG auto-mời, KHÔNG UI toggle, KHÔNG đổi schema, KHÔNG đụng ranker-scoring/screener.
- [ ] `make test` xanh (mock scheduler/email); suite cũ không vỡ.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: policy định tuyến + nhánh auto-reject + endpoint gate + test. KHÔNG đụng ranker-scoring, screener, luồng review 03b.
- An toàn là ưu tiên số 1: uncertain LUÔN về human_review; gate chỉ áp lên ca confident điểm thấp SẠCH.
- Tái dùng scheduler (điểm phát email duy nhất); KHÔNG gửi email chỗ khác.
- Cấu hình theo JD (gate_config sẵn có); mặc định TẮT; không hardcode ngưỡng (từ env).
- Commit nhỏ (vd `feat(gate): định tuyến có gate sau ranker (3 nhánh)`, `feat(gate): nhánh auto-reject delegate scheduler`, `feat(api): PATCH bật/tắt gate theo JD`, `test(gate): mock scheduler + các nhánh`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§9, §8.3). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhắc dùng email của người dùng + bật gate), checklist DoD.

---

## 7. Sau lát này

Giai đoạn 1 (vòng lặp HITL cốt lõi) HOÀN TẤT: CV vào → chấm → (tự tin: đạt→tiếp / thấp→auto-reject nếu gate bật) →
(bất định→HR duyệt) → email thật ra. Kế tiếp: **GĐ2** — UI quản lý JD (gồm UI toggle gate), nộp CV công khai, object storage. Xem ROADMAP.md.
