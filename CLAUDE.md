# CLAUDE.md

Guidance for Claude Code working in this repo. Read every session.

## Source of truth

- **`PRD.md` is the SOURCE OF TRUTH for the system** — it is written in Vietnamese (the human-facing spec).
  Every business decision, flow, agent, state, and requirement lives there. If code conflicts with the PRD,
  the PRD wins (or update the PRD first, then change code). When unsure how the system *should behave*, open
  the PRD — do NOT improvise.
- **This file (CLAUDE.md)** covers HOW to build: stack, conventions, current status. Nạp MỖI session →
  **giữ gọn**; đừng nhồi thêm chi tiết vào đây.
- **`docs/AI_GUIDE.md`** giữ **ranh giới + gotcha** (tra cứu theo việc). **Mở nó TRƯỚC mọi task đụng code.**
- **`ROADMAP.md`** is the map of remaining slices and their order.
- A slice plan file (`plan.md` / `slice-*.md`), if one exists, is a ONE-SHOT script for the current
  slice only; delete it when done — never a reference.

## What the project is

**Autonomous Recruitment System using Multi-Agent AI.** Automates the screening loop from CV intake to sending
the invitation/rejection email; HR intervenes only at decision points or when the system isn't confident enough.

**Single-tenant, internal recruitment tool — NOT a two-sided job marketplace** (not TopCV/CareerViet). One
company; HR is the admin; applicants are guests. An applicant submits a CV for a specific JD and leaves
("fire and forget") — no account, no login, no status page. They receive the outcome later by email.

Fixed pipeline (PRD §7–§8): `parser → ranker → screener → scheduler` + conditional `human_review`.

- `parser`: CV (PDF/DOCX) → structured JSON.
- `ranker`: CV–JD match + rubric scoring. The DECISION node.
- `screener`: runs AFTER ranker; sends a fixed question set via email + magic-link form; **asynchronous**
  (pipeline suspend/resume, with timeout). NOT a free chatbot.
- `scheduler`: the SOLE execution point for every email to the applicant (invite + scheduling, or rejection).
- `human_review`: conditionally triggered; always with a **ReviewCard** (summary + score + reason); HR decides
  → delegates to scheduler.

Two configurable **gates** (PRD §9): `auto-reject`, `auto-invite` — HR toggles per JD; they act ONLY on
confident cases; uncertain cases ALWAYS go to human_review (gate is a no-op for them).

Locked architecture: **fixed pipeline, NO Supervisor** — deliberate, favoring predictability + auditability
(PRD §5, four pillars).

## Current status (update every slice)

> **Chi tiết từng slice (số đo, quyết định, lỗi đã vá) → `docs/status-history.md`.** Ở đây chỉ tóm tắt;
> slice mới: ghi chi tiết vào đó, thêm MỘT dòng vào danh sách dưới.

Tất cả node đều REAL: `parser` (`gpt-4.1-mini`, structured output) · `ranker` (`gpt-5-mini`,
reasoning_effort=low; embedding chỉ là tín hiệu PHỤ) · `screener` (suspend/resume `interrupt()` +
AsyncPostgresSaver, magic-link form, nhắc/timeout → human_review, KHÔNG auto-reject) · `scheduler` (điểm
phát email DUY NHẤT qua Resend, template VN cố định, `.ics`) · `human_review` (ReviewCard, audit-logged).
`ENABLE_LLM=true` bật parser+ranker thật; `false` giữ stub (cho `test_graph`).

Slice đã XONG (tóm tắt — chi tiết ở `docs/status-history.md`):

- **JD + gate:** quản lý JD + embedding Qdrant (`text-embedding-3-small`, 1536-dim); gate auto-reject /
  auto-invite theo JD (§9) — "cờ thắng gate".
