"""cmux_mcp.client — transport implementations.

Per spec §"Architecture" and §"Transport layer details":
  CmuxSocketTransport — long-lived asyncio unix socket, JSON-RPC multiplexed by id
  CmuxCliTransport    — single-shot subprocess, semaphore + per-surface lock
  CmuxMockTransport   — implements both Protocol shapes for test isolation
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import signal as _signal
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import yaml
from oneiric.core.logging import get_logger

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.errors import CmuxProtocolError, CmuxTimeoutError, CmuxTransportError

_LOGGER = get_logger(__name__)


@dataclass
class CliResult:
    """Result envelope for CmuxCliTransport.call."""

    ok: bool
    stdout: bytes
    stderr: bytes
    returncode: int
    duration_ms: int


class CmuxSocketTransportProtocol(Protocol):
    """Long-lived unix-socket JSON-RPC client. Multiplexed by id. Retry-safe."""

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict: ...
    async def aclose(self) -> None: ...
    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]: ...


class CmuxCliTransportProtocol(Protocol):
    """Single-shot subprocess. NOT retry-safe — cmux state already mutated."""

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult: ...
    async def aclose(self) -> None: ...
    @property
    def active_subprocesses(self) -> int: ...


def _match_fixture(entry: dict, method: str, params: dict | None) -> bool:
    if entry["method"] != method:
        return False
    entry_params = entry.get("params") or {}
    if not entry_params:
        return True  # wildcard match
    return entry_params == (params or {})


class CmuxMockTransport:
    """In-process canned responses. Implements BOTH protocol shapes.

    Tool code is identical against real and mock transports because both
    conform to the same Protocol shapes. Per spec decision log row 13.
    """

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path
        self._responses: list[dict] = []
        self._extra_responses: list[dict] = []
        if fixture_path is not None and fixture_path.exists():
            with fixture_path.open() as f:
                self._responses = yaml.safe_load(f) or []
        self._lock = asyncio.Lock()

    def add_response(self, method: str, params: dict | None, response: dict) -> None:
        """Register an extra canned response (per-test override)."""
        self._extra_responses.append(
            {"method": method, "params": params or {}, "response": response}
        )

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        for entry in self._extra_responses + self._responses:
            if _match_fixture(entry, method, params):
                response = entry["response"]
                if "error" in response:
                    raise CmuxProtocolError(
                        response["error"].get("message", "cmux error")
                    )
                # Mirror CmuxSocketTransport.request: return inner `result`, not envelope.
                return response["result"]
        raise CmuxProtocolError(
            f"mock: no canned response for method={method!r} params={params!r}"
        )

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult:
        # Default mock: return ok with empty stdout. Real CmuxCliTransport
        # is added in Task 12.
        return CliResult(
            ok=True,
            stdout=b"",
            stderr=b"",
            returncode=0,
            duration_ms=0,
        )

    async def aclose(self) -> None:
        return None

    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]:
        return "connected"

    @property
    def active_subprocesses(self) -> int:
        return 0


__all__ = [
    "SUBPROCESS_ENV_ALLOWLIST",
    "CliResult",
    "CmuxCliTransport",
    "CmuxCliTransportProtocol",
    "CmuxMockTransport",
    "CmuxSocketTransport",
    "CmuxSocketTransportProtocol",
]


# ---------------------------------------------------------------------------
# CmuxSocketTransport — long-lived unix-socket JSON-RPC client
# ---------------------------------------------------------------------------


class CmuxSocketTransport:
    """Long-lived unix-socket JSON-RPC client. Multiplexed by id.

    Per spec §"CmuxSocketTransport — JSON-RPC client state machine":
      - connect() opens socket, transitions to connected
      - On EOF: reconnect with exponential backoff + jitter
      - After reconnect_max_attempts: transition to disconnected
      - Single asyncio.Lock serializes writes (prevent byte-level interleaving)
      - ID generation: monotonic counter + UUID session epoch (no collision across reconnects)
    """

    def __init__(
        self,
        config: CmuxMCPConfig,
        reader: asyncio.StreamReader | None = None,
        writer: asyncio.StreamWriter | None = None,
    ) -> None:
        self._config = config
        self._reader = reader
        self._writer = writer
        self._state: Literal["connected", "reconnecting", "disconnected"] = (
            "disconnected"
        )
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._session_epoch = str(uuid.uuid4())
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._reader_task: asyncio.Task[None] | None = None
        self._reconnect_task: asyncio.Task[None] | None = None

    @classmethod
    async def connect(cls, config: CmuxMCPConfig) -> CmuxSocketTransport:
        """Open socket; on failure, transition to "reconnecting" with background retry.

        Differs from the plan's strict-raise-on-failure: production cmux-mcp may
        start before the cmux daemon is up. Resilient connect is the safer default.
        """
        transport = cls(config)
        try:
            await transport._open()
        except CmuxTransportError:
            transport._state = "reconnecting"
            transport._reconnect_task = asyncio.create_task(
                transport._reconnect_with_backoff()
            )
        return transport

    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]:
        return self._state

    async def _open(self) -> None:
        """Open socket and start the reader task. Raises CmuxTransportError on failure."""
        try:
            self._reader, self._writer = await asyncio.open_unix_connection(
                str(self._config.socket_path),
            )
        except (OSError, FileNotFoundError) as exc:
            raise CmuxTransportError(
                f"cannot open socket: {exc}",
                context={"socket_path": str(self._config.socket_path)},
            ) from exc
        self._state = "connected"
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Drain incoming JSON-RPC responses, dispatch to pending futures."""
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    raise EOFError("socket closed")
                payload = json.loads(line.decode("utf-8"))
                req_id = payload.get("id")
                if req_id is None:
                    continue
                # id may be int (correlator key) or str (from cmux); coerce.
                try:
                    fut_key = int(req_id)
                except TypeError, ValueError:
                    continue
                fut = self._pending.pop(fut_key, None)
                if fut is not None and not fut.done():
                    if payload.get("ok") is False:
                        fut.set_exception(
                            CmuxProtocolError(
                                payload.get("error", {}).get("message", "cmux error"),
                            )
                        )
                    else:
                        fut.set_result(payload.get("result", {}))
        except EOFError, asyncio.IncompleteReadError, json.JSONDecodeError:
            # Review finding H9: a single corrupt JSON frame from cmux would
            # kill the reader task. EOF + IncompleteReadError + JSONDecodeError
            # all funnel into the same recovery path: reconnect with backoff.
            self._state = "reconnecting"
            await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> None:
        attempt = 0
        while attempt < self._config.reconnect_max_attempts:
            delay = min(
                self._config.reconnect_max_delay_seconds,
                self._config.reconnect_initial_delay_seconds * (2**attempt),
            )
            # Full jitter: random.uniform(0, 1) per AWS Architecture Blog.
            # Real production jitter; tests can override `reconnect_initial_delay_seconds`
            # to make timing deterministic.
            jittered = delay * random.uniform(0.5, 1.0)
            await asyncio.sleep(jittered)
            attempt += 1
            try:
                await self._open()
                return
            except OSError, FileNotFoundError, CmuxTransportError:
                continue
        self._state = "disconnected"

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        """Send JSON-RPC request, await response.

        Returns the inner `result` field, mirroring the cmux wire format.
        Raises CmuxTimeoutError on timeout; CmuxTransportError if socket is
        not connected.
        """
        if self._state != "connected":
            raise CmuxTransportError(
                f"socket state is {self._state!r}, cannot send request"
            )
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {
                "id": str(req_id),
                "method": method,
                "params": params or {},
                "session_epoch": self._session_epoch,
            }
            assert self._writer is not None
            self._writer.write(json.dumps(payload).encode("utf-8") + b"\n")
            await self._writer.drain()
        # Wait for response (outside lock so concurrent requests can interleave writes)
        fut: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
        self._pending[req_id] = fut
        try:
            return await asyncio.wait_for(
                fut,
                timeout=timeout or self._config.socket_short_timeout_seconds,
            )
        except TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise CmuxTimeoutError(f"request timed out: method={method!r}") from exc

    async def aclose(self) -> None:
        """Close writer, cancel reader + reconnect tasks, drain pending futures."""
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CmuxTransportError("transport closed"))
        self._pending.clear()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except ConnectionResetError, OSError, TypeError:
                # asyncio StreamWriter.wait_closed() can raise if the
                # underlying transport is already torn down (peer reset,
                # half-closed socket, etc.) — expected during shutdown.
                # TypeError is also caught because test mocks (MagicMock)
                # don't make `wait_closed` an awaitable; in production this
                # path only fires for actual socket teardown races.
                _LOGGER.debug(
                    "wait_closed on shutdown raised (ignored)",
                    extra={"socket_path": str(self._config.socket_path)},
                )
        self._state = "disconnected"


