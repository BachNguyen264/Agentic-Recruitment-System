# PRD — Hệ thống Tuyển dụng Tự trị sử dụng Multi-Agent AI

> **Tài liệu này là NGUỒN CHÂN LÝ của hệ thống.** Mọi quyết định triển khai phải đối chiếu với PRD này.
> Khi code và PRD mâu thuẫn → PRD đúng (hoặc cập nhật PRD trước rồi mới sửa code).
>
> Phiên bản: 1.0 · Phạm vi: đồ án tốt nghiệp (proof-of-concept hoàn chỉnh).

---

## 1. Giới thiệu

### 1.1 Mục đích

Xây dựng hệ thống tự động hóa vòng sàng lọc tuyển dụng từ khi tiếp nhận CV đến khi gửi thư mời phỏng vấn,
trong đó bốn AI Agent chuyên biệt phối hợp trong một pipeline cố định, và con người (HR) chỉ can thiệp ở
các điểm quyết định quan trọng hoặc khi hệ thống không đủ tự tin.

### 1.2 Tầm nhìn

Giảm thời gian và công sức sàng lọc thủ công, tăng tính nhất quán và khách quan, đồng thời giữ trách nhiệm
giải trình thông qua nhật ký kiểm toán và cơ chế phê duyệt của con người. Hệ thống tự động nhưng **trong
tầm kiểm soát**: ưu tiên tính dự đoán được và khả năng kiểm toán hơn là tự trị tối đa.

### 1.3 Bối cảnh sản phẩm

Web đóng vai trò kép: cổng nộp CV công khai cho ứng viên VÀ bảng điều hành đầy đủ cho HR. Trên điện thoại,
chính web này (dạng PWA cài được lên màn hình chính) cho HR phê duyệt nhanh khi di chuyển. Backend chạy
pipeline đa tác tử bất đồng bộ.

---

## 2. Mục tiêu & Phi mục tiêu

### 2.1 Mục tiêu

- M1. Tự động bóc tách CV (PDF/DOCX) thành dữ liệu có cấu trúc.
- M2. Tự động đối sánh CV với JD và chấm điểm theo bộ tiêu chí có trọng số.
- M3. Tự động thu thập thông tin bổ sung từ ứng viên (bất đồng bộ) cho các ứng viên đã qua ngưỡng.
- M4. Tự động gửi thư mời + đặt lịch phỏng vấn, hoặc gửi thư từ chối — sau khi qua cổng kiểm soát.
- M5. Cung cấp dashboard giám sát pipeline thời gian thực + hàng đợi phê duyệt cho HR.
- M6. Bảo đảm tính kiểm soát: nhật ký kiểm toán đầy đủ, human-in-the-loop, hai cổng cấu hình được.

### 2.2 Phi mục tiêu (không làm)

- Không xử lý các khâu sau phỏng vấn (đàm phán lương, ký hợp đồng, onboarding).
- Không chấm phỏng vấn, không ra quyết định tuyển dụng cuối cùng (con người quyết).
- Không phải hệ multi-agent tự trị hoàn toàn (KHÔNG có Supervisor Agent điều phối động).
- Không hỗ trợ kênh thoại/video; Screener chỉ qua văn bản (email/form, tùy chọn Zalo).
- Luồng HR tự đặt lịch thủ công: để sau hoặc bỏ (đề tài tập trung tự động hóa).

---

## 3. Thuật ngữ

- **JD (Job Description):** tin tuyển dụng + mô tả công việc do HR đăng. Là chuẩn để Ranker đối sánh.
- **CV / Hồ sơ:** tệp ứng viên nộp (PDF/DOCX) cho một JD cụ thể.
- **Application / Candidate:** một lần nộp CV cho một JD — đơn vị chạy qua pipeline.
- **Agent:** một bước xử lý chuyên biệt trong pipeline (parser, ranker, screener, scheduler).
- **Pipeline:** chuỗi agent cố định xử lý một CV: `parser → ranker → screener → scheduler`.
- **HITL (human_review):** điểm dừng để HR quyết, kích hoạt có điều kiện.
- **Gate:** cổng cấu hình do HR bật/tắt, kiểm soát hành động tự động (auto-từ-chối, auto-mời).
- **confidence:** độ tự tin của agent với kết quả của nó (0..1).
- **uncertainty_flags:** cờ bất thường (vd `parse_failed`, `weak_match`, `no_response`).
- **escalation_reason:** lý do một CV bị đẩy sang human_review.
- **ReviewCard:** thẻ ngữ cảnh đính kèm mỗi ca human_review (tóm tắt + điểm + lý do).
- **Magic link:** liên kết có token, không cần mật khẩu, để ứng viên trả lời form Screener.

