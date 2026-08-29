from __future__ import annotations

from types import SimpleNamespace

from navi_agent.config import MCPServerSettings
from navi_agent.mcp import MCPHTTPClient, MCPStdioClient, create_mcp_client


class _FakeTimeout:
    def __init__(self, seconds) -> None:
        self.seconds = seconds


class _FakeHTTPClient:
    last = None

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        type(self).last = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _FakeMCPClient:
    last_transport = None

    def __init__(self, transport) -> None:
        self.transport = transport

    async def __aenter__(self):
        type(self).last_transport = self.transport
        return self

    async def __aexit__(self, *_args):
        return None

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="search",
                    description="Search projects.",
                    input_schema={"type": "object", "properties": {}},
                )
            ]
        )

    async def call_tool(self, name, arguments):
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=arguments["query"])],
            structured_content=None,
            is_error=False,
        )


def _fake_http_sdk():
    httpx = SimpleNamespace(AsyncClient=_FakeHTTPClient, Timeout=_FakeTimeout)

    def transport(url, *, http_client):
        return (url, http_client)

    return _FakeMCPClient, transport, httpx


def test_discovers_and_calls_streamable_http_tools(monkeypatch) -> None:
    monkeypatch.setenv("MCP_HTTP_TOKEN", "secret")
    monkeypatch.setattr("navi_agent.mcp.client._load_http_sdk", _fake_http_sdk)
    client = MCPHTTPClient(
        MCPServerSettings(
            name="projects",
            transport="http",
            url="https://mcp.example.com/api",
            headers={"Authorization": "Bearer ${MCP_HTTP_TOKEN}"},
            startup_timeout_seconds=1,
            tool_timeout_seconds=4,
        )
    )

    try:
        tools = client.start()
        result = client.call_tool("search", {"query": "Navi"})
    finally:
        client.close()

    assert [tool.name for tool in tools] == ["search"]
    assert result.content == "Navi"
    assert _FakeHTTPClient.last.kwargs["headers"] == {
        "Authorization": "Bearer secret"
    }
    assert _FakeHTTPClient.last.kwargs["follow_redirects"] is True
    assert _FakeHTTPClient.last.kwargs["timeout"].seconds == 4
    assert _FakeMCPClient.last_transport[0] == "https://mcp.example.com/api"


def test_selects_client_from_server_transport() -> None:
    http = create_mcp_client(
        MCPServerSettings(name="remote", transport="http", url="https://example.com")
    )
    stdio = create_mcp_client(
        MCPServerSettings(name="local", command=("server",))
    )

    assert isinstance(http, MCPHTTPClient)
    assert isinstance(stdio, MCPStdioClient)
