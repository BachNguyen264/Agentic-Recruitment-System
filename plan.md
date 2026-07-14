# SLICE 08b — Magic-link form + email câu hỏi (Screener do ứng viên điều khiển) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** khi pipeline dừng ở screener (08a), hệ thống **gửi email kèm magic-link** → ứng viên mở link thấy
> **form câu hỏi (cố định theo JD)** → nộp → **resume pipeline bằng chính câu trả lời** (thay endpoint dev). Câu
> trả lời được lưu + hiện cho HR. Ghép: suspend/resume (08a) + email (04) + cửa ứng viên (07).
> Tham chiếu: PRD §7.3 (Screener), §10, §12.2 (FR-AP-3), §16 (ScreeningSession). Tuân thủ `CLAUDE.md`.
>
> **⚠️ Cốt lõi lát này = BẢO MẬT MAGIC-LINK (token). Đọc kỹ mục "Bảo mật" — làm đúng từ đầu.**

---

## 1. In scope / Out of scope

**In scope:**

- Bảng `screening_session` (token, application_id, expires_at, used_at, answers) + migration Alembic.
- Khi interrupt (BackgroundTask): sinh token an toàn + tạo screening_session + delegate **scheduler** gửi email câu hỏi kèm magic-link.
- scheduler: thêm template email "screener" (magic-link + hạn) — vẫn là điểm phát email DUY NHẤT.
- Endpoint CÔNG KHAI: `GET /api/public/screening/{token}` (validate token → trả câu hỏi + tiêu đề JD, KHÔNG lộ nội bộ);
  `POST /api/public/screening/{token}` (nộp câu trả lời → validate → row-lock → **resume graph bằng câu trả lời** → đánh dấu used → lưu answers).
- Trang công khai `/screening/[token]` (hiện câu hỏi, form, nộp, xác nhận) — tách khỏi nav HR.
- Hiện câu trả lời screener cho HR (thêm nhỏ ở ReviewCard/chi tiết).
- Gỡ/gate endpoint dev `resume-screener` (token-submit là đường thật).

**Out of scope (KHÔNG làm — là 08c/08d/sau):**

- KHÔNG timeout/nhắc lịch/trả lời trễ (08c). KHÔNG cổng auto-mời (08d).
- KHÔNG dùng LLM chuẩn hóa/hỏi lại câu trả lời (lưu answers THÔ + hiện cho HR; tinh chỉnh để sau).
- KHÔNG đụng parser/ranker logic; KHÔNG đổi cơ chế checkpointer 08a (chỉ đổi trigger resume).

---

## 2. Prerequisites

- 08a xong (suspend/resume + AsyncPostgresSaver + screener interrupt). 04 xong (scheduler email thật). 05 xong
  (JD có `screener_questions`). 07 xong (pattern public endpoint + trang công khai tách nav).
- Config: `SCREENER_DEADLINE_HOURS` (vd 72), `FRONTEND_BASE_URL` (build magic-link). Email: Resend (nhắc: chưa xác thực domain → khi verify dùng email của bạn làm applicant).

---

## 3. Việc cần làm

### 3.1 Bảng screening_session + migration · `app/models/` + Alembic

- `screening_session`: `id`, `token` (unique, indexed), `application_id` (FK), `expires_at`, `used_at` (nullable),
  `answers` (JSONB, nullable), `created_at`. Migration Alembic tạo bảng.
- Cập nhật `scripts/reset_demo_data.py`: xóa application thì xóa KÈM screening_session tương ứng (tránh mồ côi, giống checkpoint/Qdrant).

### 3.2 Sinh token + gửi email khi interrupt · `app/tasks/background.py`

- Khi graph interrupt (AWAITING_SCREENER): sinh **token an toàn** (`secrets.token_urlsafe`, KHÔNG tuần tự/đoán được);
  tạo `screening_session` (application_id, expires_at = now + SCREENER_DEADLINE_HOURS, used_at=NULL).
- Delegate `scheduler.notify_decision(mode="screener", ...)` (hoặc hàm tương đương) → gửi email câu hỏi kèm
  magic-link `{FRONTEND_BASE_URL}/screening/{token}`. Lỗi gửi nuốt có kiểm soát (như 04) — không sập; audit.

