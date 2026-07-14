# CLAUDE.md

Guidance for Claude Code working in this repo. Read every session.

## Source of truth

- **`PRD.md` is the SOURCE OF TRUTH for the system** — it is written in Vietnamese (the human-facing spec).
  Every business decision, flow, agent, state, and requirement lives there. If code conflicts with the PRD,
  the PRD wins (or update the PRD first, then change code). When unsure how the system *should behave*, open
  the PRD — do NOT improvise.
- **This file (CLAUDE.md)** covers HOW to build: stack, conventions, current status, boundaries, gotchas.
- **`ROADMAP.md`** is the map of remaining slices and their order.
- `plan.md` / `slice-*.md` is a ONE-SHOT script for the current slice only; discard when done — never a reference.

---

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

---

## Current status (update every slice)

Past scaffold — building real logic slice by slice. Node REAL vs STUB:

| Node           | Status   | Notes |
| -------------- | -------- | ----- |
| `parser`       | ✅ REAL  | CV→JSON via OpenAI `gpt-4.1-mini` (structured output) + certificates/languages/awards/other |
| `ranker`       | ✅ REAL  | reasoned rubric scoring via `gpt-5-mini` (reasoning_effort=low); embedding = SIDE signal only |
| `screener`     | 🟡 PARTIAL | **08a DONE:** suspend/resume real (`interrupt()` + AsyncPostgresSaver/Neon, bền qua restart; đạt→screener→resume→human_review). Form magic-link + bộ câu hỏi email + timeout/nhắc + gate auto-mời = 08b/c/d (PRD §10) |
| `scheduler`    | ✅ REAL  | sends real invite/rejection email via **Resend** (fixed VN templates); Calendar deferred |
| `human_review` | ✅ REAL  | ReviewCard + approve/reject → delegates to scheduler; audit-logged (PRD §11) |

Also REAL: JD management (create/edit/close) + embedding to Qdrant (`text-embedding-3-small`, 1536-dim);
**gate rank** (auto-reject, per-JD toggle, §9); **public CV submission** (`/apply`, guest, safe JD projection +
server-side magic-byte validation — slice 07); **Screener suspend/resume** (Postgres checkpointer, 08a);
PWA dashboard; HR pages `/cv-check`, `/applications` (list + score detail), `/review` (queue), `/jobs` (JD UI).

**NOT yet done:** Screener 08b (form magic-link + bộ câu hỏi email → resume câu trả lời thật, thay endpoint
test `/api/agents/resume-screener`) / 08c (timeout/nhắc/trả lời trễ) / 08d (gate auto-mời — §9); object storage
(local disk for now); HR auth; analytics; observability; anti-prompt-injection; deploy; UI redesign; learning loop.

`ENABLE_LLM=true` enables real parser+ranker; `false` keeps stubs (for `test_graph`).

---

## Stack

- **Backend:** Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2. Package mgr: `uv`.
- **Infra (managed-first):** Neon (Postgres) · Upstash Redis · Qdrant Cloud. Local fallback: `docker-compose.local.yml`.
- **LLM (OpenAI):** parser `gpt-4.1-mini`; ranker `gpt-5-mini` (reasoning_effort=low); embeddings
  `text-embedding-3-small` (1536-dim). **Email: Resend.**
- **Async:** FastAPI BackgroundTasks (NO worker polling — kills Upstash free tier). Screener uses suspend/resume
  (LangGraph interrupt + Postgres checkpointer — later phase).
- **Frontend:** Next.js 14 · **plain Tailwind (slate palette)** · TanStack Query. shadcn/ui NOT installed —
  use utility classes + hand-written components; DO NOT add a UI library. API base from env `NEXT_PUBLIC_API_BASE`.
- **PWA:** installable HR dashboard (no separate mobile codebase).
- **Monorepo:** pnpm workspaces; shared code in `packages/shared-types`.

---

## Commands (and where to run them)

- **Backend (Python/uv) → Bash:** `make dev-backend` · `make test` · `make migrate`. Single scripts/tests:
  `uv run --directory apps/backend python …` / `uv run --directory apps/backend pytest -q`.
- **Node (pnpm/next/tsc) → PowerShell** (Git Bash breaks on fnm): `pnpm --filter dashboard dev|build|typecheck`.
- **git → Bash but AVOID `cd`** (fnm hook breaks): use `git -C <repo-root> …`.
- Integration tests hitting real APIs are gated: set `RUN_EMBED_IT=1` / `RUN_PARSE_IT=1` (default skip, keeps `make test` fast).

