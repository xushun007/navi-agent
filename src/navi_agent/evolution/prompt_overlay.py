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

    def list_candidate_ids(self) -> list[str]:
        blocks = self._blocks()
        ids: list[str] = []
        for block in blocks:
            for line in block.splitlines():
                if line.startswith("## Candidate "):
                    ids.append(line.removeprefix("## Candidate ").strip())
                    break
        return ids

    def candidate_count(self) -> int:
        return len(self.list_candidate_ids())

    def describe(self) -> dict[str, object]:
        return {
            "path": str(self._path),
            "exists": self._path.exists(),
            "candidate_count": self.candidate_count(),
            "candidate_ids": self.list_candidate_ids(),
        }

    def _blocks(self) -> list[str]:
        text = self.get()
        if not text:
            return []
        return [block.strip() for block in text.split("\n\n") if block.strip()]

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
