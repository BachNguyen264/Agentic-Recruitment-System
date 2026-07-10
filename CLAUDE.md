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

---

## Trạng thái hiện tại (cập nhật mỗi lát)

Đã qua scaffold — đang build từng **lát (slice)** logic thật. Node THẬT vs STUB:

| Node           | Trạng thái | Ghi chú                                                                             |
| -------------- | ---------- | ---------------------------------------------------------------------------------- |
| `parser`       | ✅ THẬT     | CV→JSON qua OpenAI `gpt-4.1-mini` (structured output) + certificates/languages/awards/other |
| `ranker`       | ✅ THẬT     | chấm rubric có suy luận qua `gpt-5-mini` (reasoning_effort=low); embedding = tín hiệu phụ |
| `screener`     | ⛔ STUB     | pass-through — async suspend/resume là lát sau (PRD §10)                            |
| `scheduler`    | ⛔ STUB     | pass-through — email/Calendar là lát sau                                            |
| `human_review` | ⛔ STUB     | set require_human_review + reason — ReviewCard là lát sau (PRD §11)                 |

Đã THẬT thêm: quản lý JD + embedding vào Qdrant (`text-embedding-3-small`, 1536 chiều); dashboard **PWA** +
trang `/cv-check` + màn ứng viên `/applications` (danh sách + chi tiết điểm, **chỉ đọc**). **CHƯA làm:** 2 gate
(§9), Screener async (§10), ReviewCard (§11), email/Calendar, vòng học.

`ENABLE_LLM=true` bật parser+ranker THẬT; `false` → giữ stub (cho `test_graph`).

---

## Stack

- **Backend:** Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2. Gói: `uv`.
- **Hạ tầng (managed-first):** Neon (Postgres) · Upstash Redis · Qdrant Cloud. Dự phòng: `docker-compose.local.yml`.
- **Async:** FastAPI BackgroundTasks (KHÔNG worker polling — phá free tier Upstash). Screener dùng suspend/resume
  (LangGraph interrupt + Postgres checkpointer — phase sau).
- **Frontend:** Next.js 14 · **plain Tailwind (bảng màu slate)** · TanStack Query. shadcn/ui **CHƯA cài** —
  dùng utility class + component tự viết; ĐỪNG thêm thư viện UI. API base đọc env `NEXT_PUBLIC_API_BASE`.
- **PWA:** web dashboard cài được trên điện thoại cho HR (không codebase mobile riêng).
- **Monorepo:** pnpm workspaces; dùng chung ở `packages/shared-types`.

---

## Lệnh (và chạy ở đâu)

- **Backend (Python/uv) → Bash:** `make dev-backend` · `make test` · `make migrate`. Script lẻ / test:
  `uv run --directory apps/backend python …` / `uv run --directory apps/backend pytest -q`.
- **Node (pnpm/next/tsc) → PowerShell** (Git Bash bung lỗi fnm): `pnpm --filter dashboard dev|build|typecheck`.
- **git → Bash nhưng TRÁNH `cd`** (hook fnm lỗi): dùng `git -C <repo-root> …`.
- Test tích hợp gọi API thật bị gate: bật `RUN_EMBED_IT=1` / `RUN_PARSE_IT=1` (mặc định skip, giữ `make test` nhanh).

---

## Quy ước code (BẮT BUỘC)

- **Async-first** ở backend: async engine/session/route. Không trộn sync I/O.
- **Cấu hình đọc từ env** qua pydantic-settings. KHÔNG hardcode secret/URL/ngưỡng.
- **Type đầy đủ:** type hints (Python), không `any` tùy tiện (TS).
- **Secret chỉ trong `.env`** (gitignore). Chỉ commit `.env.example`.
- **Commit nhỏ mỗi bước:** message rõ, prefix theo lát (`feat(parser): …`, `feat(ranker): …`, `fix(…)`, `test(…)`, `chore(…)`).
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
- Mỗi lát chỉ làm phần đã khoanh vùng; node CHƯA tới lượt (screener/scheduler/human_review) giữ stub, ĐỪNG "làm cho xịn".

### 3. Sửa có phẫu thuật — chỉ động vào cái buộc phải động

- Đừng "cải thiện" code/comment/format xung quanh. Đừng refactor cái không hỏng. Theo style sẵn có.
- Thấy dead code không liên quan → nói ra, đừng xóa. Dọn phần _do bạn_ tạo thừa.
- Mỗi dòng thay đổi truy được về yêu cầu (hoặc một mục PRD).

### 4. Thực thi theo mục tiêu — định nghĩa tiêu chí thành công rồi lặp đến khi xác minh

