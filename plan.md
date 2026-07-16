# SLICE 08d — Cổng auto-mời sau screener (hoàn tất gate thứ hai) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** thêm cổng auto-MỜI SAU screener — khi HR bật `auto_invite` cho một JD, ca SẠCH (đã trả lời screener,
> tự tin, không cờ) tự động được mời + gửi thư mời THẬT (qua scheduler) → INTERVIEW_SCHEDULED; khi tắt / có cờ /
> không phản hồi → human_review. Đối xứng với auto-reject (03c). Hoàn tất gate thứ hai → **hết GĐ3**.
> Tham chiếu: PRD §9 (hai gate + FR-GATE), §8.3, §13. Tuân thủ `CLAUDE.md`.
>
> **Đối xứng 03c:** gate chỉ áp ca CONFIDENT/SẠCH; ca bất định/`no_response` LUÔN → human_review (cờ thắng gate).
> Cấu hình THEO JD (`gate_config.auto_invite` đã có, mặc định TẮT). Toggle UI đã có ở form JD (05).

---

## 1. In scope / Out of scope

**In scope:**

- Định tuyến SAU screener (khi screener resume xong): ca sạch + `auto_invite` ON → **auto-invite**; else → human_review.
- Nhánh auto-invite: delegate `scheduler.notify_decision("invite")` (thư mời THẬT) → INTERVIEW_SCHEDULED → audit. Trong pipeline, KHÔNG cần HR.
- Đảm bảo an toàn: `no_response` (timeout), cờ bất định, low-confidence, gate OFF → human_review (gate no-op).
- Test (mock scheduler/email) + verify thật (auto-mời gửi thư mời tự động tới email của bạn).

**Out of scope (KHÔNG làm):**

- KHÔNG đánh giá NỘI DUNG câu trả lời screener để quyết (xem ghi chú thiết kế §3.1) — auto-invite dựa trên đã-trả-lời + điểm rank + không cờ; nội dung answers giữ cho HR/phỏng vấn.
- KHÔNG đụng checkpointer-08a / token-08b / timeout-08c logic. KHÔNG đụng parser/ranker/auto-reject-03c.
- KHÔNG UI mới (toggle auto_invite đã có ở form JD 05 — chỉ cần bỏ trạng thái "disabled/sẽ bật sau" nếu còn).

---

## 2. Prerequisites

- 08a/b/c xong (screener async đầy đủ; ca đạt đi qua screener rồi resume). 04 (scheduler email). 03c (mẫu gate auto-reject để đối xứng).
- `gate_config.auto_invite` đã có trên JD (mặc định false). `SCORE_PASS_THRESHOLD`, `CONFIDENCE_THRESHOLD` đã có.

---

## 3. Việc cần làm

### 3.1 Định tuyến sau screener · `app/agents/policy.py` (+ graph)

- Thêm quyết định SAU khi screener node resume (route_after_screener), theo THỨ TỰ ƯU TIÊN (an toàn trước):
  1. **`no_response` / cờ bất định / low-confidence** → `human_review` (gate KHÔNG xét — ca không sạch LUÔN về người).
  2. **Ca sạch** (đã trả lời, confident, không cờ):
     - JD `gate_config.auto_invite == True` → **`auto_invite`**.
     - ngược lại (OFF) → `human_review`.
- Đọc `gate_config` theo `job_id`. Log/audit rõ nhánh + lý do. **Mặc định auto_invite TẮT → hành vi hiện tại (sau screener → human_review) KHÔNG đổi.**
- **Ghi chú thiết kế (không code):** auto-invite KHÔNG chấm nội dung câu trả lời — đủ điều kiện = qua rank (đã tới screener) + đã trả lời + không cờ. Answers vẫn lưu, hiện cho HR/dùng khi phỏng vấn. Vì gate mặc định TẮT, mặc định vẫn có người xem (đọc answers) trước khi mời.

### 3.2 Nhánh auto-invite · node/logic

- Route = `auto_invite`: delegate `scheduler.notify_decision(mode="invite")` (điểm phát email DUY NHẤT → thư mời THẬT) →
  status `INTERVIEW_SCHEDULED` → audit (node="gate", action="auto_invite" + "email_sent:invite"). Chạy trong pipeline (async task), KHÔNG HR.
- Lỗi gửi email nuốt có kiểm soát (như 04/03c): INTERVIEW_SCHEDULED chỉ đặt khi mời đã gửi; lỗi → audit email_failed + xử lý nhất quán (đừng đặt trạng thái "đã mời" nếu email trượt — cân nhắc để human_review nếu gửi lỗi, tránh lặp lại bug "trạng thái nói dối").
- Đối xứng đúng với nhánh auto_reject của 03c (dùng lại pattern).

### 3.3 UI (nhỏ, nếu cần) · form JD (05)

