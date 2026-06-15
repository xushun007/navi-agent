from __future__ import annotations

from pathlib import Path

from .models import EvolutionCandidate


class PromptOverlayStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def get(self) -> str | None:
        if not self._path.exists():
            return None
        text = self._path.read_text(encoding="utf-8").strip()
        return text or None

    def append_candidate(self, candidate: EvolutionCandidate) -> str:
        block = self._format_candidate_block(candidate)
        current = self.get()
        next_text = f"{current}\n\n{block}".strip() if current else block
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(next_text + "\n", encoding="utf-8")
        return next_text

    @staticmethod
    def _format_candidate_block(candidate: EvolutionCandidate) -> str:
        return "\n".join(
            [
                f"## Candidate {candidate.candidate_id}",
                f"- status: {candidate.status}",
                f"- target: {candidate.target}",
                f"- summary: {candidate.summary}",
                f"- rationale: {candidate.rationale}",
                f"- note: apply as a small, focused prompt improvement.",
            ]
        )
