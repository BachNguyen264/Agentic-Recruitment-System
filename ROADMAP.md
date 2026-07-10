# ROADMAP — Hệ thống Tuyển dụng Tự trị (bản đồ các lát triển khai)

> **Bản chất:** bản đồ SỐNG để không lạc — chia công việc còn lại thành từng lát mỏng, có thứ tự + lý do.
> Không phải hợp đồng: lát có thể tách/đổi thứ tự khi phát hiện điều mới (như bug parser rớt TOEIC đã dạy).
> Nguồn chân lý vẫn là **`PRD.md`**. Mỗi lát = một plan one-shot riêng khi tới lượt.
>
> Nguyên tắc xuyên suốt: lát mỏng, backend trước UI ngay sau, verify từng lát, lọc mọi ý qua PRD chống phình.

---

## ✅ ĐÃ XONG

- Scaffold (7 phase) · PWA migration (bỏ React Native).
- **01** Parser thật (gpt-4.1-mini) · **01b** UI upload CV (/cv-check) · **01c** certificates/languages/awards/other + benchmark.
- **02a** JD + embedding Qdrant · **02b** Ranker thật (Hướng A, chọn **gpt-5-mini** effort=low).
- **03a** Màn HR: danh sách ứng viên + chi tiết điểm (chỉ đọc).
- Dọn dẹp: xóa data demo + gỡ Run demo.

---

## 🟡 GIAI ĐOẠN 1 — Hoàn thiện vòng lặp HITL cốt lõi (ĐANG LÀM)

> Mục tiêu: pipeline QUYẾT ĐỊNH được end-to-end (CV → chấm → gate/HR → email ra). Đây là lõi + câu chuyện đồ án.

- **03b — human_review THẬT** (PRD §11) · _TIẾP THEO_
  ReviewCard (tái dùng `ScoreBreakdown` từ 03a: tóm tắt + điểm + lý do leo thang) + nút Duyệt/Từ chối →
  delegate `scheduler`. Biến điểm đến human_review từ stub thành khâu thật. Ghi audit_log quyết định HR.
- **03c — Gate rank** (PRD §9) · _phụ thuộc: ranker (xong)_
  Auto-từ-chối dùng `score` + `gate_config` của JD: bật → điểm thấp thành REJECTED (+ delegate scheduler gửi thư
  từ chối); tắt → mọi từ chối vào human_review. Ca bất định LUÔN vào human_review (gate no-op). + UI bật/tắt gate.
- **04 — Scheduler THẬT (email)** (PRD §7.4) · _phụ thuộc: 03b (delegate)_
  Điểm phát email DUY NHẤT: gửi thư mời / thư từ chối qua email provider (SMTP/Resend/SendGrid free). Calendar có
  thể đơn giản hóa/để sau. Biến "duyệt/từ chối" ở 03b/03c thành email thật gửi đi.
  → **Mốc:** vòng lặp lõi chạy end-to-end thật.

---

## 🔵 GIAI ĐOẠN 2 — Cổng vào thật (đăng JD + nộp CV công khai + storage)

> Mục tiêu: ứng viên nộp CV thật cho JD thật; HR quản lý JD qua web; file lưu bền. (Hiện tạo qua /docs + local disk.)

- **05 — JD management UI** (PRD §12.1 FR-HR-JD-1)
  Trang HR tạo/sửa/đóng JD qua web (title, description, requirements, rubric, screener_questions, gate_config) —
  thay cho việc gọi API tay. Tạo JD → embedding Qdrant (đã có ở 02a).
- **06 — Object storage** (PRD §16 cv_file_ref; bàn deploy)
  Chuyển lưu CV từ đĩa local → cloud (Cloudflare R2 / Supabase Storage, S3-compatible). Bọc sau interface
  `save/get/url` (local dev ↔ cloud prod, đổi bằng config). _Có thể dời xuống GĐ5/deploy — local đủ cho dev._
- **07 — Nộp CV công khai** (PRD §8.2, §12.2 FR-AP-1/2)
  Trang công khai: xem danh sách JD đang mở → chọn JD → nộp CV (gắn đúng JD) → vào pipeline async. Đây chính là
  "tạo JD xong nộp CV tương ứng với từng JD". (Tái dùng `CVUpload`; guest, chỉ cần email.)
  → **Mốc:** luồng vào thật hoàn chỉnh.

---

## 🔵 GIAI ĐOẠN 3 — Screener bất đồng bộ (PRD §10 — phần KHÓ NHẤT)

> Mục tiêu: pipeline dừng chờ ứng viên rồi thức dậy. Tách nhỏ vì đây là lát phức tạp nhất. _Phụ thuộc: 04 (email), 07 (submission)._

- **08a — Postgres checkpointer + suspend/resume** (NFR-2, §10 FR-SCR-1/2)
  Chuyển checkpointer MemorySaver → Postgres (Neon). Pipeline dừng ở screener, lưu state bền; resume được từ điểm dừng.
