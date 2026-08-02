from __future__ import annotations

from datetime import UTC, datetime

from .models import MemoryRecord


def normalize_expiry(expires_at: str) -> str:
    value = expires_at.strip()
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("expires_at must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("expires_at must include a timezone")
    return parsed.astimezone(UTC).isoformat()


def is_memory_expired(record: MemoryRecord, *, now: datetime | None = None) -> bool:
    if not record.expires_at:
        return False
    try:
        expires_at = datetime.fromisoformat(record.expires_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires_at.tzinfo is None:
        return False
    return expires_at <= (now or datetime.now(UTC))