- **07 `/apply`:** nộp CV công khai (guest, projection JD an toàn, kiểm magic-byte phía server).
- **08a–08d Screener:** checkpointer Postgres, magic-link `/screening/{token}`, sweep nhắc/timeout, gate auto-mời.
- **09 HR auth:** `hr_user` + bcrypt, JWT HS256 cookie httpOnly, `require_hr` cấp-router; frontend guard ở `app/(hr)/` (KHÔNG middleware).
- **06 Storage:** seam `services/storage` (Local/R2); `cv_file_ref` là KEY, không phải path; bucket R2 PRIVATE.
- **13 Deploy LIVE:** Render + Cloudflare / Vercel / Neon / Qdrant / R2; sự cố prod → `docs/deploy-live-issues.md`.
- **14 Hardening tải:** session ĐỌC → CHẠY → GHI; lưới đối soát `stuck_applications`.
- **SCH-1/2/3 Đặt lịch (§10b):** ứng viên tự chọn giờ qua `/booking/{token}`, `AWAITING_BOOKING`, partial
  unique index chống đặt trùng, huỷ/gửi lại link, vòng đời nhắc/hết hạn trong sweep 08c.
- **EMAIL-1/2/3:** webhook Resend đã ký (`delivered/bounced/complained/failed`), giữ nhịp + retry, HR gửi lại thư hỏng.
- **Verify prod E2E (18/08):** 4 lỗi vá. **DASH-1:** bảng điều hành soi pipeline (`/api/applications/pipeline`).
- **CVT-1:** kho CV mẫu tĩnh `/cv-templates`. **PWA-1:** rút gọn bản cài + trang offline, SW v3.
- **UI redesign:** token **Marine**, thương hiệu **HireFlow** (tên kỹ thuật vẫn là ARS).
- **LOAD-1:** ≤80 CV đồng thời 0 mất; nút thắt = khoá của `AsyncPostgresSaver` → `MAX_CONCURRENT_PIPELINES`
  + `OPENAI_TIMEOUT_SECONDS` (đi CẶP). Số đo → `docs/load-and-scale.md`.
- **AUDIT-1/2:** phân trang + lọc server cho `/api/applications`; trần ký tự CV + cờ `cv_truncated`;
  trích PDF trong tiến trình con giết được + chặn DOCX zip bomb.
- **CONFIG-1 (NFR-8):** 39 hằng số nghiệp vụ trong bảng `app_config` + màn `/system`; lưu xong phải
  `coerce()` + `invalidate_caches()`. Đường đọc `audit_log`.
- **12 Anti-injection (NFR-5):** CV là dữ liệu KHÔNG tin cậy — loại chữ ẩn (`hidden_text`), prompt parser tách
  system + dấu phân cách ngẫu nhiên, cắt câu chỉ dẫn, hậu kiểm → `injection_suspected` → human_review.

**NOT yet done:** analytics; `email.suppressed`; mở `/cv-check` cho ứng viên (cần
endpoint công khai + rate-limit ⇒ slice riêng); runbook của 13; learning loop; Google Calendar (đang `.ics`).
Observability ĐÃ BỎ khỏi phạm vi. Nợ sau AUDIT-1: cảnh báo `no_slots_at` giả, TOCTOU sinh khung giờ.

## Stack

- **Backend:** Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2. Package mgr: `uv`.
- **Infra (managed-first):** Neon (Postgres) · Qdrant Cloud · Cloudflare R2. Local fallback: `docker-compose.local.yml`.
- **LLM (OpenAI):** parser `gpt-4.1-mini`; ranker `gpt-5-mini` (reasoning_effort=low); embeddings
  `text-embedding-3-small` (1536-dim). **Email: Resend.**
- **Async:** FastAPI BackgroundTasks (NO worker polling — no extra queue infra to feed). Screener uses
  suspend/resume (LangGraph interrupt + Postgres checkpointer) — REAL, see 08a-08d above.
- **Frontend:** Next.js 14 · **Tailwind thuần + hệ token "Marine" tự khai** (xem `tailwind.config.ts`) ·
  TanStack Query. shadcn/ui NOT installed —
  use utility classes + hand-written components; DO NOT add a UI library. API base from env `NEXT_PUBLIC_API_BASE`.
- **PWA:** installable HR dashboard (no separate mobile codebase).
- **Monorepo:** pnpm workspaces; shared code in `packages/shared-types`.

## Commands (and where to run them)

- **Backend (Python/uv) → Bash:** `make dev-backend` · `make test` · `make migrate`. Single scripts/tests:
  `uv run --directory apps/backend python …` / `uv run --directory apps/backend pytest -q`.
