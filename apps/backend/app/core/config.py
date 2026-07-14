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
    # Bật endpoint DEV (vd resume-screener thủ công của 08a). Mặc định TẮT — đường thật của
    # Screener là magic-link form (08b). Chỉ bật khi cần test nội bộ (KHÔNG bật ở production).
    enable_dev_endpoints: bool = False

    # ── LLM provider (slice-01 Parser dùng OpenAI — PRD §7.1) ─────────
    # KHÔNG hardcode key/model. PARSER_MODEL mặc định gpt-4.1-mini (rẻ, đủ tốt cho trích xuất).
    openai_api_key: str | None = None
    parser_model: str = "gpt-4.1-mini"

    # ── Embedding (slice-02a JD → Qdrant — PRD §7.2, §16) ─────────────
    # EMBEDDING_DIM phải khớp model (text-embedding-3-small = 1536); đổi model thì đổi cả dim
    # và tạo collection mới (kích thước vector là bất biến của collection).
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536

    # ── Ranker (slice-02b — PRD §7.2 chấm rubric có suy luận) ─────────
    # ĐÃ CHỌN qua benchmark (slice 01c): gpt-5-mini + reasoning_effort=low — chấm bám BẰNG CHỨNG,
    # nhất quán trên dữ liệu sạch (vd điểm Tiếng Anh khớp TOEIC thay vì suy diễn). RANKER_REASONING_EFFORT
    # rỗng → non-reasoning (temperature=0); có giá trị (low/medium/high) → reasoning (KHÔNG truyền temperature).
    ranker_model: str = "gpt-5-mini"
    ranker_reasoning_effort: str | None = "low"
    # Ngưỡng điểm đạt (0..100) + dải "sát ngưỡng" cho cờ near_threshold. PRD §8.3, §18.
    score_pass_threshold: float = 60.0
    score_near_band: float = 10.0

    # ── Lưu file CV upload (dev: local) ──────────────────────────────
    # TODO (production): chuyển sang object storage (S3/Cloudinary) — xem PRD bàn deploy.
    cv_upload_dir: str = str(_REPO_ROOT / "apps" / "backend" / "data" / "uploads")

    # ── Ngưỡng pipeline (PRD §5 trụ cột 3 · §9 gate · §10 screener) ──
    # Đọc từ env; tinh chỉnh thực nghiệm ở Chương 4 (PRD §18).
    confidence_threshold: float = 0.6
    screener_deadline_hours: int = 72
    screener_reminder_hours: int = 24

    # ── Screener magic-link (08b — PRD §7.3, §10, §12.2) ─────────────
    # Gốc URL frontend công khai để dựng magic-link trong email Screener:
    # {frontend_base_url}/screening/{token}. Dev: dashboard Next chạy :3000. Đổi khi deploy.
    frontend_base_url: str = "http://localhost:3000"

    # ── Hạ tầng ──────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/recruitment"
    # Kết nối RIÊNG cho LangGraph checkpointer (psycopg, PRD §10 Screener suspend/resume). Để rỗng →
    # suy ra từ database_url: dùng endpoint Neon TRỰC TIẾP (bỏ -pooler) tránh PgBouncer phá prepared
    # statements của psycopg. Đặt tay khi cần (vd URL không-pooled khác). Xem checkpointer_conninfo.
    checkpointer_database_url: str | None = None
    checkpointer_pool_max_size: int = 5
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None
    # Một collection dùng chung JD + CV (phân biệt bằng payload "type") — plan 02a.
    qdrant_collection: str = "cv_jd_embeddings"

    # ── Email (slice-04 Scheduler gửi thư mời/từ chối qua Resend — PRD §7.4, §12.4) ──
    # KHÔNG hardcode key. EMAIL_FROM mặc định địa chỉ test của Resend (onboarding@resend.dev) —
    # với sender này + domain CHƯA xác thực, Resend chỉ gửi tới email tài khoản Resend của bạn.
    # Đổi sang địa chỉ thuộc domain đã xác thực khi demo public.
    resend_api_key: str | None = None
    email_from: str = "onboarding@resend.dev"

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

    @property
    def checkpointer_conninfo(self) -> str:
        """libpq conninfo (URL) cho psycopg của LangGraph checkpointer (PRD §10).

        Nếu ``checkpointer_database_url`` được đặt thì dùng nguyên. Nếu KHÔNG, suy ra từ
        ``database_url`` (URL asyncpg của app):
          - scheme ``postgresql+asyncpg`` → ``postgresql`` (psycopg hiểu libpq URL).
          - Neon: dùng endpoint TRỰC TIẾP (bỏ ``-pooler``) — PgBouncer chế độ transaction làm hỏng
            prepared statements của psycopg (checkpointer prepare các câu lệnh của nó).
          - non-local: thêm ``sslmode=require`` (Neon bắt buộc SSL).
        """
        if self.checkpointer_database_url:
            return self.checkpointer_database_url

        from urllib.parse import urlsplit, urlunsplit

        parts = urlsplit(self.database_url)
        host = parts.hostname or ""
        is_local = "localhost" in host or "127.0.0.1" in host
        new_host = host if is_local else host.replace("-pooler", "")
        userinfo = ""
        if parts.username:
            userinfo = parts.username
            if parts.password:
                userinfo += f":{parts.password}"
            userinfo += "@"
        port = f":{parts.port}" if parts.port else ""
        netloc = f"{userinfo}{new_host}{port}"
        query = parts.query
        if not is_local and "sslmode" not in query:
            query = f"{query}&sslmode=require" if query else "sslmode=require"
        return urlunsplit(("postgresql", netloc, parts.path, query, ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
