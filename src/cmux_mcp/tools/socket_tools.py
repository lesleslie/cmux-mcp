"""cmux_mcp.tools.socket_tools — registers the 5 socket-direct tools.

Each tool follows the try/except/else/return pattern per spec §"/health envelope
wiring → Tool feed placement":
    state = tool_feeds[name]
    state.record_cycle()
    try:
        result = await socket.request(...)
    except CmuxError as exc:
        state.record_error()
        raise _as_tool_error(exc) from exc
    else:
        state.record_success()
        return result
"""
from __future__ import annotations

import json
from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError

from cmux_mcp.models import (
    IdentifyOutput,
    ListNotificationsOutput,
    ListWorkspacesOutput,
    Notification,
    NotifyInput,
    NotifyOutput,
    Pane,
    SendKeysInput,
    SendKeysOutput,
    Surface,
    Workspace,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def _record(state: "ToolFeedComponent") -> None:
    state.record_cycle()


def _as_tool_error(exc: Exception) -> ToolError:
    """Wrap a CmuxError (or other Exception) as fastmcp.exceptions.ToolError.

    FastMCP's tool-handler (server.py:1357-1358) catches any exception, re-raises
    as ToolError(f"Error calling tool {name!r}: {e}"), and the protocol layer
    sets isError: true. Review finding C6: returning a plain dict was being
    wrapped in isError: false. Now we raise instead, so isError: true.

    The structured envelope (code, message, retryable, data) is JSON-encoded
    into the ToolError message text — clients parse it back.
    """
    from cmux_mcp.errors import CmuxError
    if isinstance(exc, CmuxError):
        envelope = exc.to_tool_error()
    else:
        envelope = {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
    return ToolError(json.dumps(envelope))


def register_socket_tools(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register the 5 socket-direct tools on the FastMCP instance."""

    @mcp.tool(
        name="cmux_list_workspaces",
        description="List all workspaces with their panes and surfaces.",
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cmux_list_workspaces() -> ListWorkspacesOutput:
        state = tool_feeds["tool.cmux_list_workspaces"]
        state.record_cycle()
        try:
            ws_data = await socket.request("workspace.list")
            workspaces: list[Workspace] = []
            for ws in ws_data.get("workspaces", []):
                ws_id = ws["id"]
                pane_data = await socket.request("pane.surfaces", {"workspace_id": ws_id})
                workspaces.append(Workspace(
                    id=ws_id,
                    title=ws.get("title", ""),
                    focused=ws.get("focused", False),
                    panes=[Pane(
                        id=p["id"],
                        surfaces=[Surface(
                            id=s["id"],
                            kind=s["kind"],
                            cwd=s.get("cwd"),
                            focused=s.get("focused", False),
                        ) for s in p.get("surfaces", [])],
                    ) for p in pane_data.get("panes", [])],
                ))
            result = ListWorkspacesOutput(workspaces=workspaces)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_list_notifications",
        description="List pending cmux notifications.",
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cmux_list_notifications() -> ListNotificationsOutput:
        state = tool_feeds["tool.cmux_list_notifications"]
        state.record_cycle()
        try:
            data = await socket.request("notification.list")
            result = ListNotificationsOutput(
                notifications=[Notification(**n) for n in data.get("notifications", [])]
            )
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_identify",
        description="Return the focused window/workspace/pane/surface context.",
        annotations={
            "readOnlyHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def cmux_identify() -> IdentifyOutput:
        state = tool_feeds["tool.cmux_identify"]
        state.record_cycle()
        try:
            data = await socket.request("system.identify")
            result = IdentifyOutput(**data)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_send_keys",
        description=(
            "Send text or a special key to a terminal surface (fire-and-forget). "
            "Pass exactly one of `text` or `key`."
        ),
        annotations={
            "destructiveHint": True,
            "openWorldHint": True,
        },
    )
    async def cmux_send_keys(
        surface_id: str,
        text: str | None = None,
        key: str | None = None,
    ) -> SendKeysOutput:
        # Pydantic validation enforces exclusive-or at the model boundary.
        validated = SendKeysInput(surface_id=surface_id, text=text, key=key)
        state = tool_feeds["tool.cmux_send_keys"]
        state.record_cycle()
        try:
            if validated.text is not None:
                await socket.request(
                    "surface.send_text",
                    {"surface_id": validated.surface_id, "text": validated.text},
                )
            else:
                await socket.request(
                    "surface.send_key",
                    {"surface_id": validated.surface_id, "key": validated.key},
                )
            result = SendKeysOutput(surface_id=validated.surface_id)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_notify",
        description="Dispatch an OS notification that rings a pane and lights up the sidebar.",
        annotations={
            "openWorldHint": True,
        },
    )
    async def cmux_notify(
        title: str,
        subtitle: str | None = None,
        body: str | None = None,
        surface_id: str | None = None,
    ) -> NotifyOutput:
        validated = NotifyInput(title=title, subtitle=subtitle, body=body, surface_id=surface_id)
        state = tool_feeds["tool.cmux_notify"]
        state.record_cycle()
        try:
            data = await socket.request(
                "notification.create",
                validated.model_dump(mode="json", exclude_none=True),
            )
            result = NotifyOutput(**data)
        except Exception as exc:
            state.record_error()
            return _error_envelope(exc)
        else:
            state.record_success()
            return result