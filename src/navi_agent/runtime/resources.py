from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from navi_agent.tools.base import BaseTool


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    """One tool contributed to the runtime by a named source."""

    tool: BaseTool
    toolsets: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        if not self.toolsets:
            raise ValueError(f"Tool {self.tool.name!r} must belong to a toolset")
        if not self.source.strip():
            raise ValueError(f"Tool {self.tool.name!r} must have a source")


class ToolProvider(Protocol):
    """Loads a coherent group of tools and owns their external resources."""

    def load_tools(self) -> Sequence[ToolRegistration]: ...

    def close(self) -> None: ...


@dataclass(slots=True)
class RuntimeResources:
    """Resolved runtime capabilities with one idempotent cleanup boundary."""

    tools: tuple[ToolRegistration, ...] = ()
    close_callbacks: tuple[Callable[[], None], ...] = ()
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for callback in reversed(self.close_callbacks):
            callback()


def load_runtime_resources(providers: Iterable[ToolProvider]) -> RuntimeResources:
    """Resolve providers once and reject ambiguous public tool names."""

    registrations: list[ToolRegistration] = []
    loaded_providers: list[ToolProvider] = []
    sources_by_name: dict[str, str] = {}
    try:
        for provider in providers:
            loaded_providers.append(provider)
            for registration in provider.load_tools():
                existing_source = sources_by_name.get(registration.tool.name)
                if existing_source is not None:
                    raise ValueError(
                        f"Duplicate tool name {registration.tool.name!r} from "
                        f"{existing_source!r} and {registration.source!r}"
                    )
                sources_by_name[registration.tool.name] = registration.source
                registrations.append(registration)
    except BaseException:
        for provider in reversed(loaded_providers):
            provider.close()
        raise

    return RuntimeResources(
        tools=tuple(registrations),
        close_callbacks=tuple(provider.close for provider in loaded_providers),
    )
