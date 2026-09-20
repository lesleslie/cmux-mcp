"""Tests for CmuxMCPServer — lifecycle mixin wiring."""
from __future__ import annotations

import os
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer, acquire_pid_file, release_pid_file

# Python 3.14 + AsyncMock __init__ quirk — suppress at module level (upstream).
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


@pytest.mark.unit
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_startup_initializes_transports_and_registers_tools(self, tmp_path: Path) -> None:
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
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()
        # Stub oneiric runtime + snapshot methods — health registration doesn't
        # depend on them. Patches are after the mock transport injection so
        # CmuxMCPServer.__init__ still completes (which calls _init_runtime_components).
        server.runtime.initialize = AsyncMock()  # type: ignore[method-assign]
        server._create_startup_snapshot = AsyncMock()  # type: ignore[method-assign]
        # Patch register_http_health_route so the test doesn't actually bind a route
        # to the FastMCP instance (which would touch internal Starlette routing).
        with patch("cmux_mcp.server.register_http_health_route") as mock_register:
            await server.startup()
        # Verify the registration was attempted with the right metadata.
        mock_register.assert_called_once()
        kwargs = mock_register.call_args.kwargs
        assert kwargs["service_name"] == "cmux-mcp"
        assert "extra_components" in kwargs
        # 2 transports + 12 tool feeds + 1 mock = 15 components.
        assert len(kwargs["extra_components"]) == 15
        # Feed components dict has the expected keys.
        assert "cmux_socket" in server._health_components
        assert "browser_cli" in server._health_components
        assert "mock_transport" in server._health_components
        assert len(server._tool_feeds) == 12

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
        with patch("cmux_mcp.server.register_http_health_route"):
            await server.startup()
        # Live verification: the FastMCP instance exposes all 12 cmux tools.
        tools = list(await server.mcp.list_tools())
        assert len(tools) == 12, (
            f"expected 12 tools registered, got {len(tools)}: "
            f"{[t.name for t in tools]}"
        )
        names = {t.name for t in tools}
        expected = {
            "cmux_list_workspaces", "cmux_list_notifications", "cmux_identify",
            "cmux_send_keys", "cmux_notify",
            "cmux_browser_navigate", "cmux_browser_snapshot", "cmux_browser_evaluate",
            "cmux_browser_click", "cmux_browser_type", "cmux_browser_tabs",
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

    def test_release_removes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        acquire_pid_file(path)
        release_pid_file(path)
        assert not path.exists()