from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from navi_agent.telemetry import RuntimeTrace

from ..core.models import EvolutionCandidate

_VALID_SKILL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_ALLOWED_ATTACHMENT_DIRS = frozenset({"references", "templates", "scripts"})


@dataclass(frozen=True, slots=True)
class SkillReference:
    path: str
    content: str


@dataclass(frozen=True, slots=True)
class SkillAttachment:
    path: str
    kind: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class SkillRecord:
    name: str
    description: str
    content: str
    path: Path
    references: list[SkillReference]
    attachments: list[SkillAttachment]
    category: str = "general"


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
            references=_read_references(skill_dir),
            attachments=_read_attachments(skill_dir),
            category=_extract_category(content),
        )

    def update(self, *, name: str, content: str) -> SkillRecord | None:
        name = _normalize_skill_name(name)
        skill_path = self._root / name / "SKILL.md"
        if not skill_path.exists():
            return None
        skill_path.write_text(content, encoding="utf-8")
        return SkillRecord(
            name=name,
            description=_extract_description(content),
            content=content,
            path=skill_path,
            references=_read_references(skill_path.parent),
            attachments=_read_attachments(skill_path.parent),
            category=_extract_category(content),
        )

    def append_to_section(self, *, name: str, section: str, content: str) -> SkillRecord | None:
        name = _normalize_skill_name(name)
        skill_path = self._root / name / "SKILL.md"
        if not skill_path.exists():
            return None
        current = skill_path.read_text(encoding="utf-8")
        updated = append_to_markdown_section(current, section=section, content=content)
        skill_path.write_text(updated, encoding="utf-8")
        return SkillRecord(
            name=name,
            description=_extract_description(updated),
            content=updated,
            path=skill_path,
            references=_read_references(skill_path.parent),
            attachments=_read_attachments(skill_path.parent),
            category=_extract_category(updated),
        )

    def write_attachment(self, *, name: str, relative_path: str, content: str) -> SkillAttachment | None:
        name = _normalize_skill_name(name)
        skill_dir = self._root / name
        if not (skill_dir / "SKILL.md").exists():
            return None
        path = _resolve_attachment_path(skill_dir, relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return SkillAttachment(
            path=path.relative_to(skill_dir).as_posix(),
            kind=path.relative_to(skill_dir).parts[0],
            size_bytes=path.stat().st_size,
        )

    def read_attachment(self, *, name: str, relative_path: str) -> str | None:
        name = _normalize_skill_name(name)
        skill_dir = self._root / name
        if not (skill_dir / "SKILL.md").exists():
            return None
        path = _resolve_attachment_path(skill_dir, relative_path)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

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
            references=_read_references(skill_path.parent),
            attachments=_read_attachments(skill_path.parent),
            category=_extract_category(content),
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

    def archive(self, name: str) -> SkillRecord | None:
        name = _normalize_skill_name(name)
        skill_dir = self._root / name
        skill_path = skill_dir / "SKILL.md"
        if not skill_path.exists():
            return None
        content = skill_path.read_text(encoding="utf-8")
        archive_root = self._root / ".archive"
        archive_root.mkdir(parents=True, exist_ok=True)
        archive_dir = archive_root / name
        if archive_dir.exists():
            shutil.rmtree(archive_dir)
        shutil.move(str(skill_dir), str(archive_dir))
        return SkillRecord(
            name=name,
            description=_extract_description(content),
            content=content,
            path=archive_dir / "SKILL.md",
            references=_read_references(archive_dir),
            attachments=_read_attachments(archive_dir),
            category=_extract_category(content),
        )

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
                    references=_read_references(skill_path.parent),
                    attachments=_read_attachments(skill_path.parent),
                    category=_extract_category(content),
                )
            )
        return records

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
        operation = str(metadata.get("operation") or "create").strip()
        if operation == "update":
            section = metadata.get("section")
            append_content = metadata.get("append_content")
            if not isinstance(section, str) or not section.strip():
                return None
            if not isinstance(append_content, str) or not append_content.strip():
                return None
            return skill_store.append_to_section(
                name=name,
                section=section,
                content=append_content,
            )
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
                "category: learned",
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
    return _extract_frontmatter_value(content, "description")


def _extract_category(content: str) -> str:
    category = _extract_frontmatter_value(content, "category")
    return _slugify(category) if category else "general"


def _extract_frontmatter_value(content: str, key: str) -> str:
    frontmatter = _extract_frontmatter(content)
    if frontmatter is None:
        return ""
    prefix = f"{key}:"
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped.removeprefix(prefix).strip().strip("'\"")
    return ""


def _extract_frontmatter(content: str) -> str | None:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        return None
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index])
    return None


def append_to_markdown_section(markdown: str, *, section: str, content: str) -> str:
    section = section.strip()
    content = content.strip()
    if not section:
        raise ValueError("section is required")
    if not content:
        raise ValueError("content is required")
    heading = section if section.startswith("#") else f"## {section}"
    lines = markdown.rstrip().splitlines()
    heading_index = _find_heading_index(lines, heading)
    if heading_index is None:
        return "\n".join([markdown.rstrip(), "", heading, "", content, ""])

    insert_at = len(lines)
    heading_level = len(heading) - len(heading.lstrip("#"))
    for index in range(heading_index + 1, len(lines)):
        line = lines[index]
        if line.startswith("#"):
            level = len(line) - len(line.lstrip("#"))
            if level <= heading_level:
                insert_at = index
                break
    new_lines = lines[:insert_at]
    if new_lines and new_lines[-1].strip():
        new_lines.append("")
    new_lines.extend(content.splitlines())
    if insert_at < len(lines):
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.extend(lines[insert_at:])
    return "\n".join(new_lines).rstrip() + "\n"


def _find_heading_index(lines: list[str], heading: str) -> int | None:
    normalized = heading.strip().lower()
    for index, line in enumerate(lines):
        if line.strip().lower() == normalized:
            return index
    return None


def _read_references(skill_dir: Path) -> list[SkillReference]:
    references_dir = skill_dir / "references"
    if not references_dir.is_dir():
        return []
    records: list[SkillReference] = []
    for path in sorted(references_dir.rglob("*.md")):
        if not path.is_file():
            continue
        relative = path.relative_to(skill_dir).as_posix()
        records.append(
            SkillReference(
                path=relative,
                content=path.read_text(encoding="utf-8"),
            )
        )
    return records


def _read_attachments(skill_dir: Path) -> list[SkillAttachment]:
    records: list[SkillAttachment] = []
    for directory in sorted(_ALLOWED_ATTACHMENT_DIRS):
        root = skill_dir / directory
        if not root.is_dir():
            continue
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(skill_dir).as_posix()
            records.append(
                SkillAttachment(
                    path=relative,
                    kind=directory,
                    size_bytes=path.stat().st_size,
                )
            )
    return records


def _resolve_attachment_path(skill_dir: Path, relative_path: str) -> Path:
    raw_path = relative_path.strip()
    if not raw_path:
        raise ValueError("attachment path is required")
    path = Path(raw_path)
    if path.is_absolute():
        raise ValueError("attachment path must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("attachment path must not contain empty, current, or parent segments")
    if path.parts[0] not in _ALLOWED_ATTACHMENT_DIRS:
        allowed = ", ".join(sorted(_ALLOWED_ATTACHMENT_DIRS))
        raise ValueError(f"attachment path must start with one of: {allowed}")
    resolved = (skill_dir / path).resolve()
    skill_root = skill_dir.resolve()
    try:
        resolved.relative_to(skill_root)
    except ValueError as error:
        raise ValueError("attachment path escapes skill directory") from error
    return resolved
