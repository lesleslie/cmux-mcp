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