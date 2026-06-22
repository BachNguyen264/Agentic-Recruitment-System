# PLAN — Scaffold Monorepo: HỆ THỐNG TUYỂN DỤNG TỰ TRỊ

> **Bản chất file này:** kịch bản ONE-SHOT để dựng khung dự án ban đầu. Scaffold xong thì **bỏ** —
> KHÔNG phải nguồn chân lý. Nguồn chân lý của hệ thống là **`PRD.md`**.
> Repo này dành RIÊNG cho đề tài tuyển dụng (đề tài CSKH có repo riêng).
>
> **Phạm vi:** CHỈ dựng nền móng — monorepo, môi trường, skeleton **chạy được**. Node agent là **stub**,
> UI là **placeholder**. KHÔNG triển khai logic nghiệp vụ thật. Mục tiêu: khung sạch để cắm logic theo PRD.
>
> **Kiến trúc (theo PRD §5–§8):** pipeline cố định `parser → ranker → screener → scheduler` + human_review
> có điều kiện, KHÔNG có Supervisor. Hạ tầng managed-first (Neon · Upstash · Qdrant); giữ docker-compose.local.yml dự phòng.

---

## 1. Pipeline & thứ tự (khớp PRD §7–§8)

`parser → ranker → [gate rank] → screener (suspend/resume) → [gate mời] → scheduler`, cộng `human_review`
có điều kiện. Ở scaffold, 5 node là **stub**: `parser`, `ranker`, `screener`, `scheduler`, `human_review`.
Node ra quyết định là `ranker` (sau nó là gate rank). Chi tiết nghiệp vụ: xem PRD, KHÔNG lặp lại ở đây.

---

## 2. In / Out scope (scaffold)

**In scope:**

- Monorepo pnpm workspaces + backend Python.
- Kết nối Neon · Upstash Redis · Qdrant Cloud; `/api/health` ping thật cả 3.
- Skeleton LangGraph: `RecruitmentState` (chừa sẵn confidence/uncertainty/escalation + các trường Screener),
  5 node stub, `policy.py` route theo confidence, endpoint demo chạy **cả 2 nhánh** (scheduler / human_review).
- Async skeleton bằng FastAPI BackgroundTasks.
- Dashboard Next.js (trạng thái service + agent-trace placeholder) + Mobile Expo (trạng thái backend).
- `shared-types`; migration Alembic tạo bảng tối thiểu (job_posting, application, audit_log) — đủ rộng theo PRD §16.
- `.env.example`, `.gitignore`, `README.md`, `Makefile`, `docker-compose.local.yml`.
- Sao chép `PRD.md` và `CLAUDE.md` vào repo (đặt ở gốc).

**Out of scope (chỉ CHỪA CHỖ — theo PRD §17):** logic parse CV / RAG / chấm điểm / Screener async / gate /
human_review / vòng học thật; LLM trong pipeline (`ENABLE_LLM=false`); tích hợp email/Calendar/Zalo; auth đầy đủ.

---

## 3. Tech Stack & Phiên bản

| Thành phần            | Lựa chọn                                           | Phiên bản / Ghi chú                            |
| --------------------- | -------------------------------------------------- | ---------------------------------------------- |
| Monorepo (JS)         | pnpm workspaces                                    | pnpm 9.x                                       |
| Node.js               | LTS                                                | 20.x / 22.x                                    |
| Python                | CPython                                            | 3.12.x                                         |
| Python pkg manager    | uv (fallback venv+pip)                             | latest                                         |
| Backend               | FastAPI + uvicorn[standard]                        | 0.115.x / 0.30.x                               |
| Agent orchestration   | LangGraph                                          | 0.2.x                                          |
| LLM SDK               | langchain-anthropic                                | 0.2.x (chưa bật)                               |
| ORM / Migration       | SQLAlchemy 2.0.x / Alembic 1.13.x                  | async                                          |
| DB driver             | asyncpg                                            | 0.29.x (Neon cần SSL)                          |
| Validation            | Pydantic 2.9.x / pydantic-settings 2.5.x           |                                                |
| PostgreSQL            | Neon (managed)                                     | free: 0.5GB, 100 CU-hrs/tháng                  |
| Redis                 | Upstash (managed)                                  | free: 500K lệnh/tháng; cache/short-term memory |
| Vector DB             | Qdrant Cloud (managed)                             | free: 1GB; embedding JD–CV                     |
| Async jobs (scaffold) | FastAPI BackgroundTasks                            | không broker                                   |
| Async jobs (sau)      | Upstash QStash                                     | cần public URL khi dev                         |
| Frontend              | Next.js 14 · Tailwind · shadcn/ui · TanStack Query |                                                |
| Mobile                | React Native / Expo                                | SDK 51+                                        |
| Container (dự phòng)  | Docker + Compose v2                                | chỉ cho docker-compose.local.yml               |

