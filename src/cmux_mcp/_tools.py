"""cmux_mcp._tools — programmatic tool registration.

Per spec §"_tools.py — registration pattern":
  Per-instance FastMCP (in CmuxMCPServer.__init__) means @mcp.tool() decorators
  can't bind at module-load time. Instead, register_tools() registers all 12
  tools programmatically in CmuxMCPServer.startup().

  Each tool body follows the try/except/else/return pattern per spec §"/health
  envelope wiring → Tool feed placement".

FastMCP 3.4+ API used: `FunctionTool.from_function(fn, name=..., description=...,
annotations=ToolAnnotations(...), output_schema=...)` → `mcp.add_tool(tool)`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cmux_mcp.health import TOOL_NAMES

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxCliTransportProtocol, CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def build_tool_feed_components() -> list["ToolFeedComponent"]:
    """Delegate to health.build_tool_feed_components (single source of truth)."""
    from cmux_mcp.health import build_tool_feed_components as _impl
    return _impl()


def register_tools(
    mcp: "FastMCP",
    socket_transport: "CmuxSocketTransportProtocol",
    cli_transport: "CmuxCliTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register all 12 tools on the FastMCP instance. Idempotent."""
    from cmux_mcp.tools.socket_tools import register_socket_tools
    from cmux_mcp.tools.browser_tools import register_browser_tools

    register_socket_tools(mcp, socket_transport, tool_feeds)
    register_browser_tools(mcp, cli_transport, tool_feeds)


__all__ = ["register_tools", "build_tool_feed_components", "TOOL_NAMES"]