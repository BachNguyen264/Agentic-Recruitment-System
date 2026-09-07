# PRD — Hệ thống Tuyển dụng Tự trị sử dụng Multi-Agent AI

> **Tài liệu này là NGUỒN CHÂN LÝ của hệ thống.** Mọi quyết định triển khai phải đối chiếu với PRD này.
> Khi code và PRD mâu thuẫn → PRD đúng (hoặc cập nhật PRD trước rồi mới sửa code).
>
> Phiên bản: 1.2 · Phạm vi: đồ án tốt nghiệp (proof-of-concept hoàn chỉnh).

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
   chỉnh rubric/JD/prompt → HR duyệt mới áp dụng. Agent KHÔNG tự đổi control flow. (Hiện thực đầu tiên:
   _AI gợi ý rubric từ JD_ — AI đề xuất, HR duyệt/chỉnh; xem FR-HR-RUBRIC-1.)

> Đánh đổi cốt lõi: quyền tự trị ở tầng điều phối ĐỔI LẤY độ tin cậy/khả năng kiểm soát + chi phí thấp.

---

## 6. Kiến trúc tổng thể

- **Web (Next.js):** cổng công khai (xem JD, nộp CV, form Screener) + dashboard HR (giám sát, review, cấu hình).
- **Trên điện thoại:** web dạng PWA (cài lên màn hình chính) — HR xem CV + duyệt human_review nhanh.
  Một app web duy nhất, responsive; KHÔNG có codebase mobile riêng.
- **Backend (FastAPI + LangGraph):** pipeline đa tác tử; xử lý bất đồng bộ; suspend/resume cho Screener.
- **Hạ tầng managed:** Neon (Postgres), Qdrant Cloud (embedding JD–CV).
- **Tích hợp:** Email (gửi câu hỏi/thư mời/từ chối), tùy chọn Zalo OA; Google Calendar (đặt lịch).
- **Observability:** ĐÃ BỎ khỏi phạm vi — không có vai Super Admin nên dashboard ops không có khán giả.
  Giữ lại như hướng mở rộng trong báo cáo.

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
- **Rubric BẮT BUỘC:** JD phải có rubric mới được MỞ (nhận CV) — xem §12.1. Ranker do đó LUÔN có rubric để chấm, không bao giờ gặp rubric rỗng.
- **Tool tự trị (phase sau):** truy vấn vector, công cụ chấm điểm.

### 7.3 Screener (chạy SAU Ranker)

- **Đầu vào:** ứng viên đã qua ngưỡng rank.
- **TÙY CHỌN theo JD:** nếu JD KHÔNG có câu hỏi sàng lọc → BỎ QUA bước Screener (CV đạt đi thẳng human_review / gate auto-mời, không suspend). Chỉ JD CÓ câu hỏi mới kích hoạt Screener.
- **Việc:** gửi **bộ câu hỏi cố định** (cấu hình theo JD) qua **email + magic-link form** để thu thập thông
  tin hậu tuyển (lương kỳ vọng, thời gian nhận việc, xác nhận quan tâm, câu hỏi loại trừ do HR đặt). Sau khi
  nhận trả lời, chuẩn hóa thành dữ liệu có cấu trúc.
- **Bản chất:** thu thập thông tin có cấu trúc, BẤT ĐỒNG BỘ — KHÔNG phải chatbot tự do (xem §10).
- **confidence/cờ:** `no_response` khi quá hạn; cờ khi câu trả lời lộ vấn đề (lương quá cao, từ chối…).
- **Tool tự trị (phase sau):** LLM chỉ để (a) diễn đạt lời mời, (b) chuẩn hóa câu trả lời, (c) hỏi lại tối
  đa 1 lần khi mơ hồ. Bộ câu hỏi cố định, không cải biên.

### 7.4 Scheduler

