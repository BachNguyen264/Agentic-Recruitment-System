# SLICE (FIX) — Sửa 2 lỗi từ end-to-end test: (A) CV đạt không gửi mời · (B) badge review dai dẳng · plan one-shot

> **Bản chất:** plan ONE-SHOT sửa 2 lỗi phát hiện qua end-to-end test. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Chủ đề chung:** trạng thái THẬT của hồ sơ phải được phản ánh đúng — cả cách hệ thống ĐẶT trạng thái (A: backend)
> lẫn cách HIỂN THỊ (B: frontend).
> Tham chiếu: PRD §8.3, §9, §11, §13. Tuân thủ `CLAUDE.md`.

---

## BUG A (backend) — CV đạt bị auto-đặt INTERVIEW_SCHEDULED mà KHÔNG gửi thư mời

**Triệu chứng:** app 17 (91.5đ, đạt) → log `branch=auto status=INTERVIEW_SCHEDULED`, KHÔNG dòng scheduler nào → không thư mời.
Trạng thái "đã hẹn phỏng vấn" nhưng ứng viên không được báo.
**Nguyên nhân:** đường "CV đạt tự động" không có cơ chế gửi mời — cổng auto-mời (08d) CHƯA xây.
**Fix:** CV đạt → `human_review` (HR duyệt → scheduler gửi thư mời THẬT, đúng đường 03b+04). Đối xứng với auto-reject (03c).

### A.1 Định tuyến đường "đạt" → human_review · `app/agents/policy.py` (+ graph/runner)

- `route_after_ranker`: nhánh confident + `score >= SCORE_PASS_THRESHOLD` (không cờ, không low-confidence) →
  **đổi thành route `human_review`** (thay vì đường tự đặt INTERVIEW_SCHEDULED).
- 3 nhánh sau sửa (đối xứng, đúng trạng thái hiện có):
  - uncertain (lỗi/cờ/low-confidence) → human_review.
  - confident + điểm thấp → auto_reject (gate ON) / human_review (gate OFF). _(giữ nguyên 03c)_
  - confident + đạt → **human_review** (auto-mời chưa xây, mặc định TẮT). _(sửa)_
- Nếu đường "đạt" đi qua node screener→scheduler và node đó auto-đặt trạng thái câm → chỉnh route thẳng human_review
  (screener thật + cổng mời chèn lại ở GĐ3/08d — chừa slot). Runner label: bỏ nhãn "auto" gây hiểu nhầm cho nhánh này.

### A.2 INTERVIEW_SCHEDULED chỉ khi đã gửi mời

- Rà: KHÔNG đường nào đặt `INTERVIEW_SCHEDULED` mà không qua `scheduler.notify_decision("invite")`. Đường hợp lệ
  duy nhất hiện tại: human_review approve → scheduler gửi mời → set INTERVIEW_SCHEDULED (đã có 03b/04). Giữ đúng vậy.
- Nếu node scheduler tự động đang đặt INTERVIEW_SCHEDULED như hành vi stub → bỏ.

### A.3 Test

- confident + đạt → `route_after_ranker` = `human_review`; KHÔNG auto-set INTERVIEW_SCHEDULED.
- Giữ: uncertain→review; confident+thấp→auto_reject(ON)/review(OFF); auto-reject vẫn gửi thư từ chối thật (mock).

---

## BUG B (frontend) — Badge "Cần HR xem xét" hiển thị cả khi hồ sơ đã xử lý xong

**Triệu chứng:** hồ sơ đã REJECTED (auto-từ-chối) hoặc đã quyết vẫn hiện badge "Cần HR xem xét — Điểm 4.5/100 dưới
ngưỡng..." / "Điểm rubric (20.0) lệch tín hiệu tương đồng (0.5353)" ở danh sách ứng viên.
**Nguyên nhân:** badge render chỉ vì `escalation_reason`/`uncertainty_flags` CÓ dữ liệu, KHÔNG xét trạng thái.
**Đúng ra:** badge "cần xem xét" là chỉ báo HÀNH ĐỘNG — chỉ hiện khi `status == PENDING_REVIEW`. Đã xử lý xong
(REJECTED/INTERVIEW_SCHEDULED) thì KHÔNG hiện nữa; xem lại chỉ thấy trạng thái cuối.

### B.1 Gate hiển thị theo trạng thái · `/applications` (list + detail) — `components/*` liên quan

- Khối/badge "Cần HR xem xét" (+ `escalation_reason`) và các cờ hiển thị dưới dạng "cần chú ý" (vd
  `score_signal_mismatch`, `weak_match`, `near_threshold`) **CHỈ render khi `status == PENDING_REVIEW`.**
- Hồ sơ ở trạng thái cuối (REJECTED, INTERVIEW_SCHEDULED, ...) → KHÔNG hiện badge nhắc nhở này; hiện trạng thái
  cuối (passed/rejected) gọn gàng như bình thường.
