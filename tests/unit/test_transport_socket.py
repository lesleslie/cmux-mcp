"""Tests for CmuxSocketTransport — connection + state machine."""
from __future__ import annotations

import asyncio
import json
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


@pytest.mark.unit
class TestJsonRpcCorrelation:
    @pytest.mark.asyncio
    async def test_concurrent_requests_get_correct_responses(self) -> None:
        """Multiplexing: two requests in flight get responses matched by id."""
        config = CmuxMCPConfig()
        # Event-gated readline mimics real StreamReader.readline() semantics:
        # blocks until data is available, instead of returning b"" (which would
        # trigger the reader's EOF/reconnect path before any request is sent).
        response_ready = asyncio.Event()
        lines_received: list[str] = []

        async def readline() -> bytes:
            # Loop until a line is available. Clear the event after waking
            # so the next readline() blocks again — Event is sticky by default.
            while not lines_received:
                await response_ready.wait()
                response_ready.clear()
            return lines_received.pop(0).encode("utf-8") + b"\n"

        async def async_drain() -> None:
            return None

        mock_reader = MagicMock()
        mock_reader.readline = readline

        # Capture outgoing requests and queue matching canned responses.
        canned_responses = {
            "1": {"id": "1", "ok": True, "result": {"workspaces": [{"id": "ws:1"}]}},
            "2": {"id": "2", "ok": True, "result": {"pong": True}},
        }

        def write(payload: bytes) -> None:
            decoded = json.loads(payload.decode("utf-8"))
            lines_received.append(json.dumps(canned_responses[str(decoded["id"])]))
            response_ready.set()

        mock_writer = MagicMock()
        mock_writer.write = write
        mock_writer.drain = async_drain

        async def fake_open(*_args: object, **_kwargs: object) -> tuple[MagicMock, MagicMock]:
            return (mock_reader, mock_writer)

        with patch("asyncio.open_unix_connection", side_effect=fake_open):
            transport = await CmuxSocketTransport.connect(config)

        # Issue two concurrent requests — their responses must be matched by id.
        result_a, result_b = await asyncio.gather(
            transport.request("workspace.list"),
            transport.request("system.ping"),
        )
        assert result_a == {"workspaces": [{"id": "ws:1"}]}
        assert result_b == {"pong": True}

        # Cancel the background reader task so it stops blocking on readline().
        # Without this, the reader keeps running after gather() returns and
        # pops past the end of lines_received, raising IndexError in a
        # task exception that pytest logs as noise.
        await transport.aclose()