# SLICE 08a — Postgres checkpointer + suspend/resume (nền Screener async) · plan one-shot

> **Bản chất:** plan ONE-SHOT. Xong + nghiệm thu thì bỏ. Nguồn chân lý: **`PRD.md`**.
> **Mục tiêu (HẸP):** chứng minh pipeline **dừng được ở screener → lưu state xuống Postgres → resume từ đúng điểm
> dừng**, BỀN qua restart backend. Đây là NỀN cho Screener async; mọi thứ Screener khác (form, email câu hỏi,
> timeout, gate mời) xây trên nền này ở 08b/c/d.
> Tham chiếu: PRD §10 (Screener), §7.3, NFR-2 (bất đồng bộ). Tuân thủ `CLAUDE.md`.
>
> **⚠️ Đây là lát KHÓ NHẤT tới giờ (bất đồng bộ thật). Scope hẹp có chủ đích. Gặp góc tinh vi → DỪNG, hỏi.**

---

## 1. In scope / Out of scope

**In scope:**

- Thêm **Postgres checkpointer** (LangGraph `AsyncPostgresSaver`) — kết nối Neon riêng, `.setup()` một lần, compile graph với nó (thay MemorySaver).
- Đổi node `screener` từ stub pass-through → **interrupt** (pipeline tạm dừng ở đây; payload chỉ là placeholder).
- Định tuyến: confident + đạt → **screener** (chèn lại vào đường đạt). uncertain / điểm thấp KHÔNG qua screener (giữ nguyên).
- BackgroundTask: khi graph interrupt → set status `AWAITING_SCREENER`; `thread_id = application_id` (bền, để resume).
- Endpoint RESUME (dev/test): `POST /api/agents/resume-screener/{id}` (payload mock) → `Command(resume=...)` → graph
  chạy tiếp TỪ screener → node kế → trạng thái cuối (hiện: human_review, vì gate mời chưa xây).
- Test.

**Out of scope (KHÔNG làm — là 08b/c/d):**

- KHÔNG form magic-link, KHÔNG gửi email câu hỏi (resume bằng endpoint test + payload mock).
- KHÔNG bộ câu hỏi thật / chuẩn hóa câu trả lời bằng LLM. KHÔNG timeout / nhắc / trả lời trễ.
- KHÔNG cổng auto-mời (08d). KHÔNG đụng parser/ranker/scheduler/human_review logic.
- CHỈ CV đạt vào screener; đừng cho low/uncertain qua screener.

---

## 2. Prerequisites

- Deps: `langgraph-checkpoint-postgres` (cung cấp `AsyncPostgresSaver`) + driver của nó (`psycopg[binary,pool]`). Thêm qua `uv add`.
- Neon connection string (đã có cho app). **LƯU Ý:** checkpointer dùng kết nối Postgres RIÊNG (psycopg), tách khỏi
  SQLAlchemy async engine (asyncpg) của app — xem Gotchas.
- **Kiểm phiên bản LangGraph đang cài** rồi dùng ĐÚNG API checkpointer + interrupt/resume của phiên bản đó (API này
  đã thay đổi qua các version — đừng dựa theo trí nhớ; đọc docs/version thực tế).

---

## 3. Việc cần làm

### 3.1 Postgres checkpointer · (vd `app/agents/checkpointer.py` + lifespan)

- Tạo `AsyncPostgresSaver` từ Neon connection (psycopg). Gọi `.setup()` MỘT LẦN (idempotent — tạo bảng checkpoint
  trong Neon; tách khỏi bảng app). Tạo pool/kết nối trong **lifespan** (một lần, dùng lại — KHÔNG tạo mỗi request).
- Compile graph với `checkpointer=<AsyncPostgresSaver>` (thay MemorySaver hiện có).

### 3.2 Node screener → interrupt · `app/agents/nodes/screener.py`

- Đổi từ pass-through → gọi cơ chế **interrupt** của LangGraph (vd `interrupt(payload)` trong node, hoặc
  `interrupt_before=["screener"]` khi compile — chọn theo API phiên bản đang dùng; ưu tiên `interrupt()` dynamic để 08b resume bằng câu trả lời).
