"""Tests for the 5 socket-direct tools."""

from __future__ import annotations

import pytest
from fastmcp import FastMCP

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.health import build_tool_feed_components
from cmux_mcp.models import (
    IdentifyOutput,
    ListNotificationsOutput,
    ListWorkspacesOutput,
    NotifyOutput,
    SendKeysOutput,
    SurfaceKind,
)
from cmux_mcp.tools.socket_tools import register_socket_tools


@pytest.fixture
def feeds() -> dict[str, object]:
    return {comp.name: comp for comp in build_tool_feed_components()}


async def _invoke(mcp: FastMCP, name: str, **kwargs: object) -> object:
    """Find a registered tool by name and call its underlying function."""
    tools = list(await mcp.list_tools())
    tool = next(t for t in tools if t.name == name)
    return await tool.fn(**kwargs)


@pytest.mark.unit
class TestCmuxListWorkspaces:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "workspace.list",
            {},
            {
                "result": {
                    "workspaces": [
                        {"id": "workspace:1", "title": "W1", "focused": True}
                    ]
                }
            },
        )
        socket.add_response(
            "surface.list",
            {"workspace_id": "workspace:1"},
            {
                "result": {
                    "surfaces": [
                        {
                            "id": "surface:ws-root",
                            "kind": "terminal",
                            "cwd": "/home/user",
                            "focused": False,
                        }
                    ]
                }
            },
        )
        socket.add_response(
            "pane.surfaces",
            {"workspace_id": "workspace:1"},
            {
                "result": {
                    "panes": [
                        {
                            "id": "pane:1",
                            "surfaces": [
                                {
                                    "id": "surface:pane",
                                    "kind": "browser",
                                    "cwd": None,
                                    "focused": True,
                                }
                            ],
                        }
                    ]
                }
            },
        )
        register_socket_tools(mcp, socket, feeds)
        result = await _invoke(mcp, "cmux_list_workspaces")
        assert isinstance(result, ListWorkspacesOutput)
        assert result.workspaces[0].id == "workspace:1"
        assert result.workspaces[0].title == "W1"
        assert result.workspaces[0].focused is True
        # Loop body must execute — verify both sub-calls produced surfaces.
        panes = result.workspaces[0].panes
        assert len(panes) == 1
        assert panes[0].id == "pane:1"
        # surface.list's "surface:ws-root" appended to the first pane.
        assert len(panes[0].surfaces) == 2
        surface_ids = {s.id for s in panes[0].surfaces}
        assert surface_ids == {"surface:pane", "surface:ws-root"}

    @pytest.mark.asyncio
    async def test_socket_error_raises_tool_error(
        self, feeds: dict[str, object]
    ) -> None:
        """Regression for review finding C6: tool errors must propagate as exceptions
        so FastMCP's protocol layer sets isError: true on the CallToolResult.

        Previously the tool body returned a plain dict; FastMCP wrapped it in
        is_error=False, breaking MCP clients that gate on isError per the
        canonical 2025-06-18 contract.
        """
        import json

        import pytest
        from fastmcp.exceptions import ToolError

        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response("workspace.list", {}, {"error": {"message": "socket gone"}})
        register_socket_tools(mcp, socket, feeds)
        with pytest.raises(ToolError) as excinfo:
            await _invoke(mcp, "cmux_list_workspaces")
        # Structured envelope is JSON-encoded in the ToolError message text;
        # clients parse it back to recover code/retryable/data.
        envelope = json.loads(str(excinfo.value))
        assert envelope["code"] == "cmux_protocol_error"


@pytest.mark.unit
class TestCmuxSendKeys:
    @pytest.mark.asyncio
    async def test_exactly_one_validation(self, feeds: dict[str, object]) -> None:
        from pydantic import ValidationError

        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "surface.send_text",
            {"surface_id": "surface:abc", "text": "x"},
            {"result": {"ok": True}},
        )
        register_socket_tools(mcp, socket, feeds)
        # both text and key → Pydantic validation rejects at fn boundary.
        with pytest.raises(ValidationError):
            await _invoke(
                mcp, "cmux_send_keys", surface_id="surface:abc", text="x", key="enter"
            )

    @pytest.mark.asyncio
    async def test_typed_output(self, feeds: dict[str, object]) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "surface.send_text",
            {"surface_id": "surface:abc", "text": "hello"},
            {"result": {"ok": True}},
        )
        register_socket_tools(mcp, socket, feeds)
        result = await _invoke(
            mcp, "cmux_send_keys", surface_id="surface:abc", text="hello"
        )
        assert isinstance(result, SendKeysOutput)
        assert result.surface_id == "surface:abc"
        assert result.ok is True


@pytest.mark.unit
class TestCmuxNotify:
    @pytest.mark.asyncio
    async def test_returns_notification_id(self, feeds: dict[str, object]) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "notification.create",
            {"title": "T"},
            {
                "result": {
                    "notification_id": "notification:xyz",
                    "created_at": "2026-09-16T12:00:00Z",
                }
            },
        )
        register_socket_tools(mcp, socket, feeds)
        result = await _invoke(mcp, "cmux_notify", title="T")
        assert isinstance(result, NotifyOutput)
        assert result.notification_id == "notification:xyz"


@pytest.mark.unit
class TestCmuxIdentify:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "system.identify",
            {},
            {
                "result": {
                    "window": "main",
                    "workspace_id": "workspace:1",
                    "pane_id": "pane:1",
                    "surface_id": "surface:abc",
                    "kind": "terminal",
                }
            },
        )
        register_socket_tools(mcp, socket, feeds)
        result = await _invoke(mcp, "cmux_identify")
        assert isinstance(result, IdentifyOutput)
        assert result.kind == SurfaceKind.TERMINAL


@pytest.mark.unit
class TestCmuxListNotifications:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response(
            "notification.list",
            {},
            {
                "result": {
                    "notifications": [
                        {
                            "id": "notification:abc",
                            "title": "Hi",
                            "created_at": "2026-09-16T12:00:00Z",
                        }
                    ]
                }
            },
        )
        register_socket_tools(mcp, socket, feeds)
        result = await _invoke(mcp, "cmux_list_notifications")
        assert isinstance(result, ListNotificationsOutput)
        assert result.notifications[0].id == "notification:abc"
