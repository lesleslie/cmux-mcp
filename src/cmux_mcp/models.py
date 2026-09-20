"""cmux_mcp.models — Pydantic v2 models for cmux domain objects.

Per spec §"Pydantic models → Domain models" + §"Browser models".
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

# Regex patterns (per spec §"Security → Input validation")
SURFACE_ID_PATTERN = r"^surface:[a-zA-Z0-9_-]+$"
PANE_ID_PATTERN = r"^pane:[a-zA-Z0-9_-]+$"
WORKSPACE_ID_PATTERN = r"^workspace:[a-zA-Z0-9_-]+$"
NOTIFICATION_ID_PATTERN = r"^notification:[a-zA-Z0-9_-]+$"


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


class SurfaceKind(StrEnum):
    TERMINAL = "terminal"
    BROWSER = "browser"


class Surface(BaseModel):
    """A single surface within a pane (terminal or browser pane)."""

    id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    kind: SurfaceKind
    cwd: str | None = None
    focused: bool = False


class Pane(BaseModel):
    """A pane contains one or more surfaces (split layout)."""

    id: Annotated[str, Field(pattern=PANE_ID_PATTERN)]
    surfaces: list[Surface] = []


class Workspace(BaseModel):
    """A workspace contains one or more panes."""

    id: Annotated[str, Field(pattern=WORKSPACE_ID_PATTERN)]
    title: str
    focused: bool = False
    panes: list[Pane] = []


class Notification(BaseModel):
    """A pending cmux notification (sidebar entry + ring + macOS banner)."""

    id: Annotated[str, Field(pattern=NOTIFICATION_ID_PATTERN)]
    title: str
    subtitle: str | None = None
    body: str | None = None
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)] | None = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Browser models
# ---------------------------------------------------------------------------


class BrowserSnapshot(BaseModel):
    """Plain text a11y tree with `[ref=eN]` markers (Playwright-style)."""

    snapshot: str
    captured_at: datetime | None = None


class ConsoleLevel(StrEnum):
    LOG = "log"
    DEBUG = "debug"
    INFO = "info"
    WARN = "warn"
    ERROR = "error"


class ConsoleMessage(BaseModel):
    level: ConsoleLevel
    text: str
    source: str | None = None
    timestamp: datetime | None = None


class BrowserTab(BaseModel):
    id: str
    url: HttpUrl
    title: str
    active: bool


class BrowserError(BaseModel):
    message: str
    stack: str | None = None


class BrowserConsoleResult(BaseModel):
    """Aggregated result of `console list` + `errors list`."""

    messages: list[ConsoleMessage]
    errors: list[BrowserError]
    truncated: bool = False
    partial_failure: bool = False  # True if one of console list / errors list sub-call failed
    failed_subcalls: list[Literal["console_list", "errors_list"]] = []


# ---------------------------------------------------------------------------
# Tool input models (per spec §"Tool input models")
# ---------------------------------------------------------------------------


class SendKeysInput(BaseModel):
    """`cmux_send_keys` input — exactly one of `text` or `key`."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    text: str | None = None
    key: Literal[
        "enter", "tab", "escape", "backspace", "delete",
        "up", "down", "left", "right", "home", "end",
        "pageup", "pagedown",
        "f1", "f2", "f3", "f4", "f5", "f6", "f7", "f8",
        "f9", "f10", "f11", "f12",
        "space", "return",
    ] | None = None

    @model_validator(mode="after")
    def _exactly_one_of_text_or_key(self) -> "SendKeysInput":
        if (self.text is None) == (self.key is None):
            raise ValueError("send_keys requires exactly one of text or key")
        return self


class NotifyInput(BaseModel):
    """`cmux_notify` input."""

    title: str
    subtitle: str | None = None
    body: str | None = None
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)] | None = None


class BrowserNavigateInput(BaseModel):
    """`cmux_browser_navigate` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    url: HttpUrl
    snapshot_after: bool = False


class BrowserSnapshotInput(BaseModel):
    """`cmux_browser_snapshot` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class BrowserEvaluateInput(BaseModel):
    """`cmux_browser_evaluate` input — JS expression, 1–10240 chars."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    expression: Annotated[str, Field(min_length=1, max_length=10_240)]
    await_promise: bool = False


class BrowserClickInput(BaseModel):
    """`cmux_browser_click` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    selector: Annotated[str, Field(min_length=1, max_length=1_024)]
    snapshot_after: bool = False


class BrowserTypeInput(BaseModel):
    """`cmux_browser_type` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    selector: Annotated[str, Field(min_length=1, max_length=1_024)]
    text: Annotated[str, Field(max_length=10_240)]
    submit: bool = False


class BrowserTabsInput(BaseModel):
    """`cmux_browser_tabs` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class BrowserConsoleInput(BaseModel):
    """`cmux_browser_console` input."""

    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    limit: int = Field(default=50, ge=1, le=1_000)
    level: ConsoleLevel = ConsoleLevel.LOG
    since: datetime | None = None


__all__ = [
    # ID patterns
    "SURFACE_ID_PATTERN",
    "PANE_ID_PATTERN",
    "WORKSPACE_ID_PATTERN",
    "NOTIFICATION_ID_PATTERN",
    # Domain
    "SurfaceKind",
    "Surface",
    "Pane",
    "Workspace",
    "Notification",
    # Browser
    "BrowserSnapshot",
    "ConsoleLevel",
    "ConsoleMessage",
    "BrowserTab",
    "BrowserError",
    "BrowserConsoleResult",
    # Tool inputs
    "SendKeysInput",
    "NotifyInput",
    "BrowserNavigateInput",
    "BrowserSnapshotInput",
    "BrowserEvaluateInput",
    "BrowserClickInput",
    "BrowserTypeInput",
    "BrowserTabsInput",
    "BrowserConsoleInput",
]