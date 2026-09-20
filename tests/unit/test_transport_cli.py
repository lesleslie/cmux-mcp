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
            # After C2 fix: _invoke's finally-block checks proc.returncode to decide
            # whether to kill. Simulate "still running" by setting it to None.
            mock_proc.returncode = None
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


@pytest.mark.unit
class TestPerSurfaceLock:
    @pytest.mark.asyncio
    async def test_same_surface_calls_serialized(self) -> None:
        """Two concurrent calls on the same surface must serialize via per-surface lock."""
        config = CmuxMCPConfig(cli_max_concurrent=8)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        order: list[str] = []

        # Patch _invoke so call()'s per-surface lock still applies. Identify
        # each call by its surface_id (args[3] in the original positional layout).
        async def tracking_invoke(args: list[str], *_a: object, **_kw: object) -> CliResult:
            surface_id = CmuxCliTransport._extract_surface_id(args) or "?"
            order.append(f"start:{surface_id}")
            await asyncio.sleep(0.05)
            order.append(f"end:{surface_id}")
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport._invoke = tracking_invoke  # type: ignore[method-assign]
        await asyncio.gather(
            transport.call(["cmux", "browser", "--surface", "surface:abc", "navigate", "u1"]),
            transport.call(["cmux", "browser", "--surface", "surface:abc", "click", "e1"]),
        )
        # Same surface: must be start,end,start,end (not interleaved)
        assert order == [
            "start:surface:abc", "end:surface:abc",
            "start:surface:abc", "end:surface:abc",
        ], f"Expected serialized execution; got {order}"

    @pytest.mark.asyncio
    async def test_different_surfaces_can_run_in_parallel(self) -> None:
        """Two concurrent calls on different surfaces must run in parallel."""
        config = CmuxMCPConfig(cli_max_concurrent=8)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        order: list[str] = []

        async def tracking_invoke(args: list[str], *_a: object, **_kw: object) -> CliResult:
            surface_id = CmuxCliTransport._extract_surface_id(args) or "?"
            order.append(f"start:{surface_id}")
            await asyncio.sleep(0.05)
            order.append(f"end:{surface_id}")
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport._invoke = tracking_invoke  # type: ignore[method-assign]
        await asyncio.gather(
            transport.call(["cmux", "browser", "--surface", "surface:abc", "navigate", "u1"]),
            transport.call(["cmux", "browser", "--surface", "surface:xyz", "navigate", "u2"]),
        )
        # Different surfaces: must be interleaved (both starts before either end)
        starts = sum(1 for e in order if e.startswith("start:"))
        ends_before_any_start = sum(1 for i, e in enumerate(order) if e.startswith("end:") and i < 2)
        assert starts == 2 and ends_before_any_start == 0, (
            f"Expected parallel execution; got {order}"
        )


@pytest.mark.unit
class TestSubprocessLifecycle:
    """Regression tests for review findings C2 (subprocess leak on cancellation)
    and C3 (aclose() no-op)."""

    @pytest.mark.asyncio
    async def test_cancellation_kills_subprocess(self) -> None:
        """C2 regression: cancelling the awaiting task must kill the subprocess.

        Without the finally-block in _invoke, CancelledError propagates and
        the child cmux process is orphaned (Python 3.14 does NOT auto-kill
        subprocesses when the awaiting coroutine is cancelled).
        """
        config = CmuxMCPConfig(cli_timeout_seconds=30.0)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.pid = 12345

            async def hanging_communicate() -> tuple[bytes, bytes]:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    raise
                return (b"", b"")

            mock_proc.communicate = hanging_communicate
            mock_proc.send_signal = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_proc.returncode = None  # still running at cancellation time

            mock_exec.return_value = mock_proc

            async def run_call():
                await transport.call(["cmux", "--slow-op"])

            task = asyncio.create_task(run_call())
            await asyncio.sleep(0.05)  # let _invoke reach the await
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        # _invoke's finally-block ran: SIGTERM (or SIGKILL after grace).
        assert mock_proc.send_signal.call_count >= 1

    @pytest.mark.asyncio
    async def test_aclose_kills_active_subprocesses(self) -> None:
        """C3 regression: aclose() must terminate in-flight subprocesses."""
        config = CmuxMCPConfig(cli_timeout_seconds=30.0)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = MagicMock()
            mock_proc.pid = 99999

            async def hanging_communicate() -> tuple[bytes, bytes]:
                try:
                    await asyncio.sleep(30)
                except asyncio.CancelledError:
                    raise
                return (b"", b"")

            mock_proc.communicate = hanging_communicate
            mock_proc.send_signal = MagicMock()
            mock_proc.wait = AsyncMock()
            mock_proc.returncode = None

            mock_exec.return_value = mock_proc

            # Fire a call in the background, don't await it.
            async def run_call():
                await transport.call(["cmux", "--slow-op"])

            task = asyncio.create_task(run_call())
            await asyncio.sleep(0.05)  # let _invoke reach the await

            # aclose() must terminate the still-running subprocess.
            await transport.aclose()
            assert mock_proc.send_signal.call_count >= 1

            # Cancel the orphaned task (it's been killed but its CancelledError
            # hasn't been awaited).
            task.cancel()
            with pytest.raises((asyncio.CancelledError, Exception)):
                await task