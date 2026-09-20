"""Tests for cmux_mcp/_tools.py — programmatic tool registration.

Per plan: Task 17 registers 1 stub tool as proof of wiring. Task 18
registers the remaining 4 socket tools (5 total). Tasks 19-22 register
the 7 browser tools (12 total). Test assertions bump in lockstep.
"""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from cmux_mcp._tools import TOOL_NAMES, build_tool_feed_components, register_tools
from cmux_mcp.client import CmuxMockTransport


@pytest.mark.unit
class TestToolRegistration:
    def test_tool_names_has_12(self) -> None:
        assert len(TOOL_NAMES) == 12

    def test_build_tool_feed_components_has_12(self) -> None:
        feeds = build_tool_feed_components()
        assert len(feeds) == 12

    @pytest.mark.asyncio
    async def test_register_tools_registers_all_12(self) -> None:
        """All 12 tools registered (Tasks 17-22)."""
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        # FastMCP 3.x: mcp._tool_manager doesn't exist (removed in 3.x). Use
        # mcp.list_tools() (async) to introspect registered tools.
        tools = list(await mcp.list_tools())
        assert len(tools) == 12
        names = {t.name for t in tools}
        expected = {
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
        }
        assert names == expected
