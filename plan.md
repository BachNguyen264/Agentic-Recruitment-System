# SLICE 04 — Scheduler email THẬT (Resend) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** biến `scheduler.notify_decision(mode)` từ stub-log thành GỬI EMAIL THẬT qua Resend — thư mời
> phỏng vấn / thư từ chối tới ứng viên. Khép kín vòng lặp end-to-end (CV vào → email ra). Là điểm phát email DUY NHẤT.
> Tham chiếu: PRD §7.4 (Scheduler), §12.4 (FR-NOTI-1), §13. Tuân thủ `CLAUDE.md`.
>
> **Nhà cung cấp: Resend.** **Calendar (Google) HOÃN** — lát này CHỈ email; tạo sự kiện lịch để lát sau/đơn giản
> hóa (thư mời nêu sẽ liên hệ sắp lịch). Luồng review (03b) KHÔNG đổi — chỉ thay phần thân của notify_decision.

---

## 1. In scope / Out of scope

**In scope:**

- `email_service` gửi email qua Resend (API key + from-address, xử lý lỗi).
- Template email CỐ ĐỊNH: thư mời + thư từ chối (tiếng Việt), điền {candidate_name}, {job_title}.
- `scheduler.notify_decision(mode)`: dựng email từ template → gửi thật; lỗi gửi → log + ghi nhận, KHÔNG sập, quyết định vẫn giữ.
- Config `RESEND_API_KEY` + `EMAIL_FROM`; thêm dependency `resend`.
- Test (mock Resend — KHÔNG gửi thật trong test).

**Out of scope (KHÔNG làm):**

- KHÔNG tạo sự kiện Google Calendar (hoãn — OAuth phức tạp). Thư mời chỉ nêu bước sắp lịch.
- KHÔNG để LLM tự viết email — template CỐ ĐỊNH (nhất quán + an toàn pháp lý, cùng lý do Screener câu hỏi cố định).
- KHÔNG đổi luồng review 03b / endpoint / trạng thái — chỉ thay phần thân notify_decision (stub-log → gửi thật).
- KHÔNG làm gate (03c), KHÔNG cơ chế resend/retry đầy đủ (chỉ log lỗi; retry để sau).
- KHÔNG đụng parser/ranker/policy.

---

## 2. Prerequisites (đọc kỹ phần Resend)