---

## 4. Prerequisites

```bash
node --version              # >= 20
corepack enable && corepack prepare pnpm@latest --activate
python3 --version           # 3.12.x
# uv:  curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
# (tùy chọn) docker --version
```

---

## 5. TRƯỚC KHI BẮT ĐẦU — tài khoản managed (việc của con người)

Claude Code tạo `.env.example` + checklist rồi **DỪNG chờ** `.env` được điền.

| Dịch vụ                  | Đăng ký                    | Cần lấy               |
| ------------------------ | -------------------------- | --------------------- |
| Neon                     | https://neon.tech          | Connection string     |
| Upstash Redis            | https://upstash.com        | `rediss://` URL (TLS) |
| Qdrant Cloud             | https://cloud.qdrant.io    | Cluster URL + API key |
| Langfuse (optional, sau) | https://cloud.langfuse.com | Public + Secret key   |

---

## 6. Cấu trúc Monorepo

```
autonomous-recruitment-system/
├── PRD.md                        # NGUỒN CHÂN LÝ (giữ ở gốc)
├── CLAUDE.md                     # quy ước code (Claude Code tự đọc)
├── plan.md                       # file này — bỏ sau scaffold
├── README.md, Makefile, .gitignore, .env.example
├── docker-compose.local.yml      # dự phòng
├── package.json, pnpm-workspace.yaml
├── apps/
│   ├── backend/                  # FastAPI · LangGraph
│   │   ├── pyproject.toml, Dockerfile, .env.example, alembic.ini, alembic/
│   │   └── app/
│   │       ├── main.py
│   │       ├── core/{config.py, database.py, redis_client.py, qdrant_client.py, logging.py}
│   │       ├── api/{deps.py, routes/{health.py, applications.py, agents.py}}
│   │       ├── agents/{state.py, graph.py, policy.py, nodes/{parser,ranker,screener,scheduler,human_review}.py}
│   │       ├── models/{base.py, job_posting.py, application.py, audit_log.py}
│   │       ├── schemas/{application.py, agent.py}
│   │       ├── services/{application_service.py, audit_service.py}
│   │       ├── tools/            # placeholder (PRD §7 — phase sau)
│   │       └── tasks/{background.py}
│   ├── dashboard/                # Next.js 14 — dashboard HR + cổng công khai (placeholder)
│   └── mobile/                   # Expo — HR duyệt nhanh (placeholder)
├── packages/shared-types/
└── docs/architecture.md          # tóm tắt kiến trúc + trỏ PRD
```

---

## 7. Kế hoạch theo Phase

> Sau MỖI phase: chạy "Verify", hiển thị output, `git commit` (`feat(scaffold): phase N - ...`), tiếp tục nếu không lỗi.

**Phase 0 — Khởi tạo.** `git init`, `.gitignore`, prerequisites, README, pnpm-workspace, root package.json,
Makefile (`dev-backend`, `dev-dashboard`, `dev-mobile`, `migrate`, `health`, `test`, `local-infra-up/down`).
Đặt sẵn `PRD.md` + `CLAUDE.md` ở gốc.
**Verify:** `pnpm -v`, `python3 --version`, `uv --version` OK; git sạch.

**Phase 1 — Kết nối managed.** Tạo `.env.example` + checklist §5. **DỪNG** chờ `.env`. Tạo docker-compose.local.yml dự phòng.
**Verify:** script kiểm tra kết nối 3 dịch vụ.

**Phase 2 — Backend + Health.** `uv init`; `config.py` (gồm `CONFIDENCE_THRESHOLD=0.6`, `SCREENER_DEADLINE_HOURS=72`,
`SCREENER_REMINDER_HOURS=24` — đọc env, ghi chú "tinh chỉnh ở Chương 4"); `database.py` (Neon SSL qua
`connect_args={"ssl": True}`, KHÔNG `sslmode=`); redis/qdrant client; `main.py`; `health.py` ping thật.
**Verify:** `/api/health` trả `ok` cho api + 3 dịch vụ.

