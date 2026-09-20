"""cmux_mcp.client — transport implementations.

Per spec §"Architecture" and §"Transport layer details":
  CmuxSocketTransport — long-lived asyncio unix socket, JSON-RPC multiplexed by id
  CmuxCliTransport    — single-shot subprocess, semaphore + per-surface lock
  CmuxMockTransport   — implements both Protocol shapes for test isolation
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, Sequence

import yaml

from cmux_mcp.errors import CmuxProtocolError


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
        self._extra_responses.append({"method": method, "params": params or {}, "response": response})

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
                    raise CmuxProtocolError(response["error"].get("message", "cmux error"))
                # Mirror CmuxSocketTransport.request: return inner `result`, not envelope.
                return response["result"]
        raise CmuxProtocolError(f"mock: no canned response for method={method!r} params={params!r}")

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
    "CliResult",
    "CmuxSocketTransportProtocol",
    "CmuxCliTransportProtocol",
    "CmuxMockTransport",
]