---

## 4. Vai trò & Phân quyền

| Vai trò              | Đăng nhập                      | Quyền                                                                                                                                                       |
| -------------------- | ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Guest / Ứng viên** | Không bắt buộc (chỉ cần email) | Xem danh sách JD đang mở; chọn JD và nộp CV; trả lời form Screener qua magic link; (tùy chọn) tra cứu trạng thái đơn của mình qua link.                     |
| **HR Admin**         | Bắt buộc                       | Tạo/sửa/đóng JD; xem toàn bộ ứng viên + bộ lọc; dashboard giám sát agent; hàng đợi human_review (duyệt/từ chối); bật/tắt hai gate; xem thống kê & vòng học. |

> Tài khoản ứng viên (đăng nhập thường) là tùy chọn, chỉ để theo dõi đơn — KHÔNG bắt buộc để nộp CV
> (giữ chế độ guest nhằm giảm rào cản nộp hồ sơ).

---

## 5. Triết lý thiết kế (4 trụ cột)

1. **Luồng cố định để dự đoán & kiểm toán.** Thứ tự agent và nhánh rẽ do graph quy định trước, không do
   agent quyết runtime. KHÔNG có Supervisor Agent — đây là lựa chọn có chủ đích.
2. **Tự trị CÓ GIỚI HẠN ở tầng agent.** Bên trong mỗi node, agent tự quyết dùng tool nào (function calling),
   nhưng bị giới hạn số bước để giữ dự đoán được. Pipeline cố định ở tầng điều phối.
3. **An toàn trước case lạ.** Mỗi agent trả kèm `confidence` + `uncertainty_flags`; dưới ngưỡng → tự chuyển
   `human_review`. "Không chắc thì hỏi HR" là hành vi đúng, không phải thất bại.
4. **Cải thiện dần bán tự động có người duyệt.** Hệ thống phát hiện mẫu case lạ từ audit*log → *đề xuất\_
   chỉnh rubric/JD/prompt → HR duyệt mới áp dụng. Agent KHÔNG tự đổi control flow.

> Đánh đổi cốt lõi: quyền tự trị ở tầng điều phối ĐỔI LẤY độ tin cậy/khả năng kiểm soát + chi phí thấp.

---

## 6. Kiến trúc tổng thể

- **Web (Next.js):** cổng công khai (xem JD, nộp CV, form Screener) + dashboard HR (giám sát, review, cấu hình).
- **Trên điện thoại:** web dạng PWA (cài lên màn hình chính) — HR xem CV + duyệt human_review nhanh.
  Một app web duy nhất, responsive; KHÔNG có codebase mobile riêng.
- **Backend (FastAPI + LangGraph):** pipeline đa tác tử; xử lý bất đồng bộ; suspend/resume cho Screener.
- **Hạ tầng managed:** Neon (Postgres), Upstash Redis (cache/short-term memory), Qdrant Cloud (embedding JD–CV).
- **Tích hợp:** Email (gửi câu hỏi/thư mời/từ chối), tùy chọn Zalo OA; Google Calendar (đặt lịch).
- **Observability:** Langfuse (giám sát chi phí/độ trễ — phase sau).

---

## 7. Bốn Agent

### 7.1 Parser

- **Đầu vào:** tệp CV (PDF/DOCX).
- **Việc:** trích xuất thông tin ứng viên → JSON có cấu trúc (tên, liên hệ, kỹ năng, kinh nghiệm, học vấn).
- **confidence/cờ:** `parse_failed` nếu định dạng không đọc được; confidence theo chất lượng bóc tách.
- **Tool tự trị (phase sau):** chọn bộ đọc theo định dạng (PyMuPDF/python-docx).

### 7.2 Ranker

