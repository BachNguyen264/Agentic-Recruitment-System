# SLICE JD-2a — Tách form 2 màn + DRAFT + rubric-bắt-buộc-để-mở + gate ra list · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu:** tách JD thành 2 màn — **"Tin tuyển dụng"** (lưu → JD tồn tại dạng DRAFT) và **"Cấu hình sàng lọc"**
> (rubric + câu hỏi, trên JD ĐÃ LƯU); thêm status **DRAFT** + **rubric bắt buộc để MỞ JD**; chuyển 2 gate ra **danh
> sách JD**. Tham chiếu: PRD §8.1, §12.1 (FR-HR-JD-1/2/3/4), §16. Tuân thủ `CLAUDE.md`.
>
> **⚠️ Ranh giới:** JD-2a **KHÔNG đụng graph/pipeline.** Screener-tùy-chọn (đổi định tuyến bỏ qua screener khi rỗng)
> là **JD-2b** — lát riêng có adversarial review. JD-2a thuần cấu trúc form + status-rule + di chuyển gate.

---

## 1. In scope / Out of scope

**In scope:**

- Status: thêm **`DRAFT`** vào enum (DRAFT/OPEN/CLOSED; ARCHIVED để JD-4). JD tạo mới = DRAFT. Migration (include_object guard).
- **Rubric bắt buộc để MỞ:** chuyển JD `→ OPEN` bị **chặn nếu chưa có rubric** (≥1 tiêu chí + tổng trọng số hợp lệ, dùng validate sẵn của 05). DRAFT/CLOSED không nhận CV, ẩn khỏi /apply.
- **Tách form 2 màn:** (1) "Tin tuyển dụng" (field posting từ JD-1) — lưu tạo/sửa JD (mới → DRAFT); (2) "Cấu hình sàng lọc" (rubric + câu hỏi sàng lọc) — trên JD **đã lưu** (cần JD id). Di dời phần soạn rubric/câu-hỏi (từ JD-1) sang màn 2, GIỮ hành vi.
- **Gate ra list:** bỏ 2 toggle gate khỏi form; đưa lên **danh sách JD** (mỗi JD 2 toggle auto_reject/auto_invite), nối `PATCH /gate` đã có.
- JD list: hiện status (DRAFT/OPEN/CLOSED) + nút Mở/Đóng (Mở bị chặn nếu chưa rubric).

**Out of scope (KHÔNG làm):**

- KHÔNG đụng graph/policy/pipeline — **screener-tùy-chọn = JD-2b.** KHÔNG AI gợi ý rubric (JD-3). KHÔNG ARCHIVED/soft-delete (JD-4).
- KHÔNG đụng ranker-scoring/screener logic/embedding. KHÔNG đổi field posting (JD-1 xong).

---

## 2. Prerequisites

- JD-1 xong (field mới + editor). Rubric/câu-hỏi editing (từ 05) + `PATCH /gate` (03c/08d) đã có — JD-2a _di dời_ + _nối lên list_, không viết lại.
- Kiểm cách lưu `status`: nếu là **cột chuỗi** (app-validate) → chỉ cần thêm DRAFT vào tập cho phép (có thể KHÔNG cần migration). Nếu là **enum Postgres** → migration `ALTER TYPE ADD VALUE` (⚠️ không chạy trong transaction ở Postgres cũ — xem Gotchas).

## 3. Việc cần làm

### 3.1 Status DRAFT + rule mở · model/schema + jd service (+ migration nếu enum DB)

- Thêm `DRAFT` vào enum trạng thái; **tạo JD mới → DRAFT** (thay vì OPEN/CLOSED trước đây).
- **Chuyển sang OPEN validate rubric:** endpoint đổi status (hoặc PATCH JD) khi `status→OPEN` → kiểm rubric non-empty + hợp lệ; rỗng → **400 lỗi rõ** ("JD cần có rubric mới mở được"). CLOSE (tạm dừng) không cần rule.
- Migration (nếu cần) **NHỚ include_object guard**.

### 3.2 Backend hỗ trợ 2 màn

- Đảm bảo có đường lưu **posting** (tạo → trả JD id, status DRAFT) tách khỏi đường lưu **cấu hình sàng lọc** (rubric + câu hỏi) trên JD id. (Có thể tái dùng PATCH JD hiện tại, chia payload theo màn — không cần endpoint mới nếu PATCH đã đủ.) Public projection giữ chỉ OPEN + không lộ nội bộ (như 07).

### 3.3 Frontend: tách 2 màn · JobForm → 2 phần

- **Màn "Tin tuyển dụng"** (`/jobs/new` + edit): field posting (JD-1). Tạo mới: lưu → JD DRAFT → **điều hướng sang màn cấu hình** của JD đó (vì rubric cần JD đã lưu). Edit: sửa posting bình thường.
- **Màn "Cấu hình sàng lọc"** (trên JD đã lưu — tab hoặc route `/jobs/{id}/screening`): **rubric** (tiêu chí + trọng số, tổng ~1 — UI từ 05) + **câu hỏi sàng lọc** (từ 05). Nút **"Mở JD"** ở đây (chặn + tooltip nếu chưa rubric).
- Cấu trúc tab hay route riêng: Claude Code chọn; cốt lõi: posting lưu TRƯỚC → mới cấu hình rubric được (đúng phụ thuộc). Bỏ gate khỏi cả 2 màn.

