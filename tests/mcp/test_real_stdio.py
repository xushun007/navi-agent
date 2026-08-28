from __future__ import annotations

from pathlib import Path
import sys

import pytest

from navi_agent.config import MCPServerSettings
from navi_agent.mcp import MCPStdioClient


pytest.importorskip("mcp")


def test_real_sdk_discovers_and_calls_stdio_server() -> None:
    server = Path(__file__).parent / "fixtures" / "echo_server.py"
    client = MCPStdioClient(
        MCPServerSettings(
            name="echo",
            command=(sys.executable, str(server)),
            environment={},
            startup_timeout_seconds=10,
            tool_timeout_seconds=10,
        )
    )

    try:
        tools = client.start()
        result = client.call_tool("echo", {"text": "hello from Navi"})
    finally:
        client.close()

    assert [tool.name for tool in tools] == ["echo"]
    assert result.is_error is False
    assert result.content == "hello from Navi"
