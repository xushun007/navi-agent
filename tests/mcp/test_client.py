from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from navi_agent.config import MCPServerSettings
from navi_agent.mcp import MCPClientError, MCPStdioClient


@dataclass
class _FakeParameters:
    command: str
    args: list[str]
    env: dict[str, str]


class _FakeClient:
    last_parameters = None
    calls = []

    def __init__(self, parameters) -> None:
        self.parameters = parameters

    async def __aenter__(self):
        type(self).last_parameters = self.parameters
        return self

    async def __aexit__(self, *_args):
        return None

    async def list_tools(self):
        return SimpleNamespace(
            tools=[
                SimpleNamespace(
                    name="read-file",
                    description="Read a file.",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                )
            ]
        )

    async def call_tool(self, name, arguments):
        type(self).calls.append((name, arguments))
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="contents")],
            structured_content={"path": arguments["path"]},
            is_error=False,
        )


def _settings(**overrides) -> MCPServerSettings:
    values = {
        "name": "files",
        "command": ("server", "--root", "."),
        "environment": {"TOKEN": "${MCP_TEST_TOKEN}"},
        "startup_timeout_seconds": 1.0,
        "tool_timeout_seconds": 1.0,
    }
    values.update(overrides)
    return MCPServerSettings(**values)


def _fake_sdk():
    return _FakeClient, _FakeParameters


def test_discovers_and_calls_stdio_tools(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TEST_TOKEN", "secret")
    monkeypatch.setattr("navi_agent.mcp.client._load_sdk", _fake_sdk)
    client = MCPStdioClient(_settings())

    try:
        tools = client.start()
        result = client.call_tool("read-file", {"path": "README.md"})
    finally:
        client.close()

    assert tools[0].name == "read-file"
    assert tools[0].input_schema["properties"]["path"]["type"] == "string"
    assert _FakeClient.last_parameters.command == "server"
    assert _FakeClient.last_parameters.args == ["--root", "."]
    assert _FakeClient.last_parameters.env == {"TOKEN": "secret"}
    assert _FakeClient.calls[-1] == ("read-file", {"path": "README.md"})
    assert result.content == "contents"
    assert result.structured_content == {"path": "README.md"}
    assert result.is_error is False


def test_reports_missing_environment_reference(monkeypatch) -> None:
    monkeypatch.delenv("MCP_MISSING_TOKEN", raising=False)
    monkeypatch.setattr("navi_agent.mcp.client._load_sdk", _fake_sdk)
    client = MCPStdioClient(
        _settings(environment={"TOKEN": "${MCP_MISSING_TOKEN}"})
    )

    with pytest.raises(MCPClientError, match="MCP_MISSING_TOKEN.*not set"):
        client.start()

    client.close()
