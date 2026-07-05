# Makefile — giao diện lệnh chuẩn cho monorepo (chạy qua GNU make).
# Trên Windows: dùng Git Bash (đã có make) hoặc xem README cho lệnh pnpm/uv tương đương.
.DEFAULT_GOAL := help
.PHONY: help install dev-backend dev-dashboard migrate makemigration health test check-env local-infra-up local-infra-down

help: ## Liệt kê các target
	@echo "Targets:"
	@echo "  install          - cài deps backend (uv) + workspace (pnpm)"
	@echo "  dev-backend      - chạy FastAPI (uvicorn --reload :8000)"
	@echo "  dev-dashboard    - chạy Next.js dashboard (:3000)"
	@echo "  migrate          - alembic upgrade head"
	@echo "  makemigration    - alembic revision --autogenerate"
	@echo "  health           - curl /api/health"
	@echo "  test             - pytest (backend)"
	@echo "  check-env        - kiểm tra kết nối Neon/Upstash/Qdrant"
	@echo "  local-infra-up   - docker compose (Postgres/Redis/Qdrant) — dự phòng"
	@echo "  local-infra-down - tắt docker compose dự phòng"

install: ## Cài đặt phụ thuộc
	cd apps/backend && uv sync
	pnpm install

dev-backend: ## FastAPI dev server
	cd apps/backend && uv run uvicorn app.main:app --reload --port 8000

dev-dashboard: ## Next.js dashboard
	pnpm --filter dashboard dev

migrate: ## Áp dụng migration mới nhất
	cd apps/backend && uv run alembic upgrade head

makemigration: ## Tạo migration tự động (m="message")
	cd apps/backend && uv run alembic revision --autogenerate -m "$(m)"

health: ## Gọi health endpoint
	curl -s http://localhost:8000/api/health

test: ## Chạy test backend
	cd apps/backend && uv run pytest -q

check-env: ## Kiểm tra kết nối 3 dịch vụ managed (script độc lập, không cần backend)
	uv run --no-project --with asyncpg --with "redis>=5" --with qdrant-client --with python-dotenv scripts/check_connections.py

local-infra-up: ## Dựng hạ tầng local (dự phòng khi chưa có managed)
	docker compose -f docker-compose.local.yml up -d

local-infra-down: ## Tắt hạ tầng local
	docker compose -f docker-compose.local.yml down
