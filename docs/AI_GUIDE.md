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
  **Tệp `.ics` KHÔNG BAO GIỜ được chặn thư** — mọi đường sinh tệp đi qua `scheduler._interview_ics`
  (hỏng → gửi thư không đính kèm + log). Đặt `create_event` chung `try` với `send_email` nghĩa là một
  lỗi tzdata/định dạng sẽ nuốt luôn thư xác nhận của người vừa đặt lịch xong.
  **Văn bản gửi ra ngoài chỉ có MỘT nguồn:** tên gọi/tên vị trí/liên kết lấy qua
  `booking_flow.candidate_name_of` / `job_title_of` / `booking_url` (`booking_lifecycle` gọi vào đó,
  không chép lại) — hai bản chuỗi dự phòng lệch nhau là hai lá thư cùng một buổi PV xưng hô khác nhau.
  Nút HR nào ánh xạ một điều kiện của backend (vd "Gửi lại link" ↔ `has_any_session`) thì backend phải
  TRẢ RA cờ đó (`has_booking_link`) — để UI tự đoán là HR bấm rồi mới biết mình bấm nhầm qua 409.
  **PARKED (EMAIL-1, Task 7 I5):** webhook `email_delivery` lấy `pg_advisory_xact_lock(application_id)`
  TRƯỚC khi đọc/ghi hồ sơ (cùng khoá `booking_flow`/`booking_service` dùng), nhưng `confirm_booking`
  (đường ứng viên tự chốt giờ) KHÔNG xin khoá này — nó dựa vào `SELECT…FOR UPDATE` + partial unique
  index riêng của chính nó. Cửa sổ đua GIỮA đúng hai đường này (webhook hạ trạng thái do bounce ⋂
  ứng viên đang chốt giờ CÙNG lúc) không được khoá tuyệt đối, chỉ hẹp lại nhờ `_already_moved_on` đọc
  bảng ngay trước khi ghi. CỐ Ý không vá thêm: điều kiện kích hoạt gần như tự mâu thuẫn (invite bounce
  ⇒ ứng viên không có link hợp lệ để đua), và vá triệt để đòi thêm khoá thứ hai vào `confirm_booking`
  — đường công khai nóng đã có FOR UPDATE + partial unique index và từng bị deadlock-ra-500 (xem gotcha
  SCH-2), nên đánh đổi SAI. Đụng lại race này → cân nhắc kỹ trước khi thêm khoá thứ hai, đừng vá vội.
- **Storage boundary (06):** nghiệp vụ TUYỆT ĐỐI không mở path CV — chỉ qua `services/storage`
  (`get_storage().save/get/delete`). Thêm chỗ đọc/ghi CV mới → đi qua seam, nếu không sẽ vỡ khi
  `STORAGE_BACKEND=r2`. `cv_file_ref` là KEY (opaque), KHÔNG trả ra client (dùng `has_cv` + endpoint tải).
  Bucket PRIVATE + stream qua `require_hr` — KHÔNG public URL/presigned cho CV (NFR-4).
- **Email boundary (EMAIL-1):** `scheduler._dispatch` là chỗ DUY NHẤT gọi `email_service.send_email`
  và cũng là chỗ DUY NHẤT ghi `email_delivery` — thêm đường gửi mới thì đi qua một hàm `notify_*`,
  đừng gọi thẳng `send_email` (mất luôn khả năng phát hiện bounce của lá thư đó). `kind` của
  `email_delivery` PHẢI trùng chuỗi `mode` (audit đã ghi `email_sent:{mode}` từ lát 04, hai từ vựng
  là không đối soát được nữa). Webhook `/api/webhooks/resend` là endpoint CÔNG KHAI CÓ MUTATION:
  chốt chặn là CHỮ KÝ, không phải `require_hr`; nó phải nằm NGOÀI mọi xô rate-limit (Resend gọi từ
  vài IP cố định — siết theo IP là mất sự kiện bounce trong im lặng). Mọi lượt hạ trạng thái do
  bounce phải CÓ ĐIỀU KIỆN + hỏi BẢNG, và **KHÔNG BAO GIỜ auto-reject**. **Bounce ≠ Complaint** — hai
  cờ RIÊNG (`email_bounced`/`email_complained`), vì đòi hai hành động NGƯỢC nhau: bounce ⇒ tìm địa
  chỉ đúng rồi liên hệ lại (CÓ đường gỡ cờ khi thư sau tới thành công); complaint ⇒ NGỪNG gửi cho
  người này (cờ KHÔNG BAO GIỜ bị gỡ — complaint là bằng chứng thư ĐÃ TỚI, không phải sự cố kỹ thuật
  tự lành). Chỉ `BOUNCED` được phép hạ trạng thái (`_DEMOTABLE`); `COMPLAINED` chỉ gắn cờ, vì hạ nó
  sẽ giết một link đặt lịch/sàng lọc vẫn đang sống tốt. Cả hai cờ phải PHƠI RA UI ở MỌI trạng thái
  (không chỉ `PENDING_REVIEW`) — ca đáng lo nhất là ca đã quyết xong mà thư không tới nơi, giấu nhãn
  vì hồ sơ "đã xong" thì không ai phát hiện ra nữa.
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
  (`routes/public.py` — **ĐÃ SỬA**, xem gotcha "refresh() thừa" bên dưới); (b) session thoát khối `async with` khi còn transaction mở ⇒ teardown
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
  của chính mình — `/api/health` ping Postgres+Qdrant mỗi lượt ⇒ ~17k lượt/ngày ⇒ giữ Neon không bao giờ tự
  ngủ và đốt sạch compute-hours của gói free, trong khi KHÔNG có ai dùng hệ thống. Dùng `/api/health/live` (không I/O). Endpoint kiểm-sâu công khai cũng cần rate-limit, nếu không một
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
- **CORS KHÔNG phải chốt chặn CSRF — và POST không-thân là lỗ hổng (SCH-3).** Cookie phiên HR phải
  `SameSite=None` (cross-domain Vercel↔Render) nên trình duyệt gửi kèm nó cả từ trang lạ. Một `POST`
  KHÔNG có thân là *simple request*: không preflight, nên Starlette chạy XONG handler rồi mới quyết định
  có trả header CORS hay không — **tác dụng phụ đã xảy ra**, chỉ phản hồi bị giấu. Mọi mutation HR trước
  SCH-3 tình cờ an toàn vì đều nhận thân JSON (ép preflight). Thêm endpoint HR **không thân** → nhớ nó
  nằm sau `OriginCheckMiddleware` (`core/hardening.py`), đừng dựa vào CORS.
