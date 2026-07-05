# CLAUDE.md

Hướng dẫn cho Claude Code khi làm việc trong repo này. Đọc mỗi session.

## tài liệu (đọc kỹ)

- **`PRD.md` = NGUỒN CHÂN LÝ của hệ thống.** Mọi quyết định nghiệp vụ, luồng, agent, trạng thái, yêu cầu —
  tra `PRD.md`. Khi code mâu thuẫn với PRD → PRD đúng (hoặc cập nhật PRD trước rồi mới sửa code). Khi không
  chắc "hệ thống nên hành xử thế nào" → mở PRD, KHÔNG suy diễn.

---

## Project là gì (tóm tắt — chi tiết ở PRD)

**Hệ thống tuyển dụng tự trị sử dụng Multi-Agent AI**. Tự động hóa vòng sàng lọc từ nhận
CV đến gửi thư mời; HR chỉ can thiệp ở điểm quyết định hoặc khi hệ thống không đủ tự tin.

Pipeline cố định (PRD §7–§8): `parser → ranker → screener → scheduler` + `human_review` có điều kiện.

- `parser`: CV (PDF/DOCX) → JSON.
- `ranker`: đối sánh CV–JD (RAG) + chấm điểm rubric. Node ra quyết định.
- `screener`: chạy SAU ranker; gửi bộ câu hỏi cố định qua email + magic-link form; **bất đồng bộ** (pipeline
  suspend/resume, có timeout). KHÔNG phải chatbot tự do.
- `scheduler`: điểm thực thi DUY NHẤT cho mọi email tới ứng viên (mời + đặt lịch, hoặc từ chối).
- `human_review`: kích hoạt có điều kiện; luôn kèm **ReviewCard** (tóm tắt + điểm + lý do); HR duyệt → delegate scheduler.

Hai **gate** cấu hình (PRD §9): `auto-từ-chối`, `auto-mời` — HR bật/tắt; chỉ can thiệp ca tự tin, ca bất định
luôn vào human_review (gate no-op).

Kiến trúc đã chốt: **pipeline cố định, KHÔNG Supervisor** — có chủ đích, ưu tiên dự đoán được + kiểm toán
(PRD §5, 4 trụ cột).

Giai đoạn hiện tại (nếu đang theo plan.md): **chỉ scaffold** — node stub, UI placeholder, KHÔNG logic thật.

---

## Stack

- **Backend:** Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2. Gói: `uv`.
- **Hạ tầng (managed-first):** Neon (Postgres) · Upstash Redis · Qdrant Cloud. Dự phòng: `docker-compose.local.yml`.
- **Async:** FastAPI BackgroundTasks (KHÔNG worker polling — phá free tier Upstash). Screener dùng suspend/resume
  (LangGraph interrupt + Postgres checkpointer — phase sau).
- **Frontend:** Next.js 14 · Tailwind · shadcn/ui · TanStack Query.
- **PWA:** web dashboard cài được trên điện thoại cho HR (không codebase mobile riêng).
- **Monorepo:** pnpm workspaces; dùng chung ở `packages/shared-types`.

---

## Quy ước code (BẮT BUỘC)

- **Async-first** ở backend: async engine/session/route. Không trộn sync I/O.
- **Cấu hình đọc từ env** qua pydantic-settings. KHÔNG hardcode secret/URL/ngưỡng.
- **Type đầy đủ:** type hints (Python), không `any` tùy tiện (TS).
- **Secret chỉ trong `.env`** (gitignore). Chỉ commit `.env.example`.
- **Commit mỗi đơn vị công việc:** message rõ ràng (scaffold: `feat(scaffold): phase N - ...`).
- **Neon cần SSL:** `connect_args={"ssl": True}` trong `create_async_engine`. KHÔNG `?sslmode=` (asyncpg không hiểu).
- **scheduler là điểm thực thi DUY NHẤT** gửi email tới ứng viên — đừng gửi email rải rác ở node khác.

---

## Bốn nguyên tắc làm việc

_(Chắt từ quan sát của Andrej Karpathy về lỗi LLM hay mắc khi code. Thiên về cẩn trọng hơn tốc độ.)_

### 1. Nghĩ trước khi code — đừng giả định, đừng giấu chỗ khó hiểu

- Nêu rõ giả định; không chắc thì **hỏi**. Nhiều cách hiểu → **trình bày lựa chọn**, đừng tự chọn im lặng.
- Có cách đơn giản hơn → **nói ra**. Điều gì không rõ → **dừng**, gọi tên, hỏi.
- Project này: nghiệp vụ chưa rõ → mở **PRD**; PRD chưa đủ → hỏi, ĐỪNG suy diễn.

### 2. Đơn giản trước — code tối thiểu giải quyết vấn đề

- Không tính năng ngoài yêu cầu. Không trừu tượng cho code dùng một lần. Không "linh hoạt" không ai yêu cầu.
- 200 dòng mà 50 là đủ → viết lại. "Kỹ sư senior có nói cái này phức tạp quá mức không?"
- Scaffold: node là stub log + pass-through. ĐỪNG tự thêm logic agent "cho xịn" — đó là phase sau (theo PRD).

### 3. Sửa có phẫu thuật — chỉ động vào cái buộc phải động

- Đừng "cải thiện" code/comment/format xung quanh. Đừng refactor cái không hỏng. Theo style sẵn có.
- Thấy dead code không liên quan → nói ra, đừng xóa. Dọn phần _do bạn_ tạo thừa.
- Mỗi dòng thay đổi truy được về yêu cầu (hoặc một mục PRD).

### 4. Thực thi theo mục tiêu — định nghĩa tiêu chí thành công rồi lặp đến khi xác minh

- Biến task thành mục tiêu kiểm chứng. Scaffold: mỗi phase đã có bước **Verify** — chạy, cho người dùng xem, mới commit.
- Logic nghiệp vụ (phase sau): mỗi yêu cầu PRD (FR-xxx) là tiêu chí; viết test phản ánh FR rồi làm cho pass.

---

## Ranh giới & chừa chỗ (giai đoạn scaffold)

- KHÔNG Supervisor Agent / lớp điều phối động — pipeline cố định (PRD §5).
- KHÔNG gọi LLM trong pipeline (`ENABLE_LLM=false`); KHÔNG parse CV thật, RAG, Screener async, gate, vòng học — stub + TODO trỏ PRD.
- KHÔNG tích hợp email/Calendar/Zalo ở scaffold.
- KHÔNG worker queue polling Redis — dùng BackgroundTasks.
- **Chừa chỗ kiến trúc:** `RecruitmentState` có sẵn `confidence/uncertainty_flags/escalation_reason/
require_human_review` + trường Screener (`awaiting_screener`, `screener_answers`); `policy.should_review`
  route được; demo chạy cả 2 nhánh; `audit_log` đủ cột (PRD §16).
- Phase 1: sau khi tạo `.env.example` + checklist, **DỪNG chờ** người dùng điền `.env` trước khi verify.

---

## Khi nghi ngờ

Thứ tự tra cứu: **PRD.md** (nghiệp vụ, hệ thống nên làm gì) → **CLAUDE.md** (cách code) → hỏi người dùng.
KHÔNG dùng plan.md làm tham chiếu sau khi scaffold xong.