- Đăng ký Resend (https://resend.com), lấy **API key** → đặt `RESEND_API_KEY` vào `.env` + `.env.example`.
- `EMAIL_FROM`: dùng `onboarding@resend.dev` để test, HOẶC địa chỉ thuộc domain đã xác thực.
- **⚠️ Giới hạn người nhận:** với from-address test (`onboarding@resend.dev`) + chưa xác thực domain, Resend
  thường CHỈ cho gửi tới **email đã đăng ký tài khoản Resend của bạn**. → Khi verify (mục 4), tạo application với
  `applicant_email` = **email của chính bạn**. Gửi tới email tùy ý cần **xác thực domain** (thêm DNS) — để lúc demo public.
- Free tier Resend đủ cho đồ án (giới hạn ngày/tháng nhỏ). Thêm dep: `resend` (uv add).

---

## 3. Việc cần làm

### 3.1 `email_service` · `app/services/email_service.py`

- `send_email(to: str, subject: str, html: str) -> None` (async): gọi Resend (SDK `resend` hoặc httpx tới API Resend)
  với `from=settings.EMAIL_FROM`, `RESEND_API_KEY`.
- Bọc try/except: lỗi Resend (mạng/khóa/giới hạn) → raise lỗi RÕ (để caller xử lý), log chi tiết. KHÔNG nuốt lỗi im lặng.
- Config từ env; KHÔNG hardcode key/from.

### 3.2 Template email · `app/services/email_templates.py`

- `invite_email(candidate_name, job_title) -> (subject, html)`: thư mời phỏng vấn — chúc mừng, nêu vị trí, nói sẽ
  liên hệ sắp lịch phỏng vấn. Lịch sự, trung tính, tiếng Việt.
- `rejection_email(candidate_name, job_title) -> (subject, html)`: thư từ chối — cảm ơn đã ứng tuyển vị trí, rất tiếc
  chưa phù hợp lần này, chúc may mắn. Lịch sự, tôn trọng.
- HTML đơn giản (không cần đẹp cầu kỳ). Placeholder điền an toàn (escape nếu cần). CỐ ĐỊNH — không sinh bằng LLM.

### 3.3 `scheduler.notify_decision(mode)` · `app/agents/nodes/scheduler.py`

- Thay phần thân (đang log ý định) bằng:
  1. Lấy `candidate_name` (từ parsed_data.full_name, fallback "Ứng viên") + `job_title` (từ JD) + `applicant_email`.
  2. mode `invite` → `invite_email(...)`; mode `reject` → `rejection_email(...)`.
  3. `await email_service.send_email(to=applicant_email, subject, html)`.
  4. **Xử lý lỗi gửi:** try/except quanh send — lỗi → log rõ + ghi audit_log `action="email_failed"` (hoặc cờ),
     nhưng KHÔNG raise làm sập luồng review; quyết định + trạng thái (đã đặt ở 03b) VẪN giữ. (Retry/resend: để sau.)
  5. Thành công → log + audit `action="email_sent:invite/reject"`.
- GIỮ vai trò điểm phát email DUY NHẤT. Không gửi email ở chỗ khác.

### 3.4 Config · `app/core/config.py`

- Thêm `RESEND_API_KEY`, `EMAIL_FROM` (pydantic-settings). Cập nhật `.env.example`.

### 3.5 Test · `app/tests/test_scheduler_email.py`

- **Mock Resend/email_service** (KHÔNG gửi thật):
  - notify_decision(invite) → gọi email_service.send_email đúng recipient + template mời (subject/nội dung chứa job_title, tên).
  - notify_decision(reject) → gọi với template từ chối.
  - email_service ném lỗi → notify_decision KHÔNG raise (nuốt có kiểm soát) + ghi audit email_failed.
- Template: điền placeholder đúng (tên + vị trí).
- Suite cũ vẫn xanh (03b review test không vỡ).

---

## 4. Verify (chạy thật — GỬI EMAIL THẬT tới email của bạn)

1. `.env` có `RESEND_API_KEY` + `EMAIL_FROM`. `make dev-backend`.
2. Tạo application với `applicant_email` = **email của chính bạn** cho JD #2 (upload một CV) → chạy tới PENDING_REVIEW (hoặc dùng ca có sẵn nhưng đổi email về email bạn).
3. Vào `/review` → **Duyệt** ca đó → kiểm **hòm thư của bạn**: nhận được THƯ MỜI (đúng tên + vị trí). Backend log email_sent; audit có dòng.
4. Tạo ca khác (email của bạn) → **Từ chối** → nhận THƯ TỪ CHỐI trong hòm thư.
5. Thử lỗi (tùy chọn): tạm để `RESEND_API_KEY` sai → quyết định vẫn xong (trạng thái đổi), backend log email_failed, KHÔNG sập.
6. `make test` xanh (mock, không gửi thật); `pnpm build` PASS (nếu có đụng shared-types — lát này chủ yếu backend).

---

## 5. Definition of Done

- [ ] Duyệt ca → thư MỜI thật gửi tới email ứng viên (verify bằng email của bạn); Từ chối → thư TỪ CHỐI thật.
- [ ] Email dùng template CỐ ĐỊNH (không LLM), điền đúng tên + vị trí.
- [ ] scheduler là điểm phát email DUY NHẤT; luồng review 03b không đổi (chỉ thay thân notify_decision).
- [ ] Lỗi gửi email KHÔNG làm sập; quyết định/trạng thái vẫn giữ; audit ghi email_sent / email_failed.
- [ ] Config RESEND_API_KEY/EMAIL_FROM từ env; `.env.example` cập nhật; dep `resend` thêm.
- [ ] Calendar KHÔNG làm (hoãn). KHÔNG gate. KHÔNG đụng parser/ranker/policy.
- [ ] `make test` xanh (mock Resend); suite 03b không vỡ.

---

## 6. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: email_service + templates + scheduler.notify_decision (thân) + config + test. KHÔNG đổi endpoint/luồng review.
- Template CỐ ĐỊNH, KHÔNG sinh bằng LLM (nhất quán + pháp lý). Calendar hoãn.
- Lỗi gửi email nuốt có kiểm soát (log + audit), KHÔNG sập luồng; quyết định HR luôn được giữ.
- scheduler giữ vai trò điểm phát email DUY NHẤT — đừng rải send_email chỗ khác.
- Test mock Resend (không gửi thật, không tốn quota/không phụ thuộc mạng trong CI).
- Async-first; config từ env; không hardcode key/from/nội dung nhạy cảm.
- Commit nhỏ (vd `feat(email): email_service qua Resend + config`, `feat(email): template thư mời/từ chối`, `feat(scheduler): notify_decision gửi email thật + xử lý lỗi`, `test(scheduler): mock Resend + template`).
- Nghiệp vụ chưa rõ → tra **PRD.md** (§7.4, §12.4). PRD chưa đủ → DỪNG, hỏi.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhắc dùng email của người dùng), checklist DoD.

---

## 7. Lát kế tiếp (KHÔNG làm bây giờ)

**03c Gate rank** (auto-từ-chối dùng score + gate_config — giờ sẽ gửi email từ chối THẬT qua scheduler, PRD §9).
Rồi GĐ2: đăng JD UI + nộp CV công khai + storage. Xem ROADMAP.md. (Google Calendar: cân nhắc lát riêng nếu cần.)
