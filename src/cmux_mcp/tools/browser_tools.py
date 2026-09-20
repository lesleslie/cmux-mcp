"""cmux_mcp.tools.browser_tools — registers the 7 browser CLI tools.

Tasks 19-22 fill in the actual implementations.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxCliTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def register_browser_tools(
    mcp: "FastMCP",
    cli: "CmuxCliTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """No-op for Task 17. Browser tools implemented in Tasks 19-22."""
    return None