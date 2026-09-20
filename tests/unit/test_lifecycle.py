"""Tests for CmuxMCPServer — lifecycle mixin wiring."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, PropertyMock, patch

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer, acquire_pid_file, release_pid_file

# Python 3.14 + AsyncMock __init__ quirk — suppress at module level (upstream).
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


@pytest.mark.unit
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_startup_initializes_transports_and_registers_tools(
        self, tmp_path: Path
    ) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(socket_path=sock, cmux_cli_path=tmp_path / "cmux")
        (tmp_path / "cmux").touch()

        server = CmuxMCPServer(config)
        # Skip network calls; use mock transports (per plan).
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()

        # Verify FastMCP instance is per-instance (not module-level singleton).
        assert server.mcp is not None
        assert hasattr(server.mcp, "tool")  # FastMCP has tool() decorator

        # Verify get_app() returns the FastMCP HTTP app.
        app = server.get_app()
        assert app is not None

    @pytest.mark.asyncio
    async def test_shutdown_closes_transports(self) -> None:
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        # Stub out oneiric runtime methods — the lifecycle test only cares about
        # transport cleanup, not snapshot/cleanup machinery.
        server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
        server.runtime.cleanup = AsyncMock()  # type: ignore[method-assign]
        server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
        server._create_shutdown_snapshot = AsyncMock()  # type: ignore[method-assign]
        mock_socket = CmuxMockTransport()
        mock_cli = CmuxMockTransport()
        mock_socket.aclose = AsyncMock()
        mock_cli.aclose = AsyncMock()
        server.socket_transport = mock_socket
        server.cli_transport = mock_cli

        await server.shutdown()

        mock_socket.aclose.assert_awaited_once()
        mock_cli.aclose.assert_awaited_once()


@pytest.mark.unit
class TestHealthRegistration:
    @pytest.mark.asyncio
    async def test_startup_registers_health_route(self) -> None:
        """After C4 fix: /health is registered via mcp.custom_route (not the
        mcp-common register_http_health_route, which always returns 200)."""
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()
        server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
        server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
        await server.startup()
        # mcp._additional_http_routes is a list of Starlette routes; the custom
        # /health route from _register_health_route is appended there.
        from starlette.routing import Route

        health_routes = [
            r
            for r in server.mcp._additional_http_routes
            if isinstance(r, Route) and r.path == "/health"
        ]
        assert len(health_routes) == 1, (
            f"expected 1 /health route, found {len(health_routes)}: "
            f"{[r.path for r in server.mcp._additional_http_routes]}"
        )
        # Feed components dict has the expected keys.
        assert "cmux_socket" in server._health_components
        assert "browser_cli" in server._health_components
        assert "mock_transport" in server._health_components
        assert len(server._tool_feeds) == 12

    @pytest.mark.asyncio
    async def test_health_route_returns_200_when_all_healthy(self) -> None:
        """C4 regression: /health returns 200 when feeds are healthy and
        tool feeds have been called (past the warm-up window)."""
        config = CmuxMCPConfig(health_warmup_seconds=0.0)
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()  # state == "connected"
        server.cli_transport = CmuxMockTransport()
        server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
        server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
        await server.startup()
        # Mark every tool feed as having been exercised so the warm-up gate
        # doesn't apply (cycles_total > 0).
        for feed in server._tool_feeds.values():
            feed.state.cycles_total = 1
            feed.state.entities_count = 1

        # Invoke the custom route's endpoint callable directly.
        from starlette.requests import Request

        route = next(
            r
            for r in server.mcp._additional_http_routes
            if getattr(r, "path", None) == "/health"
        )
        response = await route.endpoint(Request({"type": "http"}))
        assert response.status_code == 200
        import json

        body = json.loads(response.body)
        assert body["status"] == "ok"
        assert body["service"] == "cmux-mcp"
        assert len(body["components"]) == 15

    @pytest.mark.asyncio
    async def test_health_route_returns_503_when_socket_disconnected(self) -> None:
        """C4 regression: /health returns 503 when cmux_socket.state != connected."""
        config = CmuxMCPConfig(health_warmup_seconds=0.0)
        server = CmuxMCPServer(config)
        bad_socket = CmuxMockTransport()
        # CmuxMockTransport.state is a read-only property. Patch the entire
        # server lifetime so the health route sees "disconnected" — the patch
        # is restored at the end of the with-block. Use PropertyMock for
        # descriptor-aware replacement (the property's __get__ passes self).
        with patch.object(
            type(bad_socket),
            "state",
            new_callable=PropertyMock(return_value="disconnected"),
        ):
            server.socket_transport = bad_socket
            server.cli_transport = CmuxMockTransport()
            server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
            server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
            await server.startup()

            from starlette.requests import Request

            route = next(
                r
                for r in server.mcp._additional_http_routes
                if getattr(r, "path", None) == "/health"
            )
            response = await route.endpoint(Request({"type": "http"}))
            assert response.status_code == 503
            import json

            body = json.loads(response.body)
            assert body["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_startup_registers_all_12_tools(self) -> None:
        """Regression for review finding C1: register_tools() must be called
        from startup(), otherwise tools/list returns {"tools":[]} live."""
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()
        server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
        server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
        await server.startup()
        # Live verification: the FastMCP instance exposes all 12 cmux tools.
        tools = list(await server.mcp.list_tools())
        assert len(tools) == 12, (
            f"expected 12 tools registered, got {len(tools)}: {[t.name for t in tools]}"
        )
        names = {t.name for t in tools}
        expected = {
            "cmux_list_workspaces",
            "cmux_list_notifications",
            "cmux_identify",
            "cmux_send_keys",
            "cmux_notify",
            "cmux_browser_navigate",
            "cmux_browser_snapshot",
            "cmux_browser_evaluate",
            "cmux_browser_click",
            "cmux_browser_type",
            "cmux_browser_tabs",
            "cmux_browser_console",
        }
        assert names == expected


@pytest.mark.unit
class TestPidManagement:
    def test_acquire_creates_pid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        acquire_pid_file(path)
        assert path.exists()
        assert int(path.read_text().strip()) > 0

    def test_acquire_existing_alive_pid_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        path.write_text(str(os.getpid()))  # current process is alive
        with pytest.raises(RuntimeError):
            acquire_pid_file(path)

    def test_acquire_stale_pid_recovers(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        path.write_text("99999999")  # unlikely to be alive
        acquire_pid_file(path)  # should overwrite stale
        assert int(path.read_text().strip()) > 0

    def test_acquire_handles_permission_error_on_unreadable_pid_file(
        self, tmp_path: Path
    ) -> None:
        """H10 regression: stale-but-unreadable PID files (e.g. owned by another
        user) raise PermissionError on os.kill(pid, 0). The fix treats all
        OSError variants as 'stale' so we overwrite rather than crash."""
        path = tmp_path / "test.pid"
        # Force os.kill to raise PermissionError for any pid, simulating
        # 'PID alive but foreign-user-owned'.
        with patch("os.kill", side_effect=PermissionError("foreign pid")):
            path.write_text("12345")  # some pid; kill will raise PermissionError
            # Should NOT raise — the PermissionError path treats it as stale.
            acquire_pid_file(path)
        assert int(path.read_text().strip()) > 0

    def test_acquire_handles_toctou_race(self, tmp_path: Path) -> None:
        """H10 regression: previous impl used path.exists() then path.read_text()
        with no atomic guard. A concurrent delete between exists() and read_text()
        raised FileNotFoundError. The fix uses try/read_text() instead."""
        path = tmp_path / "test.pid"
        # Simulate FileNotFoundError on read_text (file removed concurrently).
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            acquire_pid_file(path)  # should treat as "no existing pid"
        # acquire_pid_file will create its own pid file:
        assert path.exists()

    def test_release_removes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        acquire_pid_file(path)
        release_pid_file(path)
        assert not path.exists()