- Payload interrupt ở 08a chỉ là PLACEHOLDER (vd `{"awaiting": "screener_answers", "application_id": ...}`) — câu hỏi thật là 08b.
- Khi resume, node nhận payload resume (mock ở 08a) rồi tiếp tục (chưa xử lý gì với payload — chỉ đi tiếp).

### 3.3 Định tuyến: đạt → screener · `app/agents/policy.py` (+ graph)

- `route_after_ranker`: confident + đạt ngưỡng → **`screener`** (thay vì human_review như bản fix trước).
  uncertain → human_review; confident + thấp → auto_reject(ON)/human_review(OFF) — GIỮ NGUYÊN (không qua screener).
- Sau screener (khi resume xong): route tiếp → human_review (gate mời chưa xây = hành vi auto_invite TẮT; slot cho 08d).
- **CHẠY IMPACT ANALYSIS (GitNexus) trước khi sửa `route_after_ranker`** (CLAUDE.md yêu cầu).

### 3.4 BackgroundTask: xử lý interrupt → AWAITING_SCREENER · `app/tasks/background.py`

- Dùng `thread_id = application_id` trong config khi invoke graph (BẮT BUỘC khớp giữa lần chạy đầu và lúc resume).
- Sau lần invoke đầu: nếu graph DỪNG ở interrupt (kết quả có `__interrupt__` / state báo đang chờ) → set status `AWAITING_SCREENER`, log rõ. KHÔNG coi là "xong".
- Xử lý vòng lặp event loop cẩn thận (xem Gotchas) — async saver + cách invoke hiện tại (`asyncio.run`) dễ xung đột.

### 3.5 Endpoint resume (dev/test) · `app/api/routes/agents.py`

- `POST /api/agents/resume-screener/{application_id}` (body: payload mock tùy chọn):
  - Load graph cùng `thread_id = application_id`; invoke `Command(resume=<mock payload>)` (hoặc tương đương API version).
  - Graph chạy tiếp TỪ screener (KHÔNG chạy lại parser/ranker) → node kế → trạng thái cuối.
  - Cập nhật status theo kết quả; trả outcome. (Đây là chỗ 08b sẽ thay trigger = ứng viên nộp form.)
  - Validate: chỉ resume được application đang `AWAITING_SCREENER` (else 409).

### 3.6 Test · `app/tests/test_checkpointer.py`

- CV đạt → graph dừng ở screener (interrupt) → status AWAITING_SCREENER (mock/gated phù hợp).
- Resume → graph tiếp tục từ screener → trạng thái cuối; parser/ranker KHÔNG chạy lại.
- uncertain/low KHÔNG đi qua screener (route như cũ).
- (Nếu khó test durability trong unit → để phần restart cho Verify thủ công.)

---

## 4. Verify (chạy thật — bao gồm bài test DURABILITY quan trọng nhất)