- **`rollback()` expire object BẤT KỂ `expire_on_commit=False` (SCH-3).** Đóng transaction thừa (do
  `refresh()` mở lại) bằng `rollback()` thì caller đọc `app_row.status` ngay sau đó sẽ nạp lười — mở lại
  đúng transaction vừa đóng, và nổ `MissingGreenlet` nếu đọc từ ngữ cảnh đồng bộ. Dùng **`commit()`**:
  cùng tác dụng nhả connection, KHÔNG expire.
- **Cờ trạng thái không phải sự thật — bảng mới là (SCH-3).** Lưới hết hạn lọc theo `booked_at` +
  `status`; cả hai đều là CỜ và có thể lệch nếu một đường ghi hỏng giữa chừng. Thiếu chốt
  `~exists(BOOKED)` thì hồ sơ đang cầm lịch (đã có `.ics`) bị báo "không phản hồi", và khung giờ `BOOKED`
  đó không đường nào nhả nữa ⇒ mất khỏi lịch công ty vĩnh viễn (partial unique index). Lưới nào hạ trạng
  thái thì phải hỏi BẢNG, không chỉ hỏi cờ.
- **"TTL chặn vòng lặp" chỉ đúng theo THỜI GIAN, không theo SỐ EMAIL (SCH-3).** Vòng đặt-huỷ-đặt kết
  thúc sau 72h, nhưng mỗi vòng phát hai thư và trần còn lại chỉ là rate-limit IP ⇒ ~1400 thư/liên kết,
  trong khi Resend free là 100/ngày. Hết quota = thư mời/từ chối/magic-link của MỌI ứng viên khác cùng
  câm. Đường nào cho người dùng lặp lại một hành động CÓ GỬI MAIL đều cần hạn mức riêng.
- **Gắn cờ thì phải có đường GỠ cờ (SCH-3).** `booking_no_response` không được xoá khi mời lại ⇒ hồ sơ
  đã chốt lịch vẫn mang nhãn "không phản hồi" vĩnh viễn, và vì handler khử trùng theo TÊN cờ nên lần hết
  hạn THẬT tiếp theo bị bỏ qua im lặng. Cờ vòng đời phải được dọn ở nhánh thành công của lượt sau.

- **`base64.b64decode("", validate=True)` trả `b''` — HỢP LỆ, KHÔNG ném (EMAIL-1, CRITICAL).** Secret
  webhook rỗng (hoặc chỉ có tiền tố `whsec_`) decode ra khoá `b''` thay vì lỗi ⇒ HMAC verify chạy được
  bình thường với khoá rỗng ⇒ AI CŨNG GIẢ ĐƯỢC CHỮ KÝ (PoC đã chạy thật: verify(chữ ký tự tính bằng khoá
  b'') = True). Kịch bản thật: quên đặt `RESEND_WEBHOOK_SECRET` trên Render → webhook mở toang cho bất kỳ
  ai, mà log vẫn báo "đã verify" như bình thường. Fix đúng: `if not raw: return None` TRƯỚC khi decode —
  secret rỗng phải là "không verify được gì", không phải "verify được với khoá rỗng".
- **Verify webhook phải dùng BYTES THÔ của request, không phải JSON đã parse lại (EMAIL-1).** Parse rồi
  `json.dumps` lại đổi khoảng trắng/thứ tự khoá ⇒ HMAC không bao giờ khớp dù payload "giống hệt". Đọc
  `await request.body()` TRƯỚC mọi thao tác khác trên request. Kèm theo: cửa sổ chống replay theo
  `svix-timestamp` là CHỐT CHẶN THỨ HAI, không phải trang trí — chữ ký đúng mà không kiểm timestamp thì
  một request hợp lệ chặn được LÀ MỘT request phát lại được MÃI MÃI (attacker chỉ cần bắt được một sự
  kiện thật một lần).
- **Hàm `sign_*`/`verify_*` GƯƠNG NHAU thì tự khớp kể cả khi thuật toán SAI (EMAIL-1).** Nếu cả hai dùng
  chung một hàm `_digest` nội bộ, một bộ test tự sign-rồi-verify sẽ luôn xanh — kể cả khi mutation bỏ hẳn
  `msg_id`/`timestamp` khỏi phần dữ liệu được ký (đã tự bắt được lỗ này bằng mutation: bỏ `msg_id` khỏi
  `signed_content` vẫn 9/9 test cũ xanh). Chốt chặn duy nhất là test **known-answer HARDCODE** — tự tính
  tay (không import module đang test) một chữ ký cố định rồi so — cộng thêm test xác nhận chữ ký đổi khi
  `msg_id`/`timestamp` đổi.