- **Đầu vào:** quyết định "mời" hoặc "từ chối" (từ gate tự động hoặc từ HR duyệt).
- **Việc:** nếu mời → gửi **thư mời kèm link tự đặt lịch** (xem §10b) → `AWAITING_BOOKING`. Nếu từ chối → gửi
  thư từ chối. Là **điểm thực thi DUY NHẤT** cho mọi hành động gửi-email-tới-ứng-viên (mời, từ chối, xác nhận
  lịch, nhắc lịch).
- **KHÔNG tự chốt giờ** (không "push scheduling"): ứng viên chọn giờ (§10b). Lý do: đặt hộ giờ là hành động
  một chiều — ứng viên có thể bận/đã có việc/không đọc mail → slot bị khóa vô ích và tăng no-show.
- **Tool tự trị (phase sau):** chọn gửi email / tạo lịch / cả hai.

---

## 8. Luồng nghiệp vụ end-to-end

### 8.1 Thiết lập (HR) — luồng 2 bước

1a. **Tạo Tin tuyển dụng** (ứng viên thấy): tiêu đề, cấp bậc, lương, quyền lợi, loại việc, mô tả, yêu cầu (mô tả + yêu cầu là ô văn bản định dạng, dán được cả khối). Lưu → JD status `DRAFT`; hệ thống embedding JD → Qdrant.
1b. **Cấu hình sàng lọc** (nội bộ, trên JD đã lưu): nhập rubric (có nút **AI gợi ý** đọc JD → đề xuất tiêu chí + trọng số, HR chỉnh) + câu hỏi sàng lọc (tùy chọn). Gate bật/tắt ở **danh sách JD**.
1c. **MỞ JD** (`DRAFT/CLOSED → OPEN`) — **yêu cầu JD đã có rubric** (không có rubric không mở được; ranker vì thế luôn có tiêu chí). JD OPEN mới nhận CV.

### 8.2 Nộp (Ứng viên — web công khai)

2. Ứng viên xem danh sách JD đang mở, chọn một JD, nộp CV (chỉ cần email; không bắt đăng nhập).
   - Chưa có CV thì tải mẫu ở **kho CV mẫu** (§8.2b) rồi quay lại nộp — không rời khỏi luồng ứng tuyển.
3. Hệ thống lưu Application (status `SUBMITTED`), đẩy vào xử lý bất đồng bộ. Mỗi CV = một pipeline độc lập,
   chạy song song với các CV khác.

### 8.2b Kho CV mẫu (hỗ trợ ứng viên chưa có CV)

Rào cản thật ở đầu phễu: người muốn ứng tuyển nhưng **chưa có CV** thì rời trang, và hệ thống mất luôn ứng
viên đó trước khi pipeline kịp chạy. Kho mẫu dựng để giữ họ lại trong luồng.

- Trang **công khai** (không đăng nhập), liệt kê **9 mẫu CV theo nhóm ngành nghề**, mỗi mẫu có tên ngành và
  một dòng mô tả cho biết mẫu đó khác các mẫu khác ở chỗ nào.
- Mỗi mẫu có **ba hành động, ba việc KHÁC nhau** — không phải ba cách tải cùng một thứ:
  1. **Xem trước** — mở bản `.pdf` ngay trong tab để NHÌN bố cục. Chọn CV mẫu là quyết định **thị giác**: tên
     ngành + một dòng mô tả không cho biết mẫu trông ra sao. Không có bước này thì ứng viên phải tải `.docx`
     rồi mở Word/Docs chỉ để nhìn, thấy không hợp lại quay ra tải mẫu khác. **Không ép tải bản `.pdf`** — PDF
     không sửa được (phần mềm sửa PDF thường mất phí và ít phổ biến), nên tải nó về máy là ngõ cụt.
  2. **Tải .docx** — hành động chính: bản để điền (Word, Google Docs, WPS).
  3. **Sửa trên Google Docs** — link dạng *Tạo bản sao*: ứng viên bấm là có ngay bản riêng trên Drive, sửa
     online trên mọi thiết bị, tự lưu, tự xuất PDF. Chi phí xây dựng = 0 vì Google lo phần soạn thảo; hệ
     thống chỉ giữ đường link. Mẫu nào chưa có link thì **không hiện nút** (không để nút chết).
