"""Tests for CmuxSocketTransport — connection + state machine."""
from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cmux_mcp.client import CmuxSocketTransport
from cmux_mcp.config import CmuxMCPConfig

# Python 3.14 + AsyncMock __init__ always creates an internal coroutine that's
# never awaited, surfacing as a RuntimeWarning. Py3.13 didn't warn; this is
# upstream and not a cmux-mcp bug. Suppress at module level.
pytestmark = pytest.mark.filterwarnings(
    "ignore::RuntimeWarning",
)


@pytest.mark.unit
class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect_starts_in_connected_state(self, tmp_path: Path) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(socket_path=sock)
        with patch("asyncio.open_unix_connection", new_callable=AsyncMock) as mock_conn:
            mock_reader = AsyncMock()
            mock_writer = AsyncMock()
            mock_conn.return_value = (mock_reader, mock_writer)
            transport = await CmuxSocketTransport.connect(config)
        assert transport.state == "connected"

    @pytest.mark.asyncio
    async def test_aclose_closes_writer(self) -> None:
        config = CmuxMCPConfig()
        # mock_reader is unused by the transport after connect(); MagicMock avoids
        # AsyncMock's "coroutine never awaited" warning on __init__.
        mock_reader = MagicMock()
        # StreamWriter: close() is sync; drain/wait_closed are async.
        mock_writer = MagicMock()
        mock_writer.drain = AsyncMock()
        mock_writer.wait_closed = AsyncMock()

        async def fake_open(*_args: object, **_kwargs: object) -> tuple[MagicMock, MagicMock]:
            return (mock_reader, mock_writer)

        with patch("asyncio.open_unix_connection", side_effect=fake_open):
            transport = await CmuxSocketTransport.connect(config)
        await transport.aclose()
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()


@pytest.mark.unit
class TestReconnectBackoff:
    @pytest.mark.asyncio
    async def test_eof_triggers_reconnect_with_backoff(self, tmp_path: Path) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(
            socket_path=sock,
            reconnect_initial_delay_seconds=0.01,
            reconnect_max_attempts=2,
        )
        # Initial connect() succeeds (returns transport even though _open fails);
        # backoff loop eventually gives up → state = "disconnected".
        with patch("asyncio.open_unix_connection", side_effect=OSError("socket gone")):
            transport = await CmuxSocketTransport.connect(config)
        await asyncio.sleep(0.5)
        assert transport.state == "disconnected"