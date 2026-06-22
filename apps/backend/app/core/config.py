"""Cấu hình ứng dụng — đọc từ env qua pydantic-settings (KHÔNG hardcode secret).

Secrets nằm ở `.env` tại GỐC REPO (không phải apps/backend). Đường dẫn tính từ vị trí file này
nên hoạt động bất kể CWD (uvicorn/pytest/alembic).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# apps/backend/app/core/config.py -> parents[4] = gốc repo
_REPO_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Ưu tiên .env ở gốc repo; fallback .env trong apps/backend nếu có.
        env_file=(str(_REPO_ROOT / ".env"), str(_REPO_ROOT / "apps" / "backend" / ".env")),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────
    app_env: str = "local"
    log_level: str = "INFO"
    # Scaffold: KHÔNG gọi LLM trong pipeline (PRD §17). Bật ở phase sau.
    enable_llm: bool = False

    # ── Ngưỡng pipeline (PRD §5 trụ cột 3 · §9 gate · §10 screener) ──
    # Đọc từ env; tinh chỉnh thực nghiệm ở Chương 4 (PRD §18).
    confidence_threshold: float = 0.6
    screener_deadline_hours: int = 72
    screener_reminder_hours: int = 24

    # ── Hạ tầng ──────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/recruitment"
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # ── Langfuse (observability — phase sau) ─────────────────────────
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = None

    @property
    def db_connect_args(self) -> dict[str, object]:
        """connect_args cho asyncpg. Neon cần SSL; local (localhost) thì không.

        QUAN TRỌNG (CLAUDE.md): bật SSL bằng ``ssl=True``, KHÔNG dùng ``?sslmode=``
        (asyncpg không hiểu sslmode trong URL).
        """
        host_is_local = "localhost" in self.database_url or "127.0.0.1" in self.database_url
        return {} if host_is_local else {"ssl": True}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