- Nếu toggle `auto_invite` ở form JD đang disabled/nhãn "sẽ bật sau" → bật cho dùng thật, kèm ghi chú ngắn ("tự động mời ca đạt + đã trả lời sàng lọc; ca bất định/không phản hồi vẫn về HR"). Nếu đã bật sẵn thì bỏ qua.

### 3.4 Test · `app/tests/test_gate_invite.py` (mock scheduler/email)

- auto_invite ON + ca sạch (đã trả lời, confident, không cờ) → route `auto_invite`; scheduler.notify_decision(invite) gọi; INTERVIEW_SCHEDULED.
- auto_invite OFF + ca sạch → `human_review` (như hiện tại), KHÔNG gọi scheduler.
- `no_response` (timeout) + gate ON → `human_review` (an toàn), KHÔNG auto-invite.
- Ca có cờ bất định + gate ON → `human_review` (an toàn).
- Lỗi gửi mời → không đặt INTERVIEW_SCHEDULED sai (nhất quán).

---

## 4. Verify (chạy thật — auto-mời gửi thư mời THẬT tới email của bạn)

1. `make dev-backend` + `make dev-dashboard`. Bật auto_invite cho JD #2 (qua form JD /jobs hoặc PATCH gate).
2. Nộp CV đạt (backend khớp, **email của bạn**) qua `/apply` → pipeline chấm → dừng screener → nhận email câu hỏi.
3. **Trả lời screener** (trong hạn) qua magic-link → resume → ca SẠCH + auto_invite ON → **auto-invite tự động** → INTERVIEW_SCHEDULED, KHÔNG cần vào /review.
4. **Kiểm hòm thư:** nhận **thư mời THẬT** — hệ thống tự gửi, không thao tác HR. Audit: gate/auto_invite + email_sent:invite.
5. An toàn: tắt auto_invite → lặp lại → sau khi trả lời screener, ca vào `/review` (không tự mời). Một ca để **timeout** (không trả lời) + auto_invite BẬT → vẫn vào `/review` nhãn no_response (KHÔNG auto-mời).
6. Đối chứng auto-reject (03c) vẫn đúng: CV thấp + gate auto_reject ON → auto-từ-chối.
7. `make test` xanh.

---

## 5. Definition of Done

- [ ] Sau screener: ca sạch + auto_invite ON → auto-invite (thư mời THẬT, verify hòm thư) → INTERVIEW_SCHEDULED + audit.
- [ ] `no_response` / cờ / low-confidence / gate OFF → human_review (auto-invite KHÔNG áp — verify timeout + gate ON vẫn về HR).
- [ ] Mặc định auto_invite TẮT → hành vi sau-screener KHÔNG đổi so với trước 08d.
- [ ] INTERVIEW_SCHEDULED chỉ đặt khi thư mời đã gửi; lỗi gửi xử lý nhất quán (không "trạng thái nói dối").
- [ ] scheduler = điểm phát email DUY NHẤT; đối xứng đúng auto-reject 03c; parser/ranker/screener-08abc/auto-reject không hồi quy.
- [ ] Toggle auto_invite ở form JD dùng được (bỏ trạng thái "sẽ bật sau" nếu còn).
- [ ] `make test` xanh.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: route sau screener + nhánh auto-invite + (nhỏ) bật toggle auto_invite + test. KHÔNG đụng checkpointer/token/timeout/parser/ranker/auto-reject logic.
- An toàn số 1: ca không sạch (no_response/cờ/low-conf) LUÔN → human_review; gate chỉ áp ca sạch. "Cờ thắng gate."
- Tái dùng scheduler (điểm phát email duy nhất) + pattern nhánh auto_reject 03c. Cấu hình theo JD; mặc định TẮT.
- INTERVIEW_SCHEDULED = "đã mời" — chỉ sau khi thư mời gửi (đừng lặp bug trạng-thái-nói-dối).
- Chạy impact analysis trước khi sửa policy (GitNexus nếu có, không thì grep-based). Commit nhỏ (vd `feat(gate): route sau screener + nhánh auto-invite`, `feat(ui): bật toggle auto_invite JD`, `test(gate): auto-invite + an toàn no_response/cờ`).
- Nghiệp vụ chưa rõ → **PRD.md** (§9, §8.3). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn: email của bạn + thử timeout/gate), checklist DoD.

## 7. Sau lát này — HẾT GĐ3

Toàn bộ pipeline tự trị hoàn chỉnh: parser→ranker→(đạt→screener async→auto-mời/HR · thấp→auto-từ-chối/HR · bất định→HR),
mọi kết quả ra email thật, hai gate cấu hình được, ca bất định luôn về người. Kế tiếp: **GĐ4 (auth HR)** rồi **GĐ5**
(analytics/observability/anti-injection/**UI redesign**/deploy). Xem ROADMAP.md.