- **429 của Resend là HAI chuyện khác nhau, đừng phân loại theo MÃ (EMAIL-1).** `error_type:
  rate_limit_exceeded` = bùng nổ tức thời, lùi một nhịp là qua — ĐÁNG thử lại. `daily_quota_exceeded`/
  `monthly_quota_exceeded` = tài nguyên DÙNG CHUNG của cả hệ thống đã cạn ⇒ thư của MỌI ứng viên khác
  cũng câm theo, và thử lại chỉ tổ làm chậm hàng đợi (lãng phí thời gian cho một việc chắc chắn thất bại
  lần nữa). Phân loại theo `error_type` trong body, KHÔNG theo mã HTTP 429 — cả hai loại đều trả 429.
- **Retry làm dài một lượt gửi tới ~8s — Load boundary (14) siết thêm một bậc (EMAIL-1).** Trước đây giữ
  session/connection qua MỘT lượt gọi Resend đã là tệ; nay retry (tối đa `EMAIL_MAX_RETRIES` lần, có
  backoff) có thể kéo dài gấp nhiều lần. Mọi caller `notify_*` PHẢI đã `commit()` xong trước khi gọi —
  không được giữ transaction mở rồi mới gửi thư. `_send_lock` bị giữ QUA CẢ vòng retry là CÓ CHỦ Ý (429
  nghĩa là "chậm lại", không phải "thử caller khác trước") — đừng "tối ưu" bằng cách nhả khoá giữa các
  lần thử.
- **`html_to_text` BỎ href — bản text của email mất link nếu template không tự in URL thô (EMAIL-1).**
  Các template có link phải in cả URL thô ra thân thư (không chỉ dựa vào thẻ `<a href>`) để bản
  `text/plain` (một số client email/preview chỉ hiện bản này) còn giữ được đường dẫn. Thêm template có
  link mới → nhớ in URL thô + viết test `assert url in html_to_text(html)`.
- **COMPLAINED ≠ BOUNCED — đừng gộp chung xử lý (EMAIL-1).** Complaint (ứng viên bấm "đây là spam") là
  bằng chứng thư ĐÃ TỚI TAY, không phải sự cố kỹ thuật cần cứu — hạ trạng thái về `PENDING_REVIEW` không
  mở ra hành động đúng nào, mà còn GIẾT một link đặt lịch/sàng lọc vẫn đang sống tốt (đẩy hồ sơ ra khỏi
  tập trạng thái mà `booking_flow`/sweep của `screening_timeout` đòi hỏi). Chỉ `BOUNCED` được hạ trạng
  thái; `COMPLAINED` CHỈ gắn cờ — và cờ đó KHÔNG BAO GIỜ bị gỡ (khác cờ bounce, vốn được gỡ khi một thư
  sau giao thành công), vì một lượt giao hàng thành công về sau không hề phủ nhận việc ứng viên đã từng
  báo spam.
- **Đường nào HẠ trạng thái vì bounce phải ĐÓNG luôn phiên đang bay, không chỉ đổi cột status (EMAIL-1).**
  Hạ hồ sơ khỏi `AWAITING_BOOKING`/`AWAITING_SCREENER` mà không dọn `BookingSession`/`ScreeningSession`
  tương ứng thì: khung giờ đang `HELD` không ai nhả (ứng viên vẫn mở được link cũ, và nếu họ chốt giờ thì
  `confirm_and_notify` ghi ĐÈ `PENDING_REVIEW` thành `INTERVIEW_SCHEDULED` sau lưng HR); phiên sàng lọc
  rớt khỏi CẢ HAI lưới sweep (điều kiện JOIN đòi đúng `status` cũ, mà `status` vừa đổi) nên nằm MẬP MỜ
  vĩnh viễn — không dùng, không hết hạn, không ai dọn. Dùng đúng API sẵn có: `booking_service.cancel_sessions`
  cho hướng đặt lịch, đặt `timed_out_at` cho `ScreeningSession` đang mở. **KHÔNG** resume graph LangGraph
  từ webhook (đổi nặng, ngoài phạm vi EMAIL-1) — giới hạn đã biết: một thread checkpointer có thể rò lại,
  ghi nhận chứ không vá ở đây.
- **`email.failed` KHÔNG phải bounce, và cái bẫy là nó TRÔNG GIỐNG bounce (EMAIL-2).** Ba khác biệt,
  mỗi cái từng suýt thành lỗi thật: (a) nguyên nhân nằm ở `data["failed"]["reason"]` chứ KHÔNG phải
  `data["bounce"]{type,subType,message}` — dùng nhầm bộ đọc KHÔNG ném lỗi, nó chỉ trả `None` và HR
  nhận một banner đỏ TRỐNG RỖNG; (b) Resend **không** phân Transient/Permanent cho `failed` (đã tra
  tài liệu — chỉ bounce mới có `bounce.type`), nên đừng chế phân loại bằng cách so chuỗi `reason`:
  đó là chuỗi TỰ DO, không có danh sách đóng; (c) chuỗi `"email_failed"` ĐÃ BỊ CHIẾM làm tên `action`
  trong `audit_log` bởi `scheduler._dispatch` (lượt gọi Resend ném lỗi TẠI CHỖ, không sinh hàng
  `email_delivery` nào) — nên cờ HR là `email_send_failed`, và audit của webhook cũng vậy.
  **Thêm loại sự kiện xấu MỚI** (vd `email.suppressed`) → khai ở `_STATUS_FLAG`; `_NEGATIVE` tự dẫn
  xuất từ đó, còn `_RANK` PHẢI có mục tương ứng — thiếu là `outranks` luôn False ⇒ sự kiện rơi vào
  im lặng (`test_every_status_has_a_rank` là lưới cho hố đó). Nhớ luôn `tasks/background.py`: danh
  sách cờ email được GIỮ LẠI khi resume screener là tuple VIẾT TAY, thiếu tên nào là cờ đó bị xoá
  sạch ở mọi lượt resume mà không test nào đỏ.