- Ứng viên điền xong lưu lại dạng `.pdf` hoặc `.docx` rồi nộp — hệ thống nhận cả hai (FR-AP-2).
- Lối vào: dòng *"Chưa có CV? Tải CV mẫu về ngay"* trên trang ứng tuyển.
- **Tệp tĩnh, KHÔNG qua backend** — mẫu CV là tài liệu công khai, khác hẳn CV ứng viên nộp (lưu ở bucket
  PRIVATE, chỉ HR stream được — NFR-4). Trang không gọi API nào nên cũng không tiêu hạn mức chống lạm dụng
  của đường công khai.

### 8.3 Pipeline

4. `parser`: CV → JSON. (lỗi → `parse_failed` → human_review)
5. `ranker`: đối sánh JD + chấm điểm. Sau Ranker là **GATE RANK**:
   - **đạt ngưỡng** → tiếp `screener`.
   - **rank thấp** → _gate auto-từ-chối_: BẬT → tự từ chối (scheduler gửi thư) → `REJECTED`; TẮT → `human_review`.
   - **bất định** (`weak_match`/điểm sát ngưỡng) → **luôn** `human_review` (gate no-op).
6. `screener`: **nếu JD KHÔNG có câu hỏi → BỎ QUA bước này**, đi thẳng tới GATE MỜI (không suspend). Nếu JD CÓ câu hỏi → gửi email + magic-link form → **pipeline SUSPEND** (lưu state, không chiếm tài nguyên; xem §10).
   Sau khi có kết quả (trả lời / timeout / bỏ qua), tới **GATE MỜI**:
   - **ổn + auto-mời BẬT** → `scheduler` gửi thư mời + đặt lịch → `INTERVIEW_SCHEDULED`.
   - **auto-mời TẮT, hoặc có cờ (`no_response`…)** → `human_review`.
7. `scheduler`: thực thi hành động cuối (mời/từ chối).

### 8.4 human_review (xem §11)

8. CV vào human_review **kèm ReviewCard** (tóm tắt + điểm + lý do). HR quyết:
   - **duyệt** → delegate cho `scheduler` tự gửi thư mời + đặt lịch → `INTERVIEW_SCHEDULED`.
   - **từ chối** → `scheduler` gửi thư từ chối → `REJECTED`.

### 8.5 Kết thúc

9. Email báo kết quả cho ứng viên. **Từ chối** → `REJECTED` (cuối). **Mời** → thư mời kèm **link tự đặt lịch**
   → `AWAITING_BOOKING`; ứng viên chọn giờ (§10b) → `INTERVIEW_SCHEDULED` (cuối) + email xác nhận kèm `.ics`.
10. Nhắc trước buổi phỏng vấn (mặc định 24h) để giảm no-show.

---

## 9. Hai Gate cấu hình

| Gate             | Vị trí                          | BẬT (ON)                                     | TẮT (OFF — mặc định an toàn)                |
| ---------------- | ------------------------------- | -------------------------------------------- | ------------------------------------------- |
| **auto-từ-chối** | sau Ranker, ca rank thấp        | tự từ chối + gửi email                       | mọi ca từ chối → human_review               |
| **auto-mời**     | sau Screener, trước gửi thư mời | tự gửi thư mời + **link tự đặt lịch** (§10b) | mọi thư mời → human_review (HR duyệt trước) |

- **FR-GATE-1:** Gate là cấu hình của HR, lưu trong DB; có thể đặt mức toàn hệ thống hoặc theo từng JD.
- **FR-GATE-2 (BẤT BIẾN):** Gate CHỈ can thiệp ca agent **tự tin**. Ca bất định/thiếu tự tin (`parse_failed`,
  `weak_match`, `no_response`, confidence < ngưỡng) → gate **no-op**, LUÔN vào human_review, bất kể gate.
- **FR-GATE-3:** Mặc định cả hai gate TẮT (an toàn nhất).

---

