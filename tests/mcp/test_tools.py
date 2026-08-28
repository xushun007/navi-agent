from __future__ import annotations

from navi_agent.config import MCPServerSettings, MCPSettings
from navi_agent.mcp import (
    MCPCallResult,
    MCPClientError,
    MCPToolDescription,
    MCPToolProvider,
    mcp_tool_name,
)


class _FakeClient:
    instances = []

    def __init__(self, settings) -> None:
        self.settings = settings
        self.closed = False
        type(self).instances.append(self)

    def start(self):
        if self.settings.name == "broken":
            raise MCPClientError("connection failed")
        return (
            MCPToolDescription(
                name="read-file",
                description="Read a file.",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            ),
        )

    def call_tool(self, name, arguments):
        return MCPCallResult(
            content=f"read {arguments['path']}",
            structured_content={"remote_name": name},
        )

    def close(self) -> None:
        self.closed = True


def _server(name: str) -> MCPServerSettings:
    return MCPServerSettings(name=name, command=("server",), environment={})


def test_discovers_namespaced_tools_and_maps_results() -> None:
    _FakeClient.instances.clear()
    provider = MCPToolProvider(
        MCPSettings(servers=(_server("local files"),)),
        client_factory=_FakeClient,
    )

    tools = provider.discover()
    result = tools[0].invoke(path="README.md")
    provider.close()

    assert tools[0].name == "mcp__local_files__read_file"
    assert tools[0].description == "Read a file."
    assert tools[0].schema()["properties"]["path"]["type"] == "string"
    assert result.status == "success"
    assert result.content == "read README.md"
    assert result.structured_content == {"remote_name": "read-file"}
    assert result.metadata == {
        "mcp_server": "local files",
        "mcp_tool": "read-file",
    }
    assert _FakeClient.instances[0].closed is True


def test_isolates_broken_servers() -> None:
    _FakeClient.instances.clear()
    provider = MCPToolProvider(
        MCPSettings(servers=(_server("broken"), _server("healthy"))),
        client_factory=_FakeClient,
    )

    tools = provider.discover()

    assert [tool.name for tool in tools] == ["mcp__healthy__read_file"]
    assert "connection failed" in provider.errors["broken"]
    assert _FakeClient.instances[0].closed is True
    provider.close()


def test_limits_namespaced_tool_names() -> None:
    name = mcp_tool_name("server" * 10, "tool" * 20)

    assert len(name) == 64
    assert name.startswith("mcp__")