- **Thư NHẮC không được xử như thư ĐẦU TIÊN khi nó chở lại CÙNG một liên kết (EMAIL-2).**
  `screener_reminder` dùng LẠI đúng token của thư `screener` gốc, nên "gửi thư nhắc thất bại" KHÔNG
  hề nói liên kết đã chết. Hạ trạng thái ở nhánh đó kéo theo `_abandon_in_flight_session` đóng phiên,
  mà `screening._load_valid` từ chối mọi phiên có `timed_out_at` ⇒ ứng viên mở liên kết CÒN HẠN lại
  nhận "đã quá hạn"; `reminded_at` đã tiêu nên không có lời nhắc thứ hai, và HR KHÔNG có nút gửi lại
  link sàng lọc (chỉ đặt lịch mới có) ⇒ **mất bài dự tuyển, không đường cứu**. Nguy hiểm gấp bội vì
  `reached_daily_quota` là sự cố TOÀN HỆ THỐNG còn sweep gửi nhắc theo LÔ. Đã có ngoại lệ cho bounce
  Transient (F2) và nay cho `FAILED`; bounce **Permanent** của thư nhắc thì VẪN hạ (địa chỉ chết thì
  liên kết còn sống cũng vô nghĩa). Hai chốt chặn RIÊNG cho cùng một bất biến ⇒ test RIÊNG từng cái
  (`test_screener_reminder_*`), nếu không một guard chết từ lâu mà cả bộ test vẫn xanh.
- **CHƯA XỬ LÝ — `email.suppressed` (ghi nhận, KHÔNG phải bỏ sót).** Sau một hard bounce/complaint,
  Resend tự đưa địa chỉ vào suppression list rồi **chặn im lặng** các lượt gửi SAU: API vẫn nhận,
  vẫn trả `id`, nên `_dispatch` vẫn ghi `EmailDelivery(SENT)` + audit `email_sent:{mode}` trong khi
  thư KHÔNG BAO GIỜ được gửi. Hệ quả: ứng viên hard-bounce ở thư sàng lọc thì thư mời/từ chối về sau
  câm mà dashboard vẫn báo "đã gửi" — đúng lớp "trạng thái nói dối". Bật lên = đăng ký thêm event
  trên Resend + một `DeliveryStatus.SUPPRESSED` đi theo đúng đường đã dựng sẵn.

- **`expire_on_commit=False` KHÔNG cứu được `updated_at` — route trả ORM row sau mutation là 500
  (verify prod 18/08/2026).** `TimestampMixin.updated_at` khai `onupdate=func.now()` ở TẦNG DB, nên
  sau MỖI câu UPDATE, SQLAlchemy đánh dấu RIÊNG cột đó là expired để lần đọc sau lấy giá trị server
  vừa sinh. Cờ này độc lập hoàn toàn với `expire_on_commit`. Route kết thúc bằng
  `ApplicationRead.model_validate(app_row)` — code ĐỒNG BỘ — nên Pydantic chạm `updated_at` là nạp
  lười ngoài greenlet → `MissingGreenlet` → **HTTP 500**. Triệu chứng độc nhất và rất dễ chẩn đoán
  sai: **nghiệp vụ ĐÃ CHẠY XONG** (slot đã nhả, thư đã gửi, trạng thái đã đổi trong DB) mà HR vẫn
  nhận lỗi — rồi bấm lại lần nữa. Đã cắn `cancel_by_hr` và `resend_booking_link` (cả hai nút đặt
  lịch của HR), trong khi `review_decision` thoát nạn chỉ vì nó tình cờ `refresh(app_row)` trước khi
  return. **Hàm nghiệp vụ nào trả một ORM row cho route SAU khi đã ghi thì phải `await
  session.refresh(row)` ở CUỐI** (sau mọi lượt gửi mail, để transaction mà `refresh` mở lại đóng
  ngay khi request kết thúc). ⚠ Test gọi hàm nghiệp vụ rồi đọc DB ở session KHÁC sẽ XANH suốt —
  muốn bắt được thì test phải gọi ĐÚNG dòng của route (`ApplicationRead.model_validate(...)`), xem
  `test_hr_*_returns_serializable_row`.
- **Node nào QUYẾT ĐỊNH thì node đó ghi lý do — đừng để node trước đoán hộ (verify prod
  18/08/2026).** `ranker` chạy TRƯỚC `route_after_ranker` nên nó không thể biết JD có bật gate hay
  không; câu cũ vẫn khẳng định "(auto-từ-chối chưa bật)". Khi gate BẬT, hồ sơ bị auto-từ-chối mang
  đúng câu đó vào `application.escalation_reason` LẪN `audit_log` ⇒ bản ghi pháp y (PRD §16, NFR-3)
  mô tả sai ai đã quyết định. Nay `ranker` chỉ nói điều nó biết (điểm dưới ngưỡng) và
  `gate_auto_reject_node` GHI ĐÈ lý do bằng phát biểu của chính nó. Thêm node quyết định mới → nhớ
  ghi đè lý do, nếu không nó thừa kế câu của node trước. Lỗi này KHÔNG lộ trên UI (trang chi tiết
  giấu khối "Vì sao vào review" ở trạng thái `REJECTED`) nên chỉ đọc DB/audit mới thấy.

