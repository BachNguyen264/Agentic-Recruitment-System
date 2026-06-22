# Backend — Autonomous Recruitment System

FastAPI · LangGraph · SQLAlchemy 2 (async) · Alembic · Pydantic v2. Quản lý gói bằng `uv`.

> Scaffold: node agent là *stub*, chưa có logic nghiệp vụ. Nguồn chân lý: [`../../PRD.md`](../../PRD.md).

## Chạy

```bash
uv sync                                              # cài deps (editable install app/)
uv run uvicorn app.main:app --reload --port 8000     # http://localhost:8000/docs
uv run alembic upgrade head                          # migration (Phase 3+)
uv run pytest -q                                     # test (Phase 4+)
```

Secrets đọc từ `.env` ở **gốc repo** (không phải thư mục này) — xem `app/core/config.py`.

## Cấu trúc `app/`

```
app/
├── main.py                 # FastAPI app + lifespan
├── core/                   # config, database (Neon SSL), redis, qdrant, logging
├── api/                    # deps + routes (health, applications, agents)
├── agents/                 # state, graph, policy, nodes/* (LangGraph — Phase 4)
├── models/                 # SQLAlchemy models (Phase 3)
├── schemas/                # Pydantic I/O (Phase 3+)
├── services/               # application_service, audit_service (Phase 3+)
├── tasks/                  # background.py (BackgroundTasks — Phase 5)
└── tools/                  # placeholder agent tools (PRD §7 — phase sau)
```
