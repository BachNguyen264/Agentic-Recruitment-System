# Backend (FastAPI + LangGraph) cho Render — slice 13.
#
# BỐI CẢNH: backend là TIẾN TRÌNH BỀN, KHÔNG serverless. Sweep timeout Screener (08c), pool
# checkpointer Postgres (08a) và BackgroundTasks đều sống trong process này — Lambda/Edge sẽ giết chúng.
#
# Build context = GỐC REPO (cần cả apps/backend lẫn scripts/). Trên Render:
#   Dockerfile Path = ./Dockerfile · Docker Build Context Directory = .  (mặc định)
#   Health Check Path = /api/health
# Secrets KHÔNG nằm trong image — Render truyền qua env vars (xem .env.example mục PROD).

FROM python:3.12-slim-bookworm

# uv (pin theo bản đang dùng ở local — build lặp lại được).
COPY --from=ghcr.io/astral-sh/uv:0.11.21 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    # venv của uv nằm trong thư mục backend → cho vào PATH để gọi thẳng `alembic` / `python`.
    PATH="/srv/apps/backend/.venv/bin:$PATH" \
    # Render bind 0.0.0.0 và cấp $PORT (Settings.port đọc env PORT; 8000 chỉ là fallback khi chạy tay).
    HOST=0.0.0.0 \
    APP_ENV=production

WORKDIR /srv/apps/backend

# 1) Deps TRƯỚC source → layer cache không vỡ mỗi lần sửa code.
#    --frozen: dùng đúng uv.lock, không tự giải lại phụ thuộc. --no-dev: bỏ pytest/httpx.
COPY apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Source backend + scripts (seed_hr_admin.py chạy tay trong Render Shell — xem runbook).
COPY apps/backend/ ./
COPY scripts/ /srv/scripts/
RUN uv sync --frozen --no-dev

# Chạy KHÔNG phải root (một tầng phòng thủ nữa cho CV — dữ liệu cá nhân, NFR-4).
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /srv
USER appuser

EXPOSE 8000

# Migration TRƯỚC rồi mới lên server (khớp plan §3.2). `exec` để uvicorn thành PID 1 và NHẬN SIGTERM
# của Render → lifespan teardown chạy: dừng sweep, đóng checkpointer/Redis/Qdrant/DB sạch sẽ.
# Migration hỏng → container thoát, deploy FAIL rõ ràng, KHÔNG chạy app trên schema sai.
CMD ["sh", "-c", "alembic upgrade head && exec python -m app"]
