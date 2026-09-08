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

> **Giai đoạn: đã chạy end-to-end trên bản deploy thật.** Cả 5 node đều THẬT — `parser` (CV→JSON,
> `gpt-4.1-mini`), `ranker` (chấm rubric `gpt-5-mini`, embedding Qdrant làm tín hiệu phụ), `screener`
> (suspend/resume qua LangGraph `interrupt` + magic-link, có hạn giờ/nhắc), `scheduler` (điểm phát email
> DUY NHẤT, qua Resend), `human_review` (ReviewCard + duyệt/từ chối). Hai gate auto-reject/auto-invite,
> ứng viên tự chọn giờ phỏng vấn, và dashboard HR đều đang chạy.
>
> **Còn lại:** analytics, chống prompt-injection, vòng học bán tự động, Google Calendar (hiện dùng `.ics`).
> Trạng thái chi tiết + bẫy đã vấp: [`CLAUDE.md`](./CLAUDE.md) · [`docs/AI_GUIDE.md`](./docs/AI_GUIDE.md).
>
> Tên kỹ thuật của dự án là **ARS**; tên hiển thị cho người dùng cuối là **HireFlow** (đặt ở
> `app/layout.tsx`, `app/manifest.ts`, `components/Logo.tsx`) — hai cái tên, một sản phẩm.

---

## Kiến trúc & Tech Stack

| Lớp        | Công nghệ                                                                |
| ---------- | ------------------------------------------------------------------------ |
| Backend    | Python 3.12 · FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2 · `uv` |
| Frontend   | Next.js 14 · Tailwind thuần + hệ token "Marine" tự khai · TanStack Query (KHÔNG dùng thư viện UI) |
| PWA        | web dashboard cài được trên điện thoại (Add to Home Screen) — không codebase mobile riêng |
| Hạ tầng    | Neon (Postgres) · Qdrant Cloud (vector) · Cloudflare R2 (file CV, bucket PRIVATE) |
| Email      | Resend (gửi + webhook theo dõi giao hàng đã ký)                          |
| Deploy     | Backend: Render (Docker) sau Cloudflare · Frontend: Vercel — xem [`docs/deploy-live-issues.md`](./docs/deploy-live-issues.md) |
| Async      | FastAPI BackgroundTasks (KHÔNG worker polling — không dựng hàng đợi ngoài) |
| Monorepo   | pnpm workspaces (`apps/dashboard`, `packages/*`)                         |

---

## Cấu trúc thư mục

```
autonomous-recruitment-system/
├── PRD.md  CLAUDE.md  ROADMAP.md  AGENTS.md   # tài liệu (PRD = nguồn chân lý)
├── README.md  Makefile  .env.example  .gitignore
├── Dockerfile  .dockerignore             # ảnh backend cho Render
├── docker-compose.local.yml              # hạ tầng local dự phòng
├── package.json  pnpm-workspace.yaml
├── scripts/                              # seed HR, kiểm kết nối, đo tải, LLM giả lập
├── apps/
│   ├── backend/      # FastAPI · LangGraph (Python, uv)
│   └── dashboard/    # Next.js 14 — dashboard HR + cổng công khai (PWA) + .env.example riêng cho Vercel
├── packages/shared-types/                # type dùng chung TS
└── docs/
    ├── AI_GUIDE.md                       # ranh giới được phép làm gì + mọi bẫy đã vấp
    ├── architecture.md
    ├── deploy-live-issues.md             # sự cố prod + nguyên nhân gốc + cách verify
    └── load-and-scale.md                 # số đo tải thật + hướng scale
```

---

## Yêu cầu môi trường (Prerequisites)

| Công cụ | Phiên bản    | Ghi chú                                            |
| ------- | ------------ | -------------------------------------------------- |
| Node.js | ≥ 20 (LTS)   | `corepack enable` (tự lấy đúng pnpm ghi trong `package.json`) |
| pnpm    | 9.x          |                                                    |
| Python  | 3.12.x       | Khuyến nghị quản lý qua `uv` (tự tải CPython 3.12) |
| uv      | latest       | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Docker  | (tùy chọn)   | Chỉ khi chạy hạ tầng local dự phòng                |

---

## Bắt đầu nhanh (Quickstart)

