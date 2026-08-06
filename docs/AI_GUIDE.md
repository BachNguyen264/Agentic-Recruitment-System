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
  Deploy (13) ĐÃ LIVE. NOT yet built: analytics, observability, anti-injection, UI redesign, learning loop
  — keep stub + TODO pointing to PRD; don't build outside the current slice.
- **Booking boundary (SCH-1 → SCH-3 — feature ĐÃ KHÉP, PRD §10b):** Mọi thao tác trên khung giờ đi QUA
  `booking_service` (đừng truy vấn thẳng `interview_booking`); chỗ-đã-chiếm = `BOOKED` **hoặc** `HELD` còn
  hạn; chốt chặn cuối là **partial unique index** `UNIQUE(start_at) WHERE status='BOOKED'`. Đặt lịch nằm
  NGOÀI graph: **KHÔNG thêm `interrupt()`**. Khả dụng TOÀN CỤC (env `BOOKING_*`), không theo từng JD.
  **Mọi đường tới quyết định MỜI phải gọi `booking_flow.dispatch_booking_invite`** — đừng tự viết lại thứ
  tự email-trước-trạng-thái-sau ở đường thứ tư. Hai thứ tự ghi KHÁC nhau CÓ CHỦ Ý: *gửi thư mời* = email
  trước (chưa gửi được thì chưa mời); *xác nhận lịch* = DB trước, email sau (ứng viên đang nhìn màn xác
  nhận nên họ ĐÃ biết; huỷ lịch vì gửi thư hỏng mới là cái sai lớn). Sau khi `confirm_booking` thành công
  thì **tuyệt đối không ném ra ngoài nữa**. `AWAITING_BOOKING` = thư mời ĐÃ gửi ⇒ xem *Load boundary*.
  Thêm đường đưa hồ sơ rời khỏi hướng phỏng vấn (HR từ chối, HR huỷ lịch, link hết hạn) → **nhớ
  `cancel_sessions`**, nếu không token cũ sẽ lật ngược quyết định đó.
  **SCH-3 (vòng đời sau khi có lịch):** ba lưới nhắc/hết hạn nằm ở `booking_lifecycle.sweep_once`, chạy
  GHÉP vào sweep loop 08c — thêm loại deadline mới thì thêm handler ở đó, **đừng dựng cơ chế nền thứ hai**.
  Idempotent bằng **cột mốc thời gian** (`reminder_sent_at`/`reminded_at`/`cancelled_at`/`no_slots_at`),
  không bằng bộ đếm; mốc được ghi + commit **TRƯỚC** khi gửi thư (at-most-once — thà thiếu một lời nhắc
  còn hơn dội mail mỗi vòng khi Resend trục trặc). **Huỷ KHÔNG được gia hạn TTL**: `mark_session_reopened`
  xoá `booked_at` để hạn GỐC áp lại — giữ nguyên `booked_at` là biến liên kết thành vĩnh viễn (vì
  `load_valid_session` bỏ qua hạn khi phiên đã đặt) và mở cửa cho vòng lặp đặt-huỷ-đặt. Huỷ phải **nhả
  khung giờ TỨC THÌ** (`cancel_booked`), không chờ vòng quét: slot là tài nguyên tranh chấp.
  **KHÔNG auto-reject ở BẤT KỲ nhánh nào** — hết hạn/huỷ đều về `PENDING_REVIEW`. "Đổi lịch" = HR huỷ +
  gửi lại link, **không có luồng dời-lịch riêng**; `resend_booking_link` phải `cancel_sessions` TRƯỚC, nếu
  không `dispatch_booking_invite` dùng lại đúng phiên cũ và "gửi lại" chẳng đổi được gì.
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
  cách sinh ra lớp lỗi cả hai đang chặn. Sweep loop 08c nay chạy BA lưới (screener timeout + hồ sơ kẹt +
  vòng đời lịch SCH-3) — thêm loại deadline nữa thì thêm handler vào đó, đừng dựng cơ chế nền mới.
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
- **Giữ chỗ mà không kiểm "đã giữ chưa" = RÒ SLOT (SCH-1).** `generate_slots` sinh LƯỜI mỗi lần ứng viên mở
  link; nếu không trả lại đúng các hold CÒN HẠN của chính application đó thì mỗi lần tải trang giữ thêm 5
  khung giờ — N lần bấm F5 khoá 5N khung, lịch công ty cạn sạch và **không có lỗi nào bật ra**. Cũng KHÔNG
  gia hạn hold theo mỗi lần tải (biến hold 10 phút thành hold vô hạn). Thêm đường sinh/giữ slot mới → truy
  vấn hold-còn-hạn phải nằm ở dòng ĐẦU.
- **Thứ tự thao tác quyết định chỗ `IntegrityError` bật ra (SCH-1).** Trong `confirm_booking`, câu
  `UPDATE` nhả các hold anh em sẽ **autoflush** mọi thay đổi ORM đang treo. Lật `status=BOOKED` TRƯỚC rồi
  mới `UPDATE` ⇒ unique violation của race bật ra ngay giữa hàm thay vì ở `commit()` — ngoài khối `try`
  đang bắt nó. Nhả anh em TRƯỚC, lật trạng thái SAU, để chỉ có MỘT điểm ném lỗi.
- **`datetime` naive ở tầng đặt lịch lệch đúng 7 tiếng mà KHÔNG ném lỗi (SCH-1).** Python coi naive là giờ
  hệ thống nên so sánh vẫn chạy, chỉ có slot hiện ra sai buổi. DB lưu `timestamptz` UTC, sinh/so sánh theo
  `Asia/Ho_Chi_Minh`; `booking_service._as_utc` chặn naive tại cửa — đừng gỡ. Đếm `max_per_day` phải quét
  từ **đầu ngày địa phương**, không từ `now`: buổi sáng nay đã diễn ra vẫn chiếm hạn mức của hôm nay.