## 10. Screener bất đồng bộ (suspend / resume)

Nguyên lý: **không giữ pipeline "đang chạy" để đợi con người.** Pipeline tạm dừng, lưu state bền vững, thức
dậy theo sự kiện hoặc theo hạn.

- **FR-SCR-0 (tùy chọn):** Screener chỉ chạy nếu JD CÓ câu hỏi sàng lọc. JD rỗng câu hỏi → BỎ QUA Screener (không suspend); CV đạt đi thẳng human_review / gate auto-mời. (Cũng tránh case suspend-với-form-rỗng.)
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

## 10b. Đặt lịch phỏng vấn — ứng viên tự chọn (pull scheduling)

> **Nguyên tắc:** hệ thống KHÔNG chốt hộ giờ. Ứng viên chủ động chọn → linh hoạt hơn, giảm no-show, và HR
> không phải xác nhận lại. Đây là phản hồi chủ động **lần 2** của ứng viên (lần 1 = Screener) — tín hiệu
> thực sự quan tâm vị trí.

### 10b.1 Luồng

1. Có quyết định **mời** (gate auto-mời hoặc HR duyệt) → Scheduler gửi **thư mời + link đặt lịch**
   (token riêng, KHÁC token screener) → status `AWAITING_BOOKING`.
2. Ứng viên mở link → **lúc này mới sinh slot** (lazy) từ trạng thái lịch **hiện tại** → hiện **5 khung giờ**
   → **giữ chỗ (HELD)** 5 slot đó trong **10 phút**.
3. Ứng viên chọn 1 slot → xác nhận → `INTERVIEW_SCHEDULED` + email xác nhận kèm **`.ics`**; 4 slot còn lại
   nhả ngay.
4. Nhắc trước buổi phỏng vấn **24h** (email + `.ics`).

### 10b.2 Vì sao sinh slot LƯỜI (khi click), không phải khi gửi mail

Nếu giữ chỗ ngay lúc gửi mail, slot bị khóa cho người **có thể không bao giờ mở mail** → lãng phí lịch trống
của người thực sự muốn phỏng vấn. Sinh lười ⇒ chỉ tiêu tài nguyên cho người **thực sự có ý định đặt lịch**.
Hệ quả phụ (quan trọng): **link không bao giờ ôi** — mỗi lần mở là danh sách tươi → **không cần "link thứ hai"**
kiểu resend-OTP, chỉ cần MỘT link.

### 10b.3 Hai đồng hồ (đừng nhầm)

| Đồng hồ            | Thời hạn (env)                   | Ý nghĩa                                     |
| ------------------ | -------------------------------- | ------------------------------------------- |
| **Link đặt lịch**  | 72h (`BOOKING_LINK_TTL_HOURS`)   | Ứng viên có bao lâu để **bắt đầu** đặt lịch |
| **Giữ chỗ (HELD)** | 5 phút (`BOOKING_HOLD_MINUTES`)  | Slot bị giữ trong **một phiên** chọn        |

Hold ngắn KHÔNG trừng phạt ứng viên: hết hold chỉ cần tải lại → danh sách mới ngay (nhờ sinh lười).
Token đặt lịch **KHÔNG one-time** (khác screener): mở lại được nhiều lần tới khi đặt xong hoặc link hết hạn.

### 10b.4 Chọn slot đề xuất

- **5 slot**, trộn: 2–3 slot **sớm nhất** + 2–3 slot **rải ngày/buổi khác** (sáng lẫn chiều).
- Lý do chính: cho ứng viên **lựa chọn thật** (5 slot cùng một buổi sáng thì người bận sáng đó vô dụng).
  Lý do phụ: phân tán tự nhiên, giảm tranh chấp.

### 10b.5 Chống đặt trùng (race condition)

- **HELD = khuyến nghị · BOOKED = thẩm quyền.**
- Sinh danh sách **loại trừ** slot `BOOKED` **hoặc** (`HELD` và chưa hết hạn) ⇒ hai ứng viên mở cùng lúc
  **thấy danh sách khác nhau** ⇒ xung đột gần như biến mất ngay từ khâu sinh.
