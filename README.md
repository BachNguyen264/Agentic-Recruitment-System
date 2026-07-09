# Hệ thống Tuyển dụng Tự trị sử dụng Multi-Agent AI

> Đồ án tốt nghiệp — proof-of-concept. **Nguồn chân lý nghiệp vụ: [`PRD.md`](./PRD.md).**
> Quy ước code cho Claude Code: [`CLAUDE.md`](./CLAUDE.md). Kiến trúc tóm tắt: [`docs/architecture.md`](./docs/architecture.md).

Tự động hóa vòng sàng lọc tuyển dụng từ khi nhận CV đến khi gửi thư mời phỏng vấn. Bốn AI Agent chuyên
biệt phối hợp trong một **pipeline cố định** (KHÔNG có Supervisor); HR chỉ can thiệp ở điểm quyết định hoặc
khi hệ thống không đủ tự tin.

```
parser → ranker → [gate rank] → screener (suspend/resume) → [gate mời] → scheduler
                      │                                            │
                      └──────────────► human_review ◄─────────────┘  (có điều kiện)
```

> **Giai đoạn: đang build từng lát.** Đã THẬT: `parser` (CV→JSON, OpenAI `gpt-4.1-mini`), `ranker` (chấm
> rubric, `gpt-5-mini` + embedding Qdrant làm tín hiệu phụ), quản lý JD + embedding, dashboard PWA + `/cv-check`.
> Còn **stub**: `screener`/`scheduler`/`human_review`. CHƯA làm: 2 gate (§9), Screener async (§10), ReviewCard
> (§11), email/Calendar, vòng học. Trạng thái chi tiết + gotchas: [`CLAUDE.md`](./CLAUDE.md).

---

## Kiến trúc & Tech Stack

| Lớp        | Công nghệ                                                                |
| ---------- | ------------------------------------------------------------------------ |
| Backend    | Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · `uv` |
| Frontend   | Next.js 14 · plain Tailwind (slate) · TanStack Query (shadcn/ui chưa cài) |
| PWA        | web dashboard cài được trên điện thoại (Add to Home Screen) — không codebase mobile riêng |
| Hạ tầng    | Neon (Postgres) · Upstash Redis · Qdrant Cloud · (Langfuse — phase sau)  |
| Async      | FastAPI BackgroundTasks (KHÔNG worker polling — giữ free-tier Upstash)   |
| Monorepo   | pnpm workspaces (`apps/dashboard`, `packages/*`)                         |

---

## Cấu trúc thư mục

```
autonomous-recruitment-system/
├── PRD.md  CLAUDE.md  plan.md            # tài liệu (PRD = nguồn chân lý)
├── README.md  Makefile  .env.example  .gitignore
├── docker-compose.local.yml              # hạ tầng local dự phòng
├── package.json  pnpm-workspace.yaml
├── apps/
│   ├── backend/      # FastAPI · LangGraph (Python, uv)
│   └── dashboard/    # Next.js 14 — dashboard HR + cổng công khai (PWA cài được)
├── packages/shared-types/                # type dùng chung TS
└── docs/architecture.md
```

---

## Yêu cầu môi trường (Prerequisites)

| Công cụ | Phiên bản    | Ghi chú                                            |
| ------- | ------------ | -------------------------------------------------- |
| Node.js | ≥ 20 (LTS)   | `corepack enable && corepack prepare pnpm@latest`  |
| pnpm    | 9.x          |                                                    |
| Python  | 3.12.x       | Khuyến nghị quản lý qua `uv` (tự tải CPython 3.12) |
| uv      | latest       | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker  | (tùy chọn)   | Chỉ khi chạy hạ tầng local dự phòng                |

---

## Bắt đầu nhanh (Quickstart)

```bash
# 1. Cấu hình bí mật: copy ví dụ rồi điền connection string (Neon/Upstash/Qdrant)
cp .env.example .env                 # rồi điền giá trị thật

# 2. Cài phụ thuộc
make install                         # = uv sync (backend) + pnpm install (workspace)

# 3. Kiểm tra kết nối 3 dịch vụ managed
make check-env

# 4. Migration DB (tạo bảng)
make migrate

# 5. Chạy từng phần
make dev-backend                     # FastAPI  → http://localhost:8000  (/api/health, /docs)
make dev-dashboard                   # Next.js  → http://localhost:3000
```

> Web là **PWA**: ở bản production, cài lên điện thoại qua *Add to Home Screen* — một codebase web
> duy nhất, không app mobile riêng.

> **Windows (không có make):** dùng Git Bash (đã kèm make) hoặc chạy lệnh tương đương:
> `cd apps/backend && uv run uvicorn app.main:app --reload --port 8000`,
> `pnpm --filter dashboard dev`, `cd apps/backend && uv run alembic upgrade head`, …
> (xem `Makefile` để biết lệnh đầy đủ).

### Chưa có tài khoản managed? Chạy local

```bash
make local-infra-up                  # Postgres + Redis + Qdrant qua docker compose
# rồi trỏ .env sang các URL local (xem .env.example, mục "LOCAL FALLBACK")
make local-infra-down
```

---

## Tài liệu

- **[`PRD.md`](./PRD.md)** — nguồn chân lý: nghiệp vụ, 4 agent, luồng, FR/NFR, mô hình dữ liệu.
- **[`CLAUDE.md`](./CLAUDE.md)** — quy ước code.
- **[`docs/architecture.md`](./docs/architecture.md)** — tóm tắt kiến trúc, trỏ về PRD.
- `plan.md` — kịch bản **one-shot cho lát hiện tại** (dùng xong bỏ, KHÔNG phải nguồn chân lý).