- **`zoneinfo` đọc tzdata của HỆ ĐIỀU HÀNH — ảnh Docker slim có thể không có (SCH-1).** Thiếu thì
  `ZoneInfo("Asia/Ho_Chi_Minh")` ném `ZoneInfoNotFoundError`: chết hẳn trên prod trong khi máy dev xanh.
  Đã ghim gói `tzdata` (thuần dữ liệu, zoneinfo tự dùng làm nguồn dự phòng) — đừng gỡ khi dọn dependency.
- **"Đọc rồi ghi" ở endpoint công khai là TOCTOU THẬT, không phải lo xa (SCH-2).** `generate_slots` kiểm
  "đã có hold chưa" rồi mới chèn; đo trên Postgres thật: 2 lượt GET chồng nhau trên CÙNG token → 10 hàng
  giữ chỗ, 8 lượt → 40. Bất biến "bấm lại trả slot cũ" chỉ đúng khi TUẦN TỰ, mà ứng viên bấm F5 hai lần
  là đủ phá. Vá bằng `pg_advisory_xact_lock` theo `application_id` — nhớ **commit ở mọi nhánh trả về sớm**
  để nhả khoá. Cùng họ: **đếm hạn mức theo HÀNG thay vì theo mốc giờ** làm `max_per_day` phồng lên và đóng
  sạch những ngày gần nhất với MỌI ứng viên khác.
- **Khối `except` đọc thuộc tính ORM sau khi commit hỏng thì CHÍNH NÓ ném (SCH-2).** Flush lỗi ⇒ SQLAlchemy
  expire TOÀN BỘ object trong session; `logger.exception(..., booking.id)` trong handler sẽ nạp lười trên
  session đang cần rollback → `PendingRollbackError` thoát ra route → 500 cho người vừa đặt lịch THÀNH
  CÔNG. Trong mọi handler kiểu "không bao giờ được ném", **lấy giá trị nguyên thuỷ TRƯỚC** rồi chỉ dùng
  chúng; đừng chạm object ORM.
- **Nhánh idempotent trả về mà KHÔNG commit = giữ khoá + connection qua I/O mạng (SCH-2).**
  `confirm_booking` mở `SELECT … FOR UPDATE`; nhánh "đã BOOKED rồi, trả về luôn" quên commit nên caller đi
  gọi Resend trong lúc vẫn giữ khoá hàng — đo được 1.29s. Mọi `return` sớm sau một `FOR UPDATE` phải đóng
  transaction. Kèm theo: đường bấm-lại phải **bỏ qua việc gửi lại** biên nhận, nếu không mỗi lần tải lại
  là một email nữa (Resend là kênh DUY NHẤT của hệ thống — đốt quota là làm câm cả pipeline).
- **Deadlock KHÔNG phải `IntegrityError` (SCH-2).** Hai tab của cùng ứng viên chốt hai `booking_id` khác
  nhau khoá chéo nhau qua `release_holds`; `DeadlockDetectedError` là `DBAPIError`, lọt qua
  `except IntegrityError` → 500 thay vì 409. Bắt `DBAPIError` cho các đường có thể khoá chéo.
- **Test async chạm DB THẬT: đừng dùng `AsyncSessionLocal` toàn cục (SCH-1).** pytest-asyncio cấp mỗi test
  một event loop MỚI, còn pool của engine toàn cục giữ connection asyncpg gắn với loop của test TRƯỚC →
  test thứ hai nổ `Future attached to a different loop` (test đầu vẫn xanh, nên trông như lỗi ngẫu nhiên).
  Dùng engine RIÊNG mỗi test + `NullPool` (xem `tests/test_booking_db.py`).

- **Xoá `booked_at` là thứ CHẶN vòng lặp đặt-huỷ-đặt, không phải dọn dẹp cho đẹp (SCH-3).**
  `load_valid_session` cố ý BỎ QUA hạn 72h khi `booked_at` có giá trị (để người đã đặt xong còn mở lại link
  xem/huỷ). Nếu lúc huỷ mà giữ nguyên `booked_at`, liên kết sống VĨNH VIỄN — đúng cái "gia hạn TTL" mà PRD
  §10b.6 cấm, và triệu chứng (`expires_at` vẫn y nguyên trong DB) trông như KHÔNG có gì sai. Chỉ lộ ra khi
  thử huỷ-đặt-huỷ nhiều vòng.
- **Truy vấn "phiên đã đặt xong" KHÔNG được lọc `expires_at` (SCH-3).** Buổi phỏng vấn thường nằm SAU hạn
  72h của liên kết, nên `booked_session` mà dùng lại điều kiện của `active_session` thì thư nhắc trước buổi
  PV mất nút huỷ đúng lúc ứng viên cần nó nhất. Hai truy vấn trông giống nhau nhưng trả lời hai câu hỏi
  khác nhau — đừng gộp.
- **Hai chốt chặn cho cùng một bất biến thì phải test RIÊNG từng cái (SCH-3).** Lưới hết hạn lọc cả
  `booked_at IS NULL` lẫn `status == AWAITING_BOOKING`; test "người vừa đặt xong không bị hạ" vẫn XANH khi
  gỡ hẳn `booked_at` vì vế trạng thái che mất. Muốn biết chốt chặn còn sống thì phải dựng đúng trạng thái
  mâu thuẫn (phiên đã đặt + hồ sơ AWAITING_BOOKING) rồi đo — nếu không, một guard chết từ lâu mà cả bộ test
  vẫn xanh.
