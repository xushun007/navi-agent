from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
from typing import Any, Iterable

from .models import Message


def context_projection_hash(messages: Iterable[Message]) -> str:
    return _canonical_hash([asdict(message) for message in messages])


def tool_schema_projection_hash(tools: Iterable[dict[str, Any]]) -> str:
    return _canonical_hash(list(tools))


def capability_names(tools: Iterable[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(
        sorted(
            name
            for tool in tools
            if isinstance((name := tool.get("name")), str) and name
        )
    )


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
