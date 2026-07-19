# ROADMAP — Autonomous Recruitment System (map of implementation slices)

> **Living map** to stay oriented — remaining work split into thin slices, ordered, with rationale.
> **Not a contract:** slices may split/reorder as we learn (the parser-dropped-TOEIC bug taught us).
> Source of truth is still **`PRD.md`** (Vietnamese). Each slice = its own one-shot plan when its turn comes.
>
> Throughout: thin slices, backend then UI right after, verify each slice, filter every idea through the PRD.

---

## ✅ DONE

- Scaffold (7 phases) · PWA migration (dropped React Native).
- **01** Parser (gpt-4.1-mini) · **01b** CV-upload UI (`/cv-check`) · **01c** certificates/languages/awards/other + model benchmark.
- **02a** JD + Qdrant embedding · **02b** Ranker (Hướng A: reasoned rubric scoring; chose **gpt-5-mini** effort=low).
- **03a** HR candidate list + score detail (read-only).
- **03b** human_review (ReviewCard + approve/reject → scheduler) · **03c** gate rank (auto-reject, per-JD toggle).
- **04** Scheduler email (real invite/rejection via **Resend**).
- **05** JD management UI (create/edit/close + gate toggle + dynamic rubric).
- Cleanup: removed demo data + Run-demo.

---

## ✅ PHASE 1 — Core HITL loop — **COMPLETE**

Verified end-to-end live: **CV in → scored → (confident: pass→continue / clean-low→auto-reject if gated) →
(uncertain→HR review) → real email out.** This is the core + the thesis story. (Slices 03b, 03c, 04.)

---

## 🟡 PHASE 2 — Real intake (JD posting + public CV submission + storage) — IN PROGRESS

> Goal: applicants submit real CVs for real JDs; HR manages JDs via web; files persist.

- **05 — JD management UI** — **DONE** (create/edit/close, gate toggle, dynamic rubric, conditional re-embed).
- **07 — Public CV submission ← NEXT** (PRD §8.2, §12.2). Public page listing OPEN JDs → applicant (guest,
  email only) picks a JD → submits CV tied to that JD → async pipeline. Applicant is fire-and-forget: no account,
  confirmation screen only, outcome by email later. Public JD projection hides rubric/gate/screener. Reuses
  `CVUpload`. Local file storage for now.
- **06 — Object storage — ✅ DONE** (PRD §16, NFR-4). Seam `FileStorage` (save/get/url/delete, async) +
  `LocalStorage` (dev) + `R2Storage` (Cloudflare R2 qua S3/boto3, bọc `asyncio.to_thread`); chọn bằng
  `STORAGE_BACKEND`. `cv_file_ref` = KEY `cv/{app_id}/{uuid}{đuôi}`; MỌI chỗ đọc/ghi CV qua interface
  (cv_reader làm việc trên BYTES, parser_node async lấy qua `storage.get()`, parse-cv bỏ file tạm).
  **HR tải CV gốc:** `GET /api/applications/{id}/cv` STREAM trong khu HR (`require_hr`), bucket PRIVATE,
  KHÔNG public URL. `reset_demo_data` xóa file qua storage. Verified live CẢ HAI backend (local không hồi
  quy · R2 thật: file lên bucket, parser đọc từ R2 chấm 87đ, **BỀN qua restart**, tải 401/200, reset xóa
  sạch bucket) + adversarial review (5 fix, gồm 1 hồi quy chặn event loop).
  → **Milestone:** complete real intake path — file CV bền trên cloud, sẵn sàng deploy.

---

## ✅ PHASE 3 — Screener async (PRD §10 — the HARDEST part) — **COMPLETE**

> Pipeline pauses waiting for the applicant, then wakes. Split small; most complex. Depends on 04 (email) + 07.
> Done end-to-end (08a suspend/resume · 08b magic-link form · 08c timeout/nhắc/trả lời trễ · 08d gate auto-mời).
> Full autonomous pipeline: CV → score → (đạt → screener async → auto-mời/HR · thấp → auto-từ-chối/HR · bất
> định → HR), mọi kết quả ra email thật, hai gate cấu hình được, ca bất định luôn về người.