- **Node (pnpm/next/tsc) → PowerShell** (Git Bash breaks on fnm): `pnpm --filter dashboard dev|build|typecheck`.
- **git → Bash but AVOID `cd`** (fnm hook breaks): use `git -C <repo-root> …`.
- Integration tests hitting real APIs are gated: set `RUN_EMBED_IT=1` / `RUN_PARSE_IT=1` (default skip, keeps `make test` fast).

## Code conventions (MANDATORY)

- **Async-first** backend: async engine/session/route. No mixed sync I/O.
- **Config from env** via pydantic-settings. NO hardcoded secret/URL/threshold.
- **Full typing:** type hints (Python), no loose `any` (TS).
- **Secrets only in `.env`** (gitignored). Commit only `.env.example`.
- **Small commits per step:** clear message, slice-prefixed (`feat(parser): …`, `fix(…)`, `test(…)`, `chore(…)`).
- **Neon needs SSL:** `connect_args={"ssl": True}` in `create_async_engine`. NOT `?sslmode=` (asyncpg won't parse it).
- **scheduler is the SOLE email-send point** to applicants — don't scatter email sends in other nodes.

## Four working principles

*(Distilled from Karpathy's observations on LLM coding failures. Bias toward caution over speed.)*

1. **Think before coding — don't assume, don't hide confusion.** State assumptions; unsure → ASK. Multiple
   interpretations → PRESENT the options, don't silently pick one. Simpler way exists → SAY SO. Business unclear
   → open the PRD; PRD insufficient → ask, don't improvise.
2. **Simplicity first — minimum code that solves the problem.** No features beyond the ask. No abstractions for
   single-use code. 200 lines where 50 suffice → rewrite. Nodes not yet in scope stay stub — don't "make them nice."
3. **Surgical edits — touch only what you must.** Don't "improve" surrounding code/comments/format. Don't refactor
   what isn't broken. See unrelated dead code → mention it, don't delete. Every changed line traces to a requirement (or PRD item).
4. **Goal-directed execution — define success criteria, then iterate until verified.** Each slice: a real Verify
   (show the user output) + independent review before finalizing; each PRD requirement (FR-xxx) is a criterion —
   write a test reflecting it, make it pass.

## Ranh giới & Gotcha → `docs/AI_GUIDE.md`

**Mỗi task đụng code: MỞ `docs/AI_GUIDE.md` TRƯỚC** — *Current boundaries* (không được vượt) + *Gotchas*
(bẫy đã vấp, kèm nguyên nhân gốc). Quét theo thứ sắp sửa: CV/file → *Storage*; thêm router → *Auth*;
CORS/rate-limit/health → *Deploy*; DB trong đường có gọi LLM/mạng → *Load*; chấm điểm → *Ranker*.
**Gotcha mới → ghi vào `docs/AI_GUIDE.md`, KHÔNG nhồi vào file này.**

## When in doubt

Lookup order: **PRD.md** → **CLAUDE.md** → **`docs/AI_GUIDE.md`** → **ROADMAP.md** → ask the user.
**Sự cố live / vận hành:** `docs/deploy-live-issues.md` (đọc TRƯỚC khi đụng checkpointer / rate-limit /
config deploy; problem MỚI ghi vào đó). **Lịch sử slice:** `docs/status-history.md`.

## GitNexus — đọc CÁI NÀY trước khối tự sinh bên dưới

Khối dưới marker do công cụ TỰ SINH (ghi đè mỗi lần index lại) — đính chính bắt buộc (kiểm 2026-08-04):

1. **LUÔN truyền `repo: "Agentic-Recruitment-System"`** (máy index nhiều repo). Thiếu `repo`:
   `impact`/`context` trả `"Target not found"` (KHÔNG phải symbol không tồn tại); `detect_changes()` trả
   "No changes detected" dù đang có file sửa — XANH GIẢ ngay trước commit.
2. **`impact` KHÔNG thấy hàm chỉ được đăng ký runtime** (vd `process_application` qua
   `background_tasks.add_task` ra `impactedCount: 0`) — báo LOW không có nghĩa là an toàn, grep thêm.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Agentic-Recruitment-System** (3597 symbols, 6659 relationships, 146 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
