"""cmux_mcp.server — CmuxMCPServer(BaseOneiricServerMixin).

Per spec §"Server class":
  - Per-instance FastMCP (not module-level singleton)
  - startup() opens transports, registers tools, calls register_http_health_route
  - shutdown() closes transports, captures shutdown snapshot
  - get_app() returns the FastMCP HTTP app
"""
from __future__ import annotations

from fastmcp import FastMCP
from mcp_common.server import BaseOneiricServerMixin

from cmux_mcp import __version__
from cmux_mcp.client import CmuxCliTransport, CmuxMockTransport, CmuxSocketTransport
from cmux_mcp.config import CmuxMCPConfig


class CmuxMCPServer(BaseOneiricServerMixin):
    def __init__(self, config: CmuxMCPConfig) -> None:
        self.config = config
        self.mcp = FastMCP(name="cmux-mcp", version=__version__)
        self.socket_transport: CmuxSocketTransport | CmuxMockTransport | None = None
        self.cli_transport: CmuxCliTransport | CmuxMockTransport | None = None

    async def startup(self) -> None:
        """Initialize transports. /health wiring + tool registration added in Tasks 16/17."""
        if self.config.mock_mode:
            self.socket_transport = CmuxMockTransport()
            self.cli_transport = CmuxMockTransport()
        else:
            self.socket_transport = await CmuxSocketTransport.connect(self.config)
            from cmux_mcp.cli_discovery import discover_cmux_cli
            cli_path = self.config.cmux_cli_path or discover_cmux_cli()
            self.cli_transport = CmuxCliTransport(self.config, binary_path=cli_path)
        self._create_startup_snapshot(custom_components={
            "cmux_socket": self.socket_transport.state if hasattr(self.socket_transport, "state") else "n/a",
            "cmux_cli": str(getattr(self.cli_transport, "_binary_path", "n/a")),
        })

    async def shutdown(self) -> None:
        if self.cli_transport:
            await self.cli_transport.aclose()
        if self.socket_transport:
            await self.socket_transport.aclose()
        self._create_shutdown_snapshot()

    def get_app(self):  # type: ignore[no-untyped-def]
        return self.mcp.http_app()


__all__ = ["CmuxMCPServer"]