# AI_GUIDE — Ranh giới & Gotcha (đọc TRƯỚC mỗi task đụng code)

> Tách khỏi `CLAUDE.md` để file nạp-mỗi-session giữ gọn. Đây là phần **tra cứu theo việc**:
> mở đúng mục liên quan tới thứ bạn sắp sửa, không cần đọc hết.
>
> - **Sắp sửa code?** đọc *Current boundaries* — thứ TUYỆT ĐỐI không được vượt.
> - **Sắp đụng storage / auth / deploy / tải-đồng-thời / ranker?** đọc đúng mục "boundary" của nó.
> - **Gặp lỗi lạ, hoặc sắp làm điều gì đó "chắc là ổn"?** quét *Gotchas* trước — mỗi dòng ở đó là
>   một lần đã mất thời gian thật.
>
> Nghiệp vụ (*hệ thống PHẢI hành xử ra sao*) vẫn ở **`PRD.md`**. Trạng thái từng lát + stack + lệnh ở
> **`CLAUDE.md`**. Sự cố sau khi deploy ở **`docs/deploy-live-issues.md`**.
>
> **Thêm gotcha mới vào ĐÂY, đừng nhồi vào `CLAUDE.md`.**

---

## Current boundaries

- NO Supervisor Agent / dynamic orchestration — fixed pipeline (PRD §5).
- Screener REAL (08a–08d complete: suspend/resume + magic-link + timeout/nhắc/trả lời trễ + gate auto-mời). Cả
  HAI gate (§9) đã xây: auto-reject (03c) + auto-mời (08d). HR auth (09) DONE: một vai HR-admin, seed từ env,
  KHÔNG đăng ký/quên/reset/RBAC/OAuth; ứng viên GUEST vĩnh viễn (KHÔNG account). Object storage (06) DONE.
  Deploy (13) ĐÃ LIVE. NOT yet built: analytics, observability, anti-injection, UI redesign, learning loop,
  **pull scheduling (PRD §10b)** — keep stub + TODO pointing to PRD; don't build outside the current slice.
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
- **Load boundary (14):** TUYỆT ĐỐI không giữ session/connection qua I/O chậm (LLM, R2, email). Thêm đường
  mới chạm DB rồi chờ mạng → tách ĐỌC/CHẠY/GHI như `process_application`. Pool chỉ 15 connection; giữ qua
  một lượt LLM (T≈34s) là cạn pool ở ~28 hồ sơ đồng thời. Chỉ `IN_FLIGHT_STATUSES` (SUBMITTED/PARSING/
  RANKING — hằng số ở `models/application.py`) được phép ghi đè: đó là các trạng thái CHƯA quyết và CHƯA
  email gì. Handler lỗi VÀ sweep đối soát PHẢI dùng CHUNG hằng số này — hai lưới lệch định nghĩa chính là
  cách sinh ra lớp lỗi cả hai đang chặn. Sweep loop 08c nay chạy HAI lưới (screener timeout + hồ sơ kẹt).
  **Thêm TRẠNG THÁI MỚI vào vòng đời → dừng lại và hỏi: "tới trạng thái này, ứng viên ĐÃ nhận email/link
  chưa?"** Nếu RỒI thì nó KHÔNG được vào `IN_FLIGHT_STATUSES` và KHÔNG được vào tầm quét của sweep — cứ
  thêm vào là tái sinh đúng lỗi mất-bài-dự-tuyển đã vá (xem gotcha "Đóng session KHÔNG vô hại"). Áp dụng
  ngay cho `AWAITING_BOOKING` của **PRD §10b** (pull scheduling — thư mời + link đặt lịch ĐÃ gửi trước khi
  vào trạng thái đó), y như `AWAITING_SCREENER` và `SCHEDULING` hôm nay.
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

- **"Commit xong là nhả connection" — SAI, vì `refresh()` MỞ LẠI transaction (14).** `audit_service.record(
  commit=True)` kết thúc bằng `await session.refresh(entry)`, và `refresh` autobegin một transaction MỚI,
  mượn lại connection và GIỮ tới lần commit/close kế tiếp. Đo thực nghiệm (pool event checkout/checkin):
  `commit` + `refresh` rồi I/O 1s ⇒ giữ **1.00s**; `commit` trần rồi I/O 1s ⇒ giữ **0.00s**. Hai hệ quả
  đã cắn thật: (a) `create_application` commit+refresh nên đường NHẬN CV giữ connection SUỐT lúc upload R2
  (`routes/public.py` — CHƯA sửa); (b) session thoát khối `async with` khi còn transaction mở ⇒ teardown
  bắn một ROLLBACK QUA MẠNG và ROLLBACK đó NÉM ĐƯỢC (xem gotcha kế). Muốn biết chỗ nào thật sự giữ
  connection thì ĐO bằng `event.listens_for(engine.sync_engine, "checkout"/"checkin")` — đừng suy luận.
- **Đóng session KHÔNG vô hại — đừng để nó hạ trạng thái hồ sơ (14).** Khi bọc `try` ra NGOÀI `async with`
  (cần thiết, để thao tác DB ĐẦU TIÊN cũng được bắt), phần teardown cũng rơi vào tay handler lỗi. Adversarial
  review bắt được: teardown ném → handler hạ hồ sơ đang `AWAITING_SCREENER` (magic-link ĐÃ gửi) về
  PENDING_REVIEW[error] → ứng viên nộp câu trả lời nhận 409 ở `screening._load_valid` → **MẤT bài dự tuyển**,
  mà guest KHÔNG có tài khoản để khiếu nại. Đối xứng ở `SCHEDULING` = "mời xong lại từ chối". Vì vậy mọi
  đường ghi-đè-trạng-thái phải kiểm `status in IN_FLIGHT_STATUSES` (allowlist), KHÔNG dùng blocklist "trạng
  thái cuối" — blocklist luôn thiếu đúng những trạng thái đã phát email ra ngoài.
- **BackgroundTasks KHÔNG bắt lỗi và KHÔNG bền (14).** Exception thoát khỏi task = biến mất, trong khi 201 đã
  trả cho ứng viên ⇒ hồ sơ nằm mãi ở SUBMITTED, `audit_log` TRỐNG, dashboard hiện "Vừa nộp" (trạng thái nói
  dối tệ nhất: mất hồ sơ mà không ai biết). Mọi hàm chạy trong BackgroundTask phải bắt TOÀN BỘ thân, và
  đường cứu hộ phải mở session MỚI (lỗi đưa ta tới đó thường LÀ lỗi của session cũ). Cứu hộ cũng hỏng →
  log + nhường `stuck_applications` (lưới cuối, cũng là lưới cho ca process restart/OOM).
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

