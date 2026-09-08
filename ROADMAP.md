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

## ✅ PHASE 2 — Real intake (JD posting + public CV submission + storage) — COMPLETE

> Goal: applicants submit real CVs for real JDs; HR manages JDs via web; files persist.

- **05 — JD management UI** — **DONE** (create/edit/close, gate toggle, dynamic rubric, conditional re-embed).
- **07 — Public CV submission ✅ DONE** (PRD §8.2, §12.2). Public page listing OPEN JDs → applicant (guest,
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
- **UI redesign — ✅ DONE (merge `e69b57a`).** Full visual pass over the UI. Ghi chép gốc: Do
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
- **14 — Hardening tải** (NFR-1 "xử lý nhiều CV song song"). → **Milestone:** nhiều CV nộp cùng lúc KHÔNG
  làm mất hồ sơ nào trong im lặng.
  - ✅ **DONE:** `process_application` tách vòng đời session **ĐỌC → CHẠY → GHI** (trước: một session giữ
    connection + transaction MỞ trọn cả hai lượt LLM) · toàn thân trong MỘT try (thao tác DB đầu tiên trước
    nằm NGOÀI → pool cạn là ném thẳng ra BackgroundTasks, hồ sơ kẹt SUBMITTED, audit trống, **mất vĩnh viễn**) ·
    lưới đối soát `services/stuck_applications` (quá `STUCK_APPLICATION_TIMEOUT_MINUTES`=30 → PENDING_REVIEW
    [error], **KHÔNG auto-reject**) đi chung sweep loop 08c · chỉ `IN_FLIGHT_STATUSES` được ghi đè (dùng CHUNG
    cho handler lỗi + sweep).
  - **Đo thật (5 CV, tuần tự, LLM thật):** T=34.3s (parser 9.4s · **ranker 24.7s = 72%**); connection giữ
    0.68s = **2% của T** (trước ~100%) ⇒ trần một đợt **28 → 678 hồ sơ**. Công cụ: `scripts/loadtest_apply.py`.
  - **Adversarial review** 21 cáo buộc → 20 bị bác, 1 lỗi THẬT (teardown session hạ trạng thái hồ sơ đã gửi
    email) đã vá + test hồi quy Prove-It. 290 test xanh.
  - ⏳ **Còn nợ (đợt scale sau):** semaphore chặn số pipeline song song · parser dùng `ainvoke` (bỏ trần
    thread pool 14 luồng ≈1.5 CV/s) · đường NHẬN CV vẫn giữ connection lúc upload R2 (`create_application`
    commit rồi `refresh()` → mở lại transaction).

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
- **JD-3 — AI gợi ý rubric — ✅ DONE (LLM-verified + benchmark).** Endpoint `POST /api/jobs/{id}/suggest-rubric`
  (`require_hr`, router HR-only): đọc JD plain-text (bóc HTML) + cấp bậc → `rubric_suggester` (gpt-5-mini
  `reasoning_effort`, KHÔNG temperature) structured output `[{criterion, weight, reasoning}]`; nút "✨ AI gợi ý
  rubric" ở màn cấu hình → ĐIỀN SẴN để HR chỉnh trước khi lưu (KHÔNG tự áp — trụ cột 4). **Cap 3/JD**
  (`rubric_suggestion_count`, migration hand-written + include_object guard): count≥max→429 KHÔNG gọi LLM; +1 SAU
  khi LLM OK (lỗi không tiêu lượt); **reset về 0 khi nội dung JD đổi** (dùng CHUNG phép so sánh re-embed trong
  `update_job`). JobPostingRead lộ count + computed `rubric_suggestions_remaining`. 260 test (13 mới). **Verified
  thật (LLM):** tạo Lead Node.js → suggest×3 (tiêu chí+trọng số bám JD, trọng số phản ánh lead: Node.js 0.30 +
  leadership 0.25 nặng nhất) → lần 4 chặn 429 → sửa mô tả reset 0/3 → chưa login 401 → lưu rubric AI + nộp CV →
  ranker chấm ĐÚNG theo rubric đó (pipeline không hồi quy). **Benchmark low vs medium (3 JD × 2 effort):** cả hai
  bám JD + trọng số phản ánh vị trí; medium sắc hơn ở phân bố trọng số nhưng ~30-50% chậm hơn (~12s vs ~7-10s) →
  **chọn `low`** (đủ tốt, đồng nhất ranker; env chỉnh được). _Điểm nhấn: AI TĂNG CƯỜNG năng lực người, khác auto-hóa._
- **JD-4 — Soft-delete (ARCHIVED) — ✅ DONE (live-verified).** `status` String (JD-2a) → thêm ARCHIVED, KHÔNG
  migration. `archive_job` (bất kỳ status → ARCHIVED) + `restore_job` (→ CLOSED, KHÔNG tự OPEN — mở lại theo
  rubric-bắt-buộc JD-2a); routes `POST /jobs/{id}/archive|restore`; `list_jobs(archived=?)` ẩn/hiện; UI tab "Đang
  hoạt động / Đã lưu trữ" + nút Lưu-trữ (confirm) / Khôi-phục. **KHÔNG hard-delete** — Application+AuditLog+vector
  GIỮ NGUYÊN. Seam `qdrant_service.delete_jd_vector` (idempotent, CHỈ true-delete) → `reset_demo_data` dùng seam
  (đóng nợ vector-mồ-côi JD-1); archive GIỮ vector dormant (khôi phục khỏi re-embed). Guard submit: `get_open_job`
  loại ARCHIVED → nộp CV vào JD lưu-trữ 404, thiếu job_id 422 (không rác). 270 test (10 mới). Adversarial review.
  **Live-verified 14/14:** archive→ẩn list+/apply, Application sống, archived-list thấy, guard 404/422, restore→CLOSED,
  vector xóa khỏi Qdrant khi true-delete, pipeline chấm điểm 84.0 (không hồi quy).
  → **Milestone:** khâu tạo JD dùng được THẬT cho HR không-chuyên-kỹ-thuật — **HẾT CỤM TỐI-ƯU-TẠO-JD.**

---

## ✅ CVT — Kho CV mẫu (hạ rào cản đầu phễu, PRD §8.2b) — **DONE**

> Ý tưởng đến TỪ NGOÀI roadmap → lọc qua PRD trước (§8.2b + FR-AP-6/7), rồi mới xây — đúng quy tắc ở cuối file.
> Rào cản thật: người muốn ứng tuyển nhưng chưa có CV thì rời trang, mất ứng viên TRƯỚC khi pipeline kịp chạy.

- **CVT-1 — Trang kho mẫu + lối vào — ✅ DONE (verify bằng trình duyệt thật).** Route CÔNG KHAI
  `/cv-templates`: lưới **3×3** cho 9 mẫu theo nhóm ngành, mỗi thẻ = tên ngành + mô tả một dòng + **ba nút,
  ba việc KHÁC nhau**: **Xem trước** (mở `.pdf` trong tab) · **Tải .docx** (chính) · **Sửa trên Google Docs**
  (chỉ hiện khi có link — đã dán đủ 9). 18 file tĩnh trong `public/cv-templates/`, **không backend,
  không API, không migration** → cũng không tiêu hạn mức rate-limit công khai. Nguồn duy nhất
  `lib/cv-templates.ts` (`slug` suy ra cả hai đường dẫn file). Lối vào: dòng "Chưa có CV? Tải CV mẫu về ngay"
  ở `/apply` (cùng tab) và `/apply/[jobId]` (**tab mới** — email+file là state React, rời trang là mất sạch;
  đã kiểm phản chứng: điều hướng cùng tab rồi Back mất cả hai).
  - **Code-split khỏi bundle HR** bằng CẤU TRÚC chứ không phải cấu hình: nằm ngoài nhóm route `(hr)` +
    Server Component không `"use client"` → route JS 186 B, `○ Static` (nhỏ nhất app). Không nạp shell
    sidebar lẫn guard `/api/auth/me`.
  - **Adversarial review 13 agent** (Next.js · a11y · quy ước repo · bề mặt công khai) → **7 lỗi thật đã vá**,
    đáng kể: `PublicHeader` khoá cứng 720px làm header lệch 160px dưới container 1040px (4/4 lăng kính cùng
    bắt → thêm prop `maxWidth`, mặc định giữ 720px nên `/apply|/screening|/booking` KHÔNG hồi quy);
    `aria-label` **thay** chữ nhìn thấy làm hỏng **WCAG 2.5.3 Label in Name** mức A trên cả 18 link (5/5 lăng
    kính); nút `ghost` cao 26px thay vì 37.5px khi xuống dòng; hover trên thẻ hứa "bấm được" nhưng ~90% diện
    tích vô tác dụng. Hai gotcha rút ra → `docs/AI_GUIDE.md`.
  - **CVT-1b — bỏ ép tải `.pdf`, đổi thành "Xem trước" — ✅ DONE.** Nhận ra sau khi dùng thật: PDF **không
    sửa được** (phần mềm sửa PDF thường mất phí, ít phổ biến) nên tải nó về máy là ngõ cụt — hai trong ba
    nút cùng làm một việc "quăng file vào máy", chỉ khác đuôi. Nhưng xoá hẳn PDF thì mất luôn khả năng
    **nhìn mẫu trước khi chọn**, mà chọn CV mẫu vốn là quyết định thị giác (tên ngành + một dòng mô tả
    không nói lên bố cục). Nên giữ file, đổi VIỆC: bỏ `download` + `target="_blank"` → PDF mở thẳng trong
    tab (đã kiểm header: Next KHÔNG gửi `Content-Disposition: attachment`), trình xem PDF của trình duyệt
    lại có sẵn nút tải nên không mất gì. Thứ tự nút đảo theo hành trình thật: xem → tải → sửa online.
  - **Chưa làm (có chủ ý):** mở `/cv-check` cho ứng viên — ý
    "đóng khung lại, 0 dòng code" KHÔNG đúng: `/api/agents/*` nằm sau `require_hr` (main.py `_HR_ONLY`), muốn
    khách dùng phải thêm endpoint công khai + rate-limit + chống lạm dụng LLM ⇒ **slice riêng**, chưa lên lịch.
  → **Milestone:** ứng viên chưa có CV không còn là ngõ cụt.

---

## ⚪ PWA — HR dashboard rút gọn + offline

> **Ngoại lệ Phase-7 ("UI polish is end-phase"):** PWA-1 kéo giao diện lên sớm vì phần UI của nó là
> **hành vi tính năng, không phải trang trí** — lọc điều hướng, guard route, danh sách responsive.
> Sau khi cắt 6 hạng mục theo spec (§10), phần còn lại **không chứa thiết kế nguyên tử nào mới**.

- **PWA-1 — HR dashboard rút gọn + offline trang "Mất kết nối" — ✅ DONE** (PRD §14, FR-PWA-1, NFR-4):
  khi chạy ở chế độ đã cài (`standalone`), PWA hiển thị **CHỈ ba màn:** Đăng nhập / Ứng viên
  (chi tiết rút gọn, chỉ đọc) / Hàng đợi review. Các màn còn lại (JD management, stat, live trace,
  gate toggle) **ẩn khỏi sidebar VÀ chặn ở đường dẫn** (redirect + lời giải thích). Offline: service
  worker cache tài nguyên tĩnh (không cache API/token-pages); trang offline có thương hiệu.

---

## 🧹 Dọn nhỏ còn treo

- **Đổi mật khẩu admin prod** (`admin@ars.prod` đã lộ trong chat) — script băm mật khẩu mới cho hr_user.

---

## 🟡 PHASE 7 — UI redesign ✅ XONG · tùy chọn cuối

- **UI redesign — ✅ XONG** (merge `e69b57a`, ~23 commit: hệ token Marine, thương hiệu HireFlow,
  redesign cổng công khai + đăng nhập, a11y WCAG AA). Ghi chép gốc bên dưới giữ lại làm bối cảnh:
  đánh bóng toàn giao diện trên bản live (SAU khâu tạo-JD, vì user chính = HR). Từng phần,
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
  4 đường) · [x] JD-3 AI-gợi-ý-rubric (LLM-verified + benchmark low<medium → chọn low) · [x] JD-4 soft-delete
  (ARCHIVED + delete_jd_vector seam + guard submit; live-verified 14/14) — **HẾT CỤM TỐI-ƯU-TẠO-JD**
