from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from navi_agent.runtime.models import ToolContext, ToolResult


class BaseTool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    @abstractmethod
    def schema(self) -> dict[str, Any]: ...

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult: ...


class FunctionTool(BaseTool):
    def __init__(
        self,
        name: str,
        description: str,
        handler: Callable[..., ToolResult],
        parameters: dict[str, Any] | None = None,
    ) -> None:
        self._name = name
        self._description = description
        self.handler = handler
        self.parameters = parameters

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    def schema(self) -> dict[str, Any]:
        return self.parameters or {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        if context is not None and "context" in self.handler.__code__.co_varnames:
            return self.handler(context=context, **kwargs)
        return self.handler(**kwargs)
