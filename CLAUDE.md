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
| `screener`     | ✅ REAL  | **08a–08d DONE (GĐ3 hết):** suspend/resume (`interrupt()` + AsyncPostgresSaver/Neon) + **magic-link form** (token/hết hạn/one-time/row-lock → resume BẰNG câu trả lời) + **timeout/nhắc** (in-process sweep sau seam `ScreeningTimeoutScheduler`/`InProcessScheduler`: nhắc 1 lần → hết hạn resume `no_response` → human_review, KHÔNG auto-reject; trả lời trễ báo êm) + **gate auto-mời 08d** (sau resume: ca sạch + JD `auto_invite` ON → thư mời THẬT qua scheduler → INTERVIEW_SCHEDULED; no_response/cờ/low-conf/OFF → human_review; "cờ thắng gate"). Answers hiện cho HR (PRD §9, §10) |
| `scheduler`    | ✅ REAL  | sends real invite/rejection email via **Resend** (fixed VN templates); Calendar deferred |
| `human_review` | ✅ REAL  | ReviewCard + approve/reject → delegates to scheduler; audit-logged (PRD §11) |

Also REAL: JD management (create/edit/close) + embedding to Qdrant (`text-embedding-3-small`, 1536-dim);
**gate rank** (auto-reject, per-JD toggle, §9); **public CV submission** (`/apply`, guest, safe JD projection +
server-side magic-byte validation — slice 07); **Screener suspend/resume** (Postgres checkpointer, 08a) +
**magic-link form** (08b: `screening_session` token + email câu hỏi qua scheduler + public `/screening/{token}` +
`/api/public/screening/{token}` GET/POST + answers hiện cho HR) + **timeout/nhắc/trả lời trễ** (08c: seam
`ScreeningTimeoutScheduler`+`InProcessScheduler` sweep quét Postgres ở lifespan; handler nghiệp vụ
`screening_timeout.send_screening_reminder`/`handle_screening_timeout` tách khỏi cơ chế; cột `reminded_at`/
`timed_out_at`; timeout resume `no_response` → human_review) + **gate auto-mời** (08d: `route_after_screener`
đối xứng `route_after_ranker`; ca sạch + JD `auto_invite` → `scheduler_node` (SCHEDULING) → `resume_screener`
gửi thư mời THẬT → INTERVIEW_SCHEDULED; dispatch CÔ LẬP khỏi error handler; toggle auto_invite ở form JD);
PWA dashboard; HR pages `/cv-check`, `/applications` (list + score detail), `/review` (queue), `/jobs` (JD UI).
**HR auth (09, GĐ4 XONG):** `hr_user` (email + bcrypt hash) + seed từ env (`scripts/seed_hr_admin.py`,
idempotent); JWT HS256 trong cookie httpOnly (`core/security.py` — bcrypt trực tiếp + pyjwt, KHÔNG passlib);
`require_hr` dependency áp cấp-router lên `/api/jobs|applications|agents` + `GET /api/auth/me`; `login/logout/me`
(lỗi login CHUNG, chống enumeration + timing). Frontend: nhóm route `app/(hr)/` một guard gọi `/api/auth/me`
(KHÔNG middleware — cross-domain), `/login`, logout, `credentials:"include"`. Public/*+/apply+/screening MỞ.

**Object storage (06) DONE:** seam `services/storage` — `FileStorage` (save/get/url/delete, async) +
`LocalStorage` (dev, đĩa) + `R2Storage` (Cloudflare R2 qua S3/boto3, bọc `asyncio.to_thread`), chọn bằng
`STORAGE_BACKEND`. `cv_file_ref` = **KEY** `cv/{app_id}/{uuid}{đuôi}` (KHÔNG phải path). MỌI chỗ đọc/ghi CV
qua interface: `cv_reader.extract_text(data, name)` làm việc trên BYTES, `parser_node` async lấy bytes qua
`storage.get()`; `/api/agents/parse-cv` parse thẳng từ bytes (bỏ file tạm). **HR tải CV gốc:**
`GET /api/applications/{id}/cv` STREAM qua `storage.get()` trong router HR (`require_hr` → chưa login 401);
bucket R2 **PRIVATE**, KHÔNG public URL (NFR-4). `reset_demo_data` xóa file qua storage (sau commit DB).

**Deploy (13) — CODE-PREP XONG, chưa lên mạng.** Repo sẵn sàng deploy; phần tạo service Render/Vercel +
đặt env do NGƯỜI DÙNG làm (runbook), sau đó verify live cùng nhau. Đã có: **CORS từ env**
(`CORS_ORIGINS` CSV → allowlist cụ thể + `allow_credentials`; rỗng = dev fallback regex localhost; từ
chối `*`/thiếu scheme/có path vì Starlette so chuỗi CHÍNH XÁC — sai kiểu nào cũng ra cùng triệu chứng
"login 200 nhưng mất phiên"); **bind từ env** (`HOST`/`PORT`, reload CHỈ khi `app_env=local`);
**Dockerfile** (uv pin + `uv sync --frozen --no-dev`, non-root, `alembic upgrade head && exec python -m app`);
**`/api/health/live`** (liveness KHÔNG I/O — path cho health check nền tảng); **hardening công khai**
(`core/hardening.py`: body-size limit đọc-có-đếm + rate-limit cửa sổ trượt theo IP cho login/ghi công
khai/health-sâu, `PROXY_TRUSTED_HOPS` + log chẩn đoán khoá quota); `.env.example` có CHECKLIST env prod.

**NOT yet done:** analytics; observability; anti-prompt-injection; **runbook + verify live của 13**;
UI redesign; learning loop.

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
- Screener REAL (08a–08d complete: suspend/resume + magic-link + timeout/nhắc/trả lời trễ + gate auto-mời). Cả
  HAI gate (§9) đã xây: auto-reject (03c) + auto-mời (08d). HR auth (09) DONE: một vai HR-admin, seed từ env,
  KHÔNG đăng ký/quên/reset/RBAC/OAuth; ứng viên GUEST vĩnh viễn (KHÔNG account). Object storage (06) DONE.
  NOT yet built: analytics, observability, anti-injection, deploy, UI redesign, learning loop — keep stub +
  TODO pointing to PRD; don't build outside the current slice.
- **Storage boundary (06):** nghiệp vụ TUYỆT ĐỐI không mở path CV — chỉ qua `services/storage`
  (`get_storage().save/get/delete`). Thêm chỗ đọc/ghi CV mới → đi qua seam, nếu không sẽ vỡ khi
  `STORAGE_BACKEND=r2`. `cv_file_ref` là KEY (opaque), KHÔNG trả ra client (dùng `has_cv` + endpoint tải).
  Bucket PRIVATE + stream qua `require_hr` — KHÔNG public URL/presigned cho CV (NFR-4).
- **Auth boundary (09):** `require_hr` bảo vệ MỌI router HR (`/api/jobs|applications|agents` + `/api/auth/me`).
  GIỮ MỞ tuyệt đối: `/api/public/*`, `/api/auth/login|logout`, health — ứng viên guest KHÔNG bị chặn. Thêm
  router/endpoint HR mới → NHỚ áp `require_hr` (hoặc thêm vào `_HR_ONLY` trong `main.py`). Cookie Secure/SameSite/
  domain đọc TỪ ENV (dev: lax+insecure; prod cross-domain: none+secure) — đừng hardcode.
- NO Redis-polling worker queue — use BackgroundTasks. Screener timeout = **in-process sweep** (asyncio task ở
  lifespan quét Postgres, KHÔNG Redis) sau seam `ScreeningTimeoutScheduler` (đổi QStash sau không sửa nghiệp vụ).
- **Deploy boundary (13):** backend là **TIẾN TRÌNH BỀN**, KHÔNG serverless (sweep loop + pool checkpointer +
  BackgroundTasks cần process sống). Thêm origin frontend mới → thêm vào `CORS_ORIGINS`, ĐỪNG nới thành `*`
  (browser cấm wildcard khi có cookie). Thêm endpoint công khai mới → cân nhắc cho vào `_bucket()` của
  `RateLimitMiddleware`, nhưng **CHỈ siết method có body**: siết cả GET đã từng làm ứng viên hết quota rồi mất
  luôn bài dự tuyển. Health check của nền tảng phải trỏ `/api/health/live` (KHÔNG phải `/api/health`).
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
  Applies to BOTH gates: auto-mời (08d, in `resume_screener`) wraps `notify_decision("invite")` + status-write
  in its OWN try/except — once the invite email MAY have gone out, a later commit blip must NOT fall to the outer
  handler (→ PENDING_REVIEW[error] → HR từ chối = "mời xong lại từ chối"). INTERVIEW_SCHEDULED is set ONLY after
  `email_sent` is true (email-first, then status — no "trạng thái nói dối"); on send-fail → human_review.
- **LLM/embedding/Qdrant errors must NOT crash the pipeline** → try/except sets a flag (`parse_failed`/`rank_failed`) + escalation.
- **Windows dev + psycopg async:** the Screener checkpointer (`AsyncPostgresSaver`, PRD §10) uses psycopg async,
  which CANNOT run on Windows' default `ProactorEventLoop` — it needs `WindowsSelectorEventLoopPolicy`, set in
  `app/__main__.py` (win32-guarded, at module scope) BEFORE uvicorn creates its loop. Run the backend via
  `python -m app` (what `make dev-backend` now does), NOT `uvicorn app.main:app` directly. Linux/prod = no-op.
  Checkpointer connects to Neon's DIRECT endpoint (strip `-pooler`) to avoid PgBouncer prepared-statement issues.
- **Screener timeout sweep (08c) lifecycle:** the `InProcessScheduler` sweep task starts in lifespan AFTER
  `setup_checkpointer()` (timeout resume needs the compiled graph) and stops BEFORE teardown. It runs in the MAIN
  event loop (await graph resume directly — NO `asyncio.run` per-item, that was the 08a per-request trap). Each
  due session is processed in its OWN transaction with `SELECT … FOR UPDATE` + in-lock re-check; idempotency =
  `reminded_at`/`timed_out_at` + `status == AWAITING_SCREENER` filter. Verify with tiny env thresholds
  (`SCREENER_DEADLINE_HOURS`/`REMINDER_HOURS` are **float** → set <1h; `SCREENER_SWEEP_INTERVAL_SECONDS` low) then RESTORE.
- **passlib is dead — use `bcrypt` directly (09):** passlib 1.7.4 (2020, unmaintained) CRASHES against bcrypt 5.0
  (`detect_wrap_bug` → `ValueError: password cannot be longer than 72 bytes`). `core/security.py` calls `bcrypt`
  (pyca) directly + `pyjwt` for HS256. bcrypt truncates >72 bytes silently → we RAISE instead. Don't re-add passlib.
- **Login email = `str`, NOT `EmailStr` (09):** `EmailStr` rejects special-use TLDs (`.local`, internal domains)
  → an HR account seeded with such a domain could never log in (422). It's just a DB-matched identifier; validating
  format adds no security. Normalize `strip().lower()` in the handler. Login errors are GENERIC (no user enumeration)
  + verify a REAL dummy hash when email is unknown (constant-time-ish, no timing leak).
- **Frontend HR guard = `app/(hr)/` route group + `/api/auth/me`, NOT Next.js middleware (09):** middleware runs at
  the frontend edge and can't read the httpOnly cookie once backend is on a different domain (Vercel + Render) — it
  would pass in dev then silently fail on deploy. The real boundary is `require_hr` (backend); the layout guard is UX.
  URLs unchanged (route groups are transparent). `/login`, `/apply`, `/screening` live OUTSIDE `(hr)/`.
- **Alembic `include_object` guard is already global** in `env.py` (protects the 4 LangGraph checkpoint tables from
  autogenerate DROP). New model migrations inherit it — but STILL eyeball the autogen file + confirm the 4 tables
  survive (`SELECT … LIKE 'checkpoint%'`) before/after `upgrade head`.
- **Node async ⇒ MẤT thread-offload của LangGraph (06):** node `def` được LangGraph tự chạy trong thread
  executor; đổi sang `async def` thì nó `await` THẲNG trên event loop. `parser_node` thành async (để await
  storage) mà vẫn gọi `parse_cv` đồng bộ (PyMuPDF + LLM sync) → CHẶN cả event loop vài giây (adversarial
  review bắt được). Node async gọi code đồng bộ nặng → BẮT BUỘC `await asyncio.to_thread(...)`.
- **`cv_file_ref` rỗng = "không có CV" → parser chạy nhánh STUB và trả confidence 1.0** (trông như parse
  THÀNH CÔNG). Nên mọi đường ghi CV phải: lưu storage OK rồi mới gán key; lưu hỏng → XÓA hồ sơ + báo lỗi
  (503), tuyệt đối không để lại hồ sơ cv_file_ref rỗng ("dữ liệu nói dối").
- **Health check nền tảng ping VÀI GIÂY/LẦN, liên tục (13):** trỏ nó vào endpoint kiểm-sâu là tự phá hạ tầng
  của chính mình — `/api/health` ping Postgres+Redis+Qdrant mỗi lượt ⇒ ~17k lượt/ngày ⇒ vượt hạn mức Upstash
  free (10k lệnh/ngày) + giữ Neon không bao giờ tự ngủ (đốt compute-hours), trong khi KHÔNG có ai dùng hệ
  thống. Dùng `/api/health/live` (không I/O). Endpoint kiểm-sâu công khai cũng cần rate-limit, nếu không một
  vòng `curl` nặc danh đốt hộ.
- **Rate-limit sau proxy: khoá quota là chỗ dễ vỡ NHẤT (13).** Không tin X-Forwarded-For ⇒ khoá = peer TCP =
  router của nền tảng ⇒ CẢ THẾ GIỚI CHUNG MỘT XÔ (vài request nặc danh khoá sạch login HR, lặp vô hạn). Tin
  XFF nhưng lấy cứng phần phải nhất ⇒ chỉ đúng khi có ĐÚNG một chặng proxy; Render đặt Cloudflare trước
  `*.onrender.com` (có thể 2 chặng) ⇒ lại gộp chung xô. Vì thế: `trust_proxy` tự suy từ `app_env`,
  `PROXY_TRUSTED_HOPS` cấu hình được, và **log MỘT lần khoá quota đã suy ra + XFF thô** — đừng đoán số chặng,
  hãy đọc log trên bản live rồi chỉnh.
- **Chỉ rate-limit method CÓ BODY ở đường công khai (13):** siết cả GET nghĩa là ứng viên mở lại form screening
  (TanStack Query mặc định refetch mỗi lần focus tab) sẽ tiêu hết quota, rồi POST câu trả lời bị 429 → quá hạn
  → `no_response` → hồ sơ bị xử như không phản hồi. Guest KHÔNG có tài khoản để khiếu nại: mất bài dự tuyển vì
  cơ chế chống spam là cái giá không chấp nhận được.
- **Đừng trả 411 khi thiếu Content-Length (13):** trình duyệt luôn gửi Content-Length, nhưng request thật đi
  qua proxy — reverse proxy CÓ QUYỀN chuyển tiếp body dạng chunked. Nếu từ chối thẳng thì mọi lượt nộp CV chết
  trên bản live trong khi dev xanh mượt. Cách đúng: đọc CÓ ĐẾM tới hạn mức rồi phát lại body cho handler.
- **`.dockerignore` pattern KHÔNG có `/` chỉ khớp GỐC context:** viết trần `.env` bỏ sót `apps/backend/.env`
  (vị trí env_file dự phòng hợp lệ) → `COPY apps/backend/ ./` nướng secret vào layer image. Dùng `**/.env`.
  Ngược lại `*.md` ở gốc KHÔNG loại `apps/backend/README.md` (hatchling cần file này) — đúng ý đồ.
- **`chown -R` SAU khi dựng .venv nhân đôi cả cây thư viện thành một layer nữa** (image phình vài trăm MB,
  chậm mọi lần pull + cold start). Tạo user TRƯỚC rồi `COPY --chown`; nhớ `mkdir -p` + chown cây thư mục
  trước `WORKDIR` (WORKDIR tự tạo thư mục nhưng thuộc root → uv không ghi nổi `.venv`).
- **Dữ liệu CŨ trước 06:** `cv_file_ref` là path tuyệt đối Windows → `validate_key` từ chối (đúng ý đồ,
  chặn traversal). Không migrate (data dev); reset_demo_data báo "dọn thủ công", endpoint tải trả 502 rõ ràng.

---

## When in doubt

Lookup order: **PRD.md** (business, what the system should do) → **CLAUDE.md** (how to code + status) → **ROADMAP.md** (what's next) → ask the user.

**Sự cố live / vận hành (post-deploy):** xem `docs/deploy-live-issues.md` — tổng hợp problem sau khi
deploy + nguyên nhân gốc + fix + verify (Neon autosuspend giết pool checkpointer, rate-limit sau
Cloudflare, v.v.). Gặp lỗi tương tự hoặc trước khi đụng checkpointer/rate-limit/config deploy → đọc đó
trước. Problem MỚI sau fix → ghi vào docs đó, ĐỪNG nhồi vào CLAUDE.md (file này nạp mỗi session, giữ gọn).

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Agentic-Recruitment-System** (2136 symbols, 3662 relationships, 75 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
