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
| `screener`     | ✅ REAL  | **08a–08d DONE (GĐ3 hết):** suspend/resume (`interrupt()` + AsyncPostgresSaver/Neon) + **magic-link form** (token/hết hạn/one-time/row-lock → resume BẰNG câu trả lời) + **timeout/nhắc** (in-process sweep sau seam `ScreeningTimeoutScheduler`/`InProcessScheduler`: nhắc 1 lần → hết hạn resume `no_response` → human_review, KHÔNG auto-reject; trả lời trễ báo êm) + **gate auto-mời 08d** (sau resume: ca sạch + JD `auto_invite` ON → thư mời THẬT qua scheduler → **AWAITING_BOOKING** (SCH-2 đổi: kèm link tự đặt lịch); no_response/cờ/low-conf/OFF → human_review; "cờ thắng gate"). Answers hiện cho HR (PRD §9, §10) |
| `scheduler`    | ✅ REAL  | điểm phát email DUY NHẤT qua **Resend** (template VN cố định): mời/từ chối/sàng lọc + **6 loại thư đặt lịch** (mời có link, xác nhận kèm `.ics` + link huỷ, nhắc trước PV, nhắc chọn lịch, báo huỷ). Google Calendar deferred (seam `IcsProvider`). **EMAIL-1 XONG:** giao hàng có theo dõi (webhook Resend đã ký) + giữ nhịp/retry + `reply_to`/bản text + cờ bounce/complaint hiện cho HR |
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
gửi thư mời THẬT → AWAITING_BOOKING (SCH-2); dispatch CÔ LẬP khỏi error handler; toggle auto_invite ở form JD);
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

**Deploy (13) — ✅ ĐÃ LIVE** (Render Docker sau Cloudflare + Vercel + Neon/Upstash/Qdrant/R2; cross-domain
cookie `SameSite=None; Secure` + CORS allowlist chạy thật). **4 sự cố prod đã vá** — chi tiết +
cách verify ở `docs/deploy-live-issues.md` (ĐỌC TRƯỚC khi đụng checkpointer / rate-limit / config deploy).
Code-prep đã có: **CORS từ env**
(`CORS_ORIGINS` CSV → allowlist cụ thể + `allow_credentials`; rỗng = dev fallback regex localhost; từ
chối `*`/thiếu scheme/có path vì Starlette so chuỗi CHÍNH XÁC — sai kiểu nào cũng ra cùng triệu chứng
"login 200 nhưng mất phiên"); **bind từ env** (`HOST`/`PORT`, reload CHỈ khi `app_env=local`);
**Dockerfile** (uv pin + `uv sync --frozen --no-dev`, non-root, `alembic upgrade head && exec python -m app`);
**`/api/health/live`** (liveness KHÔNG I/O — path cho health check nền tảng); **hardening công khai**
(`core/hardening.py`: body-size limit đọc-có-đếm + rate-limit cửa sổ trượt theo IP cho login/ghi công
khai/health-sâu, `PROXY_TRUSTED_HOPS` + log chẩn đoán khoá quota); `.env.example` có CHECKLIST env prod.

**Hardening tải (14) XONG:** `process_application` tách vòng đời session **ĐỌC → CHẠY → GHI** (trước đây
một session giữ connection + TRANSACTION MỞ trọn cả hai lượt LLM); TOÀN BỘ thân hàm trong MỘT try (thao
tác DB đầu tiên trước nằm NGOÀI → pool cạn là ném thẳng ra BackgroundTasks, hồ sơ mất im lặng);
`_escalate_technical_error` mở session MỚI + KHÔNG BAO GIỜ raise; lưới đối soát
`services/stuck_applications` (SUBMITTED/PARSING/RANKING quá `STUCK_APPLICATION_TIMEOUT_MINUTES`=30 →
PENDING_REVIEW[error], KHÔNG auto-reject) đi chung sweep loop 08c. **Số đo thật (5 CV, tuần tự):**
T=34.3s (parser 9.4s · ranker 24.7s ⇒ ranker chiếm 72%); connection giữ 0.68s = **2% của T** (trước:
100%) ⇒ trần một đợt **28 → 678 hồ sơ**. Nút thắt kế tiếp: thread pool 14 luồng (parser gọi LLM ĐỒNG BỘ,
~1.5 CV/s bền) rồi RAM (~11MB/CV 10MB đang bay). Công cụ: `scripts/loadtest_apply.py`.