- **08a — Postgres checkpointer + suspend/resume** (NFR-2, §10) — ✅ **DONE.** MemorySaver → AsyncPostgresSaver
  (Neon direct); pipeline pauses at screener (`interrupt()`), state durable, resumes from the pause point (bền
  qua restart backend, verified live: đạt→AWAITING_SCREENER→restart→resume→PENDING_REVIEW, không chạy lại parser/ranker).
  Windows dev: `python -m app` (SelectorEventLoop cho psycopg). Resume qua endpoint test + payload mock (08b thay bằng form).
- **08b — Magic-link form** (§7.3, §12.2) — ✅ **DONE.** `screening_session` (token urlsafe + expires_at +
  used_at + questions snapshot); interrupt → email câu hỏi + magic-link qua scheduler; public `/screening/<token>`
  - `GET/POST /api/public/screening/{token}` (projection an toàn: chỉ câu hỏi + tiêu đề JD); nộp → resume BẰNG
    câu trả lời → human_review; answers hiện cho HR. Bảo mật: token crypto-random, hết hạn, one-time, row-lock
    chống double-submit, chỉ resume AWAITING_SCREENER. Verified live (API + browser) + adversarial security review
    (0 finding). Chuẩn hóa answers bằng LLM = hoãn (lưu thô). Endpoint dev resume gated ENABLE_DEV_ENDPOINTS.
- **08c — Timeout + reminder + late reply** (§10) — ✅ **DONE.** Seam `ScreeningTimeoutScheduler` +
  `InProcessScheduler` (sweep loop ở lifespan, quét Postgres — KHÔNG Redis); handler nghiệp vụ
  (`send_screening_reminder`/`handle_screening_timeout`) TÁCH khỏi cơ chế (đổi QStash sau không sửa nghiệp vụ).
  Nhắc **một lần** `+REMINDER_HOURS` (`reminded_at` chặn lặp); hết hạn `+DEADLINE_HOURS` → resume `no_response`
  → human_review + cờ (**NEVER auto-reject**), `timed_out_at` idempotent; trả lời trễ → thông báo êm (410).
  Cột `reminded_at`/`timed_out_at`. Verified live (nhắc→timeout→PENDING_REVIEW[no_response] + trả lời trễ + đối
  chứng trong hạn + HR thấy nhãn no_response) + adversarial review (0 finding).
- **08d — Gate invite** (§9) — ✅ **DONE.** `route_after_screener` (đối xứng `route_after_ranker`): ca SẠCH (đã
  trả lời, tự tin, không cờ) + JD `auto_invite` ON → `scheduler_node` (SCHEDULING) → `resume_screener` gửi thư
  mời THẬT qua scheduler → INTERVIEW_SCHEDULED; no_response/cờ/low-conf/OFF → human_review ("cờ thắng gate").
  INTERVIEW_SCHEDULED chỉ đặt khi email đã gửi; dispatch CÔ LẬP khỏi error handler (adversarial review bắt +
  fix bug reset-về-error sau khi mời). Toggle auto_invite ở form JD. Verified live (A auto-mời→thư mời thật+
  INTERVIEW_SCHEDULED · B gate OFF→/review · C timeout+gate ON→/review an toàn).
  → **Milestone:** full Screener + hai gate cấu hình được — **GĐ3 (Screener async) HOÀN TẤT.**

---

## ✅ PHASE 4 — Auth (PRD §4) — **COMPLETE**

- **09 — HR admin auth — ✅ DONE.** Tự làm: `hr_user` (email + bcrypt) + seed từ env (idempotent); JWT HS256
  trong cookie **httpOnly** (bcrypt trực tiếp + pyjwt — KHÔNG passlib); `require_hr` bảo vệ MỌI router HR
  (`/api/jobs|applications|agents` + `/api/auth/me`); `login/logout/me` (lỗi CHUNG, chống enumeration + timing).
  Frontend: nhóm route `app/(hr)/` một guard gọi `/api/auth/me` (KHÔNG middleware — an toàn cross-domain),
  `/login`, logout, `credentials:"include"`, cookie Secure/SameSite/domain từ ENV. Public/\*+/apply+/screening
  giữ MỞ (ứng viên GUEST vĩnh viễn — no account). Verified live (HR chặn khi chưa login · guest nộp CV + magic-
  link vẫn mở · login seed → dashboard · logout → chặn lại · e2e nguyên) + 14 test. **Applicant stays guest
  forever** — no applicant accounts (single-tenant, fire-and-forget). ONE user type only.
  → **Milestone:** real access control (guest submits, HR logs in to manage). **GĐ4 HOÀN TẤT.**