- [x] **14 hardening tải** (session ĐỌC→CHẠY→GHI · toàn thân trong try · lưới đối soát hồ sơ kẹt; đo thật
  T=34.3s ⇒ trần 28→678 hồ sơ/đợt; adversarial review 21→1 lỗi thật đã vá; 290 test xanh)
- [ ] **10b — Pull scheduling (PRD §10b, MỚI):** thư mời + link đặt lịch (token RIÊNG, khác screener) →
  `AWAITING_BOOKING` → sinh slot LƯỜI khi ứng viên click → giữ 5 slot 10 phút → chọn 1 → INTERVIEW_SCHEDULED
  + `.ics` → nhắc trước 24h. ⚠️ `AWAITING_BOOKING` = thư mời ĐÃ gửi ⇒ **TUYỆT ĐỐI không cho vào
  `IN_FLIGHT_STATUSES`/tầm quét sweep** (xem *Load boundary* ở `docs/AI_GUIDE.md` — tái sinh lỗi mất hồ sơ).
  - [x] **SCH-1 nền booking** (tầng nghiệp vụ thuần, CHƯA ai gọi tới): `InterviewBooking`+`BookingSession`
    + migration viết tay **partial unique index** `UNIQUE(start_at) WHERE status='BOOKED'` (checkpoint
    LangGraph nguyên, `alembic check` sạch) · 14 env `BOOKING_*` qua `BookingConfig` có validate ·
    `generate_slots` sinh lười + giữ 10 phút + **bấm lại trả ĐÚNG slot cũ** + trộn sáng/chiều nhiều ngày ·
    `confirm_booking` HELD→BOOKED chống race · seam `CalendarProvider`+`IcsProvider` (0-dependency).
    51 test (36 trong `make test`, 15 gated `RUN_BOOKING_IT=1` gồm **race thật 2 transaction**).
  - [x] **SCH-2 lát dọc — luồng CHẠY THẬT:** cả BA đường quyết định mời (gate lần-đầu, gate sau-screener,
    HR duyệt) đi chung `booking_flow.dispatch_booking_invite` → thư mời kèm link → `AWAITING_BOOKING`
    (chỉ sau khi email gửi THÀNH CÔNG); endpoint công khai GET/POST + trang `/booking/[token]` (giờ VN,
    đếm ngược hold, 409 tự làm mới, `already_booked`); thư xác nhận kèm `.ics` → `INTERVIEW_SCHEDULED`.
    Verify LIVE (LLM + email thật) 8/8 bước, gồm race 2 ứng viên → đúng 1 thắng + 409.
    **Adversarial review 3 góc bắt 7 lỗi THẬT** (TOCTOU giữ chỗ 2 lượt GET → 10 hàng; đếm hạn mức theo
    hàng; `except` tự ném `PendingRollbackError`; giữ khoá hàng 1.29s qua lượt gửi mail + gửi thư trùng;
    thư mời bay trước khi ghi token → link 404; ứng viên bị từ chối vẫn tự đặt lịch được; deadlock ra
    500 thay vì 409) — đã vá + 5 test hồi quy trên DB thật.
  - [x] **SCH-3 hoàn thiện:** nhắc trước PV 24h · link hết hạn → nhắc 1 lần → `PENDING_REVIEW[booking_no_response]`
    (**KHÔNG auto-reject**) qua sweep 08c · link hủy → nhả slot + báo HR · HR xem/dời/hủy lịch trên dashboard.