- **08b — Magic-link form** (§7.3, §12.2 FR-AP-3)
  Route công khai `/screening/<token>`; gửi email bộ câu hỏi (cố định theo JD); ứng viên điền form → nhận trả lời →
  resume pipeline. Kiểm token (hạn/đã dùng). Chuẩn hóa câu trả lời (LLM nhẹ, không chatbot).
- **08c — Timeout + nhắc + trả lời trễ** (§10 FR-SCR-3/4/5)
  Job quét deadline định kỳ; nhắc +24h một lần; timeout → human_review (`no_response`, KHÔNG auto-loại); xử lý reply trễ.
- **08d — Gate mời** (PRD §9)
  Sau screener: auto-mời bật + ổn → scheduler; tắt / có cờ → human_review. Hoàn thiện gate thứ hai.
  → **Mốc:** Screener đầy đủ, pipeline bất đồng bộ hoàn chỉnh (điểm nhấn kỹ thuật lớn).

---

## 🔵 GIAI ĐOẠN 4 — Xác thực & phân quyền (PRD §4)

- **09 — HR admin auth**
  Đăng nhập HR; bảo vệ mọi route/màn HR (dashboard, JD, review, gate). Ứng viên giữ **guest** (không bắt đăng nhập
  để nộp); tùy chọn tài khoản ứng viên tra cứu đơn. _Có thể dời sớm hơn nếu cần bảo mật/demo; dev thì làm muộn tiện hơn._
  → **Mốc:** phân quyền thật (guest nộp CV, HR đăng nhập quản lý).

---

## 🔵 GIAI ĐOẠN 5 — Vững chắc & triển khai

- **10 — Thống kê / analytics** (PRD §12.1 FR-HR-ANALYTICS-1)
  Số CV, tỉ lệ passed/rejected/pending theo JD; nền cho vòng học sau.
- **11 — Observability** (NFR-6)
  Langfuse Cloud: giám sát chi phí token, độ trễ, tỉ lệ lỗi của các lời gọi LLM.
- **12 — Chống prompt injection** (NFR-5)
  Làm sạch/đóng khung nội dung CV + câu trả lời ứng viên trước khi đưa vào LLM (chống chèn lệnh qua CV).
- **13 — Triển khai (deploy)**
  Backend → Render/Railway; frontend → Vercel; storage cloud (nếu chưa làm ở 06); env secrets; xử lý managed
  auto-suspend (đánh thức trước demo). Lưu ý dữ liệu cá nhân (NFR-4) — dùng CV ẩn danh khi demo public.
  → **Mốc:** hệ thống chạy trên internet, demo từ xa được.

---

## ⚪ GIAI ĐOẠN 6 — Tương lai / tùy chọn (PRD §17)

- **14 — LLM đề xuất rubric từ JD + HR duyệt/chỉnh** (bán tự động, trụ cột 4)
  Gắn vào luồng đăng JD (GĐ2): HR nhập JD → LLM đề xuất rubric → HR sửa → lưu. Giải bài "HR quên đặt tiêu chí".
  Điểm nhấn học thuật mạnh (AI đề xuất, người duyệt). Làm khi có thời gian.
- **15 — Khác:** Zalo OA cho Screener · web push xuyên nền tảng (iOS) · vòng học đầy đủ (gom mẫu→đề xuất) ·
  đa JD/ứng viên · A/B testing rubric.

---

## Ghi chú thứ tự & điểm linh hoạt

- **Vì sao GĐ1 trước:** hoàn thiện vòng quyết định = giá trị/câu chuyện cao nhất. Có nó, bạn demo được lõi tự trị + HITL.
- **Vì sao auth (GĐ4) muộn:** dev đỡ vướng đăng nhập; chức năng vẫn chạy không cần auth. Dời sớm nếu cần bảo mật/demo.
- **Vì sao Screener (GĐ3) sau cổng vào:** nó cần email (04) + luồng nộp (07) mới có nghĩa, và là phần khó nhất → làm khi nền vững.
- **Storage (06) linh hoạt:** local đủ cho dev; có thể gộp vào lúc deploy (13).
- **Nếu thiếu thời gian (bản tối thiểu để bảo vệ):** GĐ1 đầy đủ + 05/07 (cổng vào) + 09 (auth) + 13 (deploy);
  Screener (GĐ3) có thể rút gọn (vd bỏ timeout tự động, làm luồng cơ bản) — nêu rõ phần rút gọn trong báo cáo.
- **Đừng để design/ý tưởng đẻ lát ngoài roadmap** — ý mới lọc qua PRD trước; đáng làm thì cập nhật PRD/roadmap rồi mới làm.

---

## Trạng thái nhanh (cập nhật khi xong lát)

- [x] Scaffold · PWA · 01 · 01b · 01c · 02a · 02b · 03a · cleanup
- [ ] 03b human_review ← **TIẾP THEO**
- [ ] 03c gate rank · 04 scheduler email
- [ ] 05 JD UI · 06 storage · 07 nộp CV công khai
- [ ] 08a/b/c/d Screener async
- [ ] 09 auth
- [ ] 10 analytics · 11 observability · 12 anti-injection · 13 deploy
- [ ] 14 LLM gợi ý rubric · 15 tùy chọn
