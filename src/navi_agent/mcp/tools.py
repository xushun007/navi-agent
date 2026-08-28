from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
import logging
import re
from typing import Any

from navi_agent.config import MCPSettings
from navi_agent.tooling import ToolContext, ToolResult
from navi_agent.tools.base import BaseTool

from .client import MCPClientError, MCPStdioClient, MCPToolDescription


logger = logging.getLogger("navi_agent.mcp")
_INVALID_NAME = re.compile(r"[^A-Za-z0-9_]+")
_MAX_TOOL_NAME_LENGTH = 64


class MCPTool(BaseTool):
    def __init__(
        self,
        *,
        server_name: str,
        remote: MCPToolDescription,
        client: MCPStdioClient,
    ) -> None:
        self._server_name = server_name
        self._remote = remote
        self._client = client
        self._name = mcp_tool_name(server_name, remote.name)

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._remote.description

    def schema(self) -> dict[str, Any]:
        return self._remote.input_schema

    def invoke(self, context: ToolContext | None = None, **kwargs: Any) -> ToolResult:
        try:
            result = self._client.call_tool(self._remote.name, kwargs)
        except Exception as error:
            return ToolResult.error(
                name=self.name,
                content=str(error),
                structured_content={"error": str(error)},
                metadata=self._metadata(),
            )
        factory = ToolResult.error if result.is_error else ToolResult.ok
        return factory(
            name=self.name,
            content=result.content,
            structured_content=result.structured_content,
            metadata=self._metadata(),
        )

    def _metadata(self) -> dict[str, str]:
        return {
            "mcp_server": self._server_name,
            "mcp_tool": self._remote.name,
        }


class MCPToolProvider:
    """Discover configured MCP servers without making one failure fatal."""

    def __init__(
        self,
        settings: MCPSettings,
        *,
        client_factory: Callable[[Any], MCPStdioClient] = MCPStdioClient,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory
        self._clients: list[MCPStdioClient] = []
        self._tools: tuple[MCPTool, ...] | None = None
        self.errors: dict[str, str] = {}

    def discover(self) -> tuple[MCPTool, ...]:
        if self._tools is not None:
            return self._tools
        tools: list[MCPTool] = []
        names: set[str] = set()
        for server in self._settings.servers:
            client = self._client_factory(server)
            try:
                descriptions = client.start()
            except MCPClientError as error:
                self.errors[server.name] = str(error)
                logger.warning("MCP server unavailable: server=%s error=%s", server.name, error)
                client.close()
                continue
            self._clients.append(client)
            for description in descriptions:
                tool = MCPTool(
                    server_name=server.name,
                    remote=description,
                    client=client,
                )
                if tool.name in names:
                    logger.warning(
                        "Skipped colliding MCP tool name: server=%s tool=%s public_name=%s",
                        server.name,
                        description.name,
                        tool.name,
                    )
                    continue
                names.add(tool.name)
                tools.append(tool)
        self._tools = tuple(tools)
        return self._tools

    def close(self) -> None:
        for client in reversed(self._clients):
            client.close()
        self._clients.clear()


def mcp_tool_name(server_name: str, tool_name: str) -> str:
    server = _sanitize_name(server_name)
    tool = _sanitize_name(tool_name)
    name = f"mcp__{server}__{tool}"
    if len(name) <= _MAX_TOOL_NAME_LENGTH:
        return name
    digest = sha256(name.encode("utf-8")).hexdigest()[:8]
    return f"{name[:_MAX_TOOL_NAME_LENGTH - len(digest) - 1]}_{digest}"


def _sanitize_name(value: str) -> str:
    sanitized = _INVALID_NAME.sub("_", value.strip()).strip("_")
    return sanitized or "unnamed"
