import sys

from mcp.server.mcpserver import MCPServer


server = MCPServer("navi-http-test")


@server.tool()
def echo(text: str) -> str:
    """Return the provided text."""
    return text


if __name__ == "__main__":
    server.run(
        "streamable-http",
        host="127.0.0.1",
        port=int(sys.argv[1]),
        streamable_http_path="/mcp",
    )