- **`status` các node trả về là state TRONG BỘ NHỚ — DB không hề thấy nó (DASH-1).** `parser` trả
  `PARSING`, `ranker` trả `RANKING`, nhưng `_stream_collect` chỉ gom chúng vào `trace` và
  `process_application` ghi DB một lần duy nhất ở khối GHI cuối. Hệ quả trước DASH-1: hồ sơ đứng ở
  `SUBMITTED` suốt CẢ HAI lượt LLM (~34s) rồi nhảy thẳng sang trạng thái cuối, nên hai ô
  parser/ranker trên dashboard KHÔNG THỂ sáng — nhịp hỏi nhanh cỡ nào, hay đổi sang SSE, cũng vô
  nghĩa vì dữ liệu không tồn tại. Cần mốc giữa chừng thì dùng móc `on_node` của `run_with_trace`
  (`background._mark_progress`): nó chạy GIỮA hai node, lúc KHÔNG giữ connection nào — đừng "tiện
  tay" cấp DB session cho node, các node cố ý không có session (xem `nodes/gate.py`). Mốc tiến độ
  phải luôn có guard `IN_FLIGHT_STATUSES` + `try/except` nuốt lỗi: nó là dữ liệu hiển thị, ném ra là
  giết pipeline của một ứng viên thật vì một con số trang trí. Lợi ích kèm theo: lưới đối soát
  `stuck_applications` nay biết hồ sơ kẹt Ở ĐÂU chứ không chỉ biết là kẹt.