- Biến task thành mục tiêu kiểm chứng. Mỗi lát: **Verify chạy thật** (cho người dùng xem output) + kiểm định
  độc lập (Workflow) trước khi chốt; mỗi yêu cầu PRD (FR-xxx) là tiêu chí — viết test phản ánh FR rồi làm cho pass.

---

## Ranh giới hiện tại

- KHÔNG Supervisor Agent / điều phối động — pipeline cố định (PRD §5).
- Node CHƯA tới lượt giữ **stub**: screener/scheduler/human_review. CHƯA có: 2 gate (§9), Screener async (§10),
  ReviewCard (§11), email/Calendar/Zalo, vòng học — giữ stub + TODO trỏ PRD; đừng làm ngoài phạm vi lát.
- KHÔNG worker queue polling Redis — dùng BackgroundTasks.
- **Ranker:** điểm CHỈ dựa rubric có suy luận (trọng số từ JD); cosine/embedding là **tín hiệu phụ**, KHÔNG vào
  điểm, KHÔNG chunk JD. confidence/flags = heuristic **xác định** (không hỏi LLM tự chấm).
- **scheduler là điểm gửi email DUY NHẤT** — đừng gửi email rải rác ở node khác.
- **Chừa chỗ kiến trúc (đã có):** `RecruitmentState` có confidence/uncertainty_flags/escalation_reason/
  require_human_review + score/score_breakdown/semantic_similarity + trường Screener; `policy.should_review`
  route theo giá trị thật; `audit_log` đủ cột (PRD §16).

---

## Gotchas đã gặp (đọc trước khi lặp lại)

- **Node async trong pipeline:** ranker là `async` → `runner.run_sync` dùng `asyncio.run(ainvoke)`; parser giữ
  sync; graph chạy mixed OK. Thêm node async mới → nhớ đường sync này.
- **langchain-openai BỎ `temperature`** cho model reasoning (gpt-5*): nhánh reasoning truyền `reasoning_effort`,
  KHÔNG truyền temperature. Đặt `RANKER_MODEL=gpt-5-mini` thì PHẢI đặt `RANKER_REASONING_EFFORT=low`.
- **Qdrant Cloud** bắt buộc payload index cho field dùng filter (`type`); `create_collection` không idempotent
  (409) — đã có `asyncio.Lock` + tha thứ 409 trong `ensure_collection`.
- **str.format prompt:** literal `{...}` phải escape `{{...}}` (quên → KeyError, mọi lần parse thành fail).
- **curl UTF-8 (Git Bash):** body JSON tiếng Việt phải `--data-binary @file` (inline `-d` hỏng dấu).
- Lỗi LLM/embedding/Qdrant KHÔNG được sập pipeline → try/except đặt cờ (`parse_failed`/`rank_failed`) + escalation.

---

## Khi nghi ngờ

Thứ tự tra cứu: **PRD.md** (nghiệp vụ, hệ thống nên làm gì) → **CLAUDE.md** (cách code + trạng thái) → hỏi người dùng.
`plan.md` là kịch bản **one-shot cho lát hiện tại**; xong thì bỏ, KHÔNG dùng làm tham chiếu.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Agentic-Recruitment-System** (936 symbols, 1341 relationships, 24 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

> Index stale? Run `node .gitnexus/run.cjs analyze` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? `npx gitnexus analyze` (npm 11 crash → `npm i -g gitnexus`; #1939).

## Always Do

- **MUST run impact analysis before editing any symbol.** Before modifying a function, class, or method, run `impact({target: "symbolName", direction: "upstream"})` and report the blast radius (direct callers, affected processes, risk level) to the user.
- **MUST run `detect_changes()` before committing** to verify your changes only affect expected symbols and execution flows. For regression review, compare against the default branch: `detect_changes({scope: "compare", base_ref: "main"})`.
- **MUST warn the user** if impact analysis returns HIGH or CRITICAL risk before proceeding with edits.
- When exploring unfamiliar code, use `query({search_query: "concept"})` to find execution flows instead of grepping. It returns process-grouped results ranked by relevance.
- When you need full context on a specific symbol — callers, callees, which execution flows it participates in — use `context({name: "symbolName"})`.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method without first running `impact` on it.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit changes without running `detect_changes()` to check affected scope.

## Resources

| Resource | Use for |
|----------|---------|
| `gitnexus://repo/Agentic-Recruitment-System/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Agentic-Recruitment-System/clusters` | All functional areas |
| `gitnexus://repo/Agentic-Recruitment-System/processes` | All execution flows |
| `gitnexus://repo/Agentic-Recruitment-System/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
|------|---------------------|
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->
