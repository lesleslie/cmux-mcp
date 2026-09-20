"""cmux_mcp.tools.socket_tools — registers the 5 socket-direct tools.

Task 17 registers a single stub (`cmux_list_workspaces`) as proof of wiring.
Task 18 fills in the remaining 4 socket tools.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from cmux_mcp.models import ListWorkspacesOutput

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def register_socket_tools(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Stub registration for Task 17 — full socket toolset in Task 18."""
    # Import ListWorkspacesOutput at module level so FastMCP can resolve the
    # annotation when @mcp.tool is applied. Otherwise the name is local to
    # register_socket_tools() and FastMCP's signature inspector can't find it.
    @mcp.tool(
        name="cmux_list_workspaces",
        description="[stub] list all workspaces with their panes and surfaces.",
    )
    async def cmux_list_workspaces() -> ListWorkspacesOutput:
        """Stub: returns empty list. Task 18 will compose workspace.list +
        surface.list + pane.surfaces into a real tree."""
        return ListWorkspacesOutput(workspaces=[])