1. `make dev-backend`. Nộp CV đạt (backend khớp JD #2, email của bạn) qua `/apply`.
2. Pipeline chạy parser+ranker → dừng ở screener → `/applications` thấy status **AWAITING_SCREENER** (không đi tiếp, không email). Log: dừng ở interrupt.
3. Kiểm Postgres: có bản ghi checkpoint cho thread_id = application_id (state đã lưu bền).
4. **BÀI TEST MẤU CHỐT (durability):** **RESTART backend** (`make dev-backend` lại). State PHẢI còn (trong Neon, không mất như MemorySaver).
5. Gọi `POST /api/agents/resume-screener/{id}` (payload mock) → graph chạy tiếp TỪ screener → **KHÔNG** chạy lại parser/ranker (kiểm log: không có lời gọi OpenAI parse/rank thứ hai) → route → human_review → status PENDING_REVIEW.
6. (Nối tiếp) vào `/review` duyệt → thư mời thật (đường cũ vẫn chạy). Đối chứng: CV thấp/uncertain KHÔNG vào screener (đi thẳng review/auto-reject).
7. `make test` xanh.

---

## 5. Definition of Done

- [ ] Graph compile với **AsyncPostgresSaver** (Neon); `.setup()` idempotent; pool tạo một lần ở lifespan.
- [ ] CV đạt → dừng ở screener (interrupt) → status `AWAITING_SCREENER`; state lưu bền trong Postgres (thread_id=application_id).
- [ ] **Resume BỀN qua restart backend:** sau khi restart, resume vẫn chạy tiếp từ screener (KHÔNG chạy lại parser/ranker).
- [ ] Endpoint resume tiếp tục pipeline → human_review → (duyệt) thư mời thật. Validate chỉ resume ca AWAITING_SCREENER (409 else).
- [ ] Chỉ CV đạt vào screener; uncertain/low giữ route cũ (không hồi quy).
- [ ] KHÔNG form/email câu hỏi/timeout/gate mời; parser/ranker/scheduler/human_review logic KHÔNG đụng.
- [ ] `make test` xanh.

---

## 6. ⚠️ GOTCHAS — đọc kỹ, đây là chỗ dễ sa lầy

- **thread_id BẮT BUỘC ổn định + khớp:** dùng `application_id`. Lần chạy đầu và lúc resume phải cùng thread_id, nếu không resume không tìm thấy checkpoint.
- **Kết nối Postgres của checkpointer TÁCH khỏi SQLAlchemy:** LangGraph PostgresSaver dùng psycopg (không phải asyncpg). Cần cấu hình kết nối riêng cho Neon (SSL). Lưu ý Neon pooling (`-pooler`/PgBouncer) có thể cần connection trực tiếp hoặc tham số pool phù hợp — nếu lỗi kết nối/prepared-statement, thử connection không-pooled cho checkpointer.
- **Vòng lặp event loop (RỦI RO CAO NHẤT):** app hiện invoke graph qua `runner.run_sync` = `asyncio.run(ainvoke)`. `AsyncPostgresSaver` giữ pool gắn với một event loop; `asyncio.run` tạo/đóng loop mỗi lần → dễ "loop is closed"/pool hỏng. Cần: hoặc một event loop bền cho background task, hoặc tạo pool trong cùng loop invoke, hoặc dùng API async xuyên suốt. **Nếu vướng chỗ này → DỪNG, mô tả lỗi, hỏi trước khi hack.**
- **`.setup()` chạy một lần** (tạo bảng checkpoint) — idempotent; đừng gọi mỗi request.
- **API version:** interrupt/resume (`interrupt()` + `Command(resume=...)` vs `interrupt_before`) khác nhau theo version — kiểm version cài đặt, dùng đúng.
- Interrupt payload 08a chỉ placeholder — đừng cố nhét câu hỏi/logic (đó là 08b).

## 7. Ranh giới & quy ước (theo CLAUDE.md)

- CHỈ động vào: checkpointer + screener-interrupt + routing đạt→screener + BackgroundTask interrupt-handling + resume endpoint + test. KHÔNG đụng parser/ranker/scheduler/human_review logic.
- Đơn giản trước: chứng minh cơ chế, không tối ưu; payload placeholder; resume thủ công.
- Async-first; config từ env (checkpointer connection); không hardcode.
- Commit nhỏ (vd `feat(checkpointer): AsyncPostgresSaver + setup + compile`, `feat(screener): interrupt (pause) + route đạt->screener`, `feat(agents): BackgroundTask AWAITING_SCREENER + resume endpoint`, `test(checkpointer): suspend/resume`).
- Nghiệp vụ chưa rõ → **PRD.md** (§10, §7.3). Kỹ thuật vướng (event loop/psycopg) → DỪNG, hỏi. ĐỪNG suy diễn/hack im lặng.
- Kết thúc: in tóm tắt thay đổi, lệnh verify (nhấn mạnh bài test restart-durability), checklist DoD.

## 8. Sau lát này

Nền suspend/resume xong → **08b** (magic-link form + email bộ câu hỏi → resume bằng câu trả lời thật, thay endpoint test) →
**08c** (timeout/nhắc/trả lời trễ) → **08d** (cổng auto-mời). Xem ROADMAP.md.
