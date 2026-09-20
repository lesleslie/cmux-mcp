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
    async def test_register_tools_registers_socket_set(self) -> None:
        """Task 18: 5 socket tools registered. Tasks 19-22 fill in 7 browser tools (12 total)."""
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        # FastMCP 3.x: mcp._tool_manager doesn't exist (removed in 3.x). Use
        # mcp.list_tools() (async) to introspect registered tools.
        tools = list(await mcp.list_tools())
        assert len(tools) == 5, "expected 5 socket tools"
        names = {t.name for t in tools}
        assert "cmux_list_workspaces" in names