# ---------------------------------------------------------------------------
# CmuxCliTransport — single-shot subprocess invocation
# ---------------------------------------------------------------------------

# Allowlist for env vars passed to cmux subprocesses. Anything else (e.g.
# MINIMAX_API_KEY, MAHAVISHNU_AUTH_SECRET) is filtered out. Per spec §"Subprocess env".
SUBPROCESS_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "LANG",
        "LC_ALL",
        "LC_COLLATE",
        "LC_CTYPE",
        "LC_MONETARY",
        "LC_NUMERIC",
        "LC_TIME",
        "TMPDIR",
        "USER",
        "HOME",
        "CMUX_SOCKET_PATH",
        "CMUX_SURFACE_ID",
        "CMUX_WORKSPACE_ID",
    }
)


def _filtered_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in SUBPROCESS_ENV_ALLOWLIST}


class CmuxCliTransport:
    """Single-shot subprocess. NOT retry-safe — cmux state already mutated.

    Per spec §"CmuxCliTransport — subprocess management":
      - asyncio.create_subprocess_exec with stdout/stderr PIPEd
      - per-call timeout via asyncio.wait_for(proc.communicate(), timeout=...)
      - SIGTERM (1s grace) then SIGKILL on timeout
      - stderr drained concurrently
      - global asyncio.Semaphore (default 8) caps fan-out
      - per-surface asyncio.Lock serializes same-surface calls
    """

    def __init__(self, config: CmuxMCPConfig, binary_path: str | Path) -> None:
        self._config = config
        self._binary_path = Path(binary_path)
        self._global_sem = asyncio.Semaphore(config.cli_max_concurrent)
        self._surface_locks: dict[str, asyncio.Lock] = {}
        # Review finding H8: track refcount per surface_id so we can drop the
        # asyncio.Lock entry when no in-flight calls reference it. Without
        # this, browser test suites that spawn a fresh surface per navigation
        # balloon _surface_locks unboundedly over the server lifetime.
        self._surface_lock_refs: dict[str, int] = {}
        self._active = 0
        self._active_subprocesses: dict[int, asyncio.subprocess.Process] = {}
        self._subprocess_lock = asyncio.Lock()
        self._lock_lock = asyncio.Lock()
        self._env = _filtered_env()

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult:
        full_args = [str(self._binary_path), *args]
        surface_id = self._extract_surface_id(args)
        # Review finding H7: _active was incremented only on the non-surface path.
        # Move the counter outside the surface_id branch so all in-flight
        # subprocesses (surface-locked or not) feed BrowserCliFeedComponent.active_subprocesses.
        # Review finding H8: acquire surface lock via _surface_lock_for which
        # returns a release token; always call _release_surface_lock in the
        # finally block to drop the refcount (and the lock when zero).
        async with self._global_sem:
            self._active += 1
            try:
                if surface_id:
                    lock, token = await self._surface_lock_for(surface_id)
                    async with lock:
                        try:
                            return await self._invoke(full_args, timeout)
                        finally:
                            await self._release_surface_lock(token)
                return await self._invoke(full_args, timeout)
            finally:
                self._active -= 1

    @staticmethod
    def _extract_surface_id(args: Sequence[str]) -> str | None:
        for i, a in enumerate(args):
            if a == "--surface" and i + 1 < len(args):
                return args[i + 1]
        return None

    async def _surface_lock_for(self, surface_id: str) -> tuple[asyncio.Lock, str]:
        """Return (lock, release_token). Caller MUST call _release_surface_lock(token)
        in a finally block to drop the refcount (and the lock itself when zero).

        Review finding H8: without refcounting, every distinct surface_id
        permanently retains an asyncio.Lock.
        """
        async with self._lock_lock:
            self._surface_lock_refs[surface_id] = (
                self._surface_lock_refs.get(surface_id, 0) + 1
            )
            refcount = self._surface_lock_refs[surface_id]
            lock = self._surface_locks.get(surface_id)
            if lock is None:
                lock = asyncio.Lock()
                self._surface_locks[surface_id] = lock
            return lock, (surface_id, refcount)

    def _release_surface_lock(self, token: tuple[str, int]) -> None:
        """Decrement refcount; drop the asyncio.Lock entry when zero.

        Not async — no I/O. Caller must hold no _lock_lock while calling
        (or re-acquire it; release path runs outside the locked region).
        """
        surface_id, observed_refcount = token

        async def _drop() -> None:
            async with self._lock_lock:
                current = self._surface_lock_refs.get(surface_id, 0)
                if current <= 1:
                    self._surface_locks.pop(surface_id, None)
                    self._surface_lock_refs.pop(surface_id, None)
                elif current != observed_refcount:
                    # Another caller added refs in between; don't drop theirs.
                    pass
                else:
                    self._surface_lock_refs[surface_id] = current - 1

        return _drop()

    async def _invoke(self, full_args: list[str], timeout: float | None) -> CliResult:
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        async with self._subprocess_lock:
            self._active_subprocesses[proc.pid] = proc
        start = time.monotonic()
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self._config.cli_timeout_seconds,
            )
        except TimeoutError as exc:
            raise CmuxTimeoutError(f"cmux CLI timeout: args={full_args!r}") from exc
        finally:
            if proc.returncode is None:
                await self._kill_subprocess(proc)
            async with self._subprocess_lock:
                self._active_subprocesses.pop(proc.pid, None)
        return CliResult(
            ok=proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode or 0,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def _kill_subprocess(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.send_signal(_signal.SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except TimeoutError:
            proc.send_signal(_signal.SIGKILL)
            await proc.wait()

    async def aclose(self) -> None:
        async with self._subprocess_lock:
            procs = list(self._active_subprocesses.values())
        for proc in procs:
            await self._kill_subprocess(proc)
        async with self._subprocess_lock:
            self._active_subprocesses.clear()

    @property
    def active_subprocesses(self) -> int:
        return self._active
