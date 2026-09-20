"""cmux_mcp.server — CmuxMCPServer(BaseOneiricServerMixin).

Per spec §"Server class":
  - Per-instance FastMCP (not module-level singleton)
  - startup() opens transports, registers /health route, registers tools
  - shutdown() closes transports, captures shutdown snapshot
  - get_app() returns the FastMCP HTTP app
"""
from __future__ import annotations

from fastmcp import FastMCP
from mcp_common.health import register_http_health_route
from mcp_common.server import BaseOneiricServerMixin

from cmux_mcp import __version__
from cmux_mcp.client import CmuxCliTransport, CmuxMockTransport, CmuxSocketTransport
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.health import (
    BrowserCliFeedComponent,
    MockTransportComponent,
    SocketFeedComponent,
    build_tool_feed_components,
)


class CmuxMCPServer(BaseOneiricServerMixin):
    def __init__(self, config: CmuxMCPConfig) -> None:
        self.config = config
        self.mcp = FastMCP(name="cmux-mcp", version=__version__)
        self.socket_transport: CmuxSocketTransport | CmuxMockTransport | None = None
        self.cli_transport: CmuxCliTransport | CmuxMockTransport | None = None

    async def startup(self) -> None:
        """Initialize transports, build feed components, register /health route.

        Tool registration is added in Task 17.
        """
        if self.config.mock_mode:
            self.socket_transport = CmuxMockTransport()
            self.cli_transport = CmuxMockTransport()
        else:
            self.socket_transport = await CmuxSocketTransport.connect(self.config)
            from cmux_mcp.cli_discovery import discover_cmux_cli
            cli_path = self.config.cmux_cli_path or discover_cmux_cli()
            self.cli_transport = CmuxCliTransport(self.config, binary_path=cli_path)

        # Build feed components for /health (per spec §"/health wiring").
        self._tool_feeds = {comp.name: comp for comp in build_tool_feed_components()}
        self._mock_transport_feed = MockTransportComponent()
        self._health_components: dict[str, object] = {
            "cmux_socket": SocketFeedComponent(self.socket_transport),
            "browser_cli": BrowserCliFeedComponent(self.cli_transport),
            "mock_transport": self._mock_transport_feed,
            **self._tool_feeds,
        }

        # Register /health route with all feed components. extra_components takes
        # dicts (each feed's .snapshot() shape) per mcp-common docstring.
        register_http_health_route(
            self.mcp,
            service_name="cmux-mcp",
            version=__version__,
            extra_components=[comp.snapshot() for comp in self._health_components.values()],
        )

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