- **Đầu vào:** dữ liệu CV (từ Parser) + JD (đã embedding trong Qdrant).
- **Việc:** đối sánh ngữ nghĩa CV–JD; chấm điểm theo bộ tiêu chí có trọng số (rubric); sinh điểm tổng + phân
  rã theo tiêu chí + tóm tắt; là **node ra quyết định** (đạt/không đạt/bất định).
- **confidence/cờ:** `weak_match` khi khớp yếu; confidence thấp khi điểm sát ngưỡng.
- **Tool tự trị (phase sau):** truy vấn vector, công cụ chấm điểm.

### 7.3 Screener (chạy SAU Ranker)

- **Đầu vào:** ứng viên đã qua ngưỡng rank.
- **Việc:** gửi **bộ câu hỏi cố định** (cấu hình theo JD) qua **email + magic-link form** để thu thập thông
  tin hậu tuyển (lương kỳ vọng, thời gian nhận việc, xác nhận quan tâm, câu hỏi loại trừ do HR đặt). Sau khi
  nhận trả lời, chuẩn hóa thành dữ liệu có cấu trúc.
- **Bản chất:** thu thập thông tin có cấu trúc, BẤT ĐỒNG BỘ — KHÔNG phải chatbot tự do (xem §10).
- **confidence/cờ:** `no_response` khi quá hạn; cờ khi câu trả lời lộ vấn đề (lương quá cao, từ chối…).
- **Tool tự trị (phase sau):** LLM chỉ để (a) diễn đạt lời mời, (b) chuẩn hóa câu trả lời, (c) hỏi lại tối
  đa 1 lần khi mơ hồ. Bộ câu hỏi cố định, không cải biên.

### 7.4 Scheduler

- **Đầu vào:** quyết định "mời" hoặc "từ chối" (từ gate tự động hoặc từ HR duyệt).
- **Việc:** nếu mời → gửi thư mời phỏng vấn + tạo sự kiện Google Calendar + nhắc lịch. Nếu từ chối → gửi thư
  từ chối. Là **điểm thực thi DUY NHẤT** cho mọi hành động gửi-email-tới-ứng-viên.
- **Tool tự trị (phase sau):** chọn gửi email / tạo lịch / cả hai.

---

## 8. Luồng nghiệp vụ end-to-end

### 8.1 Thiết lập (HR)

1. HR đăng nhập, tạo JD. Hệ thống embedding JD → lưu Qdrant làm chuẩn đối sánh.

### 8.2 Nộp (Ứng viên — web công khai)

2. Ứng viên xem danh sách JD đang mở, chọn một JD, nộp CV (chỉ cần email; không bắt đăng nhập).
3. Hệ thống lưu Application (status `SUBMITTED`), đẩy vào xử lý bất đồng bộ. Mỗi CV = một pipeline độc lập,
   chạy song song với các CV khác.

### 8.3 Pipeline

4. `parser`: CV → JSON. (lỗi → `parse_failed` → human_review)
5. `ranker`: đối sánh JD + chấm điểm. Sau Ranker là **GATE RANK**:
   - **đạt ngưỡng** → tiếp `screener`.
   - **rank thấp** → _gate auto-từ-chối_: BẬT → tự từ chối (scheduler gửi thư) → `REJECTED`; TẮT → `human_review`.
   - **bất định** (`weak_match`/điểm sát ngưỡng) → **luôn** `human_review` (gate no-op).
6. `screener`: gửi email + magic-link form → **pipeline SUSPEND** (lưu state, không chiếm tài nguyên). Xem §10.
   Sau khi có kết quả (trả lời / timeout), tới **GATE MỜI**:
   - **ổn + auto-mời BẬT** → `scheduler` gửi thư mời + đặt lịch → `INTERVIEW_SCHEDULED`.
   - **auto-mời TẮT, hoặc có cờ (`no_response`…)** → `human_review`.
7. `scheduler`: thực thi hành động cuối (mời/từ chối).

### 8.4 human_review (xem §11)

8. CV vào human_review **kèm ReviewCard** (tóm tắt + điểm + lý do). HR quyết:
   - **duyệt** → delegate cho `scheduler` tự gửi thư mời + đặt lịch → `INTERVIEW_SCHEDULED`.
   - **từ chối** → `scheduler` gửi thư từ chối → `REJECTED`.

### 8.5 Kết thúc

9. Email báo kết quả cho ứng viên (mời/từ chối). Trạng thái cuối: `INTERVIEW_SCHEDULED` hoặc `REJECTED`.

