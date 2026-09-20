"""cmux_mcp.models — Pydantic v2 models for cmux domain objects.

Per spec §"Pydantic models → Domain models".
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

# Regex patterns (per spec §"Security → Input validation")
SURFACE_ID_PATTERN = r"^surface:[a-zA-Z0-9_-]+$"
PANE_ID_PATTERN = r"^pane:[a-zA-Z0-9_-]+$"
WORKSPACE_ID_PATTERN = r"^workspace:[a-zA-Z0-9_-]+$"
NOTIFICATION_ID_PATTERN = r"^notification:[a-zA-Z0-9_-]+$"


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


__all__ = [
    "SURFACE_ID_PATTERN",
    "PANE_ID_PATTERN",
    "WORKSPACE_ID_PATTERN",
    "NOTIFICATION_ID_PATTERN",
    "SurfaceKind",
    "Surface",
    "Pane",
    "Workspace",
    "Notification",
]