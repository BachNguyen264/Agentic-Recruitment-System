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