- [x] **CVT-1 kho CV mẫu** (`/cv-templates` công khai, lưới 3×3, tĩnh 100%, 186 B `○ Static`, lối vào từ
  /apply; adversarial review 13 agent → 7 lỗi thật đã vá) + **CVT-1b** (ba nút ba việc: Xem trước `.pdf`
  trong tab · Tải `.docx` · Sửa trên Google Docs — 9 link đã dán) — PRD §8.2b, FR-AP-6/7
- [x] **PWA-1 — HR dashboard rút gọn + offline** (PRD §14, FR-PWA-1, NFR-4)
- [ ] Dọn: **đổi mật khẩu admin prod**
- [x] PHASE 7 — **UI redesign XONG** · [ ] 10 analytics(tùy chọn) · [ ] 12 anti-injection(tùy chọn) · [Observability BỎ] · [ ] **viết báo cáo**
- [ ] PHASE 8 — 15 optional (Zalo/push/learning-loop/hard-delete...)

---

## ✅ LOAD-1 — Test tải + scale (NFR-1) — **DONE**

> Mục tiêu do user chốt: **con số bảo vệ được trước hội đồng**, không phải scale tới enterprise.
> Toàn bộ số đo + hướng mở rộng → **`docs/load-and-scale.md`**.

- **Phương pháp:** `scripts/mock_openai.py` + env `OPENAI_API_BASE` ⇒ chạy ĐÚNG đường code thật
  (parser `invoke` đồng bộ → thread pool) với **0 đồng, 0 email**. `ENABLE_LLM=false` KHÔNG dùng được
  vì nó stub cả parser lẫn ranker = xoá đúng nút thắt cần đo. Đo local → xác nhận prod với LLM thật.