---

## 🔵 PHASE 5 — Hardening & deploy

- **10 — Analytics** (PRD §12.1) — **tí hon / tùy chọn.** Số CV, tỉ lệ passed/rejected/pending per JD (tính được từ DB cho báo cáo).
- ~~**11 — Observability** (Langfuse)~~ — **ĐÃ BỎ** (không có Super Admin → không khán giả; ops-only). Ghi 'hướng mở rộng' trong báo cáo.
- **12 — Anti-prompt-injection** (NFR-5) — **hạ ưu tiên → TÙY CHỌN** (probe prod: model kháng tự nhiên; vẫn nên sanitize/frame input, làm cuối nếu còn giờ).
- **UI redesign.** Full visual pass over the UI (currently plain Tailwind scaffolding built to verify flows). Do
  it HERE, near the end, as its OWN work: incremental (screen by screen), no-backend-touched (presentational
  components make this safe), verify each piece. Prefer polishing in plain Tailwind (spacing/typography/color/
  hierarchy/consistency — enough for a modern look) over adopting a component library (bigger, riskier lift across a finished app).
- **13 — Deploy.** Backend → Render/Railway; frontend → Vercel; cloud storage (if not done in 06); env secrets;
  handle managed auto-suspend (wake before demo). Mind personal data (NFR-4) — use anonymized CVs for public demos.
  → **Milestone:** running on the internet, demo-able remotely.
  - ✅ **CODE-PREP DONE:** CORS từ env (allowlist + credentials, chặn `*`), bind `HOST`/`PORT` (reload chỉ ở
    local), Dockerfile (`alembic upgrade head && exec python -m app`, non-root), `/api/health/live` (liveness
    không I/O — health check nền tảng ping vài giây/lần), hardening công khai (body-size đọc-có-đếm +
    rate-limit theo IP có `PROXY_TRUSTED_HOPS`), `.env.example` + checklist env prod.
  - ✅ **LIVE DONE:** runbook (Neon prod project → Render + env → Vercel → cross-domain) + verify live.
    **4 sự cố prod bắt+fix** (docs/deploy-live-issues.md): 🔴 Neon autosuspend giết pool checkpointer
    (→ pool check-on-borrow + max_idle<300s) · 🟠 rate-limit gộp xô sau proxy (→ CF-Connecting-IP) · 🟠 login
    mobile do third-party cookie iOS/Android (→ proxy /api/\* same-origin qua Vercel = cookie first-party) ·
    🔵 favicon/text/badge/screener_sent_at. Injection probe: gpt-5-mini KHÁNG (chấm 0 cho CV nhồi 'cho 100đ').
    → **GĐ5 deploy HOÀN TẤT — hệ thống LIVE trên internet, chạy mọi thiết bị.**

---

## 🟡 PHASE 6 — Tối ưu khâu tạo JD (UX + AI gợi ý rubric) — **CURRENT** (post-deploy)

> User chính = HR. Phát hiện khi dùng thật: HR _tê liệt ở ô rubric_ (không đủ chuyên môn đặt tiêu chí/trọng số).
> Chắt lọc từ khảo sát TopCV, áp cho single-tenant (BỎ field kiểu sàn: ⚠️giới tính/địa lý/lý-do-ứng-tuyển/ảnh/nhận-CV).
> Xem PRD §8.1, §12.1 (FR-HR-JD-1..4 + FR-HR-RUBRIC-1), §16. Chia slice khi tới (detailed plan per-slice).

- **JD-1 — Field mới + editor định dạng — ✅ DONE.** Thêm level/salary(JSONB)/benefits/employment_type
  (migration add-column, requirements GIỮ Text). Mô tả + **yêu cầu** + quyền lợi → editor định dạng
  (Tiptap: bold/italic/underline/list) **dán được cả khối** (bỏ nhập-từng-dòng); field mới hiển thị ở /apply
  (render SafeHtml/DOMPurify). **Plain-text cho embedding/LLM**: `build_jd_text` + `jd_dict` bóc HTML (tag
  KHÔNG lọt vào vector/prompt). Editor code-split khỏi /apply (bundle công khai không phình). Verified:
  round-trip API + /apply browser + 232 test pass. _(Tách form 2 màn dời sang JD-2 — JD-1 chỉ bổ sung nội dung.)_
