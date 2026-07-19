from __future__ import annotations

MAX_MEMORY_CONTENT_CHARS = 2_000

_BLOCKED_PHRASES = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard your instructions",
    "forget your instructions",
    "you are now",
    "system prompt:",
    "<system>",
    "</system>",
)


def normalize_memory_content(content: str) -> str:
    return " ".join(content.strip().split())


def validate_memory_content(content: str) -> str:
    normalized = normalize_memory_content(content)
    if not normalized:
        return "memory content is required"
    if len(normalized) > MAX_MEMORY_CONTENT_CHARS:
        return "memory content is too large"
    lowered = normalized.lower()
    for phrase in _BLOCKED_PHRASES:
        if phrase in lowered:
            return "memory content contains prompt-injection text"
    return ""