- **Công cụ mới:** `mock_openai.py` · `loadtest_booking.py` (chưa từng có) · `loadtest_apply.py` vá
  hai chỗ báo XANH GIẢ · `GET /api/health/metrics` (HR-only, KHÔNG I/O: pool DB · pool checkpointer ·
  executor asyncio · thread pool anyio · storage executor · pipeline đang bay).
- **Kết quả:** ≤80 CV cùng lúc xử lý trọn vẹn 0 mất · 200 CV: 107 lỗi → **0** sau vá · đặt lịch trần
  **~15 người xem đồng thời** (lưới **75** khung, KHÔNG phải ~90 như tài liệu cũ) · chống đặt trùng
  chịu được đua 12 chiều.
- **Chẩn đoán bất ngờ:** nút thắt là **khoá của `AsyncPostgresSaver`**, không phải thread pool
  (đối chứng: pool 5→25 chỉ giảm lỗi 13%) ⇒ phải chặn ở **đầu vào**, không nới ở **đầu ra**.
- **Còn nợ (đã ghi trong `docs/load-and-scale.md` §10):** `no_slots_at` giả · TOCTOU sinh khung giờ ·
  **rate limit công khai vô hiệu với người dùng thật** (ưu tiên cao — lỗ hổng chi phí LLM) ·
  `list_applications(limit=100)` làm HR mất ứng viên sau hồ sơ thứ 100 · dọn dữ liệu test trên prod.

