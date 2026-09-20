"""cmux-mcp entry point."""
from __future__ import annotations

from mcp_common.cli import MCPServerCLIFactory

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer


def main() -> None:
    """Entry point for `cmux-mcp` console script."""
    factory = MCPServerCLIFactory.create_server_cli(
        server_class=CmuxMCPServer,
        config_class=CmuxMCPConfig,
        name="cmux-mcp",
        description="MCP server for cmux terminal automation (macOS only).",
    )
    app = factory.create_app()
    app()


if __name__ == "__main__":
    main()