- Xác nhận = transaction lật `HELD → BOOKED`, chặn cuối bằng **unique constraint trên `start_at`**
  (chỉ áp cho `BOOKED`) — single-tenant, mỗi mốc giờ chỉ một buổi.
- Thua race → **409** + tự làm mới danh sách ("giờ này vừa có người đặt, mời chọn giờ khác").
- **KHÔNG cần cron dọn hold**: truy vấn đã lọc theo `hold_expires_at > now()`.

### 10b.6 Không phản hồi / hủy / đổi

- Link hết hạn (72h) mà chưa đặt → **nhắc một lần** khi còn `BOOKING_REMINDER_HOURS` nữa là hết hạn, hết
  hạn → `PENDING_REVIEW` gắn cờ `booking_no_response` (**KHÔNG auto-reject** — im lặng ≠ từ chối, đối xứng
  FR-SCR-3). Dùng sweep loop sẵn có (§10).
- **Nhắc trước buổi phỏng vấn** `BOOKING_INTERVIEW_REMINDER_HOURS` (mặc định 24h): email + `.ics`, **một
  lần** (idempotent qua mốc `reminder_sent_at`).
- **Hủy (ứng viên):** thư xác nhận lịch kèm **liên kết hủy** — chính token đặt lịch, không phát token mới.
  Hủy → slot **nhả ngay** + HR được báo, rồi:
  - liên kết **còn hạn** → về `AWAITING_BOOKING`, ứng viên **tự chọn lại giờ khác trong hạn CŨ**
    (**KHÔNG gia hạn TTL** — gia hạn là mở đường cho vòng lặp hủy-đặt-hủy không điểm dừng);
  - liên kết **đã hết hạn** → `PENDING_REVIEW` gắn cờ `booking_cancelled`, HR xử tiếp.

  Lý do cho nhánh đầu: người bận đúng khung giờ đã chọn thì việc họ cần là **một giờ khác**, không phải
  một hàng chờ HR. Ứng viên tự xử lý được thì hệ thống không kéo con người vào.
- **Hủy/đổi (HR):** dashboard có **Hủy lịch** (nhả slot + báo ứng viên → `PENDING_REVIEW`) và **Gửi lại
  link đặt lịch** (phát phiên MỚI, TTL mới → `AWAITING_BOOKING`). Hai nút này **ghép lại chính là "đổi
  lịch"** — không có luồng dời-lịch riêng.
- **Hết khung giờ:** ứng viên mở link mà kho khung giờ đã cạn → ghi nhận `no_slots_at` + **nhãn dashboard
  riêng** cho HR ("cần mở thêm lịch"), KHÔNG dùng nhãn "chờ ứng viên chọn lịch" — lỗi ở hệ thống thì
  đừng hiển thị như thể ứng viên đang chậm trễ.

### 10b.7 Cấu hình khả dụng (toàn cục)

Giờ làm việc, nghỉ trưa, độ dài buổi PV, đệm giữa hai buổi, lead-time tối thiểu (không đặt sớm hơn N giờ),
số buổi tối đa/ngày (mặc định 6), cửa sổ đặt lịch (mặc định 21 ngày tới). **Toàn hệ thống** (không theo từng
JD) — phù hợp single-tenant. Múi giờ chốt tường minh **Asia/Ho_Chi_Minh**.

**Sức chứa là ràng buộc thật, không phải con số trang trí:** kho khung giờ = `MAX_PER_DAY` × số ngày làm
việc trong cửa sổ, còn mỗi lượt ứng viên mở link giữ `SLOTS_OFFERED` khung trong `HOLD_MINUTES`. Đặt quá
thấp thì chỉ vài ứng viên xem cùng lúc là người tiếp theo thấy trang trống (đo thật ở SCH-2: 4×14 ngày ≈ 36
khung ⇒ cạn ở ~7 người xem đồng thời).

### 10b.8 Seam tích hợp lịch ngoài