### 3.3 scheduler: template screener · `app/agents/nodes/scheduler.py` + templates

- Thêm `screener_email(candidate_name, job_title, link, deadline)`: mời ứng viên trả lời vài câu hỏi bổ sung qua
  link, nêu hạn. Template CỐ ĐỊNH (không LLM). scheduler vẫn là điểm phát email DUY NHẤT.

### 3.4 Endpoint công khai · `app/api/routes/` (public)

- `GET /api/public/screening/{token}`: validate token (tồn tại + chưa hết hạn + chưa dùng + application đang
  AWAITING_SCREENER) → trả **chỉ**: câu hỏi (`screener_questions` của JD) + tiêu đề JD. **KHÔNG** lộ rubric/gate/
  điểm/parsed_data/nội bộ. Token sai/hết hạn/đã dùng → trạng thái rõ (410/404/409) để UI hiện thông báo phù hợp.
- `POST /api/public/screening/{token}` (body: answers theo câu hỏi):
  1. **Row-lock** screening_session/application (SELECT … FOR UPDATE) để chống submit trùng → resume 2 lần.
  2. Re-validate trong lock: chưa used, chưa hết hạn, application AWAITING_SCREENER.
  3. **Resume graph**: `Command(resume=answers)` với `thread_id = app-<application_id>` (đúng cơ chế 08a) → graph
     chạy tiếp từ screener → node kế → trạng thái cuối (human_review, vì gate mời chưa xây).
  4. Đánh dấu `used_at = now`; lưu `answers` (vào screening_session + state screener của application).
  5. Trả xác nhận gọn (không lộ điểm/trạng thái nội bộ).

### 3.5 Trang công khai form · `app/screening/[token]/page.tsx`

- Fetch câu hỏi qua GET public → render form (mỗi câu hỏi 1 ô trả lời). Nộp → POST public → màn xác nhận
  ("Cảm ơn, câu trả lời đã được ghi nhận"). Token sai/hết hạn/đã nộp → thông báo tương ứng (không form).
- Tách khỏi nav HR (luồng ứng viên, như /apply). Validate client cơ bản (điền đủ). Chống double-submit.

### 3.6 Hiện câu trả lời cho HR · ReviewCard/chi tiết

- Ở `/review` (và/hoặc chi tiết ứng viên), nếu application có `answers` screener → hiện khối "Câu trả lời sàng lọc"
  (câu hỏi + trả lời) để HR tham khảo khi quyết. Thuần hiển thị.

### 3.7 Gỡ/gate endpoint dev

- `POST /api/agents/resume-screener/{id}` (dev, từ 08a): gỡ, HOẶC gate sau cờ env (chỉ để test nội bộ). Đường thật giờ là token-submit.

### 3.8 Test · `app/tests/test_screening.py`

- Interrupt → screening_session tạo với token + hạn; scheduler gửi email screener (mock).
- GET token hợp lệ → trả câu hỏi (KHÔNG lộ rubric/điểm). Token sai/hết hạn/đã dùng → lỗi đúng mã.
- POST token → resume graph (mock/gated) → status chuyển; used_at set; answers lưu; parser/ranker KHÔNG chạy lại.
- POST lần 2 cùng token → bị từ chối (đã dùng). Row-lock chống double-submit (nếu test được).

---

## 4. Verify (chạy thật — luồng ứng viên đầy đủ)

1. `make dev-backend` + `make dev-dashboard`. JD #2 có `screener_questions` (nếu chưa, thêm vài câu qua /jobs).
2. Nộp CV đạt (backend khớp, **email của bạn**) qua `/apply` → pipeline chấm → dừng ở screener (AWAITING_SCREENER).
3. **Kiểm hòm thư:** nhận **email câu hỏi kèm magic-link**. Mở link → trang `/screening/{token}` hiện câu hỏi của JD (KHÔNG thấy rubric/điểm).
4. Điền câu trả lời → Nộp → màn xác nhận. Pipeline **resume** → `/applications` (HR) thấy CV chuyển PENDING_REVIEW (KHÔNG chạy lại parser/ranker — kiểm log).
5. Vào `/review` → thấy **câu trả lời screener** của ứng viên hiển thị. Duyệt → thư mời thật.
6. Bảo mật: mở lại link đã nộp → báo "đã nộp/không hợp lệ" (one-time). Sửa token bậy trên URL → báo lỗi. (Nếu chỉnh được `expires_at` về quá khứ → link báo hết hạn.)
7. `make test` xanh; `pnpm --filter dashboard build` PASS.

