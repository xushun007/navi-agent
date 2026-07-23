from __future__ import annotations

import logging
from pathlib import Path
import re


_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|cookie|password|secret|token)\b"
    r"[\"']?\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")


def redact_sensitive_data(value: object) -> str:
    text = str(value)
    text = _BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1<redacted>", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_data(super().format(record))


def setup_logging(level: str = "INFO", log_path: str | Path | None = None) -> logging.Logger:
    logger = logging.getLogger("navi_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = RedactingFormatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def set_console_log_level(level: str) -> None:
    resolved_level = getattr(logging, level.upper(), logging.WARNING)
    logger = logging.getLogger("navi_agent")
    for handler in logger.handlers:
        if isinstance(handler, logging.FileHandler):
            continue
        if isinstance(handler, logging.StreamHandler):
            handler.setLevel(resolved_level)