- KHÔNG xóa dữ liệu `escalation_reason`/flags khỏi API/DB — chỉ gate HIỂN THỊ badge "cần xem xét" theo trạng thái.
  (Tùy chọn: ở trang chi tiết, có thể hiện lý do dạng thông tin trung tính cho hồ sơ đã quyết — KHÔNG bắt buộc, và KHÔNG dùng khung "cần HR xem xét".)
- `/review` (ReviewCard) KHÔNG đổi: hàng đợi vốn luôn PENDING_REVIEW nên badge vẫn đúng ở đó.

### B.2 (kiểm tra) badge số ca chờ ở nav

- Badge đếm số ca chờ nav vốn đếm theo PENDING_REVIEW → đảm bảo vẫn đúng (không đếm hồ sơ đã quyết). Chỉ xác nhận, sửa nếu lệch.

---

## Prerequisites

- 03b (human_review + approve→scheduler) và 04 (scheduler email thật) đã xong — Bug A tái dùng đường đó.
- Có CV đạt (backend khớp JD #2) + CV thấp để test. Email của bạn để nhận thư mời.

## Verify (chạy thật)

**Bug A:**

1. `make dev-backend` + `make dev-dashboard`. JD #2 (gate tắt). Nộp CV backend khớp (email của bạn) qua `/apply`.
2. Kỳ vọng MỚI: hồ sơ vào `/review` (Chờ HR duyệt), đề xuất "mời" — KHÔNG auto INTERVIEW_SCHEDULED, KHÔNG email câm.
3. Duyệt ca đó → nhận **thư mời THẬT** trong hòm thư → status INTERVIEW_SCHEDULED. Audit: approve + email_sent:invite.

**Bug B:** 4. Bật gate auto_reject JD → nộp CV điểm thấp (email của bạn) → auto-REJECTED + thư từ chối thật. Vào `/applications`
→ hồ sơ REJECTED **KHÔNG** còn badge "Cần HR xem xét"; chỉ hiện trạng thái "Đã từ chối". 5. Hồ sơ đang PENDING_REVIEW (từ bước 2, trước khi duyệt) → **CÓ** badge "Cần HR xem xét" + lý do (đúng). 6. Hồ sơ đã INTERVIEW_SCHEDULED (sau khi duyệt) → KHÔNG badge nhắc nhở; hiện "Đã hẹn phỏng vấn". 7. Badge số ca chờ ở nav = số PENDING_REVIEW (không tính hồ sơ đã quyết). 8. `make test` xanh; `pnpm --filter dashboard build` PASS.

## Definition of Done

- [ ] **A:** CV confident+đạt → human_review (đề xuất "mời"), KHÔNG auto-schedule câm; HR duyệt → thư mời THẬT → INTERVIEW_SCHEDULED.
- [ ] **A:** INTERVIEW_SCHEDULED chỉ đạt khi thư mời đã gửi; auto-reject + uncertain→review không hồi quy.
- [ ] **B:** Badge "Cần HR xem xét" (+ escalation/flags "cần chú ý") CHỈ hiện khi status==PENDING_REVIEW; hồ sơ đã quyết không còn badge.
- [ ] **B:** Không xóa dữ liệu escalation/flags khỏi API/DB (chỉ gate hiển thị); `/review` không đổi; badge nav đếm đúng PENDING_REVIEW.
- [ ] KHÔNG xây cổng auto-mời (08d), KHÔNG làm screener thật, KHÔNG đụng ranker/parser. scheduler = điểm phát email duy nhất.
- [ ] `make test` xanh; `pnpm build` PASS.

## Ranh giới & quy ước (theo CLAUDE.md)

- A: chỉ sửa định tuyến đường "đạt" + bỏ auto-set INTERVIEW_SCHEDULED câm + test. B: chỉ sửa LOGIC HIỂN THỊ badge theo trạng thái (không đụng backend cho B).
- Giữ đối xứng 03c; auto-mời để 08d (giờ = human_review). INTERVIEW_SCHEDULED = "đã báo ứng viên" — chỉ sau khi gửi mời.
- B là thay đổi hiển thị thuần — KHÔNG đổi dữ liệu API/DB, KHÔNG đụng ReviewCard/review queue.
- Trước khi sửa `route_after_ranker`, chạy impact analysis (GitNexus) như CLAUDE.md yêu cầu.
- Commit nhỏ (vd `fix(routing): CV đạt -> human_review (không auto-schedule câm)`, `fix(state): INTERVIEW_SCHEDULED chỉ sau khi gửi mời`, `fix(ui): badge cần-xem-xét chỉ khi PENDING_REVIEW`, `test: cập nhật nhánh đạt`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§8.3, §9, §11, §13). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhắc dùng email của người dùng), checklist DoD.

## Sau lát này

Vòng lõi đúng cả hai chiều (đạt→mời qua HR, thấp→auto-reject/HR) + hiển thị trạng thái sạch. Rồi vào **GĐ3 Screener
async** (08a: Postgres checkpointer + suspend/resume); cổng auto-mời (08d) xây sau, thêm nhánh "đạt + auto_invite BẬT → tự mời". Xem ROADMAP.md.