---

## Code conventions (MANDATORY)

- **Async-first** backend: async engine/session/route. No mixed sync I/O.
- **Config from env** via pydantic-settings. NO hardcoded secret/URL/threshold.
- **Full typing:** type hints (Python), no loose `any` (TS).
- **Secrets only in `.env`** (gitignored). Commit only `.env.example`.
- **Small commits per step:** clear message, slice-prefixed (`feat(parser): …`, `fix(…)`, `test(…)`, `chore(…)`).
- **Neon needs SSL:** `connect_args={"ssl": True}` in `create_async_engine`. NOT `?sslmode=` (asyncpg won't parse it).
- **scheduler is the SOLE email-send point** to applicants — don't scatter email sends in other nodes.

---

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

---

## Current boundaries

- NO Supervisor Agent / dynamic orchestration — fixed pipeline (PRD §5).
- Nodes not yet in scope stay STUB: `screener` (still stub). NOT yet built: gate INVITE (§9), Screener async
  (§10), object storage, auth, analytics, observability, anti-injection, deploy, UI redesign, learning loop —
  keep stub + TODO pointing to PRD; don't build outside the current slice.
- NO Redis-polling worker queue — use BackgroundTasks.
- **Ranker:** score is ONLY the reasoned rubric (weights from the JD); cosine/embedding is a SIDE signal, NOT in
  the score, NO JD chunking. confidence/flags = DETERMINISTIC heuristic (don't ask the LLM to self-score).
- **scheduler is the SOLE email-send point** — don't scatter sends.
- **Applicant = guest, fire-and-forget:** no applicant account, no login, no applicant-facing status/score. Only
  HR sees scores/status. (The auth phase covers HR only — never re-introduce applicant accounts.)
- **Public JD projection must NOT leak** `rubric` / `gate_config` / `screener_questions` (applicants gaming the rubric).
- **Reserved architectural slots (exist):** `RecruitmentState` has confidence/uncertainty_flags/escalation_reason/
  require_human_review + score/score_breakdown/semantic_similarity + Screener fields; `policy` routes on real
  values; `audit_log` has the needed columns (PRD §16).

---

## Gotchas encountered (read before repeating)

- **Async node in pipeline:** ranker is `async` → `runner.run_sync` uses `asyncio.run(ainvoke)`; parser stays
  sync; mixed graph runs OK. New async node → remember this sync path.
- **langchain-openai DROPS `temperature`** for reasoning models (gpt-5*): the reasoning branch passes
  `reasoning_effort`, NOT temperature. `RANKER_MODEL=gpt-5-mini` REQUIRES `RANKER_REASONING_EFFORT=low`.
- **Qdrant Cloud** requires a payload index for filtered fields (`type`); `create_collection` isn't idempotent
  (409) — handled via `asyncio.Lock` + tolerating 409 in `ensure_collection`.
- **str.format prompts:** literal `{...}` must be escaped `{{...}}` (forgetting → KeyError, every parse fails).
- **curl UTF-8 (Git Bash):** Vietnamese JSON body must use `--data-binary @file` (inline `-d` mangles diacritics).
- **`require_human_review` is the ranker's "low-score marker"** (set for every below-threshold score), NOT an
  uncertainty signal — the gate uses it as its trigger. uncertainty = error / uncertainty_flags / low-confidence only.
- **Post-commit email dispatch must be isolated from the technical-error handler:** a decision already committed
  (e.g. auto-reject → REJECTED) must SURVIVE an email/audit failure — don't let an escaping exception reset status.
- **LLM/embedding/Qdrant errors must NOT crash the pipeline** → try/except sets a flag (`parse_failed`/`rank_failed`) + escalation.
- **Windows dev + psycopg async:** the Screener checkpointer (`AsyncPostgresSaver`, PRD §10) uses psycopg async,
  which CANNOT run on Windows' default `ProactorEventLoop` — it needs `WindowsSelectorEventLoopPolicy`, set in
  `app/__main__.py` (win32-guarded, at module scope) BEFORE uvicorn creates its loop. Run the backend via
  `python -m app` (what `make dev-backend` now does), NOT `uvicorn app.main:app` directly. Linux/prod = no-op.
  Checkpointer connects to Neon's DIRECT endpoint (strip `-pooler`) to avoid PgBouncer prepared-statement issues.

---

## When in doubt

Lookup order: **PRD.md** (business, what the system should do) → **CLAUDE.md** (how to code + status) → **ROADMAP.md** (what's next) → ask the user.

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