# AGENTS.md — Autonomous Recruitment System

> Nội dung DƯỚI cặp `gitnexus:start/end` do công cụ TỰ SINH và bị ghi đè mỗi lần index lại.
> Mọi thứ viết tay phải nằm TRÊN marker đó.

## Đọc gì trước khi làm bất cứ việc gì

| File | Là gì | Khi nào đọc |
| --- | --- | --- |
| **`PRD.md`** (tiếng Việt) | **NGUỒN CHÂN LÝ về nghiệp vụ.** Mọi flow, agent, state, gate, yêu cầu. | Bất cứ khi nào không chắc hệ thống *phải hành xử ra sao*. Code trái PRD → **PRD thắng**. |
| **`CLAUDE.md`** | CÁCH build: stack, quy ước, lệnh, trạng thái từng lát. | Mỗi phiên, trước khi viết dòng code đầu tiên. |
| **`docs/AI_GUIDE.md`** | **Ranh giới** không được vượt + **gotcha** đã vấp thật. | **Trước MỌI task đụng code** — mở đúng mục liên quan. |
| `ROADMAP.md` | Còn lát nào, theo thứ tự nào. | Khi hỏi "tiếp theo làm gì". |
| `docs/deploy-live-issues.md` | Sự cố prod đã gặp + nguyên nhân gốc + cách vá. | Trước khi đụng checkpointer / rate-limit / config deploy. |

**Thứ tự tra cứu khi bí:** PRD.md → CLAUDE.md → docs/AI_GUIDE.md → ROADMAP.md → hỏi người dùng.
**Đừng ứng biến nghiệp vụ.**

## Tóm tắt tối thiểu (chi tiết ở CLAUDE.md — đừng chép lại vào đây, sẽ lệch nhau)

- **Là gì:** công cụ tuyển dụng nội bộ MỘT công ty, đa tác tử. **KHÔNG phải sàn việc làm hai chiều.**
  HR là admin; ứng viên là **guest vĩnh viễn** (không tài khoản, không đăng nhập, không xem được điểm/trạng thái).
- **Pipeline CỐ ĐỊNH, KHÔNG có Supervisor:** `parser → ranker → screener → scheduler` + `human_review` có điều kiện.
- **Stack:** Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 async · Alembic · Pydantic v2 · `uv`.
  Next.js 14 · Tailwind thuần (KHÔNG thêm thư viện UI) · TanStack Query. Neon · Upstash · Qdrant · Resend · OpenAI.
- **Lệnh:** backend `make dev-backend` · `make test` · `make migrate`; frontend
  `pnpm --filter dashboard dev|build|typecheck`; git dùng `git -C <repo-root> …` (**tránh `cd`** — hook fnm vỡ).
- **Quy ước bắt buộc:** async-first; config từ env (KHÔNG hardcode secret/URL/ngưỡng); type đầy đủ;
  secret chỉ ở `.env`; commit nhỏ có tiền tố lát.

## Ranh giới KHÔNG được vượt

- `scheduler` là **điểm phát email DUY NHẤT** tới ứng viên — đừng rải lệnh gửi ở node khác.
- Ca bất định / có cờ **LUÔN** về `human_review`. Gate không bao giờ auto-reject một hồ sơ có cờ ("cờ thắng gate").
- Projection JD công khai **KHÔNG được lộ** `rubric` / `gate_config` / `screener_questions`.
- Đọc/ghi CV **chỉ qua** seam `services/storage`; `cv_file_ref` là KEY, không phải path, không trả ra client.
- Router HR mới → **nhớ áp `require_hr`**. `/api/public/*`, `/api/auth/login|logout`, health giữ MỞ.
- **Không giữ session/connection DB qua I/O chậm** (LLM, R2, email) — xem *Load boundary* ở `docs/AI_GUIDE.md`.
- Không tự tạo trạng thái "nói dối": chỉ đặt trạng thái CUỐI sau khi email đã thật sự gửi.

## Bốn nguyên tắc làm việc

1. **Nghĩ trước khi code** — nêu giả định; không chắc thì HỎI; nhiều cách hiểu thì TRÌNH BÀY, đừng tự chọn.
2. **Đơn giản trước** — ít code nhất giải quyết được vấn đề. Không làm quá phạm vi được giao.
3. **Sửa đúng chỗ cần sửa** — đừng "cải thiện" code xung quanh. Thấy code chết thì BÁO, đừng xoá.
4. **Có tiêu chí thành công rồi lặp tới khi kiểm chứng được** — mỗi lát cần Verify thật + review độc lập.

## GitNexus — đính chính cho khối tự sinh bên dưới

Khối dưới marker bị ghi đè mỗi lần index lại, nên hai điều này ghi ở đây (đã kiểm chứng 2026-08-04):

- **LUÔN truyền `repo: "Agentic-Recruitment-System"`** cho `impact`/`context`/`detect_changes`/`query`.
  Máy này index nhiều repo; thiếu `repo` thì `impact`/`context` trả `"Target not found"` và
  `detect_changes` trả `"No changes detected"` **dù đang có file sửa** — xanh giả ngay trước lúc commit.
- **`impact` bỏ sót hàm chỉ được đăng ký runtime** (vd `background_tasks.add_task(fn, …)`): báo LOW
  không có nghĩa là an toàn. Grep thêm khi đụng loại hàm đó.

<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Agentic-Recruitment-System** (3203 symbols, 5961 relationships, 131 execution flows). Use the GitNexus MCP tools to understand code, assess impact, and navigate safely.

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
