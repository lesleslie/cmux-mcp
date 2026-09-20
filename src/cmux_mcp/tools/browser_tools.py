"""cmux_mcp.tools.browser_tools — registers the 7 browser CLI tools.

Tasks 19-22 register all 7 tools:
  6: cmux_browser_navigate (Task 19)
  7: cmux_browser_snapshot (Task 20)
  8: cmux_browser_tabs (Task 20)
  9: cmux_browser_evaluate (Task 21)
 10: cmux_browser_click (Task 22)
 11: cmux_browser_type (Task 22)
 12: cmux_browser_console (Task 22)

Each follows the try/except/else pattern per spec §"/health envelope wiring → Tool feed placement".
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from fastmcp.exceptions import ToolError

from cmux_mcp.models import (
    BrowserClickInput,
    BrowserClickOutput,
    BrowserConsoleInput,
    BrowserConsoleResult,
    BrowserEvaluateErrorResult,
    BrowserEvaluateInput,
    BrowserEvaluateResult,
    BrowserNavigateInput,
    BrowserNavigateOutput,
    BrowserSnapshot,
    BrowserSnapshotInput,
    BrowserTabsInput,
    BrowserTabsOutput,
    BrowserTypeInput,
    BrowserTypeOutput,
)

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxCliTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def _record(state: "ToolFeedComponent") -> None:
    state.record_cycle()


def _as_tool_error(exc: Exception) -> ToolError:
    """Wrap a CmuxError (or other Exception) as fastmcp.exceptions.ToolError.

    See socket_tools.py for full rationale (review finding C6).
    """
    from cmux_mcp.errors import CmuxError
    if isinstance(exc, CmuxError):
        envelope = exc.to_tool_error()
    else:
        envelope = {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
    return ToolError(json.dumps(envelope))


def _truncate(text: bytes, limit: int) -> tuple[bytes, bool]:
    """Clip `text` to `limit` bytes; return (clipped_text, was_truncated).

    Review finding H1: max_response_bytes was config-declared but never
    enforced anywhere. cmux_browser_navigate used a hardcoded 4096 on
    stderr length (unrelated to response size) and didn't actually clip.
    """
    if limit > 0 and len(text) > limit:
        return text[:limit], True
    return text, False


def register_browser_tools(
    mcp: "FastMCP",
    cli: "CmuxCliTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register the 7 browser CLI tools on the FastMCP instance."""

    @mcp.tool(
        name="cmux_browser_navigate",
        description="Navigate the browser surface to a URL.",
        annotations={"destructiveHint": True, "openWorldHint": True},
    )
    async def cmux_browser_navigate(
        surface_id: str,
        url: str,
        snapshot_after: bool = False,
    ) -> BrowserNavigateOutput:
        from pydantic import HttpUrl
        validated = BrowserNavigateInput(surface_id=surface_id, url=url, snapshot_after=snapshot_after)
        state = tool_feeds["tool.cmux_browser_navigate"]
        state.record_cycle()
        args = ["browser", "--surface", validated.surface_id, "navigate", str(validated.url)]
        if validated.snapshot_after:
            args.append("--snapshot-after")
        try:
            cli_result = await cli.call(args)
            # Review finding H1: max_response_bytes is the configured stdout cap.
            # Clip stdout to the limit and set truncated=True when over. Stderr is
            # logged for diagnostics but is NOT part of the response shape, so
            # it's not clipped here (operators see the full stderr in /logs).
            max_bytes = int(getattr(cli, "_config", None) and cli._config.max_response_bytes) or 1_048_576
            stdout, truncated = _truncate(cli_result.stdout, max_bytes)
            _ = stdout  # stdout currently unused in response shape; kept for future
            result = BrowserNavigateOutput(
                ok=True,
                url=HttpUrl(str(validated.url)),
                snapshot=None,  # snapshot parsing not implemented (Task 20)
                truncated=truncated,
            )
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            # Spec §"/health envelope wiring → Tool feed placement" mandates the
            # success record lives in the else: clause. Without this, /health
            # reports successes_total=0 forever for this tool (review finding C5).
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_browser_snapshot",
        description="Return the accessibility tree of the current page (Playwright-style refs).",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    async def cmux_browser_snapshot(surface_id: str) -> BrowserSnapshot:
        validated = BrowserSnapshotInput(surface_id=surface_id)
        state = tool_feeds["tool.cmux_browser_snapshot"]
        state.record_cycle()
        try:
            cli_result = await cli.call(
                ["browser", "--surface", validated.surface_id, "snapshot", "--interactive"],
            )
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return BrowserSnapshot(
                snapshot=cli_result.stdout.decode("utf-8", errors="replace"),
                captured_at=datetime.now(tz=timezone.utc),
            )

    @mcp.tool(
        name="cmux_browser_tabs",
        description="List open tabs of the browser surface (read-only).",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    async def cmux_browser_tabs(surface_id: str) -> BrowserTabsOutput:
        import json
        from cmux_mcp.models import BrowserTab
        validated = BrowserTabsInput(surface_id=surface_id)
        state = tool_feeds["tool.cmux_browser_tabs"]
        state.record_cycle()
        try:
            cli_result = await cli.call(
                ["browser", "--surface", validated.surface_id, "tab", "list", "--json"],
            )
            tabs_raw = json.loads(cli_result.stdout.decode("utf-8"))
            tabs = [BrowserTab(**t) for t in tabs_raw]
            result = BrowserTabsOutput(tabs=tabs)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_browser_evaluate",
        description=(
            "Execute JavaScript in the browser context and return the result. "
            "Arbitrary JS — trust model documented."
        ),
        annotations={"destructiveHint": True, "openWorldHint": True},
    )
    async def cmux_browser_evaluate(
        surface_id: str,
        expression: str,
        await_promise: bool = False,
    ) -> BrowserEvaluateResult | BrowserEvaluateErrorResult:
        import json
        validated = BrowserEvaluateInput(
            surface_id=surface_id, expression=expression, await_promise=await_promise,
        )
        state = tool_feeds["tool.cmux_browser_evaluate"]
        state.record_cycle()
        # await_promise polling deferred (per spec §"await_promise semantics"); v1
        # passes the flag through to the CLI.
        args = ["browser", "--surface", validated.surface_id, "eval", validated.expression]
        if validated.await_promise:
            args.append("--await")
        try:
            cli_result = await cli.call(args, timeout=30.0)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        if cli_result.returncode != 0:
            state.record_error()
            stderr = cli_result.stderr.decode("utf-8", errors="replace")
            if "not serializable" in stderr.lower():
                return BrowserEvaluateErrorResult(error=stderr, error_kind="not_serializable")
            return BrowserEvaluateErrorResult(error=stderr, error_kind="runtime_exception")
        try:
            payload = json.loads(cli_result.stdout.decode("utf-8"))
        except Exception:
            state.record_error()
            return BrowserEvaluateErrorResult(
                error=f"malformed eval output: {cli_result.stdout!r}",
                error_kind="runtime_exception",
            )
        state.record_success()
        return BrowserEvaluateResult(ok=True, result=payload.get("result"))

    @mcp.tool(
        name="cmux_browser_click",
        description="Click an element by CSS selector.",
        annotations={"destructiveHint": True, "openWorldHint": True},
    )
    async def cmux_browser_click(
        surface_id: str,
        selector: str,
        snapshot_after: bool = False,
    ) -> BrowserClickOutput:
        validated = BrowserClickInput(surface_id=surface_id, selector=selector, snapshot_after=snapshot_after)
        state = tool_feeds["tool.cmux_browser_click"]
        state.record_cycle()
        args = ["browser", "--surface", validated.surface_id, "click", validated.selector]
        if validated.snapshot_after:
            args.append("--snapshot-after")
        try:
            await cli.call(args)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return BrowserClickOutput(ok=True)

    @mcp.tool(
        name="cmux_browser_type",
        description="Type text into an input by CSS selector (uses fill semantics).",
        annotations={"destructiveHint": True, "openWorldHint": True},
    )
    async def cmux_browser_type(
        surface_id: str,
        selector: str,
        text: str,
        submit: bool = False,
    ) -> BrowserTypeOutput:
        # Spec §"Tool surface" mandates BrowserTypeOutput (just {ok: True});
        # using BrowserClickOutput here would leak a 'snapshot' field that
        # strict-schema consumers don't expect (review finding H3).
        validated = BrowserTypeInput(surface_id=surface_id, selector=selector, text=text, submit=submit)
        state = tool_feeds["tool.cmux_browser_type"]
        state.record_cycle()
        args = ["browser", "--surface", validated.surface_id, "fill", validated.selector, "--text", validated.text]
        if validated.submit:
            args.append("--submit")
        try:
            await cli.call(args)
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        else:
            state.record_success()
            return BrowserTypeOutput(ok=True)

    @mcp.tool(
        name="cmux_browser_console",
        description="Read console messages and JS errors from the browser surface.",
        annotations={"readOnlyHint": True, "idempotentHint": True, "openWorldHint": True},
    )
    async def cmux_browser_console(
        surface_id: str,
        limit: int = 50,
        level: str = "log",
        since: str | None = None,
    ) -> BrowserConsoleResult:
        import asyncio
        import json
        from cmux_mcp.models import BrowserError, ConsoleMessage
        validated = BrowserConsoleInput(surface_id=surface_id, limit=limit, level=level, since=since)
        state = tool_feeds["tool.cmux_browser_console"]
        state.record_cycle()
        # Aggregate two sub-calls per spec §"Tool 12". Use gather with return_exceptions
        # so partial failure becomes empty list + flag (per spec).
        try:
            results = await asyncio.gather(
                cli.call(["browser", "--surface", validated.surface_id, "console", "list"]),
                cli.call(["browser", "--surface", validated.surface_id, "errors", "list"]),
                return_exceptions=True,
            )
        except Exception as exc:
            state.record_error()
            raise _as_tool_error(exc) from exc
        state.record_success()
        messages: list[ConsoleMessage] = []
        errors: list[BrowserError] = []
        partial_failure = False
        failed_subcalls: list[str] = []
        console_result, errors_result = results
        if isinstance(console_result, Exception):
            partial_failure = True
            failed_subcalls.append("console_list")
        else:
            try:
                raw = json.loads(console_result.stdout.decode("utf-8"))
                messages = [ConsoleMessage(**m) for m in raw]
            except Exception:
                partial_failure = True
                failed_subcalls.append("console_list")
        if isinstance(errors_result, Exception):
            partial_failure = True
            failed_subcalls.append("errors_list")
        else:
            try:
                raw = json.loads(errors_result.stdout.decode("utf-8"))
                errors = [BrowserError(**e) for e in raw]
            except Exception:
                partial_failure = True
                failed_subcalls.append("errors_list")
        return BrowserConsoleResult(
            messages=messages,
            errors=errors,
            truncated=False,
            partial_failure=partial_failure,
            failed_subcalls=failed_subcalls,
        )