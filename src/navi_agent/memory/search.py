from __future__ import annotations

import re

from .models import MemoryRecall, MemoryRecord


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
    recall = recall_memories(
        records,
        query=query,
        profile_limit=limit,
        relevant_limit=limit,
    )
    return [*recall.profile, *recall.relevant][:limit]


def recall_memories(
    records: list[MemoryRecord],
    *,
    query: str,
    profile_limit: int,
    relevant_limit: int,
) -> MemoryRecall:
    query_tokens = _tokens(query)
    normalized_query = " ".join(query.casefold().split())
    profile_ranked: list[tuple[int, int, MemoryRecord]] = []
    relevant_ranked: list[tuple[int, int, MemoryRecord]] = []
    for index, record in enumerate(records):
        is_profile = record.target == "user" or record.kind == "preference"
        normalized_content = " ".join(record.content.casefold().split())
        overlap = query_tokens & _tokens(normalized_content)
        exact_match = bool(normalized_query) and normalized_query == normalized_content
        phrase_match = bool(normalized_query) and normalized_query in normalized_content
        if not is_profile and not overlap and not phrase_match:
            continue
        score = (10_000 if exact_match else 0) + (2_000 if phrase_match else 0)
        score += sum(max(1, len(token)) * 10 for token in overlap)
        score += index
        ranked = profile_ranked if is_profile else relevant_ranked
        ranked.append((score, index, record))
    profile_ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    relevant_ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return MemoryRecall(
        profile=[
            record
            for _, _, record in profile_ranked[: max(0, profile_limit)]
        ],
        relevant=[
            record
            for _, _, record in relevant_ranked[: max(0, relevant_limit)]
        ],
    )


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