---

## 9. Hai Gate cấu hình

| Gate             | Vị trí                          | BẬT (ON)                  | TẮT (OFF — mặc định an toàn)                |
| ---------------- | ------------------------------- | ------------------------- | ------------------------------------------- |
| **auto-từ-chối** | sau Ranker, ca rank thấp        | tự từ chối + gửi email    | mọi ca từ chối → human_review               |
| **auto-mời**     | sau Screener, trước gửi thư mời | tự gửi thư mời + đặt lịch | mọi thư mời → human_review (HR duyệt trước) |

- **FR-GATE-1:** Gate là cấu hình của HR, lưu trong DB; có thể đặt mức toàn hệ thống hoặc theo từng JD.
- **FR-GATE-2 (BẤT BIẾN):** Gate CHỈ can thiệp ca agent **tự tin**. Ca bất định/thiếu tự tin (`parse_failed`,
  `weak_match`, `no_response`, confidence < ngưỡng) → gate **no-op**, LUÔN vào human_review, bất kể gate.
- **FR-GATE-3:** Mặc định cả hai gate TẮT (an toàn nhất).

---

## 10. Screener bất đồng bộ (suspend / resume)

Nguyên lý: **không giữ pipeline "đang chạy" để đợi con người.** Pipeline tạm dừng, lưu state bền vững, thức
dậy theo sự kiện hoặc theo hạn.

- **FR-SCR-1:** Khi Screener gửi câu hỏi → status `AWAITING_SCREENER`, lưu `screener_sent_at`, `deadline`
  (mặc định +72h, cấu hình được). Lần chạy pipeline kết thúc (không spin). CV chỉ là dòng DB ở trạng thái chờ;
  **không chiếm CPU; không làm nghẽn CV khác**.
- **FR-SCR-2 (resume theo sự kiện):** Khi ứng viên nộp form → webhook/endpoint nạp lại state, bơm câu trả lời,
  **resume** pipeline từ điểm dừng → GATE MỜI. (Kỹ thuật: LangGraph `interrupt` + Postgres checkpointer.)
- **FR-SCR-3 (nhắc):** +24h chưa phản hồi (cấu hình được) → gửi **một** email nhắc → tiếp tục chờ.
- **FR-SCR-4 (timeout):** quá `deadline` → job quét định kỳ resume với `no_response` → human_review. **KHÔNG
  auto-loại vì không phản hồi** (có thể là ứng viên giỏi lỡ email).
- **FR-SCR-5 (trả lời trễ):** nếu Application vẫn ở human_review → đính câu trả lời trễ vào ReviewCard. Nếu đã
  ở trạng thái cuối (đã loại/đóng) → ghi log, không mở lại (hoặc auto-reply "vòng xét đã kết thúc").
- **FR-SCR-6 (bộ câu hỏi):** câu hỏi **cố định**, cấu hình theo JD. LLM chỉ diễn đạt + chuẩn hóa câu trả lời +
  hỏi lại **tối đa 1 lần** khi mơ hồ. KHÔNG trò chuyện tự do (đảm bảo công bằng + kiểm toán + an toàn pháp lý).

---

## 11. human_review + ReviewCard

- **FR-HR-1:** Mọi ca vào human_review phải kèm **ReviewCard** để HR quyết nhanh, KHÔNG chỉ đánh dấu "cần review".
- **ReviewCard gồm:** tóm tắt ứng viên (tên, kỹ năng, kinh nghiệm nổi bật); điểm tổng + phân rã theo tiêu chí;
  yêu cầu JD đạt/thiếu; `escalation_reason` cụ thể (vd "điểm 62/100 sát ngưỡng 60", "thiếu kinh nghiệm X",
  "CV parse một phần", "không phản hồi screener sau 72h"); đề xuất của hệ thống; nút Duyệt/Từ chối + ô ghi chú.
- **FR-HR-2 (web):** thẻ đầy đủ + mở xem CV gốc + toàn bộ agent trace.
- **FR-HR-3 (điện thoại — PWA):** giao diện rút gọn, responsive (tóm tắt + điểm + lý do + 2 nút) để duyệt
  nhanh. Thông báo: badge số ca chờ hiển thị trong app. (Web push đẩy thật: xem §17.)
