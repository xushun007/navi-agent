from __future__ import annotations

from dataclasses import dataclass
import random
import socket


RETRYABLE_HTTP_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRYABLE_ERROR_TYPES = frozenset(
    {
        "RateLimitError",
        "APITimeoutError",
        "APIConnectionError",
        "InternalServerError",
    }
)


@dataclass(frozen=True, slots=True)
class ErrorClassification:
    error_category: str
    error_type: str
    error_message: str
    retryable: bool
    http_status: int | None = None
    error_source: str | None = None

    def to_metadata(self) -> dict[str, object]:
        return {
            "error_category": self.error_category,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "retryable": self.retryable,
            "http_status": self.http_status,
            "error_source": self.error_source,
        }


def classify_exception(exc: Exception, *, error_source: str | None = None) -> ErrorClassification:
    http_status = _http_status(exc)
    retryable = _is_retryable(exc, http_status=http_status)
    return ErrorClassification(
        error_category="retryable" if retryable else "fatal",
        error_type=exc.__class__.__name__,
        error_message=str(exc),
        retryable=retryable,
        http_status=http_status,
        error_source=error_source,
    )


def is_retryable_exception(exc: Exception) -> bool:
    return classify_exception(exc).retryable


def retry_delay(
    *,
    attempt: int,
    base_seconds: float = 0.5,
    max_seconds: float = 8.0,
    jitter_ratio: float = 0.1,
) -> float:
    delay = min(max_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    return delay + delay * jitter_ratio * random.random()


def _http_status(exc: Exception) -> int | None:
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_retryable(exc: Exception, *, http_status: int | None) -> bool:
    if http_status in RETRYABLE_HTTP_STATUSES:
        return True
    if exc.__class__.__name__ in RETRYABLE_ERROR_TYPES:
        return True
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, OSError)):
        return True

    message = str(exc).lower()
    if "timed out" in message or "timeout" in message:
        return True
    if "connection" in message and any(
        token in message for token in ("reset", "refused", "aborted")
    ):
        return True
    if "http " in message:
        return any(f"http {status}" in message for status in RETRYABLE_HTTP_STATUSES)
    return False
