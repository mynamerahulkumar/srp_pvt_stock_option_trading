from __future__ import annotations

import logging
import sys
from typing import Optional

LOGGER_NAME = "quant_terminal"

_SECRET_KEYS = (
    "access_token",
    "token_id",
    "client_secret",
    "api_key",
    "api_secret",
    "DHAN_ACCESS_TOKEN",
    "DHAN_CLIENT_ID",
)


class _SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = str(record.getMessage())
        lowered = message.lower()
        for key in _SECRET_KEYS:
            if key.lower() in lowered:
                record.msg = "[REDACTED] log line contained a credential key"
                record.args = ()
                break
        return True


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        handler.addFilter(_SecretFilter())
        logger.addHandler(handler)
    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    if name:
        return logging.getLogger(f"{LOGGER_NAME}.{name}")
    return logging.getLogger(LOGGER_NAME)