- **FR-HR-4 (delegate):** HR duyệt → giao cho `scheduler` thực thi (gửi thư mời + đặt lịch). HR từ chối →
  `scheduler` gửi thư từ chối. Giai đoạn đầu HR KHÔNG tự thao tác thủ công.
- **FR-HR-5:** mọi quyết định HR ghi vào `audit_log` (ai, lúc nào, duyệt/từ chối, ghi chú).

---

## 12. Yêu cầu chức năng (FR)

### 12.1 HR

- FR-HR-JD-1: tạo/sửa/đóng JD; JD được embedding vào Qdrant khi tạo.
- FR-HR-DASH-1: dashboard giám sát pipeline thời gian thực (trạng thái từng CV, agent trace, hàng đợi).
- FR-HR-LIST-1: danh sách ứng viên + bộ lọc theo trạng thái (đang chạy / chờ ứng viên / pending review / passed / rejected).
- FR-HR-DETAIL-1: chi tiết một CV (dữ liệu đã parse, điểm + phân rã, agent trace, audit log).
- FR-HR-REVIEW-1: hàng đợi human_review với ReviewCard; duyệt/từ chối.
- FR-HR-GATE-1: bật/tắt hai gate (toàn hệ thống và/hoặc theo JD).
- FR-HR-ANALYTICS-1: thống kê (số CV, tỉ lệ passed/rejected/pending, mẫu case lạ — vòng học, phase sau).

### 12.2 Ứng viên

- FR-AP-1: xem danh sách JD đang mở.
- FR-AP-2: chọn JD và nộp CV (PDF/DOCX) + email; không cần đăng nhập.
- FR-AP-3: nhận email Screener + trả lời qua magic-link form (cấu trúc).
- FR-AP-4: nhận email kết quả (mời/từ chối).
- FR-AP-5 (tùy chọn): tra cứu trạng thái đơn qua link.

### 12.3 Pipeline / Agent

- FR-PIPE-1: mỗi CV một pipeline độc lập, chạy song song.
- FR-PIPE-2: thứ tự cố định `parser → ranker → screener → scheduler` + human_review có điều kiện.
- FR-PIPE-3: mỗi agent ghi confidence + uncertainty_flags vào state; routing dựa trên đó (§9, §10).
- FR-PIPE-4: mọi bước agent ghi `audit_log`.

### 12.4 Thông báo

- FR-NOTI-1: email tới ứng viên (xác nhận nộp, câu hỏi Screener, nhắc, kết quả).
- FR-NOTI-2: badge số ca chờ trong app (web push đẩy thật: xem §17) tới HR khi có ca cần review.

---

## 13. Vòng đời CV (state machine)

```
SUBMITTED
  → PARSING → (parse_failed → PENDING_REVIEW[error])
  → RANKING → GATE RANK:
        đạt        → SCREENING
        rank thấp  → (auto-reject ON) REJECTED  |  (OFF) PENDING_REVIEW
        bất định   → PENDING_REVIEW
SCREENING
  → AWAITING_SCREENER  (suspend)
        trả lời    → (resume) → GATE MỜI
        +24h       → REMINDED → (vẫn AWAITING)
        timeout    → PENDING_REVIEW[no_response]
  GATE MỜI:
        ổn + auto-invite ON → SCHEDULING
        OFF / có cờ         → PENDING_REVIEW
SCHEDULING → INTERVIEW_SCHEDULED        (passed)
PENDING_REVIEW (HR quyết):
        duyệt   → SCHEDULING → INTERVIEW_SCHEDULED
        từ chối → REJECTED
```

**Ba rổ dashboard:** đang xử lý (`SUBMITTED..RANKING`, `SCREENING`, `AWAITING_SCREENER`, `SCHEDULING`);
chờ HR (`PENDING_REVIEW`); kết thúc (`INTERVIEW_SCHEDULED`, `REJECTED`). Lỗi kỹ thuật vào `PENDING_REVIEW`
nhưng gắn nhãn `[error]` để phân biệt với "ứng viên không đạt".

---

## 14. Web (desktop) vs Điện thoại (PWA)