**Đặt lịch — ứng viên tự chọn giờ (SCH-1 + SCH-2 + SCH-3 XONG — FEATURE ĐÃ KHÉP, PRD §10b):** CHẠY THẬT
end-to-end. **SCH-3 (vòng đời sau khi gửi link):** `services/booking_lifecycle.sweep_once` ghép vào **sweep
loop 08c** (KHÔNG cơ chế nền mới) chạy BA lưới — nhắc trước buổi PV (`BOOKING_INTERVIEW_REMINDER_HOURS`, kèm
`.ics`), nhắc chọn lịch khi link sắp hết hạn (`BOOKING_REMINDER_HOURS`, dùng LẠI token cũ), và hết hạn chưa
đặt → `PENDING_REVIEW` + cờ `booking_no_response` + nhả HELD sót (**KHÔNG auto-reject**). Ứng viên tự huỷ qua
`POST /api/public/booking/{token}/cancel` (chính token đó) → nhả khung giờ **TỨC THÌ** → link còn hạn thì về
`AWAITING_BOOKING` chọn lại **trong hạn CŨ** (`mark_session_reopened` xoá `booked_at` nên TTL gốc áp lại —
KHÔNG gia hạn), hết hạn thì `PENDING_REVIEW`. HR có **Huỷ lịch** + **Gửi lại link** (ghép lại = "đổi lịch",
không có luồng dời riêng). Hết khung giờ → `no_slots_at` + nhãn dashboard RIÊNG "Hết khung giờ — cần mở thêm
lịch" (cờ tự tắt khi có slot lại). Sức chứa nâng: `MAX_PER_DAY=6` · `WINDOW_DAYS=21` · `HOLD_MINUTES=5`
(≈90 khung ⇒ ~18 người xem đồng thời; trước 4/14/10 ≈ 36 khung ⇒ ~7 người).
**SCH-2:** cả BA đường quyết định mời (gate lần-đầu, gate sau-screener, HR duyệt) đi chung
`services/booking_flow.dispatch_booking_invite` → thư mời KÈM LINK `/booking/{token}` → **`AWAITING_BOOKING`**
(chỉ sau khi email gửi THÀNH CÔNG — bất biến 08d); `INTERVIEW_SCHEDULED` nay đặt lúc ứng viên CHỌN XONG giờ.
Endpoint công khai `GET/POST /api/public/booking/{token}` (projection an toàn; `already_booked` = 200 chứ
không phải lỗi; thua race = 409) + trang `/booking/[token]` (giờ VN, đếm ngược hold, 409 tự làm mới) + thư
xác nhận kèm `.ics`. **Thứ tự KHÁC nhau có chủ ý:** gửi thư mời = *email trước, trạng thái sau*; xác nhận
lịch = *DB trước, email sau* (ứng viên đang nhìn màn xác nhận nên họ ĐÃ biết; thư chỉ là biên nhận — gửi
hỏng thì GIỮ lịch + gắn cờ cho HR). Adversarial review bắt **7 lỗi thật** (TOCTOU giữ chỗ, đếm hạn mức sai,
`except` tự ném, giữ khoá qua lượt gửi mail, link 404, token cũ lật ngược quyết định HR, deadlock ra 500)
— đã vá + 5 test hồi quy trên DB thật.

**Nền SCH-1 (PRD §10b):** tầng nghiệp vụ thuần.
`InterviewBooking`/`BookingSession` + migration viết tay **partial unique index** `UNIQUE(start_at) WHERE
status='BOOKED'` (chốt chặn cuối chống đặt trùng; HELD chỉ là khuyến nghị nên hai người cùng HELD một giờ
là HỢP LỆ); khả dụng TOÀN CỤC qua 14 env `BOOKING_*` → `services/booking_config.BookingConfig` (có validate);
`booking_service.generate_slots` sinh **lười** + giữ chỗ `BOOKING_HOLD_MINUTES` + **bấm lại trả ĐÚNG slot cũ**
+ trộn sáng/chiều nhiều ngày, `confirm_booking` HELD→BOOKED chống race (`IntegrityError` → `SlotTaken` dịch
409), `release_holds`/`cancel_booked`; seam `services/calendar` (`CalendarProvider` + `IcsProvider`
0-dependency, giờ UTC trong `.ics`). Test: 49 trong `make test` + 33 gated `RUN_BOOKING_IT=1`
(**race thật 2 transaction**, huỷ nhả slot tức thì, sweep không đụng người vừa đặt).
Ranh giới + bẫy → `docs/AI_GUIDE.md` *Booking boundary*.

**Email hardening (EMAIL-1) XONG:** bảng `email_delivery` (1 hàng/lá thư, khoá đối chiếu
`resend_email_id`) theo dõi giao hàng qua webhook Resend đã ký (`/api/webhooks/resend`, HMAC +
chống replay); giữ nhịp 2 req/s + retry lỗi tạm thời (không retry lỗi vĩnh viễn/cạn quota);
`EMAIL_REPLY_TO` + bản text đủ link. Bounce hạ trạng thái có điều kiện (không auto-reject); complaint
CHỈ gắn cờ (dừng gửi, không hạ). Cờ `email_bounced`/`email_complained` hiện cho HR ở mọi trạng thái.
Chi tiết + gotcha → `docs/AI_GUIDE.md` *Email boundary*.

**EMAIL-2 (`email.failed`) XONG:** webhook nay xử lý cả `email.failed` → `DeliveryStatus.FAILED` +
cờ RIÊNG `email_send_failed` (KHÔNG phải `email_failed` — chuỗi đó `scheduler._dispatch` đã chiếm
làm tên audit action) + lý do đọc từ `data.failed.reason`. Hạ trạng thái CÓ điều kiện như bounce,
TRỪ `screener_reminder` (thư nhắc chở lại chính link đã giao thành công). `_NEGATIVE` nay DẪN XUẤT
từ `_STATUS_FLAG`. Không cần migration (`status` là `varchar(16)`).

