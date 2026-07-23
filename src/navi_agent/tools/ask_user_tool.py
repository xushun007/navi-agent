from __future__ import annotations

from typing import Any

from navi_agent.runtime.interactions import JsonPendingInteractionStore
from navi_agent.tooling import ToolContext, ToolResult

from .base import BaseTool


class AskUserTool(BaseTool):
    def __init__(self, store: JsonPendingInteractionStore) -> None:
        self._store = store

    @property
    def name(self) -> str:
        return "ask_user"

    @property
    def description(self) -> str:
        return "Pause the current run and ask the user for information required to continue."

    def schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "A concise question that states the missing information.",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is None:
            return ToolResult.error(name=self.name, content="ask_user requires tool context")
        question = str(kwargs.get("question") or "").strip()
        if not question:
            return ToolResult.error(name=self.name, content="question must not be empty")
        pending = self._store.create(
            session_id=context.session_id,
            user_id=context.user_id,
            kind="clarification",
            prompt=question,
            run_id=context.run_id,
        )
        return ToolResult.ok(
            name=self.name,
            content=question,
            structured_content={
                "interaction_pending": True,
                "interaction_kind": "clarification",
                "interaction_id": pending.interaction_id,
                "prompt": question,
            },
        )
