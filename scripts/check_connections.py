"""Phase 1 — Kiểm tra kết nối 3 dịch vụ managed (Neon · Upstash · Qdrant).

Script ĐỘC LẬP (chưa cần backend). Đọc secret từ `.env` ở gốc repo, KHÔNG in secret.

Chạy:
    make check-env
hoặc trực tiếp:
    uv run --no-project --with asyncpg --with "redis>=5" --with qdrant-client \
        --with python-dotenv scripts/check_connections.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

OK, BAD = "OK ", "FAIL"


def load_env() -> None:
    """Nạp .env vào os.environ (ưu tiên python-dotenv, fallback parse tay)."""
    try:
        from dotenv import load_dotenv

        load_dotenv(ENV_PATH)
        return
    except Exception:
        pass
    if ENV_PATH.exists():
        for raw in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


async def check_postgres() -> tuple[bool, str]:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        return False, "DATABASE_URL trống"
    try:
        import asyncpg
    except ImportError:
        return False, "thiếu asyncpg"
    # asyncpg cần postgres:// thuần + KHÔNG query sslmode; SSL bật bằng ssl=True.
    parts = urlsplit(url.replace("postgresql+asyncpg://", "postgresql://"))
    dsn = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
    try:
        conn = await asyncpg.connect(dsn=dsn, ssl=True, timeout=20)
        ver = await conn.fetchval("SELECT version();")
        await conn.close()
        return True, str(ver).split(" on ")[0]
    except Exception as exc:  # noqa: BLE001 — báo cáo mọi lỗi kết nối
        return False, f"{type(exc).__name__}: {exc}"


async def check_redis() -> tuple[bool, str]:
    url = os.environ.get("REDIS_URL", "")
    if not url:
        return False, "REDIS_URL trống"
    try:
        import redis.asyncio as redis
    except ImportError:
        return False, "thiếu redis"
    try:
        client = redis.from_url(url, socket_timeout=20, socket_connect_timeout=20)
        pong = await client.ping()
        await client.aclose()
        return bool(pong), "PONG" if pong else "không PONG"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def check_qdrant() -> tuple[bool, str]:
    url = os.environ.get("QDRANT_URL", "")
    key = os.environ.get("QDRANT_API_KEY", "")
    if not url:
        return False, "QDRANT_URL trống"
    try:
        from qdrant_client import QdrantClient
    except ImportError:
        return False, "thiếu qdrant-client"
    try:
        client = QdrantClient(url=url, api_key=key or None, timeout=20)
        cols = client.get_collections()
        return True, f"{len(cols.collections)} collection(s)"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


async def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # tránh lỗi encode trên Windows console
    except Exception:
        pass

    load_env()
    print(f"-> Đọc env: {ENV_PATH}")

    results = [
        ("Neon Postgres", *(await check_postgres())),
        ("Upstash Redis", *(await check_redis())),
        ("Qdrant Cloud", *check_qdrant()),
    ]

    print()
    for name, ok, msg in results:
        print(f"  [{OK if ok else BAD}] {name:<16} {msg}")

    all_ok = all(ok for _, ok, _ in results)
    print()
    print("KẾT QUẢ: TẤT CẢ KẾT NỐI OK" if all_ok else "KẾT QUẢ: CÓ LỖI (xem ở trên)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