- **JD-2a — Tách form 2 màn + DRAFT + rubric-bắt-buộc-để-mở + gate ra list — ✅ DONE.** Màn "Tin tuyển dụng"
  (posting) → lưu JD **DRAFT** → điều hướng màn "Cấu hình sàng lọc" (rubric + câu hỏi, trên JD đã lưu). MỞ
  (→OPEN) **chặn nếu rubric chưa hợp lệ** (≥1 tiêu chí + tổng trọng số > 0 → backend `RubricRequiredError`/400;
  UI disable + tooltip). Gate (auto_reject/auto_invite) ra **danh sách JD** (2 toggle/JD → PATCH /gate). Status
  là cột String → thêm DRAFT KHÔNG cần migration. **KHÔNG đụng graph/pipeline** (verify: detect_changes 0 symbol
  pipeline). Verified browser (DRAFT→config→Mở-chặn→rubric→OPEN→/apply) + gate→DB + 236 test. _(Kèm fix JD-1:
  /apply list bóc HTML preview.)_
- **JD-2b — Screener-tùy-chọn (đổi định tuyến) — ✅ DONE (live-verified).** JD KHÔNG câu
  hỏi → screener_node BỎ QUA (guard quanh `interrupt()`, đọc screener_questions từ snapshot JD) → route_after_
  screener áp gate mời như ca sạch; JD CÓ câu hỏi → suspend/resume (08a-d) BẤT BIẾN (`resume_screener` byte-
  unchanged). process_application thêm dispatch auto-mời cho ca bỏ-qua (lần chạy đầu). **Adversarial review 2
  vòng** bắt+fix 2 CRITICAL auto-mời-nhầm: ① ranker `_stub` xóa cờ parse_failed (CV hỏng bị mời) → giữ cờ →
  human_review; ② guard skip lúc resume snapshot cũ (thiếu key) nuốt no_response → skip CHỈ khi key-present-rỗng;
  + đóng suspend-form-rỗng cho app không JD. Re-review: CONFIRMED-FIXED cả hai. 247 test. **KHÔNG đụng route_
  after_ranker-scoring/parser** (chỉ chặn parse_failed lọt _stub — an toàn, không đổi scoring). **Live-verified
  4 đường (email thật):** has-Q→AWAITING_SCREENER+email screener · no-Q→PENDING_REVIEW không email · no-Q+
  auto_invite→INTERVIEW_SCHEDULED+email mời · CV thấp→human_review DÙ gate ON. `resume_screener` byte-unchanged.
- **JD-3 — AI gợi ý rubric** (trụ cột 4, was slice 14). Endpoint LLM structured-output đọc JD đã lưu → đề xuất
  tiêu chí + trọng số; nút on-demand ở màn cấu hình; **cap 3 retry/JD** (`rubric_suggestion_count`), reset khi nội
  dung JD đổi. Auth-gated. _Điểm nhấn: AI TĂNG CƯỜNG năng lực người (bắc cầu khoảng trống chuyên môn HR), khác auto-hóa._
- **JD-4 — Soft-delete (ARCHIVED).** Thêm status ARCHIVED (ẩn khỏi list, giữ dữ liệu+kiểm toán, khôi phục). KHÔNG hard-delete.
  → **Milestone:** khâu tạo JD dùng được THẬT cho HR không-chuyên-kỹ-thuật.

---

## 🧹 Dọn nhỏ còn treo

- `screener_sent_at=null` (email VẪN gửi — chỉ field không set; 1 dòng, gộp lúc tiện).
- **Đổi mật khẩu admin prod** (`admin@ars.prod` đã lộ trong chat) — script băm mật khẩu mới cho hr_user.

---

## ⚪ PHASE 7 — UI redesign & tùy chọn cuối

- **UI redesign** — đánh bóng toàn giao diện trên bản live (SAU khâu tạo-JD, vì user chính = HR). Từng phần,
  no-backend-touched (component presentational), verify từng cái. Ưu tiên Tailwind thuần (spacing/typography/màu/nhất quán).
