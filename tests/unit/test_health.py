"""Tests for cmux_mcp/health.py — /health feed components."""

from __future__ import annotations

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.health import (
    BrowserCliFeedComponent,
    MockTransportComponent,
    SocketFeedComponent,
    ToolFeedComponent,
    build_tool_feed_components,
)


@pytest.mark.unit
class TestHealthComponents:
    def test_socket_feed_reports_connected_state(self) -> None:
        transport = CmuxMockTransport()
        comp = SocketFeedComponent(transport)
        assert comp.name == "cmux_socket"
        snapshot = comp.snapshot()
        assert "state" in snapshot
        assert snapshot["state"] == "connected"

    def test_browser_cli_feed_reports_zero_active(self) -> None:
        transport = CmuxMockTransport()
        comp = BrowserCliFeedComponent(transport)
        snapshot = comp.snapshot()
        assert snapshot["active_subprocesses"] == 0

    def test_mock_transport_component_separate(self) -> None:
        comp = MockTransportComponent()
        snapshot = comp.snapshot()
        assert comp.name == "mock_transport"
        assert snapshot["cycles_total"] == 0

    def test_tool_feed_records_cycle_success_error(self) -> None:
        comp = ToolFeedComponent(name="tool.cmux_list_workspaces")
        comp.record_cycle()
        comp.record_success()
        snapshot = comp.snapshot()
        assert snapshot["cycles_total"] == 1
        assert snapshot["errors_total"] == 0

    def test_tool_feed_records_error(self) -> None:
        comp = ToolFeedComponent(name="tool.cmux_browser_click")
        comp.record_cycle()
        comp.record_error()
        snapshot = comp.snapshot()
        assert snapshot["errors_total"] == 1

    def test_tool_feed_started_at_set_on_first_cycle(self) -> None:
        comp = ToolFeedComponent(name="tool.test")
        assert comp.started_at is None
        comp.record_cycle()
        assert comp.started_at is not None

    def test_build_tool_feed_components_has_12(self) -> None:
        feeds = build_tool_feed_components()
        assert len(feeds) == 12
        names = {f.name for f in feeds}
        expected = {
            "tool.cmux_list_workspaces",
            "tool.cmux_list_notifications",
            "tool.cmux_identify",
            "tool.cmux_send_keys",
            "tool.cmux_notify",
            "tool.cmux_browser_navigate",
            "tool.cmux_browser_snapshot",
            "tool.cmux_browser_evaluate",
            "tool.cmux_browser_click",
            "tool.cmux_browser_type",
            "tool.cmux_browser_tabs",
            "tool.cmux_browser_console",
        }
        assert names == expected
