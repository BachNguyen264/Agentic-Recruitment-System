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
    # Bind của uvicorn (slice 13 deploy). Dev: loopback + hot-reload. Render: HOST=0.0.0.0 (nhận
    # request từ ngoài container) + PORT do NỀN TẢNG cấp qua env — KHÔNG hardcode. Xem app/__main__.py.
    host: str = "127.0.0.1"
    port: int = 8000
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

    # ── Lưu file CV (slice 06 — PRD §16 cv_file_ref, NFR-4) ──────────
    # Nghiệp vụ KHÔNG đọc/ghi path trực tiếp — đi qua seam `services/storage` (FileStorage).
    #   local = đĩa dev (thư mục cv_upload_dir) · r2 = Cloudflare R2 (S3 API, bucket PRIVATE).
    storage_backend: str = "local"
    cv_upload_dir: str = str(_REPO_ROOT / "apps" / "backend" / "data" / "uploads")

    # Cloudflare R2 (S3-compatible). Credentials CHỈ từ env — bucket PRIVATE (CV = dữ liệu cá nhân,
    # NFR-4: KHÔNG public URL; HR tải qua endpoint stream có require_hr).
    r2_account_id: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_bucket: str | None = None
    # Để rỗng → suy ra https://{r2_account_id}.r2.cloudflarestorage.com (xem r2_endpoint_url).
    r2_endpoint: str | None = None

    @property
    def r2_endpoint_url(self) -> str | None:
        """Endpoint S3 của R2: dùng R2_ENDPOINT nếu có, else suy từ account id."""
        if self.r2_endpoint:
            return self.r2_endpoint
        if self.r2_account_id:
            return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"
        return None

    # ── Ngưỡng pipeline (PRD §5 trụ cột 3 · §9 gate · §10 screener) ──
    # Đọc từ env; tinh chỉnh thực nghiệm ở Chương 4 (PRD §18).
    confidence_threshold: float = 0.6
    # float (không int) để VERIFY 08c đặt ngưỡng NHỎ dưới 1 giờ (vd deadline 0.033h≈2 phút,
    # reminder 0.017h≈1 phút) mà không cần đơn vị giây riêng. Prod vẫn dùng số giờ (72/24).
    screener_deadline_hours: float = 72
    screener_reminder_hours: float = 24
    # Chu kỳ quét deadline (08c, in-process sweep — PRD §10 FR-SCR-3/4). Giây để verify đặt nhỏ
    # (vd 20). Sweep chạy như asyncio task ở lifespan (KHÔNG Redis polling — CLAUDE.md).
    screener_sweep_interval_seconds: int = 600

    # ── Screener magic-link (08b — PRD §7.3, §10, §12.2) ─────────────
    # Gốc URL frontend công khai để dựng magic-link trong email Screener:
    # {frontend_base_url}/screening/{token}. Dev: dashboard Next chạy :3000. Đổi khi deploy.
    frontend_base_url: str = "http://localhost:3000"

    # ── Auth HR (slice 09 — PRD §4: CHỈ HR Admin đăng nhập; ứng viên là guest) ──
    # JWT_SECRET: BẮT BUỘC khi chạy auth, tối thiểu 32 ký tự (xem security._jwt_secret).
    # KHÔNG hardcode/mặc định — thiếu secret phải nổ ngay, không im lặng dùng khóa yếu.
    jwt_secret: str | None = None
    jwt_expiry_minutes: int = 480  # 8 giờ — một ca làm việc của HR.
    # Cookie chứa JWT. Đọc từ ENV để deploy cross-domain (Vercel + Render) KHÔNG phải sửa code:
    #   - dev (localhost:3000 → :8000, same-site vì cổng không tính): secure=False, samesite=lax.
    #   - prod (dashboard.vercel.app → api.onrender.com, CROSS-SITE): secure=True, samesite=none.
    # SameSite=None BẮT BUỘC đi kèm Secure (browser bỏ cookie nếu thiếu) — xem auth.py kiểm chứng.
    auth_cookie_name: str = "ars_session"
    cookie_secure: bool = False
    cookie_samesite: str = "lax"  # lax | none | strict
    cookie_domain: str | None = None  # None = host-only (đúng cho cả dev lẫn cross-domain).

    # Seed tài khoản HR admin (scripts/seed_hr_admin.py). KHÔNG commit mật khẩu thật — chỉ .env.
    hr_admin_email: str | None = None
    hr_admin_password: str | None = None

    # ── CORS (slice 13 deploy — cross-domain Vercel + Render) ────────
    # Danh sách origin frontend được phép, phân tách bằng dấu phẩy (vd "https://ars.vercel.app").
    # RỖNG = dev: main.py fallback regex localhost (hành vi cũ). Xem cors_allow_origins.
    cors_origins: str = ""

    # ── Hardening endpoint công khai (slice 13 — xem core/hardening.py) ──
    # Body tối đa: CV giới hạn 10MB (cv_storage.MAX_BYTES) + phần bao multipart → 12MB là vừa đủ.
    max_request_bytes: int = 12 * 1024 * 1024
    rate_limit_enabled: bool = True
    # Login: chống dò mật khẩu HR. Public: chống spam nộp CV + dò token magic-link screener.
    rate_limit_login_max: int = 10
    rate_limit_login_window_seconds: float = 900  # 15 phút
    rate_limit_public_max: int = 20
    rate_limit_public_window_seconds: float = 3600  # 1 giờ
    # Sau proxy (Render) IP thật nằm ở X-Forwarded-For, không phải peer TCP. Để None = TỰ SUY:
    # bật khi app_env != "local". Lý do KHÔNG để mặc định false: quên đặt biến này khi deploy thì
    # MỌI khách chung một khoá quota (peer TCP = router của Render) ⇒ chỉ ~10 request nặc danh là
    # khoá sạch đường đăng nhập của HR, lặp lại được vô hạn. Hỏng-mở (rate-limit yếu đi ở môi trường
    # không có proxy) ít tệ hơn hỏng-đóng (tự chặn chính mình) — và trên Render thì LUÔN có proxy.
    trust_proxy_headers: bool | None = None
    # SỐ proxy tin cậy đứng trước app; khoá quota lấy phần tử thứ N TỪ PHẢI của X-Forwarded-For.
    # 1 = chỉ Render. Render đặt Cloudflare trước *.onrender.com nên có thể cần 2 — xác nhận bằng
    # dòng log "Rate-limit: khóa quota = ..." (in một lần) rồi chỉnh, ĐỪNG đoán.
    proxy_trusted_hops: int = 1

    @property
    def trust_proxy(self) -> bool:
        """trust_proxy_headers nếu được đặt tường minh; nếu không thì suy từ app_env."""
        if self.trust_proxy_headers is None:
            return self.app_env != "local"
        return self.trust_proxy_headers

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
    def cors_allow_origins(self) -> list[str]:
        """`CORS_ORIGINS` (CSV) → list origin cho CORSMiddleware. Rỗng = không cấu hình (dev).

        Starlette so khớp origin bằng SO SÁNH CHUỖI CHÍNH XÁC. Nên mọi giá trị "gần đúng" đều lặng lẽ
        không khớp, và triệu chứng luôn giống nhau: HR đăng nhập trả 200 nhưng KHÔNG giữ được phiên
        (rủi ro #1 khi deploy cross-domain), rất khó truy. Vì thế chặn NGAY lúc khởi động:

        - Chứa `*` (kể cả `https://*.vercel.app`): wildcard bị trình duyệt CẤM khi allow_credentials,
          và Starlette KHÔNG hiểu `*` nằm giữa chuỗi — nó chỉ là ký tự thường, không bao giờ khớp.
        - Thiếu scheme (`ars.vercel.app` — đúng thứ dashboard Vercel hiển thị): Origin header trình
          duyệt gửi LUÔN có scheme, nên giá trị trần không bao giờ khớp.
        - Có path (`https://x.app/duong-dan`): Origin không bao giờ chứa path.
        Chuẩn hoá: bỏ `/` cuối và hạ chữ thường (Origin do browser gửi luôn là chữ thường).
        """
        items = [o.strip().rstrip("/").lower() for o in self.cors_origins.split(",")]
        items = [o for o in items if o]
        for origin in items:
            if "*" in origin:
                raise ValueError(
                    f"CORS_ORIGINS chứa '*' ({origin!r}): không dùng được wildcard cùng cookie "
                    "(allow_credentials=True), và Starlette so khớp origin bằng chuỗi chính xác nên "
                    "'*' sẽ KHÔNG BAO GIỜ khớp. Hãy liệt kê từng origin đầy đủ."
                )
            if not origin.startswith(("http://", "https://")):
                raise ValueError(
                    f"CORS_ORIGINS thiếu scheme ({origin!r}): phải ghi đủ 'https://...' — Origin mà "
                    "trình duyệt gửi luôn kèm scheme nên giá trị trần sẽ không khớp."
                )
            if "/" in origin.split("://", 1)[1]:
                raise ValueError(
                    f"CORS_ORIGINS không được chứa đường dẫn ({origin!r}): origin chỉ gồm "
                    "scheme + host [+ cổng]."
                )
        return items

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
