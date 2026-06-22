"""Cấu hình logging tối giản (đọc level từ env)."""

from __future__ import annotations

import logging

from app.core.config import settings

_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"


def setup_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=_FORMAT,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