Tạo sự kiện lịch đi qua seam `CalendarProvider` (`create_event/cancel_event`). Mặc định `IcsProvider`
(đính kèm `.ics` vào email — không cần OAuth). **Chừa đường** cho `GoogleCalendarProvider` (§17) mà không
phải sửa nghiệp vụ.

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

- FR-HR-JD-1: **Luồng tạo JD 2 bước** — (a) tạo _Tin tuyển dụng_ (tiêu đề, cấp bậc, lương, quyền lợi, loại việc, mô tả + yêu cầu dạng văn bản định dạng dán-được) → lưu `DRAFT` + embedding Qdrant; (b) _Cấu hình sàng lọc_ trên JD đã lưu (rubric + câu hỏi sàng lọc). Sửa mô tả/tiêu đề/yêu cầu → re-embed.
- FR-HR-JD-2: **Rubric bắt buộc để MỞ** — JD tạo được không cần rubric (DRAFT), nhưng phải có rubric mới `OPEN` (nhận CV). Câu hỏi sàng lọc **tùy chọn** (rỗng → pipeline bỏ qua Screener).
- FR-HR-RUBRIC-1 (**AI gợi ý rubric** — bước đầu của trụ cột 4): nút on-demand, đọc JD đã lưu (tiêu đề+mô tả+yêu cầu, và cấp bậc làm ngữ cảnh) → LLM đề xuất _tiêu chí + trọng số_ (structured output) → HR chỉnh/lưu. **Cap retry 3 lần/JD**, `rubric_suggestion_count` neo trên JD; **reset khi nội dung JD (tiêu đề/mô tả/yêu cầu) đổi** (dùng chung phép so sánh với re-embed). Auth-gated (require_hr).
- FR-HR-JD-3: **Trạng thái JD** `DRAFT → OPEN → CLOSED` (đóng/tạm dừng, giữ dữ liệu) và **ARCHIVED** (lưu trữ, ẩn khỏi danh sách, giữ dữ liệu + kiểm toán, khôi phục được). **KHÔNG hard-delete JD** (bảo toàn hồ sơ ứng viên + nhật ký kiểm toán); xóa data test chỉ qua script dev.
- FR-HR-JD-4: Gate (auto_reject/auto_invite) — toggle theo JD, truy cập nhanh **trên danh sách JD**.
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
- FR-AP-6: **xem trước** rồi tải **CV mẫu** theo nhóm ngành nghề (§8.2b), không cần đăng nhập — bản tải về
  là `.docx` (sửa được); bản `.pdf` chỉ dùng để xem, KHÔNG ép tải.
- FR-AP-7: từ trang ứng tuyển đi tới kho CV mẫu **mà không mất phần hồ sơ đang điền dở**.

### 12.3 Pipeline / Agent

- FR-PIPE-1: mỗi CV một pipeline độc lập, chạy song song.
- FR-PIPE-2: thứ tự cố định `parser → ranker → screener → scheduler` + human_review có điều kiện.
- FR-PIPE-3: mỗi agent ghi confidence + uncertainty_flags vào state; routing dựa trên đó (§9, §10).
- FR-PIPE-4: mọi bước agent ghi `audit_log`.
- **FR-PWA-1 (PWA rút gọn + offline):** khi chạy ở chế độ đã cài, PWA chỉ hiển thị Đăng nhập, Ứng
  viên (danh sách + chi tiết rút gọn, CHỈ ĐỌC) và Hàng đợi review; các màn còn lại theo cột "Điện
  thoại" của §14 bị ẩn khỏi điều hướng VÀ chặn ở đường dẫn (đưa về hàng đợi kèm giải thích). Mất kết
  nối thì hiện trang "Mất kết nối" có thương hiệu, KHÔNG hiện dữ liệu nghiệp vụ đã cache (NFR-4).

### 12.4 Thông báo

- FR-NOTI-1: email tới ứng viên (xác nhận nộp, câu hỏi Screener, nhắc, kết quả, **link đặt lịch, xác nhận
  lịch kèm `.ics`, nhắc trước buổi PV**).
