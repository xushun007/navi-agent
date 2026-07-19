from __future__ import annotations

from typing import Any

from navi_agent.evolution.skills import FileSkillStore
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


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
                    "enum": ["list", "view", "create", "append"],
                },
                "skill_name": {"type": "string"},
                "skill_content": {"type": "string"},
                "section": {"type": "string"},
                "append_content": {"type": "string"},
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

        return ToolResult.error(
            name=self.name,
            content=f"skill_manage_error: unsupported action: {action}",
        )