---

## 5. Definition of Done

- [ ] Interrupt → sinh token an toàn + screening_session (hạn) + scheduler gửi email magic-link (điểm phát email duy nhất).
- [ ] `/screening/{token}` hiện câu hỏi JD; nộp → **resume graph bằng câu trả lời** → PENDING_REVIEW (KHÔNG chạy lại parser/ranker).
- [ ] Câu trả lời lưu + hiện cho HR ở review.
- [ ] **Bảo mật:** token crypto-random; hết hạn bị từ chối; one-time (dùng lại bị chặn); chỉ resume application AWAITING_SCREENER; **row-lock chống double-submit**.
- [ ] Public endpoint KHÔNG lộ rubric/gate/điểm/parsed_data (chỉ câu hỏi + tiêu đề JD).
- [ ] Migration screening_session; reset_demo_data dọn kèm; endpoint dev resume gỡ/gated.
- [ ] KHÔNG timeout/nhắc (08c), KHÔNG auto-mời (08d), KHÔNG LLM chuẩn hóa câu trả lời; checkpointer 08a không đổi.
- [ ] `make test` xanh; `pnpm build` PASS.

---

## 6. 🔒 BẢO MẬT — đọc kỹ (cốt lõi lát này)

- **Token không đoán được:** `secrets.token_urlsafe(32)` — KHÔNG dùng id tuần tự / uuid dễ đoán / hash yếu.
- **Hết hạn:** `expires_at` (config SCREENER_DEADLINE_HOURS); mọi thao tác re-check còn hạn không.
- **One-time:** đánh dấu `used_at` sau khi resume thành công; token đã dùng → từ chối (tránh resume 2 lần / replay).
- **Tie đúng trạng thái:** chỉ resume application đang `AWAITING_SCREENER`; khác trạng thái → từ chối (tránh resume ca đã xử lý).
- **Row-lock chống race:** hai submit đồng thời cùng token KHÔNG được cùng resume graph (state hỏng / xử lý đôi). SELECT … FOR UPDATE trên session/application trong transaction resume; re-validate trong lock.
- **Không lộ nội bộ:** endpoint/trang công khai chỉ câu hỏi + tiêu đề JD; KHÔNG rubric/gate/điểm/parsed_data (như projection 07).
- **Lỗi gửi email không sập** (như 04): interrupt vẫn AWAITING_SCREENER, session vẫn tạo; log/audit lỗi để xử (retry/timeout là 08c).

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: screening_session + token/email trigger + scheduler screener template + public screening endpoints + trang /screening + hiện answers cho HR + gỡ endpoint dev + migration/test. KHÔNG đụng parser/ranker/checkpointer-08a logic.
- scheduler = điểm phát email DUY NHẤT (email screener qua scheduler). Template cố định (không LLM).
- resume dùng đúng thread_id = `app-<application_id>` của 08a. Chạy impact analysis (GitNexus) trước khi sửa background/policy.
- Commit nhỏ (vd `feat(screener): bảng screening_session + migration`, `feat(screener): token + email magic-link qua scheduler`, `feat(api): public screening GET/POST + resume bằng answers (row-lock)`, `feat(ui): trang /screening form`, `feat(ui): hiện answers cho HR`, `chore: gỡ endpoint dev resume`, `test(screener): token/expiry/one-time/resume`).
- Nghiệp vụ chưa rõ → **PRD.md** (§7.3, §10, §12.2, §16). Vướng kỹ thuật (resume/lock/token) → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn: dùng email của bạn, thử one-time/hết hạn), checklist DoD.

## 8. Sau lát này

Screener do ứng viên điều khiển xong → **08c** (timeout: quét deadline, nhắc +24h, timeout→human_review `no_response`,
trả lời trễ) → **08d** (cổng auto-mời sau screener). Xem ROADMAP.md.