**Phase 3 — Models + Migration.** `job_posting` (id, title, description, rubric JSONB, screener_questions JSONB,
gate_config JSONB, status, timestamps); `application` (id, job_id, applicant_email, parsed_data JSONB, score,
score_breakdown JSONB, status, confidence, uncertainty_flags JSONB, escalation_reason, screener_sent_at,
screener_deadline, timestamps); `audit_log` (id, application_id, node, action, confidence, uncertainty_flags JSONB,
escalation_reason, detail JSONB, created_at). Alembic async + migration đầu. Service + `applications.py` (POST/GET).
**Verify:** `make migrate`; POST/GET application; 3 bảng tồn tại.

**Phase 4 — Skeleton LangGraph.** `state.py` `RecruitmentState`: `application_id, input, scratchpad,
messages(append-only), status, result, error` + **chừa sẵn** `confidence, uncertainty_flags, escalation_reason,
require_human_review` + **trường Screener** `awaiting_screener: bool, screener_answers`. 5 node stub set giá trị
stub (`confidence=1.0`, `uncertainty_flags=[]`); `ranker` là node quyết định; `human_review` set
`require_human_review=True` + `escalation_reason`. `policy.py` `should_review(state)`. `graph.py`:
`parser → ranker → [should_review] → (screener-path | human_review)`; trong scaffold giữ tuyến tính đơn giản,
conditional sau ranker route `scheduler`(đại diện nhánh tự động) vs `human_review`. Checkpointer `MemorySaver`
(TODO: Postgres cho Screener suspend — PRD §10). `agents.py` `run-demo` có cờ ép nhánh → chạy **cả 2 nhánh**.
TODO rõ: `# TODO (PRD §9/§10): gate, screener suspend/resume`.
**Verify:** `make test` (graph compile + 2 nhánh); `run-demo` trả trace đúng nhánh + confidence.

**Phase 5 — Async (BackgroundTasks).** `tasks/background.py` `process_application(id)` → log + audit + (tùy chọn)
graph. TODO: QStash + Screener suspend (PRD §10).
**Verify:** POST application → task nền ghi audit_log.

**Phase 6 — Frontend & Mobile & shared-types.** `shared-types`: `Application, AgentTraceStep(node, confidence,
branch), HealthStatus`. Dashboard `/`: ServiceStatus + AgentTracePanel (Run demo + toggle ép review). Mobile
StatusScreen. `docs/architecture.md` (tóm tắt + trỏ PRD).
**Verify:** dashboard localhost:3000 (3 service xanh + Run demo 2 nhánh); Expo OK; `pnpm -r build` pass.

---

## 8. Definition of Done

- [ ] `.env` có managed HOẶC trỏ local.
- [ ] `/api/health` trả `ok` (api + 3 dịch vụ).
- [ ] `make migrate`; bảng job_posting/application/audit_log tồn tại (đủ cột theo PRD §16).
- [ ] `RecruitmentState` chừa sẵn confidence/uncertainty_flags/escalation_reason/require_human_review + trường Screener.
- [ ] `run-demo` chạy **cả 2 nhánh** (scheduler / human_review), trace có nhánh + confidence.
- [ ] `make test` xanh; BackgroundTask ghi audit_log.
- [ ] dashboard + mobile chạy; `pnpm -r build` pass; `shared-types` dùng chung.
- [ ] Chỉ `.env.example` commit; `.env` gitignore.
- [ ] `PRD.md`, `CLAUDE.md` ở gốc repo; `docs/architecture.md` trỏ PRD.

---

## 9. Lưu ý cho Claude Code

- Async-first; cấu hình từ env; không hardcode secret. Mỗi phase 1 commit.
- **Chừa chỗ, không build logic thật** (theo PRD): State có sẵn các trường; `should_review` route được;
  demo 2 nhánh; audit_log đủ cột. Logic gate/Screener-async/parse/RAG/vòng học → stub + TODO trỏ PRD.
- Async/queue: BackgroundTasks (KHÔNG worker polling Redis — phá free tier Upstash).
- Phase 1: DỪNG chờ `.env` trước khi verify kết nối.
- Mọi quyết định nghiệp vụ → tra `PRD.md`, KHÔNG suy diễn. Plan này chỉ lo dựng khung.
- Kết thúc: in cây thư mục, lệnh chạy, checklist DoD.
