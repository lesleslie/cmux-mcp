"""cmux_mcp.server — CmuxMCPServer(BaseOneiricServerMixin).

Per spec §"Server class":
  - Per-instance FastMCP (not module-level singleton)
  - startup() opens transports, registers /health route, registers tools
  - shutdown() closes transports, captures shutdown snapshot
  - get_app() returns the FastMCP HTTP app
"""
from __future__ import annotations

import atexit
import os
from pathlib import Path

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
from cmux_mcp.logging_setup import maybe_warn_mock_mode


def acquire_pid_file(path: Path) -> None:
    """Acquire a PID file with stale-detection. Refuses if PID is alive.

    Per spec §"Lifecycle → Startup preflight":
      - Read existing PID; if alive (`os.kill(pid, 0)` succeeds), refuse.
      - If dead or missing, overwrite.
    """
    if path.exists():
        try:
            existing_pid = int(path.read_text().strip())
            os.kill(existing_pid, 0)
            raise RuntimeError(
                f"PID file {path} is held by live process {existing_pid}"
            )
        except (ProcessLookupError, ValueError):
            path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))


def release_pid_file(path: Path) -> None:
    """Release PID file. Idempotent."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass


class CmuxMCPServer(BaseOneiricServerMixin):
    def __init__(self, config: CmuxMCPConfig) -> None:
        self.config = config
        self.mcp = FastMCP(name="cmux-mcp", version=__version__)
        # Per mcp-common's BaseOneiricServerMixin canonical pattern (base.py
        # docstring at line 14-18): initialize the runtime in __init__ so
        # _create_startup_snapshot / _create_shutdown_snapshot have something
        # to call into. runtime.initialize() runs in startup(); cleanup() runs
        # in shutdown().
        self.runtime = self._init_runtime_components("cmux-mcp")
        self.socket_transport: CmuxSocketTransport | CmuxMockTransport | None = None
        self.cli_transport: CmuxCliTransport | CmuxMockTransport | None = None
        # Best-effort PID release on any exit path (per plan §"Stale PID file recovery").
        atexit.register(release_pid_file, config.pid_file_path)

    async def startup(self) -> None:
        """Initialize runtime + transports, build feed components, register /health.

        Tool registration is added in Task 17.
        """
        await self.runtime.initialize()
        maybe_warn_mock_mode(self.config)
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

        await self._create_startup_snapshot(custom_components={
            "cmux_socket": self.socket_transport.state if hasattr(self.socket_transport, "state") else "n/a",
            "cmux_cli": str(getattr(self.cli_transport, "_binary_path", "n/a")),
        })

    async def shutdown(self) -> None:
        if self.cli_transport:
            await self.cli_transport.aclose()
        if self.socket_transport:
            await self.socket_transport.aclose()
        await self._create_shutdown_snapshot()
        await self.runtime.cleanup()

    def get_app(self):  # type: ignore[no-untyped-def]
        return self.mcp.http_app()


__all__ = ["CmuxMCPServer"]