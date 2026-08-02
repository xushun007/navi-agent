from __future__ import annotations

MAX_MEMORY_CONTENT_CHARS = 2_000

_DURABLE_TARGETS = {"memory", "user"}
_TRANSIENT_TARGETS = {"runtime", "session", "temp", "temporary"}

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


def normalize_memory_target(target: str, *, kind: str = "fact") -> str:
    normalized = target.strip().lower()
    if normalized in _TRANSIENT_TARGETS:
        raise ValueError(f"{normalized} state cannot be promoted to durable memory")
    if normalized in _DURABLE_TARGETS:
        return normalized
    if kind.strip().lower() == "preference":
        return "user"
    return "memory"


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