---

## ✅ Các lát post-deploy đã xong nhưng trước đây KHÔNG được theo dõi ở file này

> Bổ sung 08/09/2026 sau một đợt audit toàn repo. ROADMAP đã trôi khỏi mã nguồn: năm cụm việc dưới
> đây đều đã merge vào `main` mà không có mục nào ở đây, nên file này không còn dùng được đúng vai
> trò "bản đồ việc còn lại". Chi tiết đầy đủ từng cụm nằm ở mục **Current status** của `CLAUDE.md`.

- [x] **SCH-1 · SCH-2 · SCH-3 — Ứng viên tự chọn giờ phỏng vấn** (PRD §10b). Nền đặt lịch + thư mời
      kèm link + vòng đời sau khi gửi link (nhắc trước PV, nhắc chọn lịch, hết hạn → `PENDING_REVIEW`,
      huỷ nhả slot tức thì). Ba lưới ghép vào sweep loop 08c, KHÔNG cơ chế nền mới.
- [x] **EMAIL-1 — Giao hàng email có theo dõi.** Bảng `email_delivery` + webhook Resend đã ký (HMAC,
      chống replay) + giữ nhịp/retry + cờ bounce/complaint hiện cho HR.
- [x] **EMAIL-2 — `email.failed`.** Cờ RIÊNG `email_send_failed` (không phải `email_failed` — chuỗi đó
      `scheduler._dispatch` đã chiếm làm tên audit action).
- [x] **DASH-1 — Dashboard soi được pipeline đang chạy.** `PARSING`/`RANKING` trước đây chỉ nằm trong
      graph state, DB không thấy ⇒ hồ sơ đứng ở `SUBMITTED` suốt ~34s. Thêm móc `on_node` +
      `GET /api/applications/pipeline` (payload cỡ cố định) thay cho việc poll cả danh sách.
- [x] **AUDIT-1 — Audit prod sau LOAD-1.** 32 phát hiện, 8 commit. Gốc rễ là
      `list_applications(limit=100)` làm 86 hồ sơ đã chấm điểm sạch trở nên không thể chạm tới bằng
      bất kỳ nút nào. Đã vá: phân trang + lọc `?status=` ở server, bỏ `parsed_data` khỏi danh sách,
      trần 60k ký tự khi trích CV, nộp CV gọi thẳng Render để rate-limit đếm đúng IP ứng viên.
- [x] **AUDIT-2 — Chặn CV dựng-để-phá.** Hạn giờ cứng bằng tiến trình con giết được (PDF một trang có
      chi phí **bậc hai theo số glyph**, và PyMuPDF không nhả GIL nên `to_thread` không cô lập được),
      tiền kiểm ZIP chống zip bomb, sửa lệch biên làm mất cờ `cv_truncated`.
- [x] **CONFIG-1 — Cấu hình hệ thống đọc từ DB** (PRD §NFR-8). 39 hằng số nghiệp vụ rời `.env` sang
      bảng `app_config` + màn `/system`. Kèm đường ĐỌC `audit_log` — bảng được 8 service ghi rất dày
      nhưng trước đó không có endpoint nào đọc, muốn tra phải vào thẳng Postgres.
- [x] **Gỡ Redis + Langfuse khỏi repo.** Cả hai chưa từng có một dòng code nghiệp vụ nào dùng tới;
      Redis chỉ tồn tại để trả lời chính cái health check hỏi nó. Observability đã BỎ khỏi phạm vi.