- FR-BOOK-1: thư mời kèm **link tự đặt lịch**; ứng viên mở link → **mới** sinh 5 slot từ trạng thái hiện tại
  - giữ chỗ 10 phút (§10b.2).
- FR-BOOK-2: chọn slot → transaction `HELD → BOOKED` + unique constraint `start_at`; thua race → 409 + làm
  mới danh sách (§10b.5).
- FR-BOOK-3: token đặt lịch **KHÔNG one-time**, TTL 72h; hết hạn chưa đặt → nhắc 1 lần → `PENDING_REVIEW`
  cờ `booking_no_response`, **KHÔNG auto-reject**.
- FR-BOOK-4: nhắc trước buổi PV 24h (email + `.ics`, một lần); hủy (chính token đặt lịch, link trong email
  xác nhận) → nhả slot NGAY + báo HR → `AWAITING_BOOKING` nếu link còn hạn (KHÔNG gia hạn TTL), else
  `PENDING_REVIEW[booking_cancelled]`; HR **hủy lịch** + **gửi lại link** từ dashboard (= "đổi lịch").
- FR-BOOK-6: hết khung giờ trống khi ứng viên mở link → ghi `no_slots_at` + nhãn dashboard RIÊNG cho HR
  ("cần mở thêm lịch"), không hiển thị như thể ứng viên đang chậm.
- FR-BOOK-5: cấu hình khả dụng **toàn cục** qua env (§10b.7); mọi mốc thời gian theo `Asia/Ho_Chi_Minh`.
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
        +24h       → gửi thư nhắc (ghi mốc reminded_at) → (vẫn AWAITING_SCREENER)
        timeout    → PENDING_REVIEW[no_response]
  GATE MỜI:
        ổn + auto-invite ON → SCHEDULING
        OFF / có cờ         → PENDING_REVIEW
SCHEDULING → (gửi thư mời + link đặt lịch) → AWAITING_BOOKING
        chọn slot  → INTERVIEW_SCHEDULED   (passed; + email xác nhận .ics)
        +nhắc      → (vẫn AWAITING_BOOKING)
        hết hạn    → PENDING_REVIEW[booking_no_response]   (KHÔNG auto-reject)
INTERVIEW_SCHEDULED:
        +nhắc 24h trước buổi PV → (vẫn INTERVIEW_SCHEDULED)
        ứng viên hủy → slot nhả NGAY, rồi:
              link còn hạn → AWAITING_BOOKING (chọn lại, KHÔNG gia hạn TTL)
              link hết hạn → PENDING_REVIEW[booking_cancelled]
        HR hủy lịch  → PENDING_REVIEW (slot nhả + email báo ứng viên)
        HR gửi lại link → AWAITING_BOOKING (phiên MỚI, TTL mới)
PENDING_REVIEW (HR quyết):
        duyệt   → SCHEDULING → INTERVIEW_SCHEDULED
        từ chối → REJECTED
