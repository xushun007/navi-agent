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
    return validate_memory_prompt_content(normalized)


def validate_memory_prompt_content(content: str) -> str:
    normalized = normalize_memory_content(content)
    lowered = normalized.lower()
    for phrase in _BLOCKED_PHRASES:
        if phrase in lowered:
            return "memory content contains prompt-injection text"
    return ""


def sanitize_memory_for_prompt(content: str) -> str:
    validation_error = validate_memory_prompt_content(content)
    if not validation_error:
        return content
    return "[BLOCKED: memory entry contained prompt-injection text. Inspect memory files manually.]"