| Chức năng                             | Web HR | Điện thoại (PWA, HR) | Web công khai |
| ------------------------------------- | ------ | -------------------- | ------------- |
| Nộp CV                                | —      | —                    | ✅            |
| Xem danh sách JD                      | ✅     | —                    | ✅            |
| Quản lý JD                            | ✅     | ❌                   | —             |
| Xem danh sách CV + lọc                | ✅     | ✅ (xem)             | —             |
| Chi tiết CV (parse, điểm, trace)      | ✅     | ✅ rút gọn           | —             |
| Duyệt/từ chối human_review            | ✅     | ✅ nhanh + push      | —             |
| Dashboard giám sát agent (live trace) | ✅     | ❌                   | —             |
| Bật/tắt gate                          | ✅     | ❌                   | —             |
| Thống kê / vòng học                   | ✅     | ❌                   | —             |

> Chỉ một app web (Next.js), responsive; cột "Điện thoại" là ưu tiên hiển thị trên màn hình nhỏ,
> không phải app riêng.

---

## 15. Yêu cầu phi chức năng (NFR)

- NFR-1 (đồng thời): xử lý nhiều CV song song; một CV chờ Screener không làm nghẽn CV khác.
- NFR-2 (bền vững): state pipeline lưu bền (Postgres checkpointer) để chịu suspend/resume dài ngày + khởi động lại.
- NFR-3 (kiểm toán): mọi hành động agent và quyết định HR ghi `audit_log` đầy đủ, truy vết được.
- NFR-4 (an toàn dữ liệu): CV chứa dữ liệu cá nhân; demo dùng dữ liệu tổng hợp/ẩn danh; có phương án chạy
  local (không đẩy dữ liệu ra cloud nước ngoài) khi cần.
- NFR-5 (chống lạm dụng): chống prompt injection từ nội dung CV / câu trả lời ứng viên (phase sau).
- NFR-6 (observability): giám sát chi phí token, độ trễ, tỉ lệ lỗi (Langfuse — phase sau).
- NFR-7 (chi phí): ưu tiên dịch vụ managed free-tier; lường trần free-tier khi test tải.
- NFR-8 (cấu hình): ngưỡng confidence, mốc nhắc/timeout, bộ câu hỏi Screener, hai gate — đều cấu hình được.

---

## 16. Mô hình dữ liệu (thực thể chính)

- **HRUser:** id, email, password_hash, role.
- **JobPosting (JD):** id, title, description, requirements, rubric (tiêu chí + trọng số), screener_questions,
  gate_config (auto_reject, auto_invite), status, embedding_ref (Qdrant), created_at.
- **Application (Candidate):** id, job_id, applicant_email, cv_file_ref, parsed_data (JSONB), score,
  score_breakdown (JSONB), status, confidence, uncertainty_flags (JSONB), escalation_reason, timestamps.
- **ScreeningSession:** id, application_id, questions, answers (JSONB), magic_link_token, sent_at, deadline,
  reminded_at, responded_at, status.
- **ReviewCase:** id, application_id, review_card (JSONB: summary, score, reason, recommendation), hr_decision,
  hr_note, decided_by, decided_at.
- **AuditLog:** id, application_id, node, action, confidence, uncertainty_flags (JSONB), escalation_reason,
  detail (JSONB), created_at.
- **Vector (Qdrant):** embedding JD (và CV khi cần) phục vụ đối sánh.

---

## 17. Ngoài phạm vi / Tương lai

- Luồng HR đặt lịch thủ công (không delegate cho scheduler).
- Kênh Zalo OA / web chat real-time cho Screener (email + form là chính).
- Web push notification xuyên nền tảng cho HR (đặc biệt trên iOS, vốn hạn chế PWA push).
- Vòng học bán tự động đầy đủ (gom mẫu → đề xuất → HR duyệt) — thiết kế đã chừa, triển khai sau.
- Đa ngôn ngữ nâng cao, đa JD song song cho một ứng viên, A/B testing rubric.
- LLM đề xuất rubric từ JD, HR duyệt/chỉnh (bán tự động, trụ cột 4)

---

## 18. Giả định & Câu hỏi mở

- Giả định: ứng viên có email hợp lệ; CV ở PDF/DOCX; mỗi lần nộp gắn đúng một JD.
- Mở: ngưỡng confidence cụ thể (tinh chỉnh thực nghiệm — Chương 4); mốc nhắc/timeout tối ưu; có nên auto-reject
  mặc định cho một số JD khối lượng lớn (hiện mặc định TẮT).
