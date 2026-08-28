from __future__ import annotations

import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass
import json
import os
import re
from threading import Event, Lock, Thread, current_thread
from typing import Any

from navi_agent.config import MCPServerSettings


_ENV_REFERENCE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")


class MCPClientError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MCPToolDescription:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MCPCallResult:
    content: str
    is_error: bool = False
    structured_content: dict[str, Any] | None = None


class MCPStdioClient:
    """Persistent synchronous facade over one async MCP stdio session."""

    def __init__(self, settings: MCPServerSettings) -> None:
        self.settings = settings
        self._ready = Event()
        self._stop_requested = Event()
        self._lock = Lock()
        self._thread: Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._client: Any = None
        self._tools: tuple[MCPToolDescription, ...] = ()
        self._terminal_error: BaseException | None = None

    def start(self) -> tuple[MCPToolDescription, ...]:
        with self._lock:
            if self._thread is None:
                self._thread = Thread(
                    target=self._thread_main,
                    name=f"navi-mcp-{self.settings.name}",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(self.settings.startup_timeout_seconds):
            self.close()
            raise MCPClientError(
                f"MCP server {self.settings.name!r} did not start within "
                f"{self.settings.startup_timeout_seconds:g}s"
            )
        if self._terminal_error is not None:
            error = self._terminal_error
            self.close()
            raise MCPClientError(
                f"MCP server {self.settings.name!r} failed to start: {error}"
            ) from error
        return self._tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> MCPCallResult:
        self.start()
        loop = self._loop
        client = self._client
        if loop is None or client is None or self._terminal_error is not None:
            raise MCPClientError(f"MCP server {self.settings.name!r} is not connected")
        future = asyncio.run_coroutine_threadsafe(
            client.call_tool(name, arguments),
            loop,
        )
        try:
            result = future.result(timeout=self.settings.tool_timeout_seconds)
        except FutureTimeoutError as error:
            future.cancel()
            raise MCPClientError(
                f"MCP tool {self.settings.name}.{name} timed out after "
                f"{self.settings.tool_timeout_seconds:g}s"
            ) from error
        except Exception as error:
            raise MCPClientError(
                f"MCP tool {self.settings.name}.{name} failed: {error}"
            ) from error
        return _convert_call_result(result)

    def close(self) -> None:
        self._stop_requested.set()
        loop = self._loop
        stop_event = self._stop_event
        if loop is not None and stop_event is not None and loop.is_running():
            loop.call_soon_threadsafe(stop_event.set)
        thread = self._thread
        if thread is not None and thread is not current_thread():
            thread.join(timeout=2.0)

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as error:
            self._terminal_error = error
            self._ready.set()
        finally:
            self._client = None
            self._loop = None
            self._stop_event = None

    async def _serve(self) -> None:
        Client, StdioServerParameters = _load_sdk()
        command, *args = self.settings.command
        parameters = StdioServerParameters(
            command=command,
            args=args,
            env=_resolve_environment(self.settings.environment),
        )
        async with Client(parameters) as client:
            tools_result = await client.list_tools()
            self._loop = asyncio.get_running_loop()
            self._stop_event = asyncio.Event()
            self._client = client
            self._tools = tuple(
                _convert_tool_description(tool)
                for tool in _result_items(tools_result, "tools")
            )
            self._ready.set()
            if self._stop_requested.is_set():
                self._stop_event.set()
            await self._stop_event.wait()


def _load_sdk():
    try:
        from mcp import Client, StdioServerParameters
    except ImportError as error:
        raise MCPClientError(
            "MCP support requires the optional dependency: uv sync --extra mcp"
        ) from error
    return Client, StdioServerParameters


def _resolve_environment(environment: dict[str, str]) -> dict[str, str]:
    resolved = {}
    for name, value in environment.items():
        match = _ENV_REFERENCE.fullmatch(value)
        if match is None:
            resolved[name] = value
            continue
        source_name = match.group(1)
        source_value = os.getenv(source_name)
        if source_value is None:
            raise MCPClientError(
                f"MCP environment variable {source_name!r} is not set"
            )
        resolved[name] = source_value
    return resolved


def _result_items(result: Any, attribute: str) -> list[Any]:
    value = getattr(result, attribute, result)
    return list(value or [])


def _convert_tool_description(tool: Any) -> MCPToolDescription:
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = getattr(tool, "inputSchema", None)
    return MCPToolDescription(
        name=str(tool.name),
        description=str(getattr(tool, "description", "") or ""),
        input_schema=dict(schema or {"type": "object", "properties": {}}),
    )


def _convert_call_result(result: Any) -> MCPCallResult:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    structured_content = dict(structured) if isinstance(structured, dict) else None
    blocks = _result_items(result, "content")
    rendered = [_render_content_block(block) for block in blocks]
    content = "\n".join(item for item in rendered if item)
    if not content and structured_content:
        content = json.dumps(structured_content, ensure_ascii=False, sort_keys=True)
    is_error = bool(
        getattr(result, "is_error", getattr(result, "isError", False))
    )
    return MCPCallResult(
        content=content,
        is_error=is_error,
        structured_content=structured_content,
    )


def _render_content_block(block: Any) -> str:
    text = getattr(block, "text", None)
    if isinstance(text, str):
        return text
    block_type = str(getattr(block, "type", "content") or "content")
    mime_type = getattr(block, "mime_type", getattr(block, "mimeType", None))
    suffix = f": {mime_type}" if mime_type else ""
    return f"[MCP {block_type}{suffix}]"
