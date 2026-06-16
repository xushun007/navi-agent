from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import EvolutionCandidate


@dataclass(frozen=True, slots=True)
class PromptOverlaySnapshot:
    snapshot_id: str
    path: Path
    candidate_id: str | None = None


class PromptOverlayStore:
    def __init__(self, path: Path, snapshots_dir: Path | None = None) -> None:
        self._path = path
        self._snapshots_dir = snapshots_dir or path.parent / "prompt-overlay-snapshots"

    def get(self) -> str | None:
        if not self._path.exists():
            return None
        text = self._path.read_text(encoding="utf-8").strip()
        return text or None

    def append_candidate(self, candidate: EvolutionCandidate) -> str:
        self.snapshot(candidate_id=candidate.candidate_id)
        block = self._format_candidate_block(candidate)
        current = self.get()
        next_text = f"{current}\n\n{block}".strip() if current else block
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(next_text + "\n", encoding="utf-8")
        return next_text

    def snapshot(self, *, candidate_id: str | None = None) -> PromptOverlaySnapshot | None:
        current = self.get()
        if not current:
            return None
        snapshot_id = self._new_snapshot_id(candidate_id=candidate_id)
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)
        path = self._snapshots_dir / f"{snapshot_id}.md"
        path.write_text(current + "\n", encoding="utf-8")
        return PromptOverlaySnapshot(snapshot_id=snapshot_id, path=path, candidate_id=candidate_id)

    def list_snapshots(self) -> list[PromptOverlaySnapshot]:
        if not self._snapshots_dir.exists():
            return []
        snapshots: list[PromptOverlaySnapshot] = []
        for path in sorted(self._snapshots_dir.glob("*.md"), reverse=True):
            snapshots.append(
                PromptOverlaySnapshot(
                    snapshot_id=path.stem,
                    path=path,
                    candidate_id=self._extract_candidate_id(path),
                )
            )
        return snapshots

    def rollback(self, snapshot_id: str) -> str | None:
        snapshot_path = self._snapshots_dir / f"{snapshot_id}.md"
        if not snapshot_path.exists():
            return None
        text = snapshot_path.read_text(encoding="utf-8").strip()
        if not text:
            return None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(text + "\n", encoding="utf-8")
        return text

    def list_candidate_ids(self) -> list[str]:
        blocks = self._blocks()
        ids: list[str] = []
        for block in blocks:
            for line in block.splitlines():
                if line.startswith("## Candidate "):
                    ids.append(line.removeprefix("## Candidate ").strip())
                    break
        return ids

    def list_workflow_names(self) -> list[str]:
        return self._list_block_values("workflow")

    def list_source_session_ids(self) -> list[str]:
        return self._list_block_values("source session")

    def list_replay_session_ids(self) -> list[str]:
        return self._list_block_values("replay session")

    def candidate_count(self) -> int:
        return len(self.list_candidate_ids())

    def describe(self) -> dict[str, object]:
        return {
            "path": str(self._path),
            "exists": self._path.exists(),
            "candidate_count": self.candidate_count(),
            "candidate_ids": self.list_candidate_ids(),
            "workflow_names": self.list_workflow_names(),
            "source_session_ids": self.list_source_session_ids(),
            "replay_session_ids": self.list_replay_session_ids(),
            "snapshot_count": len(self.list_snapshots()),
        }

    def _blocks(self) -> list[str]:
        text = self.get()
        if not text:
            return []
        return [block.strip() for block in text.split("\n\n") if block.strip()]

    @staticmethod
    def _extract_candidate_id(path: Path) -> str | None:
        stem = path.stem
        if "--" not in stem:
            return None
        return stem.rsplit("--", 1)[-1] or None

    @staticmethod
    def _normalize_snapshot_id(snapshot_id: str) -> str:
        return snapshot_id.replace(":", "-")

    @staticmethod
    def _new_snapshot_id(candidate_id: str | None = None) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        if candidate_id:
            return f"{timestamp}--{PromptOverlayStore._normalize_snapshot_id(candidate_id)}"
        return timestamp

    @staticmethod
    def _format_candidate_block(candidate: EvolutionCandidate) -> str:
        lines = [
            f"## Candidate {candidate.candidate_id}",
            f"- status: {candidate.status}",
            f"- target: {candidate.target}",
            f"- summary: {candidate.summary}",
            f"- rationale: {candidate.rationale}",
        ]
        metadata = candidate.metadata or {}
        workflow_name = metadata.get("workflow_name")
        if workflow_name:
            lines.append(f"- workflow: {workflow_name}")
        source_session_id = metadata.get("source_session_id")
        if source_session_id:
            lines.append(f"- source session: {source_session_id}")
        replay_session_id = metadata.get("replay_session_id")
        if replay_session_id:
            lines.append(f"- replay session: {replay_session_id}")
        source_trace_id = metadata.get("source_trace_id")
        if source_trace_id:
            lines.append(f"- source trace: {source_trace_id}")
        replay_trace_id = metadata.get("replay_trace_id")
        if replay_trace_id:
            lines.append(f"- replay trace: {replay_trace_id}")
        step_name = metadata.get("task_name")
        if step_name:
            lines.append(f"- step: {step_name}")
        lines.append(f"- note: apply as a small, focused prompt improvement.")
        return "\n".join(lines)

    def _list_block_values(self, field_name: str) -> list[str]:
        values: list[str] = []
        prefix = f"- {field_name}: "
        for block in self._blocks():
            for line in block.splitlines():
                if line.startswith(prefix):
                    value = line.removeprefix(prefix).strip()
                    if value:
                        values.append(value)
                    break
        return values
