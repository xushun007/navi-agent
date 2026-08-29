from __future__ import annotations

from pathlib import Path
import socket
import subprocess
import sys
from time import monotonic, sleep

import pytest

from navi_agent.config import MCPServerSettings
from navi_agent.mcp import MCPHTTPClient


pytest.importorskip("mcp")


def test_real_sdk_discovers_and_calls_streamable_http_server() -> None:
    port = _free_port()
    server = Path(__file__).parent / "fixtures" / "http_echo_server.py"
    process = subprocess.Popen(
        [sys.executable, str(server), str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    client = MCPHTTPClient(
        MCPServerSettings(
            name="echo",
            transport="http",
            url=f"http://127.0.0.1:{port}/mcp",
            startup_timeout_seconds=10,
            tool_timeout_seconds=10,
        )
    )

    try:
        _wait_for_port(port)
        tools = client.start()
        result = client.call_tool("echo", {"text": "hello over HTTP"})
    finally:
        client.close()
        process.terminate()
        process.wait(timeout=5)

    assert [tool.name for tool in tools] == ["echo"]
    assert result.is_error is False
    assert result.content == "hello over HTTP"


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = monotonic() + 10
    while monotonic() < deadline:
        with socket.socket() as connection:
            if connection.connect_ex(("127.0.0.1", port)) == 0:
                return
        sleep(0.05)
    raise TimeoutError("MCP HTTP test server did not start")
