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
import time
from pathlib import Path

from fastmcp import FastMCP
from mcp_common.server import BaseOneiricServerMixin
from starlette.responses import JSONResponse

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
from cmux_mcp._tools import register_tools


def acquire_pid_file(path: Path) -> None:
    """Acquire a PID file with stale-detection. Refuses if PID is alive.

    Per spec §"Lifecycle → Startup preflight":
      - Read existing PID; if alive (`os.kill(pid, 0)` succeeds), refuse.
      - If dead or missing, overwrite.

    Review finding H10: previous impl used `if path.exists()` then
    `path.read_text()` (TOCTOU race) and only caught ProcessLookupError /
    ValueError. A stale-but-unreadable PID file owned by another user
    raised PermissionError, which was uncaught.
    """
    try:
        existing_pid_text = path.read_text().strip()
    except FileNotFoundError:
        existing_pid_text = ""
    except OSError:
        # Path unreadable (permissions etc.); treat as stale.
        existing_pid_text = ""
    if existing_pid_text:
        try:
            existing_pid = int(existing_pid_text)
            os.kill(existing_pid, 0)
            raise RuntimeError(
                f"PID file {path} is held by live process {existing_pid}"
            )
        except (ProcessLookupError, ValueError, PermissionError):
            # ProcessLookupError: PID dead.
            # ValueError: malformed PID text.
            # PermissionError: PID alive but owned by another user (cannot kill -0).
            # In all three cases, the existing PID is unusable → overwrite.
            try:
                path.unlink()
            except FileNotFoundError:
                pass
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
        # Register /health route. mcp-common's register_http_health_route always
        # returns 200 (it documents the 503 semantic as "reserved for a future
        # /readyz endpoint"), but spec §"/health envelope wiring → HTTP status
        # code" mandates 503 on degraded. We register a custom route that
        # composes the same feed-snapshot body and computes the right code.
        self._health_startup_at = time.monotonic()
        self._register_health_route()

        # Wire all 12 tools onto the FastMCP instance. Per review finding C1
        # (mcp-integration-expert, live-verified): without this call, server
        # startup completes successfully but tools/list returns {"tools":[]}.
        # This call MUST run after transport + tool-feed init (the tools
        # capture the transports and feed components in their closures).
        register_tools(self.mcp, self.socket_transport, self.cli_transport, self._tool_feeds)

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

    def _register_health_route(self) -> None:
        """Register a /health route that returns 200 (healthy) or 503 (degraded).

        Review finding C4: mcp-common's register_http_health_route always
        returns 200. The spec §"/health envelope wiring → HTTP status code"
        mandates:
        - 200 OK if all feeds healthy
        - 503 Service Unavailable if any feed degraded OR a tool feed has
          cycles_total == 0 && errors_total == 0 AND startup was >60s ago

        We register a custom FastMCP route that owns the response shape and
        code, leaving mcp-common's underlying health math (which feed states
        mean "degraded") to the per-feed snapshot.
        """
        from starlette.requests import Request
        config = self.config
        components = self._health_components
        startup_at = self._health_startup_at

        @self.mcp.custom_route("/health", methods=["GET"])
        async def health(_request: Request) -> JSONResponse:
            now = time.monotonic()
            startup_age = now - startup_at

            components_payload: list[dict[str, object]] = []
            any_degraded = False
            any_tool_never_called = False

            for name, comp in components.items():
                snap = comp.snapshot()
                cycles = int(snap.get("cycles_total", 0) or 0)
                errors = int(snap.get("errors_total", 0) or 0)
                # Tool feeds only: never-called past warmup → degraded.
                if (
                    name.startswith("tool.")
                    and cycles == 0
                    and errors == 0
                    and startup_age > config.health_warmup_seconds
                ):
                    any_tool_never_called = True
                # cmux_socket reports a state field; "reconnecting" or
                # "disconnected" → degraded. We treat socket.state !=
                # "connected" as degraded per spec §"HTTP status code".
                if name == "cmux_socket":
                    state = snap.get("state")
                    if state != "connected":
                        any_degraded = True
                components_payload.append(snap)

            degraded = any_degraded or any_tool_never_called
            body = {
                "status": "degraded" if degraded else "ok",
                "service": "cmux-mcp",
                "version": __version__,
                "components": components_payload,
            }
            status_code = 503 if degraded else 200
            return JSONResponse(body, status_code=status_code)


__all__ = ["CmuxMCPServer"]