- **`DASHBOARD_ACTIVE_STATUSES` ≠ `IN_FLIGHT_STATUSES` — đừng gộp (DASH-1).** Hai tập trong
  `models/application.py` nhìn na ná nhau nhưng khác hẳn về bản chất: `IN_FLIGHT_STATUSES` là bất
  biến AN TOÀN (tập DUY NHẤT được phép ghi đè trạng thái), `DASHBOARD_ACTIVE_STATUSES` là khái niệm
  HIỂN THỊ ("chưa tới điểm kết thúc") và cố ý CHỨA những trạng thái mà ghi đè bị CẤM
  (`AWAITING_SCREENER`, `SCHEDULING`, `AWAITING_BOOKING`). Ai đó "dọn trùng lặp" bằng cách gộp hai
  tập thì lỗi KHÔNG lộ ở dashboard mà ở `_escalate_technical_error`/sweep — tức mở đường cho "mời
  xong lại từ chối" và giết magic-link đang sống. Có test canh: `test_dashboard_active_set_is_not_
  the_safety_set`.

- **Route tĩnh phải khai TRƯỚC route có tham số (DASH-1).** `GET /api/applications/pipeline` đứng
  sau `GET /api/applications/{application_id}` thì FastAPI khớp theo THỨ TỰ khai báo → "pipeline"
  rơi vào tay handler kia và chết 422. Triệu chứng khó chịu: dashboard trắng trong khi
  `/api/health` vẫn báo mọi thứ khoẻ. Có test canh thứ tự thật trong `app.routes`.

- **"Chưa kết thúc" ≠ "đang chạy" — animation và nhịp hỏi phải bám cái thứ HAI (DASH-1, bắt trên
  prod).** `IN_FLIGHT` ở dashboard nghĩa là *chưa tới điểm kết thúc*, nên nó CHỨA `AWAITING_SCREENER`,
  `AWAITING_BOOKING` — những trạng thái ĐANG CHỜ CON NGƯỜI và kéo dài hàng NGÀY. Lấy tập
  đó để bật animation + nhịp nhanh thì sai hai đường cùng lúc: (a) ô node hiện "ĐANG CHẠY" kèm thanh
  chạy trong khi KHÔNG có tác tử nào chạy — đúng loại "trạng thái nói dối"; (b) một ứng viên chưa bấm
  link đặt lịch là ghim MỌI tab dashboard ở nhịp 2 giây vô thời hạn, tức tái tạo lại chính sự lãng phí
  mà DASH-1 sinh ra để dẹp. Tách `MACHINE_BUSY` (`SUBMITTED`/`PARSING`/`RANKING`/`SCREENING`/
  `SCHEDULING` — máy đang làm, đổi trong vài giây) khỏi `IN_FLIGHT` (con số nghiệp vụ "Đang xử lý",
  giữ nguyên). Node có hồ sơ mà không bận → nhãn "chờ ứng viên", KHÔNG animation. ⚠ Không có test
  runner ở frontend nên lưới duy nhất là chú thích tại chỗ + mục này; thêm trạng thái chờ-người mới
  (vd chờ HR ký) thì nhớ xếp nó RA NGOÀI `MACHINE_BUSY`.

- **Nhịp làm tươi của dashboard phải NGẮN HƠN chặng ngắn nhất của pipeline (DASH-1).** Đặt nhịp lúc
  rỗi 15s trong khi parser chỉ ~10s ⇒ CV nộp ngay sau một nhịp có thể chạy xong parser trước lượt
  hỏi kế tiếp: HR nhìn thẳng vào màn hình mà không thấy ô parser sáng lần nào, và kết luận tính năng
  hỏng. Hiện: rỗi 6s / đang chạy 2s. Đổi số đo pipeline (đổi model, bỏ thread pool) thì xem lại cặp
  số này. Đây là lỗi chỉ lộ ra khi chạy thử bằng trình duyệt thật — poll bằng `curl` không thấy.

- **`PublicHeader` khoá cứng `max-w-[720px]` — layout công khai MỚI mà đổi bề rộng là header lệch
  ngay (cv-templates).** Header trải hết bề ngang nhưng hàng bên trong căn giữa, nên nó chỉ thẳng
  hàng với nội dung khi HAI bề rộng bằng nhau. `/cv-templates` cần 1040px cho lưới 3 cột (720px thì
  mỗi thẻ còn ~210px, tên ngành xuống dòng giữa chừng) và lúc đầu chỉ đổi container → logo thụt vào
  160px so với tiêu đề, tagline thụt 160px so với mép lưới, trông y như lỗi render. Nay
  `PublicHeader` nhận prop `maxWidth` MẶC ĐỊNH `max-w-[720px]` (nên `/apply`, `/screening`,
  `/booking` không đổi gì) và layout nào đổi container thì PHẢI truyền theo. Cả 4/4 lăng kính review
  đều bắt lỗi này còn build + typecheck thì im — nó thuần thị giác, chỉ lộ khi mở trình duyệt.

- **Trộn biến thể `btn()` trong một hàng `flex-wrap` thì chiều cao KHÔNG tự bằng nhau
  (cv-templates).** `align-items: stretch` chỉ cân bằng TRONG một dòng flex — nút bị đẩy xuống dòng
  riêng đứng một mình nên giữ chiều cao tự nhiên của nó. Đo thật ở 390px: `primary`/`secondary` 37.5px
  còn `ghost` 26px, thành một link chữ bé tí, vùng chạm không đạt. Thêm nữa `secondary` có `border-2`
  (+4px) nên chính NÓ mới là cái định chiều cao của dòng, `primary` chỉ ăn theo nhờ stretch. Muốn nút
  `ghost` bằng hai nút kia phải bù CẢ HAI: `!py-2` và `border-2 border-transparent`. Đừng tin mắt
  nhìn ở màn rộng — ở đó ba nút cùng một dòng nên stretch che mất lỗi.

- **Node 24 CÓ sẵn `globalThis.navigator` — guard SSR bằng `typeof navigator` là VÔ HIỆU (BUG-1).**
  Node thêm global `navigator` từ v21, và máy này chạy v24. Nó KHÔNG có `onLine`, nên
  `navigator.onLine` ra `undefined` chứ không ném lỗi — guard trông như chạy đúng. Vấp thật khi seed
  `onlineManager.setOnline(navigator.onLine)` trong `app/providers.tsx`: lúc SSR guard không chặn,
  ta gọi `setOnline(undefined)`, mà `onlineManager` của TanStack là **singleton CẤP MODULE dùng chung
  cho MỌI request trên server** ⇒ cả tiến trình Next thành "offline" vĩnh viễn ⇒ query bị *paused*
  khi SSR ⇒ HTML server thiếu nhánh `isLoading` mà client lại có ⇒ **vỡ hydration trên mọi trang, kể
  cả luồng ứng viên công khai** (`/apply` báo `Expected server HTML to contain a matching <p> in
  <main>` rồi React bỏ toàn bộ SSR, chuyển sang client-render). Guard đúng là **`typeof window ===
  "undefined"`**; thêm `typeof navigator.onLine !== "boolean"` cho chắc. Bẫy này `tsc` không thấy,
  `next build` KHÔNG đỏ, và console chỉ kêu ở lần tải trang đầu — chỉ lộ ra khi mở trình duyệt thật
  và ĐỌC console ở một trang CÔNG KHAI (đường HR không lộ vì nó vốn phải chờ `getMe`).

- **Sửa hành vi offline của TanStack: `networkMode` phải đặt TẠI mutation, KHÔNG ở `QueryClient` gốc
  (BUG-1).** `app/providers.tsx` là provider GỐC (`app/layout.tsx` bọc toàn app), nên mọi
  `defaultOptions` ở đó đổi luôn hành vi của nộp CV / đặt lịch / trả lời sàng lọc của KHÁCH VÃNG LAI.
  Mặc định `networkMode: "online"` khiến mutation lúc mất mạng bị *paused* chứ không hỏng: `onMutate`
  vẫn chạy nên nút kẹt "Đang xử lý…" vĩnh viễn (chỉ `onSettled` mới xoá cờ), rồi
  `resumePausedMutations()` TỰ PHÁT LẠI khi có mạng — phát lại một quyết định HR có thể đã bỏ dở, mà
  quyết định đó gửi email THẬT cho ứng viên (FR-HR-4) và ghi `audit_log` (FR-HR-5).

- **Giả lập "Offline" của DevTools/CDP không chạm tới fetch do CHÍNH service worker phát ra (PWA-1).**
  `emulate networkConditions: Offline` áp lên target của TRANG. Một fetch mà SW gọi từ bên trong
  `event.respondWith(fetch(...))` chạy trong target của SW nên vẫn ra mạng bình thường. Đo thật trên
  repo này: lúc "offline", fetch phát từ trang tới `/api/health/live?<fresh>` ném `Failed to fetch`,
  còn `/applications?_rsc=<fresh>` do SW xử lý vẫn trả **200 trong 6 ms**, và một lượt tải lại (cold
  navigation) hiện nhánh lỗi server của app thay vì `/offline`. Hệ quả: không thể kiểm trang offline
  bằng network emulation — nó cho ra false negative rất thuyết phục. Cách kiểm THẬT là **tắt hẳn
  server** (origin chết hẳn), đúng cách slice này đã dùng để chứng minh fallback hoạt động.

- **Sửa `app/offline/page.tsx` mà không đổi `public/sw.js` thì mọi client đang cài giữ NGUYÊN trang
  offline CŨ mãi mãi (PWA-1).** SW chỉ precache `/offline` trong handler `install`, mà `install` chỉ
  chạy khi byte của `sw.js` đổi. Vấp thật trong lúc làm PWA-1: sửa link "Thử lại" ở source, `curl
  /offline` trả đúng HTML mới, mà trình duyệt vẫn hiện link cũ — bản precache cũ còn nằm đó đấy. ⇒ Mọi
  lần sửa trang offline sau này PHẢI bump `CACHE` trong `sw.js` trong CÙNG một commit.

- **Chạy `pnpm --filter dashboard build` trong lúc `next dev` đang sống thì server dev hỏng theo
  (PWA-1).** Cả hai cùng ghi vào `apps/dashboard/.next`; bản build thay các chunk framework mà dev
  server đang phục vụ, nên mọi route 404 phần JS của nó rồi kẹt ở trạng thái loading. Trông y hệt một
  lỗi code chứ không phải hệ quả thao tác. Cách hồi phục: tắt dev, xoá `.next`, bật dev lại. Trong một
  slice: kiểm trình duyệt TRƯỚC, build là bước CUỐI.

- **Nút thắt tải đọc-code-đoán-sai: KHÔNG phải thread pool mà là KHOÁ của checkpointer (lát tải+scale).**
  Đọc code thì ai cũng đoán parser gọi LLM đồng bộ ⇒ thread pool cạn trước. **Đo thì sai.** Tài nguyên
  chạm trần ĐẦU TIÊN là **pool checkpointer LangGraph, ngay từ N=10** — mà thật ra cũng không phải pool:
  `AsyncPostgresSaver` giữ **MỘT** `asyncio.Lock` cho cả tiến trình (`aio.py:46`, giữ ở cả ba nhánh
  `_cursor()`), và **lấy connection TRƯỚC rồi mới xếp hàng vào khoá** (`aio.py:328`). App lại chỉ dựng
  MỘT saver (`checkpointer.py:71`) ⇒ **đồng thời hoá SQL của checkpointer thực tế là 1**.
  Đối chứng đã chạy: nâng `CHECKPOINTER_POOL_MAX_SIZE` 5→25 (**gấp 5×**) chỉ kéo lỗi 107→93. Nới ở
  ĐẦU RA vô ích; phải chặn ở ĐẦU VÀO (`MAX_CONCURRENT_PIPELINES`). Đụng lại tải ⇒ **đừng nâng pool, hãy
  giảm số việc vào cùng lúc.**
- **Semaphore mà không có timeout là nút cổ chai CHẾT (lát tải+scale).** `MAX_CONCURRENT_PIPELINES` và
  `OPENAI_TIMEOUT_SECONDS` là một CẶP, không phải hai tính năng rời. langchain mặc định truyền
  `timeout=None` xuống httpx = **chờ vô hạn**; một request treo sẽ giữ MỘT SUẤT của van vĩnh viễn và
  hàng đợi tắc luôn chứ không chỉ chậm. Thêm van ở bất kỳ đâu ⇒ hỏi ngay "thứ bên trong van có thể
  treo vô hạn không?".
- **`ENABLE_LLM=false` KHÔNG dùng để đo tải được (lát tải+scale).** Nó stub **cả** parser lẫn ranker,
  tức xoá đúng cái nút thắt cần đo (parser gọi ĐỒNG BỘ ⇒ chiếm luồng). Cách đúng: `scripts/mock_openai.py`
  + env **`OPENAI_API_BASE`** — chuyển hướng được **cả** `ChatOpenAI` lẫn `OpenAIEmbeddings`, chạy ĐÚNG
  đường code thật, **0 dòng sửa code sản phẩm, 0 đồng**.
- **Đo tải ở local KHÔNG thấy lỗi của prod (lát tải+scale).** `STORAGE_BACKEND=local` ghi **đĩa** (~0ms)
  còn prod đẩy **R2 qua mạng**. Chính vì vậy lỗi "giữ connection suốt lượt upload" **hoàn toàn tàng hình**
  ở local (nhận p50 2.5s) nhưng trên prod làm **cạn sạch pool 15** và đẩy p50 lên **13.4s**. Mọi kết luận
  về đường NHẬN CV phải xác nhận trên prod, hoặc ít nhất chạy local với `STORAGE_BACKEND=r2`.
- **Windows: tiến trình python cũ GIỮ SOCKET, server mới im lặng không bind được (lát tải+scale).** Kill
  tiến trình cha là CHƯA đủ — cổng vẫn LISTEN và server mới khởi động, **in banner như bình thường**, rồi
  phục vụ… KHÔNG gì cả, trong khi client nói chuyện với server CŨ. Đã mất một lượt đo vì tưởng mock hỏng.
  Trước mỗi lượt đo: `Get-NetTCPConnection -LocalPort <p> -State Listen` rồi `Stop-Process -Force` **lặp
  cho tới khi cổng thật sự trống**. (Cùng họ với gotcha uvicorn-fork đã ghi.)
- **`response_model_exclude` dạng set PHẲNG trên `response_model=list[Model]` là NO-OP IM LẶNG (AUDIT-1).**
  Muốn bỏ trường khỏi MỘT DANH SÁCH thì phải viết `{"__all__": {"parsed_data", "score_breakdown"}}`.
  Viết `{"parsed_data", "score_breakdown"}` (set phẳng) thì Pydantic v2 hiểu đó là **chỉ số phần tử** của
  sequence, bỏ qua key chuỗi, và endpoint trả **đủ mọi trường** — không exception, không cảnh báo, không
  log. Một bản vá "giảm 80% payload" có thể qua review, lên prod và không giảm một byte nào. Cách duy nhất
  bắt được là **assert trường VẮNG MẶT trong JSON** (`tests/test_applications_pagination.py`).
- **`LocalStorage.delete` không bao giờ raise ⇒ mọi báo cáo "đã xoá N file" đều có thể là nói dối (AUDIT-1).**
  Nó là `unlink(missing_ok=True)`. Nên chạy `scripts/reset_demo_data.py` với `STORAGE_BACKEND=local`
  (mặc định trong `.env` dev) trong khi file CV thật nằm trên **R2** sẽ in đủ `+206/206 file CV` mà chưa
  chạm một byte nào trên bucket — báo cáo thành công hoàn hảo cho việc chưa hề xảy ra. Vì thế script nay
  in **header môi trường** (backend + đích + host DB) trước cả dry-run: ĐỌC nó trước khi gõ `--commit`.
  Suy rộng: `delete` idempotent theo hợp đồng trên CẢ HAI backend, nên "+N/N" chỉ có nghĩa "N lượt gọi
  không lỗi", KHÔNG chứng minh N file từng tồn tại. Muốn biết kho sạch chưa thì **liệt kê prefix trên
  bucket** (đã làm sau lần dọn prod 29/08/2026 — còn đúng 9 object mồ côi CŨ, không thuộc lần dọn này).
- **Cờ của parser bị ranker NUỐT nếu không chở tay (AUDIT-1).** `ranker_node` **thay mới trọn**
  `uncertainty_flags` ở MỌI nhánh return (`_stub`, `rank_cv`, cả nhánh `parse_failed` cũng phải tự dựng
  lại cờ). Nên bất kỳ cờ nào parser đặt mà muốn sống tới `policy.should_review` đều phải được **chở qua
  ranker tường minh** (`carried`) — nếu không nó biến mất im lặng và hồ sơ đi thẳng vào gate auto với
  confidence cao. Đây chính là lý do `parse_failed` phải có một nhánh `if` RIÊNG trong `ranker_node`;
  `cv_truncated` (trần ký tự CV) đi theo đúng khuôn đó và có test khoá bất biến.
- **Rate limit sau proxy Vercel KHÔNG ràng buộc ai (AUDIT-1).** Quota khoá theo `CF-Connecting-IP` do
  Cloudflare đặt = IP của bên **chạm Cloudflare**. Khi `next.config` rewrite `/api/*` sang Render thì bên
  đó là **Vercel**, mà Vercel xoay IP egress liên tục ⇒ gần như mỗi request một xô mới. Đo: thẳng vào
  Render 429 từ lượt 21; qua Vercel **52 lượt, 0 bị chặn**. Đường nộp CV vì thế đi THẲNG backend qua
  `NEXT_PUBLIC_PUBLIC_API_BASE`. Chỉ áp được cho GET + POST `multipart/form-data` (CORS-safelisted ⇒
  KHÔNG preflight); screening/booking gửi JSON nên **có** preflight, login cần cookie first-party — hai
  nhóm đó phải giữ qua proxy. Thêm endpoint công khai mới ⇒ hỏi ngay "quota này đếm IP của ai?".
- **Trần KÍCH THƯỚC không bao giờ chặn được file dựng-để-phá; chỉ HẠN GIỜ mới chặn (AUDIT-2).**
  Chi phí bố cục của PyMuPDF là **bậc hai theo số glyph**, không theo byte: PDF **một trang** 2.1 KB
  → 4.95s · 6.6 KB → **90s** · 37 KB → **>600s**. Mọi phép kiểm "file nhỏ nên chắc rẻ" đều sai ở đây.
  Và vì PyMuPDF là SWIG **không nhả GIL**, `asyncio.to_thread` KHÔNG cô lập được: event loop đứng
  theo, kể cả `/api/health/live` (đường Render kiểm sống) ⇒ Render tưởng service chết → SIGKILL →
  lifespan không chạy → mọi BackgroundTask đang bay bốc hơi. Thứ duy nhất chặn được là một tiến
  trình **GIẾT ĐƯỢC** (`cv_reader.extract_text_bounded`). Suy rộng: bất kỳ thư viện C nào xử lý file
  người lạ nộp — hỏi ngay "nếu nó chạy 10 phút thì ai giết nó?", đừng hỏi "file to bao nhiêu".
- **`Document()`/parser XML giải nén TOÀN BỘ trước khi vòng lặp của bạn chạy (AUDIT-2).** Đặt `break`
  trong vòng `for para in doc.paragraphs` KHÔNG tiết kiệm được gì: `Document(io.BytesIO(data))` đã
  dựng xong lxml cho cả `word/document.xml` trước đó. Đo: .docx **442 KB** chứa XML **116.5 MB**
  (257:1) làm RSS **+639 MB** ⇒ OOM một instance 512 MB bằng MỘT lượt upload. Chặn ở **ĐẦU VÀO**:
  ZIP khai sẵn kích thước sau giải nén trong central directory (`ZipInfo.file_size`), đọc gần như
  miễn phí. Khai gian nhỏ hơn thật không lách được — `ZipExtFile` cắt output theo cỡ đã khai nên XML
  cụt → parse lỗi → `parse_failed` (vẫn về tay người, PRD §13 giữ nguyên).
- **`multiprocessing` + module không có `if __name__ == "__main__"` = fork bomb (AUDIT-2).** `spawn`
  RE-IMPORT module chính ở tiến trình con; module nào gọi `extract_text_bounded` ở **cấp module** sẽ
  đẻ con vô hạn. `app/__main__.py` có guard nên app an toàn, nhưng **script kiểm thử thì rất dễ
  quên** — đã vấp thật, phải kill tay. Trên Unix dùng `forkserver` (không re-import `__main__`, lại
  nhanh hơn); `spawn` chỉ dành cho Windows dev.
- **Test khẳng định KẾT QUẢ không chốt được code có giá trị nằm ở CÔNG VIỆC ĐÃ TRÁNH (AUDIT-2).**
  Thay hai bộ đọc CV bằng bản ngây thơ `"\n".join(mọi trang)[:budget]` → **toàn bộ suite vẫn xanh**,
  dù bản ngây thơ tốn 421s + 382 MB trên PDF 2.000 trang và trả về chuỗi **giống hệt từng byte**.
  Khi bản vá là "dừng sớm / bớt truy vấn / nhả connection sớm", test PHẢI đếm **số lần gọi**, chứ
  không so kết quả. Cùng lớp lỗi: `.offset(offset)` xoá đi mà 499 test vẫn xanh; `await
  session.commit()` trước lượt LLM xoá đi mà 13 test vẫn xanh. Cách kiểm rẻ nhất: **đột biến** bản
  vá rồi chạy lại — xanh nghĩa là test chưa chốt gì.
