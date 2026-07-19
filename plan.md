# SLICE JD-4 — Soft-delete (ARCHIVED) + dọn vector Qdrant + guard submit · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ — **khép cụm tối-ưu-tạo-JD.** Nguồn chân lý: **`PRD.md`**
> (FR-HR-JD-3). **Mục tiêu:** HR **lưu trữ (archive)** JD thay vì xóa cứng (giữ hồ sơ ứng viên + kiểm toán);
> dọn **vector Qdrant mồ côi** khi xóa data; **guard** submission thiếu job_id. Tham chiếu: PRD §12.1 (FR-HR-JD-3), §16, §17.
>
> **Ranh giới:** KHÔNG đụng pipeline/graph/ranker/scoring/screener. Lát dọn-dẹp, rủi ro thấp. `status` là cột
> String (JD-2a) → thêm ARCHIVED = thêm vào tập giá trị, **không migration enum**.

---

## 1. In scope / Out of scope

**In scope:**

- **Soft-delete:** thêm `ARCHIVED` vào status (DRAFT/OPEN/CLOSED/**ARCHIVED**). HR **Lưu trữ** JD → ARCHIVED (ẩn khỏi list mặc định + /apply); **Khôi phục** → về CLOSED (HR mở lại có chủ đích). **KHÔNG hard-delete JD.**
- **Dọn vector Qdrant:** helper `delete_jd_vector(job_id)` (xóa vector JD khỏi Qdrant). Dùng trong `reset_demo_data` (xóa JD test → xóa vector, hết mồ côi — bài học JD-1). _Archive GIỮ vector_ (JD còn tồn tại, dormant/vô hại vì không OPEN nên không CV nào match; khôi phục không cần re-embed).
- **Guard submit thiếu job_id:** endpoint nộp CV **bắt buộc job_id hợp lệ + JD OPEN** (thiếu/sai → 400/404). /apply vốn luôn có job_id nên luồng thật không đổi — đây là chặn phòng thủ (điểm 2 reviewer ghi ở JD-2b).

**Out of scope (KHÔNG làm):**

- KHÔNG hard-delete JD (bảo toàn Application + AuditLog). KHÔNG đụng pipeline/graph/ranker/scoring/screener/parser.
- KHÔNG re-embed-on-restore (archive giữ vector). KHÔNG đổi field posting/rubric/gate logic.

---

## 2. Prerequisites

- JD-2a (status String + list JD + Mở/Đóng) · JD-1 (JD upsert vector khi tạo/sửa — nay thêm đường xóa vector) · qdrant_service (đã có). `reset_demo_data` (đã cascade session/checkpoint/file — nay thêm vector).

## 3. Việc cần làm

### 3.1 Soft-delete ARCHIVED · model/schema + jd service

- Thêm `ARCHIVED` vào tập status hợp lệ (String → không cần migration). Hành động **Lưu trữ**: JD (bất kỳ status) → ARCHIVED. **Khôi phục**: ARCHIVED → CLOSED (KHÔNG tự OPEN — mở lại là hành động chủ đích, vẫn theo rubric-bắt-buộc-để-mở của JD-2a).
- **Ẩn ARCHIVED khỏi list HR mặc định** + một cách xem/khôi phục (filter "Đã lưu trữ" hoặc mục riêng). `/apply` vốn chỉ OPEN → ARCHIVED tự loại (không cần sửa 07). Application của JD archived **GIỮ NGUYÊN** (không xóa; vẫn xem/duyệt được).

### 3.2 Dọn vector Qdrant · qdrant_service + reset_demo_data

- Helper `delete_jd_vector(job_id)` (xóa point JD khỏi collection; tolerate không-tồn-tại). Gọi trong `reset_demo_data` khi xóa JD test → không còn vector mồ côi (đóng nợ JD-1).
- Archive KHÔNG gọi delete (giữ vector dormant). _(Ghi chú: nếu sau muốn archive cũng xóa vector + re-embed-on-restore thì là mở rộng riêng — KHÔNG làm ở đây.)_

### 3.3 Guard submit thiếu job_id · endpoint nộp CV

- `POST /api/public/applications`: bắt buộc `job_id` + JD tồn tại + **status OPEN** (đã có OPEN-check từ 07; bổ sung chặn thiếu/sai job_id rõ ràng → 400/404). Không tạo Application khi job_id không hợp lệ.

### 3.4 Frontend

- Nút **Lưu trữ** trên JD row (hoặc menu) → ARCHIVED. Filter/mục **"Đã lưu trữ"** + nút **Khôi phục**. Xác nhận trước khi lưu trữ (nhẹ). ARCHIVED không hiện trong list chính.

### 3.5 Test

- Archive JD → biến khỏi list mặc định + /apply; Application của nó vẫn còn (không xóa). Khôi phục → CLOSED, xem lại được.
- `delete_jd_vector`: reset_demo_data xóa JD test → vector biến khỏi Qdrant (mock/verify). Archive KHÔNG xóa vector.
- Submit thiếu job_id → 400; job_id JD không OPEN → 404/400; /apply hợp lệ vẫn 201.

## 4. Verify (chạy thật)

1. `make dev-backend` (restart) + dashboard. Tạo vài JD; **Lưu trữ** một JD OPEN → biến khỏi list chính + khỏi `/apply`. Application cũ của JD đó vẫn xem được ở /applications.
2. Vào filter "Đã lưu trữ" → thấy JD → **Khôi phục** → về CLOSED → mở lại được (nếu có rubric).
3. `reset_demo_data` xóa một JD test → kiểm Qdrant: **vector JD đó biến mất** (không còn mồ côi). _(bạn có DATABASE_URL + Qdrant creds)_
4. Nộp CV thiếu/sai job_id (Postman) → 400/404, KHÔNG tạo Application rác. `/apply` bình thường vẫn nộp được (201).
5. Nộp CV cho JD OPEN → pipeline chạy bình thường (JD-4 KHÔNG đụng graph — không hồi quy).
6. `make test` xanh; `pnpm build` PASS.

## 5. Definition of Done

- [ ] Status có ARCHIVED; **Lưu trữ**→ARCHIVED (ẩn list + /apply, Application giữ nguyên); **Khôi phục**→CLOSED. KHÔNG hard-delete JD.
- [ ] `delete_jd_vector` helper; `reset_demo_data` xóa vector khi xóa JD (hết mồ côi); archive giữ vector.
- [ ] Submit bắt buộc job_id + JD OPEN (thiếu/sai → 400/404, không tạo rác); /apply hợp lệ vẫn 201.
- [ ] KHÔNG đụng pipeline/graph/ranker/scoring/screener; pipeline không hồi quy. `make test` xanh; `pnpm build` PASS.

## 6. Gotchas & quy ước (theo CLAUDE.md)

- **Soft-delete, KHÔNG hard-delete** (trụ cột kiểm toán + bảo toàn hồ sơ ứng viên). Khôi phục → CLOSED (không tự OPEN; theo rubric-bắt-buộc-để-mở JD-2a).
- Archive giữ vector (dormant vì không OPEN → không CV match; khôi phục khỏi re-embed). delete_jd_vector CHỈ cho true-delete (reset_demo_data). tolerate vector không-tồn-tại.
- Guard submit: /apply luôn có job_id nên không đổi luồng thật — chỉ chặn phòng thủ. KHÔNG đụng graph.
- Chạy impact analysis trước khi sửa jd service/submit (GitNexus/detect_changes nếu có, không thì grep). Commit nhỏ (vd `feat(jd): soft-delete ARCHIVED + khôi phục`, `feat(jd): delete_jd_vector + reset_demo_data dọn vector`, `feat(api): guard submit thiếu job_id`, `feat(ui): lưu-trữ/khôi-phục JD`, `test(jd): archive/vector/guard`).
- Nghiệp vụ chưa rõ → **PRD.md** (§12.1 FR-HR-JD-3, §16, §17). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify + checklist DoD.

## 7. Housekeeping (tùy chọn — gộp nếu tiện, KHÔNG bắt buộc)

- `screener_sent_at=null`: set `screener_sent_at=now()` tại chỗ `notify_screener` gửi email screener (email vẫn gửi — chỉ field chưa set; 1 dòng). Nếu tiện thì fix luôn; không thì để riêng.

## 8. Sau lát này — **HẾT CỤM TỐI-ƯU-TẠO-JD**

Khâu tạo JD hoàn chỉnh + chỉnh chu (2 màn · DRAFT/rubric-bắt-buộc-để-mở · screener tùy chọn · AI gợi ý rubric · soft-delete).
Kế tiếp theo kế hoạch: **UI redesign** (đánh bóng cho demo/screenshot) → **đóng băng tính năng** → **viết báo cáo (~60 trang)**.
Dọn ops còn: **đổi mật khẩu admin prod** (đã lộ trong chat — script nhỏ, làm trước khi coi là xong). Xem ROADMAP.md.
