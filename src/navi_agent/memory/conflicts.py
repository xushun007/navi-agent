from __future__ import annotations

import re

from .models import MemoryConflictCandidate, MemoryRecord

_NEGATIONS = {
    "cannot",
    "doesn't",
    "doesnt",
    "never",
    "no",
    "not",
    "without",
    "不",
    "不是",
    "不能",
    "没有",
}


class MemoryConflictError(ValueError):
    def __init__(self, candidates: list[MemoryConflictCandidate]) -> None:
        super().__init__("likely memory conflict requires an explicit resolution")
        self.candidates = candidates


def find_memory_conflicts(
    records: list[MemoryRecord],
    *,
    content: str,
    kind: str,
    target: str,
    exclude_record_id: str = "",
) -> list[MemoryConflictCandidate]:
    proposed_tokens = _tokens(content)
    proposed_negated = _has_negation(content)
    proposed_subject = _subject_key(content, kind=kind)
    candidates = []
    for record in records:
        if record.id == exclude_record_id or record.target != target:
            continue
        existing_tokens = _tokens(record.content)
        if not proposed_tokens or not existing_tokens:
            continue
        shared = proposed_tokens & existing_tokens
        similarity = len(shared) / max(1, min(len(proposed_tokens), len(existing_tokens)))
        threshold = 0.5 if kind == "preference" or record.kind == "preference" else 0.6
        negation_changed = proposed_negated != _has_negation(record.content)
        same_subject = proposed_subject == _subject_key(record.content, kind=record.kind)
        if (
            not same_subject
            or (similarity < threshold and not (negation_changed and shared))
        ):
            continue
        reasons = ["same_topic"]
        if negation_changed or proposed_tokens != existing_tokens:
            reasons.append("possible_contradiction")
        candidates.append(
            MemoryConflictCandidate(
                record_id=record.id,
                content=record.content,
                kind=record.kind,
                target=record.target,
                score=round(similarity, 3),
                reasons=tuple(reasons),
            )
        )
    return sorted(candidates, key=lambda item: item.score, reverse=True)


def require_explicit_conflict_resolution(
    candidates: list[MemoryConflictCandidate],
    *,
    resolution: str,
    evidence: str,
) -> bool:
    if not candidates:
        return False
    if resolution != "retain_both":
        raise MemoryConflictError(candidates)
    if not evidence.strip():
        raise ValueError("evidence is required to retain conflicting memories")
    return True


def _tokens(value: str) -> set[str]:
    normalized = value.casefold()
    tokens = set(re.findall(r"[a-z0-9_][a-z0-9_-]*", normalized))
    tokens.difference_update(_NEGATIONS)
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        tokens.update(
            run[index : index + 2]
            for index in range(max(1, len(run) - 1))
        )
    return tokens


def _has_negation(value: str) -> bool:
    normalized = value.casefold()
    return any(
        re.search(rf"\b{re.escape(token)}\b", normalized)
        if token.isascii()
        else token in normalized
        for token in _NEGATIONS
    )


def _subject_key(value: str, *, kind: str) -> tuple[str, ...]:
    normalized = value.casefold()
    for negation in sorted(_NEGATIONS, key=len, reverse=True):
        if not negation.isascii():
            normalized = normalized.replace(negation, "")
    cjk = re.search(r"[\u3400-\u9fff]+", normalized)
    if cjk:
        return (cjk.group(0)[:4],)
    tokens = re.findall(r"[a-z0-9_][a-z0-9_-]*", normalized)
    width = 1 if kind == "preference" else 2
    return tuple(tokens[:width])
