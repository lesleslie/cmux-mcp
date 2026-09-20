"""Tests for CmuxCliTransport — subprocess invocation + timeout + cleanup."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cmux_mcp.client import CliResult, CmuxCliTransport
from cmux_mcp.config import CmuxMCPConfig

# Python 3.14 + AsyncMock __init__ creates an internal coroutine Py3.14 surfaces
# as RuntimeWarning. Suppress at module level (upstream Python issue, not cmux-mcp).
pytestmark = pytest.mark.filterwarnings("ignore::RuntimeWarning")


@pytest.mark.unit
class TestSubprocessInvocation:
    @pytest.mark.asyncio
    async def test_call_returns_cli_result(self) -> None:
        config = CmuxMCPConfig()
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            result = await transport.call(["cmux", "--version"])
        assert isinstance(result, CliResult)
        assert result.ok is True
        assert result.stdout == b"hello\n"

    @pytest.mark.asyncio
    async def test_call_timeout_kills_subprocess(self) -> None:
        config = CmuxMCPConfig(cli_timeout_seconds=0.1)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()  # send_signal/wait are sync in production

            async def hanging_communicate() -> tuple[bytes, bytes]:
                await asyncio.sleep(5)
                return (b"", b"")

            mock_proc.communicate = hanging_communicate
            mock_proc.send_signal = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            with pytest.raises(Exception):  # CmuxTimeoutError
                await transport.call(["cmux", "--slow-op"])
        mock_proc.send_signal.assert_called()  # SIGTERM sent


@pytest.mark.unit
class TestConcurrencyLimits:
    @pytest.mark.asyncio
    async def test_global_semaphore_caps_fanout(self) -> None:
        """10 concurrent calls must serialize through semaphore(2) — max 2 in flight."""
        config = CmuxMCPConfig(cli_max_concurrent=2)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        active = 0
        max_active = 0
        counter_lock = asyncio.Lock()

        # Patch _invoke (NOT call) so call()'s semaphore still serializes entries.
        # The plan's version patched transport.call, which bypassed the semaphore
        # entirely — the test would have passed only because fake_call didn't
        # actually sleep, allowing 10 to increment active simultaneously.
        async def counting_invoke(*_args: object, **_kwargs: object) -> CliResult:
            nonlocal active, max_active
            async with counter_lock:
                active += 1
                max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            async with counter_lock:
                active -= 1
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport._invoke = counting_invoke  # type: ignore[method-assign]
        await asyncio.gather(*[transport.call(["cmux"]) for _ in range(10)])
        assert max_active == 2