```

**Ba rổ dashboard:** đang xử lý (`SUBMITTED..RANKING`, `SCREENING`, `AWAITING_SCREENER`, `SCHEDULING`,
`AWAITING_BOOKING`);
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
| Kiểm tra CV                           | ✅     | ❌                   | —             |
| Huỷ / gửi lại link đặt lịch           | ✅     | ❌                   | —             |

> Chỉ một app web (Next.js), responsive — KHÔNG có codebase mobile riêng (§6). Cột "Điện thoại" áp
> dụng khi app chạy ở **chế độ đã cài (standalone)**: mở cùng địa chỉ bằng trình duyệt trên điện
> thoại vẫn thấy ĐỦ mọi màn. Chọn standalone thay vì theo bề rộng màn hình để một cửa sổ desktop bị
> thu nhỏ không bị cắt mất chức năng.

---

## 15. Yêu cầu phi chức năng (NFR)

- NFR-1 (đồng thời): xử lý nhiều CV song song; một CV chờ Screener không làm nghẽn CV khác.
- NFR-2 (bền vững): state pipeline lưu bền (Postgres checkpointer) để chịu suspend/resume dài ngày + khởi động lại.
- NFR-3 (kiểm toán): mọi hành động agent và quyết định HR ghi `audit_log` đầy đủ, truy vết được.
- NFR-4 (an toàn dữ liệu): CV chứa dữ liệu cá nhân; demo dùng dữ liệu tổng hợp/ẩn danh; có phương án chạy
  local (không đẩy dữ liệu ra cloud nước ngoài) khi cần. **Ở tầng service worker / CacheStorage**, PWA
  không lưu dữ liệu nghiệp vụ xuống đĩa thiết bị: service worker chỉ cache tài nguyên tĩnh có
  content-hash và trang "Mất kết nối"; tuyệt đối không cache phản hồi API, không cache trang mang token
  (`/screening/{token}`, `/booking/{token}`). Bảo vệ ở tầng HTTP cache của trình duyệt cho `/api/*`
  (`Cache-Control: no-store`) CHƯA có — còn để ngỏ.
- NFR-5 (chống lạm dụng): chống prompt injection từ nội dung CV / câu trả lời ứng viên (phase sau).
- NFR-6 (observability): giám sát chi phí token, độ trễ, tỉ lệ lỗi — ĐÃ BỎ khỏi phạm vi (xem §6).
  Thay thế một phần: `audit_log` ghi mọi bước agent + quyết định HR, đọc được ở màn Cấu hình hệ thống.
- NFR-7 (chi phí): ưu tiên dịch vụ managed free-tier; lường trần free-tier khi test tải.
- NFR-8 (cấu hình): ngưỡng confidence, mốc nhắc/timeout, bộ câu hỏi Screener, hai gate — đều cấu hình được.

---

## 16. Mô hình dữ liệu (thực thể chính)

- **InterviewBooking:** id, application_id, start_at, end_at, `status` (`HELD`/`BOOKED`/`CANCELLED`),
  `hold_expires_at`, created_at. **Unique constraint trên `start_at` khi `status='BOOKED'`** (chống đặt trùng).
- **BookingSession:** id, application_id, token (urlsafe, **không one-time**), expires_at, reminded_at,
  booked_at, cancelled_at.

- **HRUser:** id, email, password_hash, role.
- **JobPosting (JD):** id, title, **level** (cấp bậc), **salary** (min/max/currency/negotiable), **benefits**,
  **employment_type**, description (văn bản định dạng), requirements (văn bản định dạng), rubric (tiêu chí + trọng số),
  screener_questions (tùy chọn), gate_config (auto_reject, auto_invite), **rubric_suggestion_count** (cap AI gợi ý),
  status (`DRAFT`/`OPEN`/`CLOSED`/`ARCHIVED`), embedding_ref (Qdrant), created_at.
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
- **Tích hợp Google Calendar** (`GoogleCalendarProvider` qua seam §10b.8): đọc lịch bận của người phỏng vấn
  - tạo event thật. Hiện dùng `.ics` đính kèm email (không cần OAuth).
- Lịch bận/ngày nghỉ theo từng người phỏng vấn; khả dụng theo từng JD (hiện toàn cục).
- Hard-delete / purge dữ liệu có kiểm soát (vd nghĩa vụ xóa dữ liệu cá nhân) — hiện chỉ soft-delete (ARCHIVED).
- (Đã đưa vào phạm vi active: _AI gợi ý rubric từ JD_ — xem FR-HR-RUBRIC-1, §12.1.)

---

## 18. Giả định & Câu hỏi mở

- Giả định: ứng viên có email hợp lệ; CV ở PDF/DOCX; mỗi lần nộp gắn đúng một JD.
- Mở: ngưỡng confidence cụ thể (tinh chỉnh thực nghiệm — Chương 4); mốc nhắc/timeout tối ưu; có nên auto-reject
  mặc định cho một số JD khối lượng lớn (hiện mặc định TẮT).
