from __future__ import annotations

import re

from .models import MemoryRecord


_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "do",
    "for",
    "how",
    "i",
    "in",
    "is",
    "of",
    "on",
    "the",
    "to",
    "what",
    "which",
}


def search_memories(
    records: list[MemoryRecord],
    *,
    query: str,
    limit: int,
) -> list[MemoryRecord]:
    query_tokens = _tokens(query)
    ranked: list[tuple[int, int, MemoryRecord]] = []
    for index, record in enumerate(records):
        is_profile = record.target == "user" or record.kind == "preference"
        overlap = query_tokens & _tokens(record.content)
        exact_match = bool(query.strip()) and query.strip().casefold() in record.content.casefold()
        if not is_profile and not overlap and not exact_match:
            continue
        score = (10_000 if is_profile else 0) + (1_000 if exact_match else 0)
        score += sum(max(1, len(token)) for token in overlap)
        ranked.append((score, index, record))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [record for _, _, record in ranked[:limit]]


def _tokens(value: str) -> set[str]:
    normalized = value.casefold()
    tokens = {
        token
        for token in re.findall(r"[a-z0-9_][a-z0-9_-]*", normalized)
        if token not in _STOP_WORDS
    }
    cjk_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    for run in cjk_runs:
        if len(run) == 1:
            tokens.add(run)
        else:
            tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens
