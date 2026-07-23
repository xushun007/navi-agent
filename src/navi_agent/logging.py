from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re


_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b(?:api[_-]?key|authorization|cookie|password|secret|token)\b"
    r"[\"']?\s*[=:]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]+")
_LOG_CONTEXT: ContextVar[dict[str, str]] = ContextVar("navi_log_context", default={})


def redact_sensitive_data(value: object) -> str:
    text = str(value)
    text = _BEARER_TOKEN_RE.sub("Bearer <redacted>", text)
    return _SENSITIVE_ASSIGNMENT_RE.sub(r"\1<redacted>", text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact_sensitive_data(super().format(record))


class CorrelationContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        context = _LOG_CONTEXT.get()
        fields = []
        if "run_id" in context:
            fields.append(f"run_id={context['run_id']}")
        if "session_id" in context:
            fields.append(f"session_id={context['session_id']}")
        record.correlation = f" [{' '.join(fields)}]" if fields else ""
        return True


@contextmanager
def log_context(**values: str) -> Iterator[None]:
    current = _LOG_CONTEXT.get()
    token = _LOG_CONTEXT.set({**current, **values})
    try:
        yield
    finally:
        _LOG_CONTEXT.reset(token)


def update_log_context(**values: str) -> None:
    _LOG_CONTEXT.set({**_LOG_CONTEXT.get(), **values})


class SecureRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        stream = super()._open()
        os.chmod(self.baseFilename, 0o600)
        return stream


def setup_logging(
    level: str = "INFO",
    log_path: str | Path | None = None,
    *,
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 5,
) -> logging.Logger:
    logger = logging.getLogger("navi_agent")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.propagate = False

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    formatter = RedactingFormatter(
        fmt="%(asctime)s %(levelname)s [%(name)s]%(correlation)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = CorrelationContextFilter()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.addFilter(context_filter)
    logger.addHandler(stream_handler)

    if log_path is not None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        file_handler = SecureRotatingFileHandler(
            path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
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
