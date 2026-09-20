"""Tests for the 7 browser CLI tools."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from cmux_mcp.client import CliResult, CmuxMockTransport
from cmux_mcp.health import build_tool_feed_components
from cmux_mcp.models import (
    BrowserClickOutput,
    BrowserConsoleResult,
    BrowserEvaluateErrorResult,
    BrowserEvaluateResult,
    BrowserNavigateOutput,
    BrowserSnapshot,
    BrowserTabsOutput,
    BrowserTypeOutput,
)
from cmux_mcp.tools.browser_tools import register_browser_tools


@pytest.fixture
def feeds() -> dict[str, object]:
    return {comp.name: comp for comp in build_tool_feed_components()}


@pytest.fixture
def mock_cli() -> CmuxMockTransport:
    """CmuxMockTransport; tests override `cli.call` per case to control CLI output."""
    return CmuxMockTransport()


async def _invoke(mcp: FastMCP, name: str, **kwargs: object) -> object:
    """Find a registered tool by name and call its underlying function."""
    tools = list(await mcp.list_tools())
    tool = next(t for t in tools if t.name == name)
    return await tool.fn(**kwargs)


def _ok_cli(stdout: bytes = b"", stderr: bytes = b"") -> AsyncMock:
    """AsyncMock returning ok CliResult with the given stdout/stderr."""
    async def fake_call(args, *, timeout=None):
        return CliResult(ok=True, stdout=stdout, stderr=stderr, returncode=0, duration_ms=10)
    return AsyncMock(side_effect=fake_call)


@pytest.mark.unit
class TestCmuxBrowserNavigate:
    @pytest.mark.asyncio
    async def test_returns_typed_output(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(
            mcp, "cmux_browser_navigate",
            surface_id="surface:abc", url="https://example.com",
        )
        assert isinstance(result, BrowserNavigateOutput)
        assert str(result.url) == "https://example.com/"
        assert result.ok is True

    @pytest.mark.asyncio
    async def test_record_success_fires_on_success(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        """Regression for review finding C5: state.record_success() was unreachable
        because the original implementation returned from inside the try: block.

        Without this fix, /health reports successes_total=0 forever for this tool
        even though it executes successfully — silently breaking the spec's
        warm-up gate logic that depends on cycles_total vs successes_total."""
        mcp = FastMCP(name="test")
        register_browser_tools(mcp, mock_cli, feeds)
        navigate_feed = feeds["tool.cmux_browser_navigate"]
        # Counters live on .state (mcp-common's HealthFeedState), not the wrapper.
        assert navigate_feed.state.cycles_total == 0
        assert navigate_feed.state.errors_total == 0
        await _invoke(
            mcp, "cmux_browser_navigate",
            surface_id="surface:abc", url="https://example.com",
        )
        # record_cycle + record_success must have fired exactly once.
        assert navigate_feed.state.cycles_total == 1
        assert navigate_feed.state.errors_total == 0


@pytest.mark.unit
class TestCmuxBrowserSnapshot:
    @pytest.mark.asyncio
    async def test_returns_typed_output(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")
        mock_cli.call = _ok_cli(stdout=b"[ref=e1] button Sign in")
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(mcp, "cmux_browser_snapshot", surface_id="surface:abc")
        assert isinstance(result, BrowserSnapshot)
        assert "Sign in" in result.snapshot


@pytest.mark.unit
class TestCmuxBrowserTabs:
    @pytest.mark.asyncio
    async def test_returns_typed_output(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        tabs_json = json.dumps([
            {"id": "t1", "url": "https://a.example", "title": "A", "active": False},
            {"id": "t2", "url": "https://b.example", "title": "B", "active": True},
        ]).encode()
        mcp = FastMCP(name="test")
        mock_cli.call = _ok_cli(stdout=tabs_json)
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(mcp, "cmux_browser_tabs", surface_id="surface:abc")
        assert isinstance(result, BrowserTabsOutput)
        assert len(result.tabs) == 2
        assert result.tabs[0].id == "t1"


@pytest.mark.unit
class TestCmuxBrowserEvaluate:
    @pytest.mark.asyncio
    async def test_returns_typed_result_on_value(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")
        mock_cli.call = _ok_cli(stdout=json.dumps({"ok": True, "result": 42}).encode())
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(
            mcp, "cmux_browser_evaluate",
            surface_id="surface:abc", expression="document.title.length",
        )
        assert isinstance(result, BrowserEvaluateResult)
        assert result.ok is True
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_returns_error_envelope_on_runtime_exception(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")

        async def fake_call(args, *, timeout=None):
            return CliResult(
                ok=False, stdout=b"", stderr=b"ReferenceError: x is not defined",
                returncode=1, duration_ms=10,
            )

        mock_cli.call = AsyncMock(side_effect=fake_call)
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(
            mcp, "cmux_browser_evaluate", surface_id="surface:abc", expression="x.y.z",
        )
        assert isinstance(result, BrowserEvaluateErrorResult)
        assert result.ok is False
        assert result.error_kind == "runtime_exception"

    @pytest.mark.asyncio
    async def test_expression_length_validated(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        from pydantic import ValidationError
        mcp = FastMCP(name="test")
        register_browser_tools(mcp, mock_cli, feeds)
        with pytest.raises(ValidationError):
            await _invoke(mcp, "cmux_browser_evaluate", surface_id="surface:abc", expression="")


@pytest.mark.unit
class TestCmuxBrowserClick:
    @pytest.mark.asyncio
    async def test_returns_typed_output(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")
        mock_cli.call = _ok_cli()
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(
            mcp, "cmux_browser_click",
            surface_id="surface:abc", selector="button#submit",
        )
        assert isinstance(result, BrowserClickOutput)
        assert result.ok is True


@pytest.mark.unit
class TestCmuxBrowserType:
    @pytest.mark.asyncio
    async def test_returns_typed_output(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")
        mock_cli.call = _ok_cli()
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(
            mcp, "cmux_browser_type",
            surface_id="surface:abc", selector="input#q", text="cmux",
        )
        # Regression for review finding H3: previously returned BrowserClickOutput
        # (which leaks a `snapshot` field BrowserTypeOutput doesn't declare).
        assert isinstance(result, BrowserTypeOutput)
        assert result.ok is True


@pytest.mark.unit
class TestCmuxBrowserConsole:
    @pytest.mark.asyncio
    async def test_returns_typed_output_aggregated(
        self, feeds: dict[str, object], mock_cli: CmuxMockTransport
    ) -> None:
        mcp = FastMCP(name="test")

        async def fake_call(args, *, timeout=None):
            if "errors" in args:
                return CliResult(ok=True, stdout=b"[]", stderr=b"", returncode=0, duration_ms=5)
            return CliResult(
                ok=True,
                stdout=json.dumps([{"level": "info", "text": "hello"}]).encode(),
                stderr=b"", returncode=0, duration_ms=5,
            )

        mock_cli.call = AsyncMock(side_effect=fake_call)
        register_browser_tools(mcp, mock_cli, feeds)
        result = await _invoke(mcp, "cmux_browser_console", surface_id="surface:abc")
        assert isinstance(result, BrowserConsoleResult)
        assert len(result.messages) == 1
        assert result.partial_failure is False