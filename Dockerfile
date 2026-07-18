# Backend (FastAPI + LangGraph) cho Render — slice 13.
#
# BỐI CẢNH: backend là TIẾN TRÌNH BỀN, KHÔNG serverless. Sweep timeout Screener (08c), pool
# checkpointer Postgres (08a) và BackgroundTasks đều sống trong process này — Lambda/Edge sẽ giết chúng.
#
# Build context = GỐC REPO (cần cả apps/backend lẫn scripts/). Trên Render:
#   Dockerfile Path = ./Dockerfile · Docker Build Context Directory = .  (mặc định)
#   Health Check Path = /api/health/live   ← liveness THUẦN, KHÔNG phải /api/health (kiểm sâu):
#     Render ping vài giây một lần, liên tục → trỏ vào /api/health sẽ đốt hạn mức Upstash free
#     (10k lệnh/ngày) và giữ Neon luôn thức. Xem api/routes/health.py.
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

# Chạy KHÔNG phải root (một tầng phòng thủ nữa cho CV — dữ liệu cá nhân, NFR-4). Tạo user TRƯỚC khi
# cài deps: `chown -R` SAU khi dựng .venv sẽ chạm lại từng file của pymupdf/boto3/psycopg/langgraph
# → Docker ghi TOÀN BỘ cây thư viện thành một layer nữa (image phình vài trăm MB, kéo dài mọi lần
# pull + cold start trên gói free). Dùng --chown lúc COPY thì không phải chown lại gì cả.
# Tạo SẴN cả cây thư mục rồi chown (WORKDIR tự tạo thư mục thiếu nhưng thuộc root — uv sẽ không ghi
# nổi .venv). Lúc này các thư mục còn rỗng nên -R gần như miễn phí.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /srv/apps/backend /srv/scripts \
    && chown -R appuser:appuser /srv
USER appuser
WORKDIR /srv/apps/backend

# 1) Deps TRƯỚC source → layer cache không vỡ mỗi lần sửa code.
#    --frozen: dùng đúng uv.lock, không tự giải lại phụ thuộc. --no-dev: bỏ pytest/httpx.
COPY --chown=appuser:appuser apps/backend/pyproject.toml apps/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 2) Source backend + scripts (seed_hr_admin.py chạy tay trong Render Shell — xem runbook).
COPY --chown=appuser:appuser apps/backend/ ./
COPY --chown=appuser:appuser scripts/ /srv/scripts/
RUN uv sync --frozen --no-dev

# KHÔNG đặt EXPOSE: cổng thật do Render cấp qua $PORT lúc chạy (Settings.port đọc env PORT). Ghi một
# con số cố định ở đây chỉ tạo mâu thuẫn với cổng thực sự được bind.

# Migration TRƯỚC rồi mới lên server (khớp plan §3.2). `exec` để uvicorn thành PID 1 và NHẬN SIGTERM
# của Render → lifespan teardown chạy: dừng sweep, đóng checkpointer/Redis/Qdrant/DB sạch sẽ.
# Migration hỏng → container thoát, deploy FAIL rõ ràng, KHÔNG chạy app trên schema sai.
CMD ["sh", "-c", "alembic upgrade head && exec python -m app"]
