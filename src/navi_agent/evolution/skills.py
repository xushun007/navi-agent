from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from navi_agent.telemetry import RuntimeTrace

from .models import EvolutionCandidate

_VALID_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class SkillRecord:
    name: str
    description: str
    content: str
    path: Path


class FileSkillStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def create(self, *, name: str, content: str) -> SkillRecord:
        name = _normalize_skill_name(name)
        skill_dir = self._root / name
        skill_path = skill_dir / "SKILL.md"
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path.write_text(content, encoding="utf-8")
        return SkillRecord(
            name=name,
            description=_extract_description(content),
            content=content,
            path=skill_path,
        )

    def get(self, name: str) -> SkillRecord | None:
        name = _normalize_skill_name(name)
        skill_path = self._root / name / "SKILL.md"
        if not skill_path.exists():
            return None
        content = skill_path.read_text(encoding="utf-8")
        return SkillRecord(
            name=name,
            description=_extract_description(content),
            content=content,
            path=skill_path,
        )

    def remove(self, name: str) -> bool:
        name = _normalize_skill_name(name)
        skill_dir = self._root / name
        if not skill_dir.exists():
            return False
        if not skill_dir.is_dir():
            return False
        shutil.rmtree(skill_dir)
        return True

    def list(self) -> list[SkillRecord]:
        if not self._root.exists():
            return []
        records = []
        for skill_path in sorted(self._root.glob("*/SKILL.md")):
            content = skill_path.read_text(encoding="utf-8")
            records.append(
                SkillRecord(
                    name=skill_path.parent.name,
                    description=_extract_description(content),
                    content=content,
                    path=skill_path,
                )
            )
        return records

    def search(self, query: str, *, limit: int = 3) -> list[SkillRecord]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        query_terms = set(_tokenize(query))
        if not query_terms:
            return []

        scored: list[tuple[int, SkillRecord]] = []
        for record in self.list():
            searchable = " ".join([record.name, record.description, record.content])
            score = len(query_terms.intersection(_tokenize(searchable)))
            if score > 0:
                scored.append((score, record))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [record for _, record in scored[:limit]]


class EvolutionEngine:
    def propose_skill_candidate(self, trace: RuntimeTrace) -> EvolutionCandidate | None:
        if trace.status != "success":
            return None
        if not trace.final_response.strip():
            return None
        if not trace.tool_executions:
            return None

        skill_name = self._skill_name_from_trace(trace)
        content = self._skill_content_from_trace(trace, skill_name=skill_name)
        return EvolutionCandidate(
            target="skill",
            summary=f"Create reusable skill `{skill_name}` from session {trace.session_id}",
            rationale="Successful tool-using sessions can become procedural memory after review.",
            metadata={
                "source_session_id": trace.session_id,
                "source_trace_id": trace.trace_id,
                "skill_name": skill_name,
                "skill_content": content,
                "tool_names": [execution.tool_name for execution in trace.tool_executions],
            },
        )

    def apply_skill_candidate(
        self,
        candidate: EvolutionCandidate,
        *,
        skill_store: FileSkillStore,
    ) -> SkillRecord | None:
        if candidate.target != "skill":
            return None
        if candidate.status != "accepted":
            return None
        metadata = candidate.metadata or {}
        name = metadata.get("skill_name")
        content = metadata.get("skill_content")
        if not isinstance(name, str) or not name.strip():
            return None
        if not isinstance(content, str) or not content.strip():
            return None
        return skill_store.create(name=name, content=content)

    @staticmethod
    def _skill_name_from_trace(trace: RuntimeTrace) -> str:
        base = _slugify(trace.user_message) or f"session-{trace.session_id}"
        return _normalize_skill_name(f"learned-{base}"[:64].rstrip("-._"))

    @staticmethod
    def _skill_content_from_trace(trace: RuntimeTrace, *, skill_name: str) -> str:
        tool_names = []
        for execution in trace.tool_executions:
            if execution.tool_name not in tool_names:
                tool_names.append(execution.tool_name)
        tool_line = ", ".join(tool_names) if tool_names else "none"
        title = skill_name.replace("-", " ").title()
        return "\n".join(
            [
                "---",
                f"name: {skill_name}",
                f"description: Reusable procedure learned from session {trace.session_id}",
                "source: navi-agent",
                "---",
                "",
                f"# {title}",
                "",
                "## When To Use",
                "",
                f"Use this when a future task resembles: {trace.user_message}",
                "",
                "## Procedure",
                "",
                f"- Start from the user's request: {trace.user_message}",
                f"- Reuse the proven tool pattern: {tool_line}",
                "- Verify the outcome before presenting it as complete.",
                "",
                "## Evidence",
                "",
                f"- source_session_id: {trace.session_id}",
                f"- source_trace_id: {trace.trace_id}",
            ]
        )


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    return lowered.strip("-")


def _tokenize(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.lower()) if len(token) > 2]


def _normalize_skill_name(name: str) -> str:
    normalized = _slugify(name)
    if not normalized:
        raise ValueError("skill name is required")
    if len(normalized) > 64:
        normalized = normalized[:64].rstrip("-._")
    if not _VALID_SKILL_NAME.match(normalized):
        raise ValueError(f"invalid skill name: {name}")
    return normalized


def _extract_description(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("description:"):
            return line.removeprefix("description:").strip()
    return ""
