from mcp.server.mcpserver import MCPServer


server = MCPServer("navi-test")


@server.tool()
def echo(text: str) -> str:
    """Return the provided text."""
    return text


if __name__ == "__main__":
    server.run()
