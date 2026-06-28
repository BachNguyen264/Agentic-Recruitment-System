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
    # Scaffold: KHÔNG gọi LLM trong pipeline (PRD §17). Slice-01 bật cho RIÊNG parser
    # (chỉ node parser đọc cờ này; các node khác vẫn stub bất kể giá trị).
    enable_llm: bool = False

    # ── LLM provider (slice-01 Parser dùng OpenAI — PRD §7.1) ─────────
    # KHÔNG hardcode key/model. PARSER_MODEL mặc định gpt-4.1-mini (rẻ, đủ tốt cho trích xuất).
    openai_api_key: str | None = None
    parser_model: str = "gpt-4.1-mini"

    # ── Lưu file CV upload (dev: local) ──────────────────────────────
    # TODO (production): chuyển sang object storage (S3/Cloudinary) — xem PRD bàn deploy.
    cv_upload_dir: str = str(_REPO_ROOT / "apps" / "backend" / "data" / "uploads")

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

        ``statement_cache_size=0``: Neon dùng endpoint ``-pooler`` (PgBouncer, chế độ
        transaction). Tắt prepared-statement cache của asyncpg để tránh lỗi
        "prepared statement already exists" khi pool tái dùng kết nối.
        """
        host_is_local = "localhost" in self.database_url or "127.0.0.1" in self.database_url
        if host_is_local:
            return {}
        return {"ssl": True, "statement_cache_size": 0}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