### 3.4 Frontend: gate + status ở JD list

- Mỗi JD row: badge status (Nháp/Đang mở/Đã đóng) + **2 toggle gate** (auto_reject/auto_invite → `PATCH /gate`) + nút **Mở/Đóng**.
- **Mở bị chặn nếu JD chưa rubric** (nút disable + tooltip "cần cấu hình rubric trước", dẫn tới màn cấu hình). Đóng luôn cho phép.

### 3.5 Test

- Tạo JD → status DRAFT; chưa rubric → gọi mở → 400 (chặn). Thêm rubric → mở → OPEN.
- Round-trip 2 màn: lưu posting → JD id → lưu rubric/câu hỏi trên id đó → đọc lại đúng.
- Gate toggle trên list → `PATCH /gate` đổi đúng. DRAFT/CLOSED KHÔNG hiện ở /apply; chỉ OPEN hiện.

## 4. Verify (chạy thật)

1. `make dev-backend` + `make dev-dashboard`. HR đăng nhập → `/jobs/new` → điền tin tuyển dụng → lưu → **JD tạo dạng "Nháp"**, tự chuyển sang **màn cấu hình sàng lọc**.
2. Ở màn cấu hình: chưa nhập rubric → bấm **"Mở JD"** → **bị chặn** (thông báo cần rubric). Nhập rubric (tổng trọng số ~1) + (tùy chọn) câu hỏi → lưu → bấm Mở → **OPEN**.
3. `/apply`: JD giờ hiện (OPEN). JD ở trạng thái Nháp/Đóng khác → KHÔNG hiện.
4. JD list: badge status đúng; **2 toggle gate** bật/tắt được (kiểm DB đổi); JD chưa rubric → nút Mở disable + tooltip.
5. Nộp CV cho JD OPEN → pipeline chạy bình thường (JD-2a KHÔNG đụng graph — không hồi quy).
6. `make test` xanh; `pnpm --filter dashboard build` PASS.

## 5. Definition of Done

- [ ] Status có DRAFT; JD mới = DRAFT; chuyển OPEN **chặn nếu chưa rubric** (400 rõ). Migration (+ include_object guard nếu cần).
- [ ] 2 màn: "Tin tuyển dụng" (lưu → DRAFT → sang cấu hình) + "Cấu hình sàng lọc" (rubric + câu hỏi trên JD đã lưu). Rubric/câu hỏi di dời, GIỮ hành vi.
- [ ] Gate ra **JD list** (2 toggle/JD → PATCH /gate); bỏ khỏi form. Status + Mở/Đóng trên list; Mở chặn nếu chưa rubric.
- [ ] /apply chỉ hiện OPEN (DRAFT/CLOSED ẩn); projection không lộ nội bộ.
- [ ] **KHÔNG đụng graph/pipeline/ranker/screener logic** (screener-routing = JD-2b); pipeline không hồi quy.
- [ ] `make test` xanh; `pnpm build` PASS.

## 6. Gotchas & quy ước (theo CLAUDE.md)

- **Migration status nếu là enum Postgres:** `ALTER TYPE ... ADD VALUE 'DRAFT'` **không chạy trong transaction** ở Postgres cũ (cần `op.execute` ngoài transaction / autocommit). Nếu status là cột chuỗi → chỉ thêm vào tập validate, không cần ALTER. Claude Code kiểm schema thật rồi chọn. include_object guard.
- **Phụ thuộc dữ liệu:** posting lưu TRƯỚC (có JD id) → mới cấu hình rubric (đúng lý do tách). Đừng cho cấu hình rubric khi JD chưa lưu.
- Di dời rubric/câu-hỏi/gate — **tái dùng UI + validate + endpoint sẵn có** (05/03c/08d), không viết lại logic. KHÔNG đụng graph.
- Chạy impact analysis trước khi sửa jd service/status (GitNexus nếu có, không thì grep). Commit nhỏ (vd `feat(jd): status DRAFT + rubric-bắt-buộc-để-mở`, `feat(ui): tách màn tin-tuyển-dụng / cấu-hình-sàng-lọc`, `feat(ui): gate + status ở JD list`, `test(jd): DRAFT/rule mở/round-trip 2 màn`).
- Nghiệp vụ chưa rõ → **PRD.md** (§8.1, §12.1, §16). Vướng → DỪNG, hỏi.
- Kết thúc: in tóm tắt + lệnh verify + checklist DoD.

## 7. Sau lát này

**JD-2b** — screener-tùy-chọn: JD không có câu hỏi → pipeline BỎ QUA bước screener (đổi định tuyến §8.3/§10, cô lập +
adversarial review; vá case suspend-form-rỗng). Rồi **JD-3** (AI gợi ý rubric), **JD-4** (soft-delete + dọn vector Qdrant). Xem ROADMAP.md.
