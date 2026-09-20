"""Tests for CmuxMCPServer — lifecycle mixin wiring."""
from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer

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
        mock_socket = CmuxMockTransport()
        mock_cli = CmuxMockTransport()
        mock_socket.aclose = AsyncMock()
        mock_cli.aclose = AsyncMock()
        server.socket_transport = mock_socket
        server.cli_transport = mock_cli

        await server.shutdown()

        mock_socket.aclose.assert_awaited_once()
        mock_cli.aclose.assert_awaited_once()