- **10 Analytics** (tí hon, tùy chọn) · **12 Anti-injection** (tùy chọn — model đã kháng) · Observability đã BỎ.
- Rồi **VIẾT BÁO CÁO** — tư liệu sẵn: kiến trúc pipeline cố định (không Supervisor), Hướng A scoring, benchmark model,
  screener bền qua autosuspend (connection-pool resilience), 2 gate + 'cờ thắng gate', 4 sự cố prod, kháng injection.

---

## ⚪ PHASE 8 — Xa hơn (PRD §17)

- **15 — Others:** Zalo OA for Screener · cross-platform web push (iOS) · full learning loop (collect samples →
  propose) · multi-JD/applicant · rubric A/B testing · hard-delete/GDPR purge có kiểm soát.

---

## Sequencing notes & flex points

- **Phase 1 first:** completing the decision loop = highest value/story. With it, you can demo the autonomous core + HITL.
- **Auth (Phase 4) late:** dev is easier without login friction; features work without it. Move earlier if security/demo needs it.
- **Screener (Phase 3) after intake:** it needs email (04) + submission (07) to be meaningful, and it's the hardest → do it on a solid base.
- **Storage (06) flexible:** local is fine for dev; can fold into deploy (13).
- **Applicant is guest forever** (no accounts) — deliberate scope: single-tenant internal system, not a two-sided
  marketplace. Don't re-introduce applicant auth/accounts.
- **UI polish is its own end-phase**, not per-slice — build flows in plain Tailwind now, redesign once at the end (incremental, no backend touched).
- **Minimum viable thesis** (if time is short): full Phase 1 + 05/07 (intake) + 09 (HR auth) + 13 (deploy);
  Screener (Phase 3) can be scoped down (e.g., drop the automatic timeout, do the basic flow) — state the reduction in the report.
- **Don't let design/ideas spawn slices outside this roadmap** — filter new ideas through the PRD first; if worth it, update PRD/roadmap, then build.

---

## Quick status (update per slice)

- [x] Scaffold · PWA · 01 · 01b · 01c · 02a · 02b · 03a · cleanup
- [x] **Phase 1** — 03b human_review · 03c gate rank · 04 scheduler email — **COMPLETE**
- [x] 05 JD management UI
- [x] 07 public CV submission (`/apply`, guest)
- [x] **08a Postgres checkpointer + suspend/resume** (durable qua restart, verified live)
- [x] **08b Magic-link form + email câu hỏi** (token/expiry/one-time/row-lock, verified live + security review)
- [x] **08c timeout/nhắc/trả lời trễ** (in-process sweep sau seam, nhắc-1-lần, timeout→human_review[no_response], verified live)
- [x] **08d gate auto-mời sau screener** (route_after_screener; ca sạch+auto_invite→thư mời thật→INTERVIEW_SCHEDULED; cờ thắng gate; verified live) — **GĐ3 XONG**
- [x] **09 HR auth** (hr_user+seed+bcrypt/JWT httpOnly · require_hr router HR · (hr) guard+/login+logout · guest MỞ; verified live + 14 test) — **GĐ4 XONG**
- [x] **06 object storage** (seam FileStorage · Local+R2 · cv_file_ref=KEY · HR tải CV gốc stream/require_hr · bucket PRIVATE · reset xóa file; verified live 2 backend + bền qua restart)
- [x] **13 deploy — ✅ LIVE** (Render + Vercel, cross-domain OK, **4 sự cố prod fixed**, injection probe: model kháng) — **GĐ5 deploy XONG**
- [ ] **PHASE 6 (CURRENT) — Tối ưu tạo JD:** [x] JD-1 field+editor+plain-text embedding · [x] JD-2a tách-form-2-màn+
  DRAFT+rubric-bắt-buộc-để-mở+gate-ra-list · [x] JD-2b screener-tùy-chọn (adversarial review 2 vòng + live-verified
  4 đường) · JD-3 AI-gợi-ý-rubric · JD-4 soft-delete(ARCHIVED)
- [ ] Dọn: screener_sent_at · **đổi mật khẩu admin prod**
- [ ] PHASE 7 — UI redesign · 10 analytics(tùy chọn) · 12 anti-injection(tùy chọn) · [Observability BỎ] · **viết báo cáo**
- [ ] PHASE 8 — 15 optional (Zalo/push/learning-loop/hard-delete...)
