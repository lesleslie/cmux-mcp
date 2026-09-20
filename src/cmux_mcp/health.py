"""cmux_mcp.health — /health feed components using mcp-common's HealthFeedState.

Per spec §"/health envelope wiring":
  - Per-transport feed components (SocketFeedComponent, BrowserCliFeedComponent, MockTransportComponent)
  - Per-tool feed components (one ToolFeedComponent per tool)
  - Each carries the four signals: entities_count, last_updated_timestamp, errors_total, cycles_total
  - HTTP 503 if any feed degraded after health_warmup_seconds

Wraps mcp-common's HealthFeedState with thin wrappers for the cycle/success/error
ergonomics tools need (mcp-common's record_success / record_error are mutator
helpers that don't track cycles_total or errors_total — per docstring, the caller
is responsible for those counters).
"""
from __future__ import annotations

import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from mcp_common.health.feed import HealthFeedState, record_error as _mcp_record_error
from mcp_common.health.feed import record_success as _mcp_record_success

if TYPE_CHECKING:
    from cmux_mcp.client import CmuxCliTransport, CmuxSocketTransport


class _Feed:
    """Base /health component wrapping mcp-common's HealthFeedState.

    Adds a wrapper-level `started_at` (set on first record_cycle) so tools
    can implement the warm-up gate without reaching into HealthFeedState
    internals. mcp-common's `record_success`/`record_error` are called here
    with the underlying state for the cross-feed aggregator.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.state = HealthFeedState()
        self.started_at: float | None = None

    def record_cycle(self) -> None:
        self.state.cycles_total += 1
        self.state.last_updated_timestamp = time.time()
        if self.started_at is None:
            self.started_at = self.state.last_updated_timestamp

    def record_success(self) -> None:
        _mcp_record_success(self.state)

    def record_error(self) -> None:
        # Caller-side counter (mcp-common's record_error doesn't bump errors_total).
        self.state.errors_total += 1
        _mcp_record_error(self.state)

    def snapshot(self) -> dict[str, Any]:
        return {"name": self.name, **asdict(self.state)}


class SocketFeedComponent(_Feed):
    def __init__(self, transport: "CmuxSocketTransport") -> None:
        super().__init__(name="cmux_socket")
        self._transport = transport

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["state"] = self._transport.state
        return snap


class BrowserCliFeedComponent(_Feed):
    def __init__(self, transport: "CmuxCliTransport") -> None:
        super().__init__(name="browser_cli")
        self._transport = transport

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["active_subprocesses"] = self._transport.active_subprocesses
        return snap


class MockTransportComponent(_Feed):
    def __init__(self) -> None:
        super().__init__(name="mock_transport")


class ToolFeedComponent(_Feed):
    pass


TOOL_NAMES = [
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
]


def build_tool_feed_components() -> list[ToolFeedComponent]:
    """Returns one ToolFeedComponent per registered tool."""
    return [ToolFeedComponent(name=f"tool.{name}") for name in TOOL_NAMES]


__all__ = [
    "TOOL_NAMES",
    "ToolFeedComponent",
    "SocketFeedComponent",
    "BrowserCliFeedComponent",
    "MockTransportComponent",
    "build_tool_feed_components",
]