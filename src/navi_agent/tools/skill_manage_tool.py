from __future__ import annotations

import re
from typing import Any

from navi_agent.evolution.skills import FileSkillStore
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool

_MAX_ATTACHMENT_CHARS = 200_000


class SkillManageTool(BaseTool):
    def __init__(self, skill_store: FileSkillStore) -> None:
        self._skill_store = skill_store

    @property
    def name(self) -> str:
        return "skill_manage"

    @property
    def description(self) -> str:
        return "Review and maintain Navi Agent skills."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "view", "create", "append", "write_attachment"],
                },
                "skill_name": {"type": "string"},
                "skill_content": {"type": "string"},
                "section": {"type": "string"},
                "append_content": {"type": "string"},
                "attachment_path": {"type": "string"},
                "attachment_content": {"type": "string"},
            },
            "required": ["action"],
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        action = str(kwargs["action"]).strip()
        if action == "list":
            records = self._skill_store.list()
            return ToolResult.ok(
                name=self.name,
                content="\n".join(f"- {item.name}: {item.description}" for item in records)
                or "skills_empty",
                structured_content={
                    "skills": [
                        {"name": item.name, "description": item.description} for item in records
                    ],
                    "skill_count": len(records),
                },
            )

        skill_name = str(kwargs.get("skill_name") or "").strip()
        if not skill_name:
            return ToolResult.error(
                name=self.name,
                content="skill_manage_error: skill_name is required",
            )

        if action == "view":
            record = self._skill_store.get(skill_name)
            if record is None:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: skill not found: {skill_name}",
                )
            return ToolResult.ok(
                name=self.name,
                content=record.content,
                structured_content={
                    "skill_name": record.name,
                    "description": record.description,
                    "attachments": [attachment.path for attachment in record.attachments],
                },
            )

        if action == "create":
            skill_content = str(kwargs.get("skill_content") or "").strip()
            if not skill_content:
                return ToolResult.error(
                    name=self.name,
                    content="skill_manage_error: skill_content is required for create",
                )
            if self._skill_store.get(skill_name) is not None:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: skill already exists: {skill_name}",
                )
            validation_error = _validate_new_skill(skill_name, skill_content)
            if validation_error:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: {validation_error}",
                )
            record = self._skill_store.create(name=skill_name, content=skill_content)
            return ToolResult.ok(
                name=self.name,
                content=f"skill_created: {record.name}",
                structured_content={
                    "action": "create",
                    "skill_name": record.name,
                    "description": record.description,
                },
            )

        if action == "append":
            section = str(kwargs.get("section") or "").strip()
            append_content = str(kwargs.get("append_content") or "").strip()
            if not section:
                return ToolResult.error(
                    name=self.name,
                    content="skill_manage_error: section is required for append",
                )
            if not append_content:
                return ToolResult.error(
                    name=self.name,
                    content="skill_manage_error: append_content is required for append",
                )
            validation_error = _validate_append_content(append_content)
            if validation_error:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: {validation_error}",
                )
            record = self._skill_store.append_to_section(
                name=skill_name,
                section=section,
                content=append_content,
            )
            if record is None:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: skill not found: {skill_name}",
                )
            return ToolResult.ok(
                name=self.name,
                content=f"skill_updated: {record.name}",
                structured_content={
                    "action": "append",
                    "skill_name": record.name,
                    "section": section,
                },
            )

        if action == "write_attachment":
            attachment_path = str(kwargs.get("attachment_path") or "").strip()
            attachment_content = str(kwargs.get("attachment_content") or "")
            if not attachment_path:
                return ToolResult.error(
                    name=self.name,
                    content="skill_manage_error: attachment_path is required for write_attachment",
                )
            validation_error = _validate_attachment_content(attachment_content)
            if validation_error:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: {validation_error}",
                )
            try:
                attachment = self._skill_store.write_attachment(
                    name=skill_name,
                    relative_path=attachment_path,
                    content=attachment_content,
                )
            except ValueError as error:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: {error}",
                )
            if attachment is None:
                return ToolResult.error(
                    name=self.name,
                    content=f"skill_manage_error: skill not found: {skill_name}",
                )
            return ToolResult.ok(
                name=self.name,
                content=f"skill_attachment_written: {attachment.path}",
                structured_content={
                    "action": "write_attachment",
                    "skill_name": skill_name,
                    "attachment_path": attachment.path,
                    "attachment_kind": attachment.kind,
                    "size_bytes": attachment.size_bytes,
                },
            )

        return ToolResult.error(
            name=self.name,
            content=f"skill_manage_error: unsupported action: {action}",
        )


def _validate_new_skill(skill_name: str, content: str) -> str:
    if not content.lstrip().startswith("#"):
        return "skill_content must start with a markdown title"
    required_sections = ["## When To Use", "## Procedure"]
    missing = [section for section in required_sections if section.lower() not in content.lower()]
    if missing:
        return f"skill_content missing required section: {missing[0]}"
    if len(content) < 80:
        return "skill_content is too short for a reusable skill"
    if len(content) > 12000:
        return "skill_content is too large"
    polluted = _validate_persistent_content(content)
    if polluted:
        return polluted
    if _looks_like_micro_skill_name(skill_name):
        return "skill_name looks session-specific rather than class-level"
    return ""


def _validate_append_content(content: str) -> str:
    if len(content) < 12:
        return "append_content is too short"
    if len(content) > 4000:
        return "append_content is too large"
    if _has_placeholder(content):
        return "append_content contains placeholder text"
    return _validate_persistent_content(content)


def _validate_attachment_content(content: str) -> str:
    if not content.strip():
        return "attachment_content is required for write_attachment"
    if len(content) > _MAX_ATTACHMENT_CHARS:
        return "attachment_content is too large"
    if _has_placeholder(content):
        return "attachment_content contains placeholder text"
    return ""


def _validate_persistent_content(content: str) -> str:
    lowered = content.lower()
    blocked_phrases = [
        "does not work",
        "doesn't work",
        "cannot use",
        "can't use",
        "is broken",
        "not available",
        "command not found",
        "missing binary",
        "unconfigured credential",
        "unconfigured credentials",
    ]
    for phrase in blocked_phrases:
        if phrase in lowered:
            return "content contains transient or negative tool claim"
    return ""


def _has_placeholder(content: str) -> bool:
    lowered = content.lower()
    placeholder_patterns = [
        r"\.\.\.",
        r"keep existing",
        r"保持不变",
        r"其余.*不变",
        r"same as before",
        r"todo",
    ]
    return any(re.search(pattern, lowered) for pattern in placeholder_patterns)


def _looks_like_micro_skill_name(skill_name: str) -> bool:
    lowered = skill_name.lower()
    if re.search(r"\b(trace|session|today|tmp|temp|pr-\d+|issue-\d+)\b", lowered):
        return True
    if re.search(r"\d{4,}", lowered):
        return True
    return False