**VERIFY PROD E2E (18/08/2026) — ĐÃ CHẠY THẬT, 4 lỗi tìm được + đã vá:** dọn sạch prod rồi chạy trọn
vòng đời trên bản live (JD + AI-gợi-ý-rubric → 4 CV → cả 3 nhánh quyết định → magic-link sàng lọc →
gate auto-mời → ứng viên tự chọn giờ → huỷ/đặt lại → HR duyệt). Webhook Resend nay CÓ bằng chứng
chạy thật trên prod: `delivered` · `bounced` (hạ trạng thái + huỷ phiên đúng) · `complained` (chỉ
gắn cờ). Bốn lỗi: **(1)+(2) HTTP 500 ở CẢ HAI nút lịch của HR** (`cancel_by_hr`,
`resend_booking_link` — thiếu `refresh` nên `updated_at` expired làm `model_validate` nổ
`MissingGreenlet`; nghiệp vụ vẫn chạy xong nên rất dễ chẩn đoán sai); **(3)** `escalation_reason`
của ca auto-từ-chối ghi sai "(auto-từ-chối chưa bật)"; **(4)** thư sàng lọc in "72.0 giờ". Chi tiết
+ cách tránh → `docs/AI_GUIDE.md` (2 gotcha cuối).

**NOT yet done:** analytics; observability; anti-prompt-injection; `email.suppressed` (xem AI_GUIDE);
**runbook của 13**; test tải + scale;
UI redesign; learning loop. Hardening tải còn nợ: semaphore chặn số pipeline song song, parser dùng
`ainvoke` (bỏ thread pool), và **đường NHẬN CV vẫn giữ connection suốt lúc upload R2** (xem gotcha `refresh()`).

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

## Ranh giới & Gotcha → `docs/AI_GUIDE.md`

**Mỗi task đụng code: MỞ `docs/AI_GUIDE.md` TRƯỚC.** Ở đó có (a) *Current boundaries* — những thứ tuyệt
đối không được vượt (pipeline cố định, storage seam, auth, deploy, tải-đồng-thời, ranker, email, guest,
projection JD công khai), và (b) *Gotchas* — mọi cái bẫy đã vấp thật, kèm nguyên nhân gốc.

Không chắc mục nào liên quan? Quét theo thứ bạn sắp sửa: đụng CV/file → *Storage boundary*; thêm router →
*Auth boundary*; đụng CORS/rate-limit/health → *Deploy boundary*; đụng DB trong đường có gọi LLM/mạng →
*Load boundary*; đụng chấm điểm → *Ranker*.

**Gotcha mới phát hiện → ghi vào `docs/AI_GUIDE.md`, KHÔNG nhồi vào file này** (file này nạp mỗi session).

---

## When in doubt

Lookup order: **PRD.md** (business, what the system should do) → **CLAUDE.md** (how to code + status) →
**`docs/AI_GUIDE.md`** (ranh giới được phép làm gì + bẫy đã vấp) → **ROADMAP.md** (what's next) → ask the user.

**Sự cố live / vận hành (post-deploy):** xem `docs/deploy-live-issues.md` — tổng hợp problem sau khi
deploy + nguyên nhân gốc + fix + verify (Neon autosuspend giết pool checkpointer, rate-limit sau
Cloudflare, v.v.). Gặp lỗi tương tự hoặc trước khi đụng checkpointer/rate-limit/config deploy → đọc đó
trước. Problem MỚI sau fix → ghi vào docs đó, ĐỪNG nhồi vào CLAUDE.md (file này nạp mỗi session, giữ gọn).

## GitNexus — đọc CÁI NÀY trước khối tự sinh bên dưới

Khối dưới marker do công cụ TỰ SINH (ghi đè mỗi lần index lại) nên **không sửa được ở đó** — hai đính
chính bắt buộc, đã kiểm chứng ngày 2026-08-04:

1. **LUÔN truyền `repo: "Agentic-Recruitment-System"`.** Máy này index NHIỀU repo (còn `aov-bundle`), và
   khi đó `impact`/`context` **thiếu `repo` sẽ trả `"Target not found"`** — nghe như "symbol không tồn
   tại", thực ra là "bạn chưa nói repo nào". Đã mất một phiên vì tưởng index hỏng rồi bỏ sang `grep`.
   (`query` thì báo lỗi rõ ràng; `impact`/`context` thì không.)
2. **`impact` KHÔNG thấy hàm chỉ được đăng ký runtime.** `process_application` ra `impactedCount: 0`
   dù có 2 chỗ `background_tasks.add_task(process_application, …)` — đó là tham chiếu, không phải cạnh
   gọi tĩnh. Với hàm chạy qua BackgroundTasks/handler đăng ký động, **`impact` báo LOW không có nghĩa
   là an toàn** — grep thêm cho chắc.

`detect_changes()` cũng cần `repo`; thiếu nó nó trả "No changes detected" **dù đang có file sửa** — một
kết quả XANH GIẢ, đúng thứ nguy hiểm nhất ngay trước lúc commit.

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
