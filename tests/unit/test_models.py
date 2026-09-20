"""Tests for src/cmux_mcp/models.py — domain models."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from cmux_mcp.models import (
    NOTIFICATION_ID_PATTERN,
    Notification,
    Pane,
    Surface,
    SurfaceKind,
    SURFACE_ID_PATTERN,
    Workspace,
    # Browser models
    BrowserConsoleResult,
    BrowserError,
    BrowserSnapshot,
    BrowserTab,
    ConsoleLevel,
    ConsoleMessage,
    # Tool inputs
    BrowserClickInput,
    BrowserConsoleInput,
    BrowserEvaluateInput,
    BrowserNavigateInput,
    BrowserSnapshotInput,
    BrowserTabsInput,
    BrowserTypeInput,
    NotifyInput,
    SendKeysInput,
    # Tool outputs
    BrowserClickOutput,
    BrowserEvaluateErrorResult,
    BrowserNavigateOutput,
    BrowserTabsOutput,
    IdentifyOutput,
    ListNotificationsOutput,
    ListWorkspacesOutput,
    NotifyOutput,
    SendKeysOutput,
)


@pytest.mark.unit
class TestSurfaceIdPatterns:
    def test_surface_id_pattern_accepts_canonical(self) -> None:
        assert Surface(id="surface:abc123", kind=SurfaceKind.TERMINAL).id == "surface:abc123"

    def test_surface_id_pattern_rejects_path_traversal(self) -> None:
        with pytest.raises(ValidationError):
            Surface(id="surface:../../etc/passwd", kind=SurfaceKind.TERMINAL)

    def test_surface_id_pattern_rejects_non_kebab(self) -> None:
        with pytest.raises(ValidationError):
            Surface(id="surface:has spaces", kind=SurfaceKind.TERMINAL)

    def test_notification_id_pattern_rejects_bad_format(self) -> None:
        with pytest.raises(ValidationError):
            Notification(
                id="notif-abc",  # missing notification: prefix
                title="test",
                created_at="2026-09-16T00:00:00Z",
            )

    def test_surface_kind_is_strenum(self) -> None:
        assert SurfaceKind.TERMINAL == "terminal"
        assert SurfaceKind.BROWSER == "browser"


@pytest.mark.unit
class TestTreeStructure:
    def test_workspace_contains_panes(self) -> None:
        surface = Surface(id="surface:abc", kind=SurfaceKind.TERMINAL, focused=True)
        pane = Pane(id="pane:1", surfaces=[surface])
        ws = Workspace(id="workspace:1", title="My Workspace", focused=True, panes=[pane])
        assert ws.panes[0].surfaces[0].id == "surface:abc"
        assert ws.panes[0].surfaces[0].focused is True

    def test_workspace_default_panes_is_empty(self) -> None:
        ws = Workspace(id="workspace:1", title="Empty")
        assert ws.panes == []


@pytest.mark.unit
class TestNotification:
    def test_notification_with_all_fields(self) -> None:
        n = Notification(
            id="notification:xyz",
            title="Test",
            subtitle="Sub",
            body="Body text",
            surface_id="surface:abc",
            created_at="2026-09-16T12:34:56Z",
        )
        assert n.title == "Test"
        assert n.surface_id == "surface:abc"

    def test_notification_created_at_serializes_iso8601(self) -> None:
        n = Notification(id="notification:xyz", title="Test", created_at="2026-09-16T12:34:56Z")
        dumped = n.model_dump(mode="json")
        # Both are valid RFC 3339 UTC; Pydantic v2 preserves the input suffix
        # ("Z" stays "Z", "+00:00" stays "+00:00") in mode="json".
        assert dumped["created_at"] in (
            "2026-09-16T12:34:56Z",
            "2026-09-16T12:34:56+00:00",
        )


@pytest.mark.unit
class TestBrowserModels:
    def test_browser_snapshot_round_trip(self) -> None:
        snap = BrowserSnapshot(snapshot="[ref=e1] button Sign in", captured_at="2026-09-16T12:34:56Z")
        assert "Sign in" in snap.snapshot

    def test_console_level_strenum(self) -> None:
        assert ConsoleLevel.LOG == "log"
        assert ConsoleLevel.ERROR == "error"
        assert ConsoleLevel.WARN == "warn"
        assert ConsoleLevel.INFO == "info"
        assert ConsoleLevel.DEBUG == "debug"

    def test_console_message_optional_source(self) -> None:
        msg = ConsoleMessage(level=ConsoleLevel.LOG, text="hello", timestamp="2026-09-16T12:34:56Z")
        assert msg.source is None

    def test_browser_tab_url_https_only(self) -> None:
        tab = BrowserTab(id="t1", url="https://example.com", title="Example", active=True)
        assert str(tab.url) == "https://example.com/"

    def test_browser_tab_url_rejects_javascript(self) -> None:
        with pytest.raises(ValidationError):
            BrowserTab(id="t1", url="javascript:alert(1)", title="x", active=False)

    def test_browser_error_stack_optional(self) -> None:
        err = BrowserError(message="undefined is not a function")
        assert err.stack is None

    def test_browser_console_result_partial_failure_flags(self) -> None:
        result = BrowserConsoleResult(
            messages=[], errors=[], partial_failure=True, failed_subcalls=["errors_list"]
        )
        assert result.partial_failure is True
        assert result.failed_subcalls == ["errors_list"]


@pytest.mark.unit
class TestSendKeysInput:
    def test_text_only_accepted(self) -> None:
        inp = SendKeysInput(surface_id="surface:abc", text="hello world")
        assert inp.text == "hello world"
        assert inp.key is None

    def test_key_only_accepted(self) -> None:
        inp = SendKeysInput(surface_id="surface:abc", key="enter")
        assert inp.key == "enter"
        assert inp.text is None

    def test_both_text_and_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SendKeysInput(surface_id="surface:abc", text="x", key="enter")

    def test_neither_text_nor_key_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SendKeysInput(surface_id="surface:abc")

    def test_key_literal_enum_validates_known_only(self) -> None:
        with pytest.raises(ValidationError):
            SendKeysInput(surface_id="surface:abc", key="Eneter")  # typo


@pytest.mark.unit
class TestBrowserNavigateInput:
    def test_https_url_accepted(self) -> None:
        inp = BrowserNavigateInput(surface_id="surface:abc", url="https://example.com")
        assert str(inp.url) == "https://example.com/"

    def test_javascript_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BrowserNavigateInput(surface_id="surface:abc", url="javascript:alert(1)")

    def test_file_url_rejected(self) -> None:
        with pytest.raises(ValidationError):
            BrowserNavigateInput(surface_id="surface:abc", url="file:///etc/passwd")


@pytest.mark.unit
class TestBrowserEvaluateInput:
    def test_expression_length_bounds(self) -> None:
        with pytest.raises(ValidationError):
            BrowserEvaluateInput(surface_id="surface:abc", expression="")
        with pytest.raises(ValidationError):
            BrowserEvaluateInput(surface_id="surface:abc", expression="x" * 10_241)


@pytest.mark.unit
class TestBrowserConsoleInput:
    def test_limit_bounds(self) -> None:
        with pytest.raises(ValidationError):
            BrowserConsoleInput(surface_id="surface:abc", limit=0)
        with pytest.raises(ValidationError):
            BrowserConsoleInput(surface_id="surface:abc", limit=1_001)

    def test_default_limit_is_50(self) -> None:
        inp = BrowserConsoleInput(surface_id="surface:abc")
        assert inp.limit == 50
        assert inp.level == ConsoleLevel.LOG
        assert inp.since is None


@pytest.mark.unit
class TestToolOutputModels:
    def test_list_workspaces_output_wraps_workspace_list(self) -> None:
        out = ListWorkspacesOutput(workspaces=[])
        assert out.workspaces == []

    def test_list_notifications_output_wraps_notification_list(self) -> None:
        out = ListNotificationsOutput(notifications=[])
        assert out.notifications == []

    def test_identify_output_shape(self) -> None:
        out = IdentifyOutput(
            window="main",
            workspace_id="workspace:1",
            pane_id="pane:1",
            surface_id="surface:abc",
            kind=SurfaceKind.TERMINAL,
        )
        assert out.kind == "terminal"

    def test_send_keys_output_ok_is_true(self) -> None:
        out = SendKeysOutput(surface_id="surface:abc")
        assert out.ok is True

    def test_notify_output_serializes_datetime(self) -> None:
        out = NotifyOutput(notification_id="notification:xyz", created_at="2026-09-16T12:34:56Z")
        assert "2026" in out.model_dump(mode="json")["created_at"]

    def test_browser_navigate_output_truncated_flag(self) -> None:
        out = BrowserNavigateOutput(
            ok=True,
            url="https://example.com",
            snapshot=None,
            truncated=True,
        )
        assert out.truncated is True

    def test_browser_click_output_shape(self) -> None:
        out = BrowserClickOutput(ok=True)
        assert out.ok is True

    def test_browser_tabs_output_order_preserved(self) -> None:
        out = BrowserTabsOutput(
            tabs=[
                BrowserTab(id="t1", url="https://a.example", title="A", active=False),
                BrowserTab(id="t2", url="https://b.example", title="B", active=True),
            ]
        )
        assert [t.id for t in out.tabs] == ["t1", "t2"]

    def test_browser_evaluate_error_result_error_kind_enum(self) -> None:
        out = BrowserEvaluateErrorResult(
            error="not serializable", error_kind="not_serializable"
        )
        assert out.error_kind == "not_serializable"
        assert out.ok is False
        assert out.result is None

    def test_browser_evaluate_error_result_disallows_result_field(self) -> None:
        # When ok=False, result must be None (discriminated union)
        with pytest.raises(ValidationError):
            BrowserEvaluateErrorResult(
                error="x", error_kind="runtime_exception", result="should not be allowed"
            )  # type: ignore[call-arg]