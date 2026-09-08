# Makefile — giao diện lệnh chuẩn cho monorepo (chạy qua GNU make).
# Trên Windows: dùng Git Bash (đã có make) hoặc xem README cho lệnh pnpm/uv tương đương.
.DEFAULT_GOAL := help
.PHONY: help install dev-backend dev-dashboard migrate makemigration health test check-env local-infra-up local-infra-down

# Danh sách target ĐỌC TỪ chính các chú thích `##` bên dưới. Trước đây thân `help` chép tay lại 11
# mô tả đó: hai danh sách phải sửa song song và đã lệch ngay ở `dev-backend` (chú thích nói
# `python -m app`, dòng echo vẫn nói `uvicorn --reload`). Một nguồn duy nhất thì không lệch được nữa.
help: ## Liệt kê các target
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s - %s\n", $$1, $$2}'

install: ## Cài đặt phụ thuộc
	cd apps/backend && uv sync
	pnpm install

dev-backend: ## FastAPI dev server (qua `python -m app`: set SelectorEventLoop cho psycopg async trên Windows)
	cd apps/backend && uv run python -m app

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

check-env: ## Kiểm tra kết nối 2 dịch vụ managed (script độc lập, không cần backend)
	uv run --no-project --with asyncpg --with qdrant-client --with python-dotenv scripts/check_connections.py

local-infra-up: ## Dựng hạ tầng local (dự phòng khi chưa có managed)
	docker compose -f docker-compose.local.yml up -d

local-infra-down: ## Tắt hạ tầng local
	docker compose -f docker-compose.local.yml down