```bash
# 1. Cấu hình bí mật
cp .env.example .env                 # rồi điền giá trị thật — xem bảng biến tối thiểu bên dưới

# 2. Cài phụ thuộc
make install                         # = uv sync (backend) + pnpm install (workspace)

# 3. Kiểm tra kết nối 2 dịch vụ managed (Neon · Qdrant)
make check-env

# 4. Migration DB (tạo bảng)
make migrate

# 5. Tạo tài khoản HR — BẮT BUỘC, hệ thống KHÔNG có luồng tự đăng ký
uv run --directory apps/backend python ../../scripts/seed_hr_admin.py   # idempotent

# 6. Chạy từng phần
make dev-backend                     # FastAPI  → http://localhost:8000  (/api/health, /docs)
make dev-dashboard                   # Next.js  → http://localhost:3000  (đăng nhập tại /login)
```

**Biến tối thiểu để chạy được** (chi tiết + checklist prod nằm trong `.env.example`):

| Biến | Vì sao bắt buộc |
| --- | --- |
| `DATABASE_URL` · `QDRANT_URL` | Không có thì migration và embedding JD đều hỏng |
| `JWT_SECRET` (≥ 32 ký tự) | Thiếu là **đăng nhập HR ném lỗi cấu hình**, không phải 401. Sinh bằng `openssl rand -hex 32` |
| `HR_ADMIN_EMAIL` · `HR_ADMIN_PASSWORD` | Đầu vào của bước 5. Backend lúc chạy KHÔNG đọc hai biến này — chỉ script seed đọc |
| `ENABLE_LLM` | Mặc định `false` = parser/ranker chạy **nhánh stub** (dùng cho test, không tốn tiền). Đặt `true` mới gọi OpenAI thật |
| `OPENAI_API_KEY` | Chỉ cần khi `ENABLE_LLM=true` |
| `RESEND_API_KEY` | Chỉ cần khi muốn gửi email thật cho ứng viên |

> Có **HAI** file `.env.example`: file ở gốc repo dành cho backend (Render), file
> `apps/dashboard/.env.example` dành cho frontend (Vercel).

> Web là **PWA**: ở bản production, cài lên điện thoại qua *Add to Home Screen* — một codebase web
> duy nhất, không app mobile riêng.

> **Windows (không có make):** dùng Git Bash (đã kèm make) hoặc chạy lệnh tương đương:
> `cd apps/backend && uv run python -m app`, `pnpm --filter dashboard dev`,
> `cd apps/backend && uv run alembic upgrade head`, … (xem `Makefile` để biết lệnh đầy đủ).
>
> ⚠ Trên Windows **phải** chạy `python -m app`, KHÔNG được gọi `uvicorn app.main:app` trực tiếp:
> `app/__main__.py` đặt `WindowsSelectorEventLoopPolicy` trước khi khởi động, mà psycopg async cần
> event loop đó. Gọi thẳng uvicorn thì backend chết ngay lúc dựng checkpointer.

### Chưa có tài khoản managed? Chạy local

```bash
make local-infra-up                  # Postgres + Qdrant qua docker compose
# rồi trỏ .env sang các URL local (xem .env.example, mục "LOCAL FALLBACK")
make local-infra-down
```

---

## Tài liệu

- **[`PRD.md`](./PRD.md)** — nguồn chân lý: nghiệp vụ, 4 agent, luồng, FR/NFR, mô hình dữ liệu.
- **[`CLAUDE.md`](./CLAUDE.md)** — quy ước code + trạng thái từng lát.
- **[`docs/AI_GUIDE.md`](./docs/AI_GUIDE.md)** — ranh giới không được vượt + mọi cái bẫy đã vấp thật,
  kèm nguyên nhân gốc. Mở file này trước khi sửa code.
- **[`ROADMAP.md`](./ROADMAP.md)** — các lát còn lại và thứ tự.
- **[`docs/architecture.md`](./docs/architecture.md)** — tóm tắt kiến trúc, trỏ về PRD.
- **[`docs/deploy-live-issues.md`](./docs/deploy-live-issues.md)** — sự cố đã gặp trên bản deploy thật,
  nguyên nhân gốc và cách verify. Đọc trước khi đụng checkpointer / rate-limit / cấu hình deploy.
- **[`docs/load-and-scale.md`](./docs/load-and-scale.md)** — số đo tải thật và hướng scale.
