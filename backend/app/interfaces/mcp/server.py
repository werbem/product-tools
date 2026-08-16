"""MCP Server entrypoint for Competitive Intelligence MCP."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.interfaces.mcp.tools.collect_intelligence_tool import (
    register_collect_intelligence_tool,
)
from app.interfaces.mcp.tools.analyze_competition_tool import (
    register_analyze_competition_tool,
)


SERVER_NAME = "Competitive Intelligence MCP"


def create_mcp_server(name: str = SERVER_NAME) -> FastMCP:
    """Create and configure the Competitive Intelligence MCP server."""

    mcp = FastMCP(name)
    register_collect_intelligence_tool(mcp)
    register_analyze_competition_tool(mcp)
    return mcp


def main() -> None:
    """Run the MCP server using the default transport."""

    create_mcp_server().run(transport="stdio")


if __name__ == "__main__":
    main()
