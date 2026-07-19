from __future__ import annotations

from typing import Any

from navi_agent.evolution.skills import FileSkillStore
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class SkillListTool(BaseTool):
    def __init__(self, skill_store: FileSkillStore) -> None:
        self._skill_store = skill_store

    @property
    def name(self) -> str:
        return "skill_list"

    @property
    def description(self) -> str:
        return "List available Navi Agent skills with compact metadata."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
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


class SkillViewTool(BaseTool):
    def __init__(self, skill_store: FileSkillStore) -> None:
        self._skill_store = skill_store

    @property
    def name(self) -> str:
        return "skill_view"

    @property
    def description(self) -> str:
        return "Load a skill's full SKILL.md or an explicitly referenced attachment."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "attachment_path": {"type": "string"},
            },
            "required": ["skill_name"],
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        skill_name = str(kwargs.get("skill_name") or "").strip()
        if not skill_name:
            return ToolResult.error(name=self.name, content="skill_view_error: skill_name is required")
        attachment_path = str(kwargs.get("attachment_path") or "").strip()
        if attachment_path:
            return self._view_attachment(skill_name=skill_name, attachment_path=attachment_path)
        record = self._skill_store.get(skill_name)
        if record is None:
            return ToolResult.error(
                name=self.name,
                content=f"skill_view_error: skill not found: {skill_name}",
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

    def _view_attachment(self, *, skill_name: str, attachment_path: str) -> ToolResult:
        try:
            content = self._skill_store.read_attachment(
                name=skill_name,
                relative_path=attachment_path,
            )
        except ValueError as error:
            return ToolResult.error(name=self.name, content=f"skill_view_error: {error}")
        if content is None:
            return ToolResult.error(
                name=self.name,
                content=f"skill_view_error: attachment not found: {attachment_path}",
            )
        return ToolResult.ok(
            name=self.name,
            content=content,
            structured_content={
                "skill_name": skill_name,
                "attachment_path": attachment_path,
            },
        )
