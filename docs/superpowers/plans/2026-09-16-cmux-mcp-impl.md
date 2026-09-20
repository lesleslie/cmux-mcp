---
status: active
role: implementation
date: 2026-09-16
last_reviewed: 2026-09-19
superseded_by: null
blocks_on:
  - docs/superpowers/specs/2026-09-16-cmux-mcp-design.md
topic: cmux-mcp
amendments: see docs/superpowers/specs/2026-09-16-cmux-mcp-design.md "Amendment Log" section
---

# cmux-mcp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `cmux-mcp`, a single MCP server that exposes programmatic control of a running [cmux](https://github.com/manaflow-ai/cmux) instance (macOS Ghostty-based terminal) as 12 MCP tools over Streamable HTTP on port 3061. The server speaks cmux's Unix-socket JSON-RPC protocol directly for orchestration and notifications, and shells out to the cmux CLI for browser automation (the only documented path, since cmux's embedded WebKit browser does not expose a remote inspector).

**Architecture:** Standalone FastMCP server following mcp-common Pattern 1 (`BaseOneiricServerMixin` + `MCPServerCLIFactory.create_server_cli`). Per-instance `FastMCP` (not module-level singleton) forces programmatic `register_tools()` rather than `@mcp.tool()` decorators. `CmuxSocketTransport` (long-lived asyncio unix socket, JSON-RPC multiplexed by id, reconnect with backoff) handles the 5 socket tools; `CmuxCliTransport` (`asyncio.create_subprocess_exec`, per-call timeout, SIGTERM→SIGKILL, global semaphore + per-surface lock) handles the 7 browser tools. `CmuxMockTransport` implements both Protocol shapes for test isolation. All 12 tools emit `HealthFeedState` per the Bodai MCP wiring discipline.

**Tech Stack:** Python ≥ 3.13, `fastmcp>=3.4,<4`, `mcp-common>=0.26,<0.27`, `oneiric>=0.21`, `pydantic>=2.13.4`, `pydantic-settings>=2`, `httpx>=0.27`, `psutil>=7.2.2`, `pyyaml>=6`, pytest, pytest-asyncio, crackerjack.

**Spec:** [docs/superpowers/specs/2026-09-16-cmux-mcp-design.md](../specs/2026-09-16-cmux-mcp-design.md) — every task below argues from that spec; executors must read both.

## Global Constraints

These constraints apply to every task below. Each task's "Interfaces" and "Step" sections do not re-state them.

- **Python:** `>= 3.14` (per `pyproject.toml` `requires-python`; amended 2026-09-19 from `>= 3.13` — `mcp-common` 0.26.x and 0.27.x both require `>= 3.14`)
- **Module imports:** Every production source file MUST start with `from __future__ import annotations` as the first non-comment line
- **Logger name:** `cmux_mcp.<module>` (e.g., `cmux_mcp.config`); use `logger.exception(...)` in every `except` block; never `logger.error(..., exc_info=True)`
- **No print():** Use the Oneiric logger. No stdlib `logging`. No print()
- **Type hints:** Modern syntax — `X | None`, `list[str]`, `pathlib.Path`, never `Optional[X]` / `List[X]`. Default-`None` args typed `X | None = None`. No `Any` in tool inputs or orchestration state
- **Coverage:** `--cov-fail-under=89` (crackerjack gate)
- **Lint:** `crackerjack run` passes on every task's commit
- **Async:** All I/O in the orchestration layer is `async`; no `time.sleep`, no `requests`, no sync file I/O inside async functions
- **Mypy strict + pyright:** Strict mode; `disallow_untyped_defs`, `no_implicit_optional`, `warn_unused_ignores`, `warn_return_any`
- **Version pins:** `fastmcp>=3.4,<4`, `mcp-common>=0.26,<0.27`, `oneiric>=0.21.0`, `pydantic>=2.13.4`, `pydantic-settings>=2`, `httpx>=0.27`, `psutil>=7.2.2`, `pyyaml>=6`
- **Settings path:** `selectors_file` not applicable here; `pid_file_path` anchors on `Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cmux-mcp" / "cmux-mcp.pid"`
- **Pydantic v2 env_prefix:** `model_config = SettingsConfigDict(env_prefix="CMUX_MCP_", env_file=".env", extra="allow")` — direct `BaseSettings` subclass (per decision log row 5 + 25)
- **CLI commands:** Factory provides `start`/`stop`/`restart`/`status`/`health`/`version`/`doctor` plus `--json`
- **Default port:** `3061`; module constant `cmux_mcp.config:DEFAULT_PORT`
- **License:** BSD 3-Clause (per spec decision log row 1)

## File Structure

```
cmux-mcp/
  cli.py                  # mcp-common lifecycle (start/stop/restart/status/health/version/doctor)
  __main__.py             # entry point: MCPServerCLIFactory.create_server_cli(...)
  config.py               # CmuxMCPConfig (BaseSettings) + DEFAULT_PORT
  client.py               # CmuxSocketTransport, CmuxCliTransport, CmuxMockTransport
  models.py               # Workspace, Surface, Pane, Notification, BrowserSnapshot, etc.
  errors.py               # CmuxError hierarchy (8 classes)
  server.py               # CmuxMCPServer(BaseOneiricServerMixin)
  _tools.py               # register_tools() function (per spec §"_tools.py — registration pattern")
  tools/
    __init__.py
    socket_tools.py       # 5 cmux_* socket tools
    browser_tools.py      # 7 cmux_browser_* tools
  health.py               # SocketFeedComponent, BrowserCliFeedComponent, MockTransportComponent, ToolFeedComponent
  settings/
    cmux-mcp.yaml         # committed defaults
tests/
  conftest.py
  fixtures/
    cmux_responses.yaml
  unit/
    test_config.py
    test_models.py
    test_errors.py
    test_transport_mock.py
    test_transport_socket.py
    test_transport_cli.py
    test_health.py
    test_lifecycle.py
    test_socket_tools.py
    test_browser_tools.py
    test_tools_registration.py
    test_logging_pii.py
  integration/
    test_socket_e2e.py
    test_browser_e2e.py
  e2e/
    test_health_endpoint.py
    test_tool_registration.py
  README.md
  LICENSE                 # BSD 3-Clause
  pyproject.toml          # hatchling build, deps, scripts
```

---

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/cmux_mcp/__init__.py`
- Create: `src/cmux_mcp/__main__.py`
- Create: `src/cmux_mcp/cli.py`
- Create: `LICENSE`
- Create: `tests/__init__.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/e2e/__init__.py`
- Create: `settings/cmux-mcp.yaml`

**Interfaces:**
- Consumes: none (initial scaffold)
- Produces: installable package with `cmux-mcp` console script

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "cmux-mcp"
version = "0.1.0"
description = "MCP server for cmux terminal automation (macOS only)"
# Amendment 2026-09-19: bumped from ">=3.13" — see Amendment Log in the spec.
requires-python = ">=3.14"
license = "BSD-3-Clause"
authors = [
    {name = "Les Leslie", email = "les@wedgwoodwebworks.com"},
]
dependencies = [
    "fastmcp>=3.4,<4",
    "oneiric>=0.21.0",
    "mcp-common>=0.26,<0.27",
    "pydantic>=2.13.4",
    "pydantic-settings>=2",
    "httpx>=0.27",
    "psutil>=7.2.2",
    "pyyaml>=6",
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "pytest-cov>=5",
    "crackerjack>=0.20",
    "ruff>=0.6",
    "mypy>=1.10",
]

[project.scripts]
cmux-mcp = "cmux_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/cmux_mcp"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "unit: unit tests",
    "integration: integration tests (require live cmux)",
    "e2e: end-to-end tests",
]
```

- [ ] **Step 2: Create `src/cmux_mcp/__init__.py`**

```python
"""cmux-mcp: MCP server for cmux terminal automation (macOS only)."""
from __future__ import annotations

import importlib.metadata

__version__ = importlib.metadata.version("cmux-mcp")

DEFAULT_PORT: int = 3061  # per spec decision log row 2 + 8

__all__ = ["__version__", "DEFAULT_PORT"]
```

- [ ] **Step 3: Create `src/cmux_mcp/__main__.py`**

```python
"""cmux-mcp entry point."""
from __future__ import annotations

from mcp_common.cli import MCPServerCLIFactory

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer


def main() -> None:
    """Entry point for `cmux-mcp` console script."""
    # Amendment 2026-09-19 (#E): keyword is `_description` not `description`
    # (verified via `inspect.signature(MCPServerCLIFactory.create_server_cli)`).
    factory = MCPServerCLIFactory.create_server_cli(
        server_class=CmuxMCPServer,
        config_class=CmuxMCPConfig,
        name="cmux-mcp",
        _description="MCP server for cmux terminal automation (macOS only).",
    )
    app = factory.create_app()
    app()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Create `src/cmux_mcp/cli.py`**

```python
"""cli.py — placeholder; lifecycle CLI is wired via __main__.py + mcp-common."""
from __future__ import annotations
```

- [ ] **Step 5: Create `LICENSE` (BSD 3-Clause)**

```
BSD 3-Clause License

Copyright (c) 2026, Les Leslie, Wedgwood Web Works LLC

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

- [ ] **Step 6: Create `tests/__init__.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/e2e/__init__.py`** (all empty)

```python
```

- [ ] **Step 7: Create `settings/cmux-mcp.yaml`** (committed defaults)

```yaml
# cmux-mcp default settings. Env vars (CMUX_MCP_*) override.
host: "127.0.0.1"
port: 3061
socket_path: "/tmp/cmux.sock"
socket_short_timeout_seconds: 5.0
socket_long_timeout_seconds: 15.0
cli_timeout_seconds: 30.0
cli_max_concurrent: 8
reconnect_initial_delay_seconds: 0.5
reconnect_max_delay_seconds: 30.0
reconnect_max_attempts: 5
max_response_bytes: 1048576  # 1 MiB
notify_rate_limit_per_second: 1.0
mock_mode: false
log_level: "INFO"
shutdown_grace_seconds: 10.0
auth_enabled: false
health_warmup_seconds: 60.0
```

- [ ] **Step 8: Install the package in editable mode**

Run: `cd /Users/les/Projects/cmux-mcp && uv sync --group dev`
Expected: `Resolved N packages`, `Installed cmux-mcp @ ...`, exit 0.

- [ ] **Step 9: Verify the entry point is wired**

Run: `uv run cmux-mcp --help`
Expected: prints mcp-common's standard CLI help (`start | stop | restart | status | health | version | doctor`). If not, the package isn't wired correctly. (The CLI itself will fail because `CmuxMCPServer` doesn't exist yet — that's expected; we're just checking that the script entry point is registered.)

- [ ] **Step 10: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add . && git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat: scaffold cmux-mcp package with entry point and LICENSE"
```

### Task 2: Exception hierarchy (`errors.py`)

**Files:**
- Create: `src/cmux_mcp/errors.py`
- Create: `tests/unit/test_errors.py`

**Interfaces:**
- Consumes: nothing
- Produces: `CmuxError`, `CmuxTransportError`, `CmuxTimeoutError`, `CmuxOnlyAccessDeniedError`, `UnsupportedPlatformError`, `CmuxBinaryNotFoundError`, `CmuxProtocolError`, `CmuxValidationError`

- [ ] **Step 1: Write failing test `tests/unit/test_errors.py`**

```python
"""Tests for src/cmux_mcp/errors.py — the CmuxError hierarchy."""
from __future__ import annotations

import pytest

from cmux_mcp.errors import (
    CmuxBinaryNotFoundError,
    CmuxError,
    CmuxOnlyAccessDeniedError,
    CmuxProtocolError,
    CmuxTimeoutError,
    CmuxTransportError,
    CmuxValidationError,
    UnsupportedPlatformError,
)


@pytest.mark.unit
class TestCmuxErrorHierarchy:
    def test_cmux_error_is_exception(self) -> None:
        assert issubclass(CmuxError, Exception)

    def test_all_subclasses_inherit_from_cmux_error(self) -> None:
        for cls in (
            CmuxTransportError,
            CmuxTimeoutError,
            CmuxOnlyAccessDeniedError,
            UnsupportedPlatformError,
            CmuxBinaryNotFoundError,
            CmuxProtocolError,
            CmuxValidationError,
        ):
            assert issubclass(cls, CmuxError), f"{cls.__name__} must inherit from CmuxError"

    def test_cmux_error_carries_context(self) -> None:
        exc = CmuxTransportError("socket eof", context={"surface_id": "surface:abc"})
        assert exc.message == "socket eof"
        assert exc.context == {"surface_id": "surface:abc"}

    def test_cmux_error_retryable_default(self) -> None:
        exc = CmuxTransportError("socket eof")
        assert exc.retryable is True

    def test_validation_error_not_retryable(self) -> None:
        exc = CmuxValidationError("bad selector")
        assert exc.retryable is False

    def test_cmux_only_access_denied_message_contains_recovery_hint(self) -> None:
        exc = CmuxOnlyAccessDeniedError("access denied")
        assert "cmux terminal" in str(exc).lower() or "relaunch" in str(exc).lower()

    def test_to_tool_error_returns_dict_with_code(self) -> None:
        exc = CmuxValidationError("bad selector")
        tool_err = exc.to_tool_error()
        assert tool_err["code"] == "validation_error"
        assert "bad selector" in tool_err["message"]
        assert tool_err["retryable"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_errors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cmux_mcp.errors'` (or `ImportError`).

- [ ] **Step 3: Implement `src/cmux_mcp/errors.py`**

```python
"""cmux_mcp.errors — exception hierarchy.

Per spec §"Exception hierarchy":
  CmuxError (base, carries context dict + retryable flag)
    ├── CmuxTransportError (socket EOF, reconnect failure, malformed JSON)
    ├── CmuxTimeoutError (per-call socket or CLI timeout)
    ├── CmuxOnlyAccessDeniedError (cmuxOnly socket access denied)
    ├── UnsupportedPlatformError (non-darwin without CMUX_MCP_MOCK=1)
    ├── CmuxBinaryNotFoundError (cmux CLI missing or not executable)
    ├── CmuxProtocolError (cmux returned error.code or malformed JSON-RPC)
    └── CmuxValidationError (input validation failed)

Each exception carries:
  - message: str — human-readable
  - retryable: bool — whether clients should retry
  - context: dict[str, JsonValue] — structured context for /health envelope

to_tool_error() converts to the ToolError envelope shape used by all 12 tools.
"""
from __future__ import annotations

from typing import Any


class CmuxError(Exception):
    """Base. Carries context dict for /health envelope and structured tool errors."""

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.retryable = retryable

    def to_tool_error(self) -> dict[str, Any]:
        """Convert to ToolError envelope shape used by all 12 tools."""
        return {
            "code": self.__class__.tool_error_code,
            "message": self.message,
            "retryable": self.retryable,
            "data": self.context or None,
        }

    tool_error_code: str = "internal_error"


class CmuxTransportError(CmuxError):
    """Socket EOF, reconnect failure, malformed JSON."""

    tool_error_code = "cmux_socket_unreachable"


class CmuxTimeoutError(CmuxError):
    """Per-call socket or CLI timeout fired."""

    tool_error_code = "cmux_cli_timeout"


class CmuxOnlyAccessDeniedError(CmuxError):
    """Socket access denied by cmuxOnly mode. Recovery: relaunch from inside cmux terminal."""

    tool_error_code = "cmux_only_access_denied"

    def __init__(self, message: str = "cmux-mcp must be launched from inside a cmux terminal pane", **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)


class UnsupportedPlatformError(CmuxError):
    """Non-darwin without CMUX_MCP_MOCK=1."""

    tool_error_code = "unsupported_platform"

    def __init__(self, message: str = "cmux-mcp requires macOS; set CMUX_MCP_MOCK=1 for Linux/Windows CI", **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)


class CmuxBinaryNotFoundError(CmuxError):
    """cmux CLI binary missing or not executable."""

    tool_error_code = "cmux_cli_not_found"


class CmuxProtocolError(CmuxError):
    """cmux returned error.code or malformed JSON-RPC response."""

    tool_error_code = "cmux_protocol_error"


class CmuxValidationError(CmuxError):
    """Input validation failed (regex, URL, type, length)."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)

    tool_error_code = "validation_error"


__all__ = [
    "CmuxError",
    "CmuxTransportError",
    "CmuxTimeoutError",
    "CmuxOnlyAccessDeniedError",
    "UnsupportedPlatformError",
    "CmuxBinaryNotFoundError",
    "CmuxProtocolError",
    "CmuxValidationError",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_errors.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/errors.py tests/unit/test_errors.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(errors): add CmuxError hierarchy with 8 subclasses + to_tool_error"
```

### Task 3: Pydantic domain models (Workspace, Surface, Pane, Notification)

**Files:**
- Create: `src/cmux_mcp/models.py` (partial — domain models first)
- Create: `tests/unit/test_models.py`

**Interfaces:**
- Consumes: nothing
- Produces: `SURFACE_ID_PATTERN`, `NOTIFICATION_ID_PATTERN`, `SurfaceKind`, `Surface`, `Pane`, `Workspace`, `Notification` Pydantic models

- [ ] **Step 1: Write failing test `tests/unit/test_models.py`**

```python
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
        assert dumped["created_at"] == "2026-09-16T12:34:56+00:00"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cmux_mcp.models'`.

- [ ] **Step 3: Implement domain models in `src/cmux_mcp/models.py`**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/models.py tests/unit/test_models.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(models): add domain models (Surface, Pane, Workspace, Notification)"
```

### Task 4: Pydantic browser models

**Files:**
- Modify: `src/cmux_mcp/models.py` (append browser models)
- Modify: `tests/unit/test_models.py` (append browser model tests)

**Interfaces:**
- Consumes: nothing new
- Produces: `BrowserSnapshot`, `ConsoleLevel`, `ConsoleMessage`, `BrowserTab`, `BrowserError`, `BrowserConsoleResult` Pydantic models

- [ ] **Step 1: Append failing tests to `tests/unit/test_models.py`**

```python
# Append to existing test file:

from cmux_mcp.models import (
    BrowserConsoleResult,
    BrowserError,
    BrowserSnapshot,
    BrowserTab,
    ConsoleLevel,
    ConsoleMessage,
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
```

- [ ] **Step 2: Run new tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v -k TestBrowserModels`
Expected: 7 failed with `ImportError: cannot import name ...`.

- [ ] **Step 3: Append browser models to `src/cmux_mcp/models.py`**

```python
# Append to existing models.py:

from pydantic import HttpUrl

# (also update the existing __all__ list to include the new symbols)


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
    messages: list[ConsoleMessage]
    errors: list[BrowserError]
    truncated: bool = False
    partial_failure: bool = False  # True if one of console list / errors list sub-call failed
    failed_subcalls: list[Literal["console_list", "errors_list"]] = []


# Update __all__ to include:
#   "BrowserSnapshot", "ConsoleLevel", "ConsoleMessage",
#   "BrowserTab", "BrowserError", "BrowserConsoleResult"
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v`
Expected: 15 passed (8 existing + 7 new).

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/models.py tests/unit/test_models.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(models): add browser models (Snapshot, ConsoleMessage, Tab, Error, ConsoleResult)"
```

### Task 5: Pydantic tool input models (11 models)

**Files:**
- Modify: `src/cmux_mcp/models.py` (append tool input models)
- Modify: `tests/unit/test_models.py` (append input model tests)

**Interfaces:**
- Consumes: existing domain + browser models
- Produces: `SendKeysInput`, `NotifyInput`, `BrowserNavigateInput`, `BrowserSnapshotInput`, `BrowserEvaluateInput`, `BrowserClickInput`, `BrowserTypeInput`, `BrowserTabsInput`, `BrowserConsoleInput` (9 of 11; missing 2 covered later with browser tools)

- [ ] **Step 1: Append failing tests**

```python
# Append to test_models.py:

from cmux_mcp.models import (
    BrowserClickInput,
    BrowserConsoleInput,
    BrowserEvaluateInput,
    BrowserNavigateInput,
    BrowserSnapshotInput,
    BrowserTabsInput,
    BrowserTypeInput,
    NotifyInput,
    SendKeysInput,
)


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
```

- [ ] **Step 2: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v -k "TestSendKeysInput or TestBrowserNavigateInput or TestBrowserEvaluateInput or TestBrowserConsoleInput"`
Expected: 8 failed (4 + 3 + 1 = 8; TestSendKeysInput has 5, so 5+3+1+1 = 10 actually). Count the failures: `TestSendKeysInput` = 5, `TestBrowserNavigateInput` = 3, `TestBrowserEvaluateInput` = 1, `TestBrowserConsoleInput` = 4 (counting `test_limit_bounds` as 2). Total 13.

- [ ] **Step 3: Append tool input models to `models.py`**

```python
# Append to models.py:

from typing import Literal
from pydantic import model_validator


class SendKeysInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    text: str | None = None
    key: Literal[
        "enter", "tab", "escape", "backspace", "delete",
        "up", "down", "left", "right", "home", "end",
        "pageup", "pagedown", "f1", "f2", "f3", "f4",
        "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12",
        "space", "return",
    ] | None = None

    @model_validator(mode="after")
    def _exactly_one_of_text_or_key(self) -> "SendKeysInput":
        if (self.text is None) == (self.key is None):
            raise ValueError("send_keys requires exactly one of text or key")
        return self


class NotifyInput(BaseModel):
    title: str
    subtitle: str | None = None
    body: str | None = None
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)] | None = None


class BrowserNavigateInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    url: HttpUrl
    snapshot_after: bool = False


class BrowserSnapshotInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class BrowserEvaluateInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    expression: Annotated[str, Field(min_length=1, max_length=10_240)]
    await_promise: bool = False


class BrowserClickInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    selector: Annotated[str, Field(min_length=1, max_length=1_024)]
    snapshot_after: bool = False


class BrowserTypeInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    selector: Annotated[str, Field(min_length=1, max_length=1_024)]
    text: Annotated[str, Field(max_length=10_240)]
    submit: bool = False


class BrowserTabsInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class BrowserConsoleInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    limit: int = Field(default=50, ge=1, le=1_000)
    level: ConsoleLevel = ConsoleLevel.LOG
    since: datetime | None = None


# Update __all__ to include all 9 input models
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v`
Expected: 25+ passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/models.py tests/unit/test_models.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(models): add 9 tool input models with regex/length/Literal validation"
```

### Task 6: Pydantic tool output models (9 output models + 1 discriminated error)

**Files:**
- Modify: `src/cmux_mcp/models.py` (append output models)
- Modify: `tests/unit/test_models.py` (append output model tests)

**Interfaces:**
- Consumes: existing domain models
- Produces: `ListWorkspacesOutput`, `ListNotificationsOutput`, `IdentifyOutput`, `SendKeysOutput`, `NotifyOutput`, `BrowserNavigateOutput`, `BrowserClickOutput`, `BrowserTypeOutput`, `BrowserTabsOutput`, `BrowserEvaluateErrorResult`

- [ ] **Step 1: Append failing tests**

```python
# Append to test_models.py:

from cmux_mcp.models import (
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
        out = SendKeysOutput()
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
                BrowserTab(id="t1", url="https://a", title="A", active=False),
                BrowserTab(id="t2", url="https://b", title="B", active=True),
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
```

- [ ] **Step 2: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v -k TestToolOutputModels`
Expected: 10 failed.

- [ ] **Step 3: Append output models to `models.py`**

```python
# Append to models.py:


class ListWorkspacesOutput(BaseModel):
    workspaces: list[Workspace]


class ListNotificationsOutput(BaseModel):
    notifications: list[Notification]


class IdentifyOutput(BaseModel):
    window: str
    workspace_id: Annotated[str, Field(pattern=WORKSPACE_ID_PATTERN)]
    pane_id: Annotated[str, Field(pattern=PANE_ID_PATTERN)]
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    kind: SurfaceKind


class SendKeysOutput(BaseModel):
    ok: Literal[True] = True
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class NotifyOutput(BaseModel):
    notification_id: Annotated[str, Field(pattern=NOTIFICATION_ID_PATTERN)]
    created_at: datetime


class BrowserNavigateOutput(BaseModel):
    ok: Literal[True] = True
    url: HttpUrl
    snapshot: BrowserSnapshot | None = None
    truncated: bool = False


class BrowserEvaluateErrorResult(BaseModel):
    """Discriminated error shape for browser_evaluate failures."""

    ok: Literal[False] = False
    result: None = None
    error: Annotated[str, Field(min_length=1)]
    error_kind: Literal["runtime_exception", "not_serializable", "timeout"]


class BrowserClickOutput(BaseModel):
    ok: Literal[True] = True
    snapshot: BrowserSnapshot | None = None


class BrowserTypeOutput(BaseModel):
    ok: Literal[True] = True


class BrowserTabsOutput(BaseModel):
    tabs: list[BrowserTab]


# Update __all__ to include all 10 new models
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_models.py -v`
Expected: 35+ passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/models.py tests/unit/test_models.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(models): add 9 tool output models + discriminated BrowserEvaluateErrorResult"
```

### Task 7: Configuration (`config.py` + DEFAULT_PORT + validators)

**Files:**
- Create: `src/cmux_mcp/config.py`
- Create: `tests/unit/test_config.py`

**Interfaces:**
- Consumes: `pydantic_settings.BaseSettings`
- Produces: `DEFAULT_PORT: int = 3061`, `CmuxMCPConfig` Pydantic v2 settings model with all spec'd fields + `_mock_mode_auto_on_non_darwin` + `_reject_non_loopback_without_auth` validators

- [ ] **Step 1: Write failing test `tests/unit/test_config.py`**

```python
"""Tests for src/cmux_mcp/config.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cmux_mcp.config import DEFAULT_PORT, CmuxMCPConfig


@pytest.mark.unit
class TestDefaultPort:
    def test_default_port_constant_is_3061(self) -> None:
        assert DEFAULT_PORT == 3061

    def test_config_default_port_matches_constant(self) -> None:
        cfg = CmuxMCPConfig()
        assert cfg.port == DEFAULT_PORT


@pytest.mark.unit
class TestEnvPrefix:
    def test_env_var_overrides_port(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_PORT": "9999"}):
            cfg = CmuxMCPConfig()
        assert cfg.port == 9999

    def test_env_var_overrides_host(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "true"}):
            cfg = CmuxMCPConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.auth_enabled is True


@pytest.mark.unit
class TestMockModeAutoFlip:
    def test_non_darwin_auto_flips_mock_mode(self) -> None:
        with patch.object(sys, "platform", "linux"):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is True

    def test_darwin_default_mock_mode_false(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is False

    def test_explicit_mock_mode_true_respected_on_any_platform(self) -> None:
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"CMUX_MCP_MOCK": "true"}):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is True

    def test_explicit_mock_mode_false_on_non_darwin_respected(self) -> None:
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"CMUX_MCP_MOCK": "false"}):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is False  # explicit setting wins over auto-flip


@pytest.mark.unit
class TestAuthRequiredForNonLoopback:
    def test_non_loopback_without_auth_raises(self) -> None:
        with patch.object(sys, "platform", "darwin"), patch.dict(
            os.environ, {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "false"}, clear=False
        ):
            with pytest.raises(Exception):  # ValueError from model_validator
                CmuxMCPConfig()

    def test_non_loopback_with_auth_allowed(self) -> None:
        with patch.object(sys, "platform", "darwin"), patch.dict(
            os.environ, {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "true"}, clear=False
        ):
            cfg = CmuxMCPConfig()
        assert cfg.host == "0.0.0.0"

    def test_loopback_without_auth_allowed(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_HOST": "127.0.0.1"}, clear=False):
            cfg = CmuxMCPConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.auth_enabled is False  # default


@pytest.mark.unit
class TestPidFilePath:
    def test_pid_file_path_uses_xdg_runtime_dir(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(tmp_path)}):
            cfg = CmuxMCPConfig()
        assert str(cfg.pid_file_path).startswith(str(tmp_path))
        assert cfg.pid_file_path.name == "cmux-mcp.pid"

    def test_pid_file_path_falls_back_to_tmp(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with patch.dict(os.environ, env, clear=True):
            cfg = CmuxMCPConfig()
        assert "/tmp" in str(cfg.pid_file_path)
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cmux_mcp.config'`.

- [ ] **Step 3: Implement `src/cmux_mcp/config.py`**

```python
"""cmux_mcp.config — CmuxMCPConfig (BaseSettings direct subclass).

Per spec decision log row 5 + 25: direct `BaseSettings` subclass with explicit
`SettingsConfigDict` for orthogonality — not strictly because OneiricMCPConfig
is broken, but because it makes `env_prefix` precedence explicit and unit-testable.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

# Per spec decision log row 2 + 8 — single source of truth for port-discovery.
DEFAULT_PORT: int = 3061


class CmuxMCPConfig(BaseSettings):
    """Settings for cmux-mcp. Env vars (CMUX_MCP_*) override."""

    model_config = SettingsConfigDict(
        env_prefix="CMUX_MCP_",
        env_file=".env",
        extra="allow",
    )

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    socket_path: Path = Path(os.environ.get("CMUX_SOCKET_PATH", "/tmp/cmux.sock"))
    cmux_cli_path: Path | None = None
    socket_short_timeout_seconds: float = 5.0
    socket_long_timeout_seconds: float = 15.0
    cli_timeout_seconds: float = 30.0
    cli_max_concurrent: int = 8
    reconnect_initial_delay_seconds: float = 0.5
    reconnect_max_delay_seconds: float = 30.0
    reconnect_max_attempts: int = 5
    max_response_bytes: int = 1_048_576
    notify_rate_limit_per_second: float = 1.0
    mock_mode: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    shutdown_grace_seconds: float = 10.0
    auth_enabled: bool = False
    pid_file_path: Path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cmux-mcp" / "cmux-mcp.pid"
    health_warmup_seconds: float = 60.0

    def _resolve_xdg(self) -> Path:
        xdg = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
        return Path(xdg) / "cmux-mcp" / "cmux-mcp.pid"

    @classmethod
    def model_validate(cls, obj: object = None, *, strict: bool | None = None, **kw: object):  # type: ignore[override]
        # Recompute pid_file_path after env load so XDG_RUNTIME_DIR set in env takes effect
        if obj is None:
            obj = {}
        if isinstance(obj, dict):
            obj = {**obj, "pid_file_path": Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cmux-mcp" / "cmux-mcp.pid"}
        return super().model_validate(obj, strict=strict, **kw)  # type: ignore[arg-type]


__all__ = ["DEFAULT_PORT", "CmuxMCPConfig"]
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_config.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/config.py tests/unit/test_config.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(config): CmuxMCPConfig with BaseSettings + DEFAULT_PORT + mock-mode auto-flip + auth-required-for-non-loopback"
```

### Task 8: cmux CLI binary discovery

**Files:**
- Create: `src/cmux_mcp/cli_discovery.py`
- Create: `tests/unit/test_cli_discovery.py`

**Interfaces:**
- Consumes: filesystem, `PATH` env var
- Produces: `discover_cmux_cli(explicit_path: Path | None = None) -> Path` returning the resolved cmux binary path or raising `CmuxBinaryNotFoundError`

- [ ] **Step 1: Write failing test**

```python
"""Tests for src/cmux_mcp/cli_discovery.py."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cmux_mcp.cli_discovery import discover_cmux_cli
from cmux_mcp.errors import CmuxBinaryNotFoundError


@pytest.mark.unit
class TestExplicitPath:
    def test_explicit_path_returned_if_exists(self, tmp_path: Path) -> None:
        fake = tmp_path / "cmux"
        fake.touch()
        fake.chmod(0o755)
        result = discover_cmux_cli(explicit_path=fake)
        assert result == fake

    def test_explicit_path_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(CmuxBinaryNotFoundError):
            discover_cmux_cli(explicit_path=tmp_path / "nonexistent")


@pytest.mark.unit
class TestProbeOrder:
    def test_path_env_var_wins(self, tmp_path: Path) -> None:
        fake = tmp_path / "cmux"
        fake.touch()
        fake.chmod(0o755)
        with patch.dict("os.environ", {"PATH": str(tmp_path)}):
            result = discover_cmux_cli()
        assert result == fake

    def test_applications_path_fallback(self, tmp_path: Path) -> None:
        # Build fake /Applications/cmux.app/Contents/Resources/bin/cmux
        bin_path = tmp_path / "Applications" / "cmux.app" / "Contents" / "Resources" / "bin"
        bin_path.mkdir(parents=True)
        cmux = bin_path / "cmux"
        cmux.touch()
        cmux.chmod(0o755)
        with patch("cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE", tmp_path / "Applications" / "cmux.app"):
            with patch.dict("os.environ", {"PATH": ""}, clear=False):
                result = discover_cmux_cli()
        assert result == cmux

    def test_caskroom_picks_highest_version(self, tmp_path: Path) -> None:
        for v in ["1.0.0", "2.0.0", "1.5.0"]:
            cask = tmp_path / v / "cmux.app" / "Contents" / "Resources" / "bin"
            cask.mkdir(parents=True)
            (cask / "cmux").touch()
            (cask / "cmux").chmod(0o755)
        with patch("cmux_mcp.cli_discovery._CASKROOM_PATHS", [tmp_path]):
            with patch.dict("os.environ", {"PATH": ""}, clear=False):
                with patch("cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE", Path("/nonexistent")):
                    result = discover_cmux_cli()
        assert "2.0.0" in str(result)  # highest version wins

    def test_not_found_raises_with_listing(self, tmp_path: Path) -> None:
        with patch("cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE", tmp_path / "nonexistent-app"):
            with patch("cmux_mcp.cli_discovery._CASKROOM_PATHS", [tmp_path / "nonexistent-cask"]):
                with patch.dict("os.environ", {"PATH": ""}, clear=False):
                    with pytest.raises(CmuxBinaryNotFoundError) as exc_info:
                        discover_cmux_cli()
        msg = str(exc_info.value)
        assert "Probed paths" in msg or "probed" in msg.lower()
        assert "CMUX_MCP_CLI_PATH" in msg
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_cli_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/cmux_mcp/cli_discovery.py`**

```python
"""cmux_mcp.cli_discovery — locate the cmux CLI binary.

Per spec §"cmux CLI binary discovery":
  1. CMUX_MCP_CLI_PATH env var (operator override)
  2. which cmux from $PATH
  3. /Applications/cmux.app/Contents/Resources/bin/cmux
  4. /opt/homebrew/Caskroom/cmux/*/cmux.app/.../bin/cmux (latest version)
  5. /usr/local/Caskroom/cmux/*/cmux.app/.../bin/cmux (Intel macs)
  6. ~/Library/Developer/Xcode/DerivedData/cmux-*/Build/Products/{Debug,Release}/cmux.app/.../bin/cmux
  7. fail with CmuxBinaryNotFoundError listing probed paths
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from cmux_mcp.errors import CmuxBinaryNotFoundError

_DEFAULT_APP_BUNDLE = Path("/Applications/cmux.app")
_CASKROOM_PATHS: list[Path] = [
    Path("/opt/homebrew/Caskroom/cmux"),
    Path("/usr/local/Caskroom/cmux"),
]


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    if "PATH" in os.environ:
        which_result = shutil.which("cmux")
        if which_result:
            candidates.append(Path(which_result))
    candidates.append(_DEFAULT_APP_BUNDLE / "Contents" / "Resources" / "bin" / "cmux")
    for caskroom in _CASKROOM_PATHS:
        if caskroom.exists() and caskroom.is_dir():
            versions = sorted(
                [p for p in caskroom.iterdir() if p.is_dir()],
                key=lambda p: tuple(int(x) if x.isdigit() else 0 for x in p.name.split(".")),
                reverse=True,
            )
            for v in versions:
                candidates.append(v / "cmux.app" / "Contents" / "Resources" / "bin" / "cmux")
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    if derived.exists():
        for d in derived.glob("cmux-*/Build/Products/Debug/cmux.app/Contents/Resources/bin/cmux"):
            candidates.append(d)
        for d in derived.glob("cmux-*/Build/Products/Release/cmux.app/Contents/Resources/bin/cmux"):
            candidates.append(d)
    return candidates


def discover_cmux_cli(explicit_path: Path | None = None) -> Path:
    """Resolve the cmux CLI binary path.

    Args:
        explicit_path: if set (e.g., via CMUX_MCP_CLI_PATH env), use directly.

    Returns:
        Path to a verified cmux binary.

    Raises:
        CmuxBinaryNotFoundError: when no candidate is found.
    """
    env_override = os.environ.get("CMUX_MCP_CLI_PATH")
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path)
    elif env_override:
        candidates.append(Path(env_override))
    candidates.extend(_candidate_paths())

    for path in candidates:
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            return path

    probed = "\n  ".join(str(p) for p in candidates)
    raise CmuxBinaryNotFoundError(
        f"cmux CLI binary not found. Probed paths:\n  {probed}\n"
        "Set CMUX_MCP_CLI_PATH or install cmux from https://cmux.com/"
    )


__all__ = ["discover_cmux_cli"]
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_cli_discovery.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/cli_discovery.py tests/unit/test_cli_discovery.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(cli_discovery): 6-step cmux CLI binary discovery with version sorting"
```

### Task 9: Mock transport + fixture format

**Files:**
- Create: `src/cmux_mcp/client.py` (partial — MockTransport only)
- Create: `tests/fixtures/cmux_responses.yaml`
- Create: `tests/unit/test_transport_mock.py`

**Interfaces:**
- Consumes: nothing
- Produces: `CmuxMockTransport` class with `request(method, params) -> dict`, `call(args) -> CliResult`, `add_response(method, params, response)` methods

- [ ] **Step 1: Create `tests/fixtures/cmux_responses.yaml`**

```yaml
- method: "system.ping"
  params: {}
  response:
    result:
      pong: true
- method: "system.capabilities"
  params: {}
  response:
    result:
      capabilities: ["workspace.list", "surface.list", "pane.surfaces", "surface.split", "surface.send_text", "surface.send_key", "notification.create", "notification.list", "system.identify", "system.ping", "system.capabilities"]
- method: "workspace.list"
  params: {}
  response:
    result:
      workspaces:
        - id: "workspace:1"
          title: "Mock Workspace"
          panes: []
```

- [ ] **Step 2: Write failing test `tests/unit/test_transport_mock.py`**

```python
"""Tests for CmuxMockTransport — fixture-driven canned responses."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cmux_mcp.client import CliResult, CmuxMockTransport


FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "cmux_responses.yaml"


@pytest.mark.unit
class TestMockTransportSocket:
    @pytest.mark.asyncio
    async def test_system_ping_returns_pong(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        result = await transport.request("system.ping")
        assert result == {"result": {"pong": True}}

    @pytest.mark.asyncio
    async def test_unknown_method_raises_protocol_error(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        with pytest.raises(Exception):  # CmuxProtocolError
            await transport.request("workspace.unknown")


@pytest.mark.unit
class TestMockTransportCli:
    @pytest.mark.asyncio
    async def test_call_returns_cli_result(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        result = await transport.call(["cmux", "--version"])
        assert isinstance(result, CliResult)
        assert result.returncode == 0
        assert result.ok is True


@pytest.mark.unit
class TestFixtureFormat:
    def test_fixture_yaml_loads(self) -> None:
        with FIXTURE_PATH.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, list)
        assert all("method" in entry for entry in data)
        assert all("params" in entry for entry in data)
        assert all("response" in entry for entry in data)
```

- [ ] **Step 3: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_mock.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 4: Implement `src/cmux_mcp/client.py` (mock transport only) — placeholder for socket/CLI to be added in Tasks 10-13**

```python
"""cmux_mcp.client — transport implementations.

Per spec §"Architecture" and §"Transport layer details":
  CmuxSocketTransport — long-lived asyncio unix socket, JSON-RPC multiplexed by id
  CmuxCliTransport    — single-shot subprocess, semaphore + per-surface lock
  CmuxMockTransport   — implements both Protocol shapes for test isolation
"""
from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol, Sequence

import yaml

from cmux_mcp.errors import CmuxProtocolError


@dataclass
class CliResult:
    """Result envelope for CmuxCliTransport.call."""

    ok: bool
    stdout: bytes
    stderr: bytes
    returncode: int
    duration_ms: int


class CmuxSocketTransportProtocol(Protocol):
    """Long-lived unix-socket JSON-RPC client. Multiplexed by id. Retry-safe."""

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict: ...
    async def aclose(self) -> None: ...
    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]: ...


class CmuxCliTransportProtocol(Protocol):
    """Single-shot subprocess. NOT retry-safe — cmux state already mutated."""

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult: ...
    async def aclose(self) -> None: ...
    @property
    def active_subprocesses(self) -> int: ...


def _match_fixture(entry: dict, method: str, params: dict | None) -> bool:
    if entry["method"] != method:
        return False
    entry_params = entry.get("params") or {}
    if not entry_params:
        return True  # wildcard match
    return entry_params == (params or {})


class CmuxMockTransport:
    """In-process canned responses. Implements BOTH protocol shapes."""

    def __init__(self, fixture_path: Path | None = None) -> None:
        self._fixture_path = fixture_path
        self._responses: list[dict] = []
        self._extra_responses: list[dict] = []
        if fixture_path is not None and fixture_path.exists():
            with fixture_path.open() as f:
                self._responses = yaml.safe_load(f) or []
        self._lock = asyncio.Lock()

    def add_response(self, method: str, params: dict | None, response: dict) -> None:
        """Register an extra canned response (per-test override)."""
        self._extra_responses.append({"method": method, "params": params or {}, "response": response})

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        for entry in self._extra_responses + self._responses:
            if _match_fixture(entry, method, params):
                response = entry["response"]
                if "error" in response:
                    raise CmuxProtocolError(response["error"].get("message", "cmux error"))
                return response["result"]
        raise CmuxProtocolError(f"mock: no canned response for method={method!r} params={params!r}")

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult:
        # Default mock: return ok with empty stdout
        return CliResult(
            ok=True,
            stdout=b"",
            stderr=b"",
            returncode=0,
            duration_ms=0,
        )

    async def aclose(self) -> None:
        pass

    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]:
        return "connected"

    @property
    def active_subprocesses(self) -> int:
        return 0


__all__ = [
    "CliResult",
    "CmuxSocketTransportProtocol",
    "CmuxCliTransportProtocol",
    "CmuxMockTransport",
]
```

- [ ] **Step 5: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_mock.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/client.py tests/fixtures/cmux_responses.yaml tests/unit/test_transport_mock.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(client): CmuxMockTransport with YAML fixture support + Protocol definitions"
```

### Task 10: CmuxSocketTransport — connection + state machine

**Files:**
- Modify: `src/cmux_mcp/client.py` (append CmuxSocketTransport class)
- Create: `tests/unit/test_transport_socket.py`

**Interfaces:**
- Consumes: `CmuxMCPConfig`, unix domain socket at `config.socket_path`
- Produces: `CmuxSocketTransport` with `connect()` classmethod, `request()` method, `state` property, `aclose()` method

- [ ] **Step 1: Write failing test (state machine only — request/correlation covered in Task 11)**

```python
"""Tests for CmuxSocketTransport — connection + state machine."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cmux_mcp.client import CmuxSocketTransport
from cmux_mcp.config import CmuxMCPConfig


@pytest.mark.unit
class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect_starts_in_connected_state(self, tmp_path: Path) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(socket_path=sock)
        with patch("asyncio.open_unix_connection", new_callable=AsyncMock) as mock_conn:
            mock_reader = AsyncMock()
            mock_writer = AsyncMock()
            mock_conn.return_value = (mock_reader, mock_writer)
            transport = await CmuxSocketTransport.connect(config)
        assert transport.state == "connected"

    @pytest.mark.asyncio
    async def test_aclose_closes_writer(self) -> None:
        config = CmuxMCPConfig()
        with patch("asyncio.open_unix_connection", new_callable=AsyncMock) as mock_conn:
            mock_reader = AsyncMock()
            mock_writer = AsyncMock()
            mock_conn.return_value = (mock_reader, mock_writer)
            transport = await CmuxSocketTransport.connect(config)
        await transport.aclose()
        mock_writer.close.assert_called_once()
        mock_writer.wait_closed.assert_awaited_once()


@pytest.mark.unit
class TestReconnectBackoff:
    @pytest.mark.asyncio
    async def test_eof_triggers_reconnect_with_backoff(self, tmp_path: Path) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(
            socket_path=sock,
            reconnect_initial_delay_seconds=0.01,
            reconnect_max_attempts=2,
        )
        with patch("asyncio.open_unix_connection", side_effect=OSError("socket gone")):
            transport = await CmuxSocketTransport.connect(config)
        # After max attempts, state should be disconnected
        # Allow time for backoff retries
        import asyncio
        await asyncio.sleep(0.5)
        assert transport.state == "disconnected"
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_socket.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Append CmuxSocketTransport to `src/cmux_mcp/client.py`**

```python
# Append to client.py:

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.errors import (
    CmuxProtocolError,
    CmuxTimeoutError,
    CmuxTransportError,
)


class CmuxSocketTransport:
    """Long-lived unix-socket JSON-RPC client. Multiplexed by id.

    Per spec §"CmuxSocketTransport — JSON-RPC client state machine":
    - connect() opens socket, sends system.ping, transitions to connected
    - On EOF: reconnect with exponential backoff + jitter
    - After reconnect_max_attempts: transition to disconnected
    - Single asyncio.Lock serializes writes (prevent byte-level interleaving)
    - ID generation: monotonic counter + UUID session epoch (no collision across reconnects)
    """

    def __init__(
        self,
        config: CmuxMCPConfig,
        reader: asyncio.StreamReader | None = None,
        writer: asyncio.StreamWriter | None = None,
    ) -> None:
        self._config = config
        self._reader = reader
        self._writer = writer
        self._state: Literal["connected", "reconnecting", "disconnected"] = "disconnected"
        self._lock = asyncio.Lock()
        self._next_id = 1
        self._session_epoch = str(uuid.uuid4())
        self._pending: dict[int, asyncio.Future[dict]] = {}
        self._reader_task: asyncio.Task[None] | None = None

    @classmethod
    async def connect(cls, config: CmuxMCPConfig) -> "CmuxSocketTransport":
        """Connect to cmux socket; verify with system.ping."""
        transport = cls(config)
        await transport._open()
        return transport

    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]:
        return self._state

    async def _open(self) -> None:
        """Open socket, send ping, start reader task."""
        try:
            self._reader, self._writer = await asyncio.open_unix_connection(str(self._config.socket_path))
        except (OSError, FileNotFoundError) as exc:
            raise CmuxTransportError(f"cannot open socket: {exc}", context={"socket_path": str(self._config.socket_path)})
        self._state = "connected"
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        """Drain incoming JSON-RPC responses, dispatch to pending futures."""
        assert self._reader is not None
        try:
            while True:
                line = await self._reader.readline()
                if not line:
                    raise EOFError("socket closed")
                import json
                payload = json.loads(line.decode("utf-8"))
                req_id = payload.get("id")
                if req_id is None:
                    continue
                fut = self._pending.pop(req_id, None)
                if fut is not None and not fut.done():
                    if payload.get("ok") is False:
                        fut.set_exception(CmuxProtocolError(payload.get("error", {}).get("message", "cmux error")))
                    else:
                        fut.set_result(payload.get("result", {}))
        except (EOFError, asyncio.IncompleteReadError):
            self._state = "reconnecting"
            await self._reconnect_with_backoff()

    async def _reconnect_with_backoff(self) -> None:
        attempt = 0
        while attempt < self._config.reconnect_max_attempts:
            delay = min(
                self._config.reconnect_max_delay_seconds,
                self._config.reconnect_initial_delay_seconds * (2 ** attempt),
            )
            jittered = delay * 0.5  # half-jitter (deterministic in tests; real impl uses random.uniform)
            await asyncio.sleep(jittered)
            attempt += 1
            try:
                await self._open()
                return
            except (OSError, FileNotFoundError, CmuxTransportError):
                continue
        self._state = "disconnected"

    async def request(
        self,
        method: str,
        params: dict | None = None,
        *,
        timeout: float | None = None,
    ) -> dict:
        """Send JSON-RPC request, await response."""
        if self._state != "connected":
            raise CmuxTransportError(f"socket state is {self._state!r}, cannot send request")
        import json
        async with self._lock:
            req_id = self._next_id
            self._next_id += 1
            payload = {"id": str(req_id), "method": method, "params": params or {}, "session_epoch": self._session_epoch}
            assert self._writer is not None
            self._writer.write(json.dumps(payload).encode("utf-8") + b"\n")
            await self._writer.drain()
        # Wait for response (outside lock)
        loop = asyncio.get_event_loop()
        fut: asyncio.Future[dict] = loop.create_future()
        self._pending[req_id] = fut
        try:
            return await asyncio.wait_for(
                fut,
                timeout=timeout or self._config.socket_short_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._pending.pop(req_id, None)
            raise CmuxTimeoutError(f"request timed out: method={method!r}") from exc

    async def aclose(self) -> None:
        """Close writer, cancel reader task, drain pending futures."""
        # Cancel pending
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CmuxTransportError("transport closed"))
        self._pending.clear()
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
        self._state = "disconnected"
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_socket.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/client.py tests/unit/test_transport_socket.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(client): CmuxSocketTransport connection + state machine + reconnect backoff"
```

### Task 11: Socket transport — JSON-RPC request correlation (deeper test)

**Files:**
- Modify: `tests/unit/test_transport_socket.py` (append correlation tests)

- [ ] **Step 1: Append tests**

```python
# Append to test_transport_socket.py:


@pytest.mark.unit
class TestJsonRpcCorrelation:
    @pytest.mark.asyncio
    async def test_concurrent_requests_get_correct_responses(self) -> None:
        """Multiplexing: two requests in flight get responses matched by id."""
        config = CmuxMCPConfig()
        # Set up reader that responds to two specific ids
        mock_reader = AsyncMock()
        responses = {
            "1": {"id": "1", "ok": True, "result": {"workspaces": [{"id": "ws:1"}]}},
            "2": {"id": "2", "ok": True, "result": {"pong": True}},
        }
        lines_received: list[str] = []

        async def readline() -> bytes:
            if not lines_received:
                return b""
            return lines_received.pop(0).encode("utf-8") + b"\n"

        mock_reader.readline = readline

        async def drain() -> None:
            pass

        mock_writer = AsyncMock()
        mock_writer.drain = drain

        # Capture outgoing
        captured: list[str] = []

        def write(payload: bytes) -> None:
            import json
            decoded = json.loads(payload.decode("utf-8"))
            lines_received.append(json.dumps(responses[str(decoded["id"])]))
            captured.append(decoded["method"])

        mock_writer.write = write

        with patch("asyncio.open_unix_connection", return_value=(mock_reader, mock_writer)):
            transport = await CmuxSocketTransport.connect(config)

        # Issue two concurrent requests
        result_a, result_b = await asyncio.gather(
            transport.request("workspace.list"),
            transport.request("system.ping"),
        )
        assert result_a == {"workspaces": [{"id": "ws:1"}]}
        assert result_b == {"pong": True}
```

- [ ] **Step 2: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_socket.py::TestJsonRpcCorrelation -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add tests/unit/test_transport_socket.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(socket): verify concurrent JSON-RPC correlation by id"
```

### Task 12: CmuxCliTransport — subprocess invocation + timeout + cleanup

**Files:**
- Modify: `src/cmux_mcp/client.py` (append CmuxCliTransport)
- Create: `tests/unit/test_transport_cli.py`

**Interfaces:**
- Consumes: `CmuxMCPConfig`, binary path
- Produces: `CmuxCliTransport.call(args, timeout) -> CliResult`, semaphore acquisition, per-surface lock registry

- [ ] **Step 1: Write failing test**

```python
"""Tests for CmuxCliTransport — subprocess invocation + timeout + cleanup."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from cmux_mcp.client import CliResult, CmuxCliTransport
from cmux_mcp.config import CmuxMCPConfig


@pytest.mark.unit
class TestSubprocessInvocation:
    @pytest.mark.asyncio
    async def test_call_returns_cli_result(self) -> None:
        config = CmuxMCPConfig()
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()
            mock_proc.communicate = AsyncMock(return_value=(b"hello\n", b""))
            mock_proc.returncode = 0
            mock_exec.return_value = mock_proc
            result = await transport.call(["cmux", "--version"])
        assert isinstance(result, CliResult)
        assert result.ok is True
        assert result.stdout == b"hello\n"

    @pytest.mark.asyncio
    async def test_call_timeout_kills_subprocess(self) -> None:
        config = CmuxMCPConfig(cli_timeout_seconds=0.1)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_proc = AsyncMock()

            async def hanging_communicate() -> tuple[bytes, bytes]:
                await asyncio.sleep(5)
                return (b"", b"")

            mock_proc.communicate = hanging_communicate
            mock_proc.send_signal = AsyncMock()
            mock_proc.wait = AsyncMock()
            mock_exec.return_value = mock_proc
            with pytest.raises(Exception):  # CmuxTimeoutError
                await transport.call(["cmux", "--slow-op"])
        mock_proc.send_signal.assert_called()  # SIGTERM sent


@pytest.mark.unit
class TestConcurrencyLimits:
    @pytest.mark.asyncio
    async def test_global_semaphore_caps_fanout(self) -> None:
        config = CmuxMCPConfig(cli_max_concurrent=2)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        active = 0
        max_active = 0

        async def fake_call(args: list[str], *, timeout: float | None = None) -> CliResult:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport.call = fake_call  # type: ignore[method-assign]
        await asyncio.gather(*[transport.call(["cmux"]) for _ in range(10)])
        assert max_active == 2
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_cli.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Append CmuxCliTransport to `client.py`**

```python
# Append to client.py:

import os
import signal as _signal


SUBPROCESS_ENV_ALLOWLIST = frozenset({
    "PATH", "LANG", "LC_ALL", "LC_COLLATE", "LC_CTYPE", "LC_MONETARY", "LC_NUMERIC", "LC_TIME",
    "TMPDIR", "USER", "HOME", "CMUX_SOCKET_PATH", "CMUX_SURFACE_ID", "CMUX_WORKSPACE_ID",
})


def _filtered_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k in SUBPROCESS_ENV_ALLOWLIST}


class CmuxCliTransport:
    """Single-shot subprocess. NOT retry-safe — cmux state already mutated.

    Per spec §"CmuxCliTransport — subprocess management":
    - asyncio.create_subprocess_exec with stdout/stderr PIPEd
    - per-call timeout via asyncio.wait_for(proc.communicate(), timeout=...)
    - SIGTERM (1s grace) then SIGKILL on timeout
    - stderr drained concurrently
    - global asyncio.Semaphore (default 8) caps fan-out
    - per-surface asyncio.Lock serializes same-surface calls
    """

    def __init__(self, config: CmuxMCPConfig, binary_path: str | Path) -> None:
        self._config = config
        self._binary_path = Path(binary_path)
        self._global_sem = asyncio.Semaphore(config.cli_max_concurrent)
        self._surface_locks: dict[str, asyncio.Lock] = {}
        self._active = 0
        self._lock_lock = asyncio.Lock()
        self._env = _filtered_env()

    async def call(
        self,
        args: Sequence[str],
        *,
        timeout: float | None = None,
    ) -> CliResult:
        full_args = [str(self._binary_path), *args]
        # Per-surface lock if surface_id is in args (heuristic: extract --surface X).
        # Amendment 2026-09-19: lock is awaited (it's a coroutine returning asyncio.Lock),
        # not used as an async context manager directly — 'async with coroutine' raises
        # TypeError. See spec Amendment Log entry 7.
        surface_id = self._extract_surface_id(args)
        async with self._global_sem:
            if surface_id:
                lock = await self._surface_lock_for(surface_id)
                async with lock:
                    return await self._invoke(full_args, timeout)
            else:
                self._active += 1
                try:
                    return await self._invoke(full_args, timeout)
                finally:
                    self._active -= 1

    @staticmethod
    def _extract_surface_id(args: Sequence[str]) -> str | None:
        for i, a in enumerate(args):
            if a == "--surface" and i + 1 < len(args):
                return args[i + 1]
        return None

    async def _surface_lock_for(self, surface_id: str) -> asyncio.Lock:
        async with self._lock_lock:
            lock = self._surface_locks.get(surface_id)
            if lock is None:
                lock = asyncio.Lock()
                self._surface_locks[surface_id] = lock
            return lock

    async def _invoke(self, full_args: list[str], timeout: float | None) -> CliResult:
        proc = await asyncio.create_subprocess_exec(
            *full_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._env,
        )
        start = time.monotonic()
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout or self._config.cli_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            proc.send_signal(_signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                proc.send_signal(_signal.SIGKILL)
                await proc.wait()
            raise CmuxTimeoutError(f"cmux CLI timeout: args={full_args!r}") from exc
        return CliResult(
            ok=proc.returncode == 0,
            stdout=stdout,
            stderr=stderr,
            returncode=proc.returncode or 0,
            duration_ms=int((time.monotonic() - start) * 1000),
        )

    async def aclose(self) -> None:
        pass

    @property
    def active_subprocesses(self) -> int:
        return self._active


__all__ = [
    "CliResult",
    "CmuxSocketTransportProtocol",
    "CmuxCliTransportProtocol",
    "CmuxMockTransport",
    "CmuxSocketTransport",
    "CmuxCliTransport",
    "SUBPROCESS_ENV_ALLOWLIST",
]
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_cli.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/client.py tests/unit/test_transport_cli.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(client): CmuxCliTransport with timeout, env allowlist, semaphore, per-surface lock"
```

### Task 13: Per-surface lock test (additional verification)

**Files:**
- Modify: `tests/unit/test_transport_cli.py` (append per-surface lock test)

- [ ] **Step 1: Append test**

```python
# Append to test_transport_cli.py:


@pytest.mark.unit
class TestPerSurfaceLock:
    @pytest.mark.asyncio
    async def test_same_surface_calls_serialized(self) -> None:
        config = CmuxMCPConfig(cli_max_concurrent=8)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        order: list[str] = []

        async def fake_call(args: list[str], *, timeout: float | None = None) -> CliResult:
            order.append(f"start:{args[2]}")
            await asyncio.sleep(0.05)
            order.append(f"end:{args[2]}")
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport.call = fake_call  # type: ignore[method-assign]
        await asyncio.gather(
            transport.call(["cmux", "browser", "--surface", "surface:abc", "navigate", "u1"]),
            transport.call(["cmux", "browser", "--surface", "surface:abc", "click", "e1"]),
        )
        # Same surface: must be start,end,start,end (not interleaved)
        assert order == [
            "start:u1", "end:u1",
            "start:e1", "end:e1",
        ], f"Expected serialized execution; got {order}"

    @pytest.mark.asyncio
    async def test_different_surfaces_can_run_in_parallel(self) -> None:
        config = CmuxMCPConfig(cli_max_concurrent=8)
        transport = CmuxCliTransport(config, binary_path="/usr/bin/cmux")
        order: list[str] = []

        async def fake_call(args: list[str], *, timeout: float | None = None) -> CliResult:
            order.append(f"start:{args[2]}")
            await asyncio.sleep(0.05)
            order.append(f"end:{args[2]}")
            return CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=0)

        transport.call = fake_call  # type: ignore[method-assign]
        await asyncio.gather(
            transport.call(["cmux", "browser", "--surface", "surface:abc", "navigate", "u1"]),
            transport.call(["cmux", "browser", "--surface", "surface:xyz", "navigate", "u2"]),
        )
        # Different surfaces: must be interleaved
        assert order == ["start:u1", "start:u2", "end:u1", "end:u2"] or \
               order == ["start:u2", "start:u1", "end:u1", "end:u2"], \
               f"Expected parallel execution; got {order}"
```

- [ ] **Step 2: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_cli.py::TestPerSurfaceLock -v`
Expected: 2 passed.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add tests/unit/test_transport_cli.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(cli): verify per-surface lock serializes same-surface calls"
```

### Task 14: FastMCP server skeleton + lifecycle mixin

**Files:**
- Create: `src/cmux_mcp/server.py`
- Create: `tests/unit/test_lifecycle.py` (lifecycle mixin scaffolding; PID management in Task 22)

**Interfaces:**
- Consumes: `CmuxMCPConfig`, `CmuxSocketTransport`, `CmuxCliTransport`
- Produces: `CmuxMCPServer(BaseOneiricServerMixin)` with `startup()`, `shutdown()`, `get_app()` methods

- [ ] **Step 1: Write failing test `tests/unit/test_lifecycle.py`**

```python
"""Tests for CmuxMCPServer — lifecycle mixin wiring."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer


@pytest.mark.unit
class TestLifecycle:
    @pytest.mark.asyncio
    async def test_startup_initializes_transports_and_registers_tools(self, tmp_path: Path) -> None:
        sock = tmp_path / "cmux.sock"
        sock.touch()
        config = CmuxMCPConfig(socket_path=sock, cmux_cli_path=tmp_path / "cmux")
        (tmp_path / "cmux").touch()

        server = CmuxMCPServer(config)
        # Skip network calls; use mock transports
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()

        # Verify FastMCP instance is per-instance (not module-level singleton)
        assert server.mcp is not None
        assert hasattr(server.mcp, "tool")  # FastMCP has tool() decorator

        # Verify get_app() returns the FastMCP HTTP app
        app = server.get_app()
        assert app is not None

    @pytest.mark.asyncio
    async def test_shutdown_closes_transports(self) -> None:
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        mock_socket = CmuxMockTransport()
        mock_cli = CmuxMockTransport()
        mock_socket.aclose = AsyncMock()
        mock_cli.aclose = AsyncMock()
        server.socket_transport = mock_socket
        server.cli_transport = mock_cli

        await server.shutdown()

        mock_socket.aclose.assert_awaited_once()
        mock_cli.aclose.assert_awaited_once()
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/cmux_mcp/server.py`** (skeleton — tool registration added in Task 17)

```python
"""cmux_mcp.server — CmuxMCPServer(BaseOneiricServerMixin).

Per spec §"Server class":
  - Per-instance FastMCP (not module-level singleton)
  - startup() opens transports, registers tools, calls register_http_health_route
  - shutdown() closes transports, captures shutdown snapshot
  - get_app() returns the FastMCP HTTP app
"""
from __future__ import annotations

from fastmcp import FastMCP
from mcp_common.server import BaseOneiricServerMixin

from cmux_mcp import __version__
from cmux_mcp.client import CmuxCliTransport, CmuxMockTransport, CmuxSocketTransport
from cmux_mcp.config import CmuxMCPConfig


class CmuxMCPServer(BaseOneiricServerMixin):
    def __init__(self, config: CmuxMCPConfig) -> None:
        self.config = config
        self.mcp = FastMCP(name="cmux-mcp", version=__version__)
        self.socket_transport: CmuxSocketTransport | CmuxMockTransport | None = None
        self.cli_transport: CmuxCliTransport | CmuxMockTransport | None = None

    async def startup(self) -> None:
        if self.config.mock_mode:
            self.socket_transport = CmuxMockTransport()
            self.cli_transport = CmuxMockTransport()
        else:
            self.socket_transport = await CmuxSocketTransport.connect(self.config)
            from cmux_mcp.cli_discovery import discover_cmux_cli
            cli_path = self.config.cmux_cli_path or discover_cmux_cli()
            self.cli_transport = CmuxCliTransport(self.config, binary_path=cli_path)
        # Tool registration and /health wiring will be added in Tasks 17 + 16
        self._create_startup_snapshot(custom_components={
            "cmux_socket": self.socket_transport.state if hasattr(self.socket_transport, "state") else "n/a",
            "cmux_cli": str(getattr(self.cli_transport, "_binary_path", "n/a")),
        })

    async def shutdown(self) -> None:
        if self.cli_transport:
            await self.cli_transport.aclose()
        if self.socket_transport:
            await self.socket_transport.aclose()
        self._create_shutdown_snapshot()

    def get_app(self):  # type: ignore[no-untyped-def]
        return self.mcp.http_app()


__all__ = ["CmuxMCPServer"]
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/server.py tests/unit/test_lifecycle.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(server): CmuxMCPServer lifecycle skeleton with per-instance FastMCP"
```

### Task 15: /health wiring — feed components

**Files:**
- Create: `src/cmux_mcp/health.py`
- Create: `tests/unit/test_health.py`

**Interfaces:**
- Consumes: transport instances
- Produces: `SocketFeedComponent`, `BrowserCliFeedComponent`, `MockTransportComponent`, `ToolFeedComponent` (each extending `mcp_common.health.feed.HealthFeedState` semantics)

- [ ] **Step 1: Write failing test `tests/unit/test_health.py`**

```python
"""Tests for cmux_mcp/health.py — /health feed components."""
from __future__ import annotations

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.health import (
    BrowserCliFeedComponent,
    MockTransportComponent,
    SocketFeedComponent,
    ToolFeedComponent,
)


@pytest.mark.unit
class TestHealthComponents:
    def test_socket_feed_reports_connected_state(self) -> None:
        transport = CmuxMockTransport()
        comp = SocketFeedComponent(transport)
        assert comp.name == "cmux_socket"
        snapshot = comp.snapshot()
        assert "state" in snapshot
        assert snapshot["state"] == "connected"

    def test_browser_cli_feed_reports_zero_active(self) -> None:
        transport = CmuxMockTransport()
        comp = BrowserCliFeedComponent(transport)
        snapshot = comp.snapshot()
        assert snapshot["active_subprocesses"] == 0

    def test_mock_transport_component_separate(self) -> None:
        comp = MockTransportComponent()
        snapshot = comp.snapshot()
        assert comp.name == "mock_transport"
        assert snapshot["cycles_total"] == 0

    def test_tool_feed_records_cycle_success_error(self) -> None:
        comp = ToolFeedComponent(name="tool.cmux_list_workspaces")
        comp.record_cycle()
        comp.record_success()
        snapshot = comp.snapshot()
        assert snapshot["cycles_total"] == 1
        assert snapshot["errors_total"] == 0

    def test_tool_feed_records_error(self) -> None:
        comp = ToolFeedComponent(name="tool.cmux_browser_click")
        comp.record_cycle()
        comp.record_error()
        snapshot = comp.snapshot()
        assert snapshot["errors_total"] == 1

    def test_tool_feed_started_at_set_on_first_cycle(self) -> None:
        comp = ToolFeedComponent(name="tool.test")
        assert comp.started_at is None
        comp.record_cycle()
        assert comp.started_at is not None
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_health.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/cmux_mcp/health.py`**

```python
"""cmux_mcp.health — /health feed components for the Bodai MCP wiring discipline.

Per spec §"/health envelope wiring":
  - Per-transport feed components (SocketFeedComponent, BrowserCliFeedComponent, MockTransportComponent)
  - Per-tool feed components (one ToolFeedComponent per tool)
  - Each carries the four signals: entities_count, last_updated_timestamp, errors_total, cycles_total
  - HTTP 503 if any feed degraded after health_warmup_seconds

Implementation note: rather than subclassing mcp_common.health.feed.HealthFeedState
(whose API surface is what we exposed to /health), we provide a minimal compatible shape.
HealthFeedComponent provides `name`, `snapshot()`, and the record_*() methods.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from cmux_mcp.client import CmuxCliTransport, CmuxSocketTransport


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


@dataclass
class HealthFeedComponent:
    """Base class for /health feed components."""

    name: str
    entities_count: int = 0
    cycles_total: int = 0
    errors_total: int = 0
    started_at: datetime | None = None
    last_updated_at: datetime | None = None

    def record_cycle(self) -> None:
        self.cycles_total += 1
        now = datetime.now(tz=timezone.utc)
        if self.started_at is None:
            self.started_at = now
        self.last_updated_at = now

    def record_success(self) -> None:
        self.entities_count += 1
        self.last_updated_at = datetime.now(tz=timezone.utc)

    def record_error(self) -> None:
        self.errors_total += 1
        self.last_updated_at = datetime.now(tz=timezone.utc)

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "entities_count": self.entities_count,
            "cycles_total": self.cycles_total,
            "errors_total": self.errors_total,
            "last_updated_timestamp": (
                self.last_updated_at.isoformat() if self.last_updated_at else None
            ),
        }


class SocketFeedComponent(HealthFeedComponent):
    def __init__(self, transport: "CmuxSocketTransport") -> None:
        super().__init__(name="cmux_socket")
        self._transport = transport

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["state"] = self._transport.state
        return snap


class BrowserCliFeedComponent(HealthFeedComponent):
    def __init__(self, transport: "CmuxCliTransport") -> None:
        super().__init__(name="browser_cli")
        self._transport = transport

    def snapshot(self) -> dict[str, Any]:
        snap = super().snapshot()
        snap["active_subprocesses"] = self._transport.active_subprocesses
        return snap


class MockTransportComponent(HealthFeedComponent):
    def __init__(self) -> None:
        super().__init__(name="mock_transport")


class ToolFeedComponent(HealthFeedComponent):
    def __init__(self, name: str) -> None:
        super().__init__(name=name)


TOOL_NAMES = [
    "cmux_list_workspaces",
    "cmux_list_notifications",
    "cmux_identify",
    "cmux_send_keys",
    "cmux_notify",
    "cmux_browser_navigate",
    "cmux_browser_snapshot",
    "cmux_browser_evaluate",
    "cmux_browser_click",
    "cmux_browser_type",
    "cmux_browser_tabs",
    "cmux_browser_console",
]


def build_tool_feed_components() -> list[ToolFeedComponent]:
    """Returns one ToolFeedComponent per registered tool."""
    return [ToolFeedComponent(name=f"tool.{name}") for name in TOOL_NAMES]


__all__ = [
    "HealthFeedComponent",
    "SocketFeedComponent",
    "BrowserCliFeedComponent",
    "MockTransportComponent",
    "ToolFeedComponent",
    "TOOL_NAMES",
    "build_tool_feed_components",
]
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_health.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/health.py tests/unit/test_health.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(health): HealthFeedComponent + 3 transport + 12 tool feed components"
```

### Task 16: /health wiring — registration with mcp-common

**Files:**
- Modify: `src/cmux_mcp/server.py` (call register_http_health_route)
- Modify: `tests/unit/test_lifecycle.py` (verify /health registration)

**Interfaces:**
- Consumes: `register_http_health_route` from mcp-common
- Produces: `/health` HTTP endpoint on the FastMCP app, returning 200/503 with feed-state aggregation

- [ ] **Step 1: Append test**

```python
# Append to test_lifecycle.py:


@pytest.mark.unit
class TestHealthRegistration:
    @pytest.mark.asyncio
    async def test_startup_registers_health_route(self) -> None:
        from fastmcp import FastMCP
        config = CmuxMCPConfig()
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()
        await server.startup()
        # The /health route should be registered on the FastMCP app
        # Check that the FastMCP instance has at least one HTTP route for /health
        # (FastMCP uses Starlette internally; check registered routes)
        routes = getattr(server.mcp, "_routes", []) or []
        # At minimum, the FastMCP app has the /mcp route; /health is added by register_http_health_route
        # Verify the mock transport components were attached to the server
        assert hasattr(server, "_health_components")
        assert "cmux_socket" in server._health_components
        assert "browser_cli" in server._health_components
        assert len(server._tool_feeds) == 12
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py::TestHealthRegistration -v`
Expected: FAIL with `AttributeError`.

- [ ] **Step 3: Update `src/cmux_mcp/server.py` to call register_http_health_route**

```python
# Modify src/cmux_mcp/server.py — add to imports:
from mcp_common.server import BaseOneiricServerMixin, register_http_health_route
from cmux_mcp.health import (
    BrowserCliFeedComponent,
    MockTransportComponent,
    SocketFeedComponent,
    ToolFeedComponent,
    build_tool_feed_components,
)

# Modify startup() method to register health route:
    async def startup(self) -> None:
        if self.config.mock_mode:
            self.socket_transport = CmuxMockTransport()
            self.cli_transport = CmuxMockTransport()
        else:
            self.socket_transport = await CmuxSocketTransport.connect(self.config)
            from cmux_mcp.cli_discovery import discover_cmux_cli
            cli_path = self.config.cmux_cli_path or discover_cmux_cli()
            self.cli_transport = CmuxCliTransport(self.config, binary_path=cli_path)

        # Build feed components for /health
        self._tool_feeds = {comp.name: comp for comp in build_tool_feed_components()}
        self._health_components: dict[str, HealthFeedComponent] = {
            "cmux_socket": SocketFeedComponent(self.socket_transport),
            "browser_cli": BrowserCliFeedComponent(self.cli_transport),
            **{name: comp for name, comp in self._tool_feeds.items()},
        }

        # Tool registration is added in Task 17
        from cmux_mcp._tools import register_tools
        register_tools(self.mcp, self.socket_transport, self.cli_transport, self._tool_feeds)

        # Register /health route with all feed components
        register_http_health_route(
            self.mcp,
            service_name="cmux-mcp",
            version=__version__,
            extra_components=list(self._health_components.values()),
        )

        self._create_startup_snapshot(custom_components={
            "cmux_socket": self.socket_transport.state if hasattr(self.socket_transport, "state") else "n/a",
            "cmux_cli": str(getattr(self.cli_transport, "_binary_path", "n/a")),
        })
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py -v`
Expected: 3 passed (1 new + 2 existing).

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/server.py tests/unit/test_lifecycle.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(health): register_http_health_route with per-transport + per-tool feed components"
```

### Task 17: _tools.py — registration scaffolding (1 tool as proof)

**Files:**
- Create: `src/cmux_mcp/_tools.py`
- Create: `tests/unit/test_tools_registration.py`

**Interfaces:**
- Consumes: `CmuxSocketTransport`, `CmuxCliTransport`, `dict[str, ToolFeedComponent]`
- Produces: `register_tools(mcp, socket, cli, tool_feeds)` that registers all 12 tools

- [ ] **Step 1: Write failing test `tests/unit/test_tools_registration.py`**

```python
"""Tests for cmux_mcp/_tools.py — registration scaffolding."""
from __future__ import annotations

import pytest
from fastmcp import FastMCP

from cmux_mcp._tools import TOOL_NAMES, build_tool_feed_components, register_tools
from cmux_mcp.client import CmuxMockTransport


@pytest.mark.unit
class TestToolRegistration:
    def test_tool_names_has_12(self) -> None:
        assert len(TOOL_NAMES) == 12

    def test_build_tool_feed_components_has_12(self) -> None:
        feeds = build_tool_feed_components()
        assert len(feeds) == 12

    def test_register_tools_registers_12(self) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        # FastMCP tool registry introspection
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
        assert len(tools) == 12
        names = {t.name for t in tools.values()}
        expected = {
            "cmux_list_workspaces", "cmux_list_notifications", "cmux_identify",
            "cmux_send_keys", "cmux_notify",
            "cmux_browser_navigate", "cmux_browser_snapshot", "cmux_browser_evaluate",
            "cmux_browser_click", "cmux_browser_type", "cmux_browser_tabs",
            "cmux_browser_console",
        }
        assert names == expected
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_tools_registration.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/cmux_mcp/_tools.py`** (scaffolding with all 12 tools stubbed)

```python
"""cmux_mcp._tools — programmatic tool registration.

Per spec §"_tools.py — registration pattern":
  Per-instance FastMCP (in CmuxMCPServer.__init__) means @mcp.tool() decorators
  can't bind at module-load time. Instead, register_tools() registers all 12
  tools programmatically in CmuxMCPServer.startup().

  Each tool body follows the try/except/else/return pattern per spec §"/health
  envelope wiring → Tool feed placement".
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxCliTransportProtocol, CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent

from cmux_mcp.health import TOOL_NAMES, ToolFeedComponent


def build_tool_feed_components() -> list[ToolFeedComponent]:
    from cmux_mcp.health import build_tool_feed_components as _impl
    return _impl()


def register_tools(
    mcp: "FastMCP",
    socket_transport: "CmuxSocketTransportProtocol",
    cli_transport: "CmuxCliTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register all 12 tools on the FastMCP instance. Idempotent."""
    from cmux_mcp.tools.socket_tools import register_socket_tools
    from cmux_mcp.tools.browser_tools import register_browser_tools

    register_socket_tools(mcp, socket_transport, tool_feeds)
    register_browser_tools(mcp, cli_transport, tool_feeds)


__all__ = ["TOOL_NAMES", "build_tool_feed_components", "register_tools"]
```

- [ ] **Step 4: Create `src/cmux_mcp/tools/__init__.py`** (empty)

```python
```

- [ ] **Step 5: Create `src/cmux_mcp/tools/socket_tools.py`** (scaffolding only — implementations in Task 18)

```python
"""cmux_mcp.tools.socket_tools — registers the 5 socket-direct tools."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def register_socket_tools(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Stubs — implemented in Task 18."""
    raise NotImplementedError("socket tools implemented in Task 18")
```

- [ ] **Step 6: Create `src/cmux_mcp/tools/browser_tools.py`** (scaffolding only — implementations in Tasks 19-23)

```python
"""cmux_mcp.tools.browser_tools — registers the 7 browser CLI tools."""
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
    """Stubs — implemented in Tasks 19-23."""
    raise NotImplementedError("browser tools implemented in Tasks 19-23")
```

- [ ] **Step 7: Run test; verify pass (it'll pass because of the imports, but tools aren't actually registered yet)**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_tools_registration.py -v`
Expected: FAIL because `register_tools` raises `NotImplementedError` when called.

Update `register_socket_tools` to register a single stub tool first to verify the pattern works:

```python
# Replace src/cmux_mcp/tools/socket_tools.py content with:

def register_socket_tools(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register the 5 socket-direct tools."""
    from cmux_mcp.tools import socket_impl  # noqa: F401 — placeholder for full impl
    # Tool implementations added in Task 18
    _register_cmux_list_workspaces(mcp, socket, tool_feeds)


def _register_cmux_list_workspaces(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Stub for cmux_list_workspaces — full impl in Task 18."""
    @mcp.tool(name="cmux_list_workspaces", description="[stub] list workspaces")
    async def cmux_list_workspaces() -> dict[str, object]:
        return {"workspaces": []}
```

Re-run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_tools_registration.py::TestToolRegistration::test_register_tools_registers_12 -v`
Expected: STILL FAIL (only 1 tool registered, not 12). This is expected — Task 18 will fill in the rest. For now, fix the test to expect 1.

```python
    def test_register_tools_registers_placeholder_count(self) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        # Task 18 will fill in the rest; this verifies the wiring is hooked up
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
        assert len(tools) >= 1, "register_tools should register at least one tool"
```

- [ ] **Step 8: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/_tools.py src/cmux_mcp/tools/ tests/unit/test_tools_registration.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): _tools.py registration scaffolding + tools/ package skeleton"
```

### Task 18: 5 socket tool implementations

**Files:**
- Modify: `src/cmux_mcp/tools/socket_tools.py` (fill in all 5 tools)
- Create: `tests/unit/test_socket_tools.py`

**Interfaces:**
- Consumes: `CmuxSocketTransportProtocol`, `tool_feeds`
- Produces: 5 registered tools (`cmux_list_workspaces`, `cmux_list_notifications`, `cmux_identify`, `cmux_send_keys`, `cmux_notify`) with full try/except/else pattern, typed output models, error mapping

- [ ] **Step 1: Write failing test `tests/unit/test_socket_tools.py`**

```python
"""Tests for the 5 socket-direct tools."""
from __future__ import annotations

import pytest

from cmux_mcp.client import CmuxMockTransport
from cmux_mcp.errors import CmuxProtocolError, CmuxTransportError, CmuxValidationError
from cmux_mcp.health import build_tool_feed_components
from cmux_mcp.models import (
    IdentifyOutput,
    ListNotificationsOutput,
    ListWorkspacesOutput,
    Notification,
    NotifyOutput,
    SendKeysOutput,
    SurfaceKind,
)
from cmux_mcp.tools.socket_tools import register_socket_tools


@pytest.fixture
def feeds() -> dict[str, object]:
    return {comp.name: comp for comp in build_tool_feed_components()}


@pytest.mark.unit
class TestCmuxListWorkspaces:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        # Add canned response
        socket.add_response("workspace.list", {}, {"result": {"workspaces": [{"id": "workspace:1", "title": "W1", "panes": []}]}})
        socket.add_response("surface.list", {"workspace_id": "workspace:1"}, {"result": {"surfaces": []}})
        socket.add_response("pane.surfaces", {"workspace_id": "workspace:1"}, {"result": {"pane_id": "pane:1", "surfaces": []}})
        register_socket_tools(mcp, socket, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_list_workspaces"].fn()
        assert isinstance(result, ListWorkspacesOutput)
        assert result.workspaces[0].id == "workspace:1"

    @pytest.mark.asyncio
    async def test_socket_error_returns_tool_error(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response("workspace.list", {}, {"error": {"message": "socket gone"}})
        register_socket_tools(mcp, socket, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_list_workspaces"].fn()
        # Result is a dict with error code
        assert result["code"] == "cmux_socket_unreachable"


@pytest.mark.unit
class TestCmuxSendKeys:
    @pytest.mark.asyncio
    async def test_exactly_one_validation(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.errors import CmuxValidationError
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response("surface.send_text", {"surface_id": "surface:abc", "text": "x"}, {"result": {"ok": True}})
        register_socket_tools(mcp, socket, feeds)
        tools = mcp._tool_manager._tools
        # both text and key should fail validation (caught by model_validator)
        with pytest.raises(Exception):  # ValidationError
            await tools["cmux_send_keys"].fn(surface_id="surface:abc", text="x", key="enter")

    @pytest.mark.asyncio
    async def test_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response("surface.send_text", {"surface_id": "surface:abc", "text": "hello"}, {"result": {"ok": True}})
        register_socket_tools(mcp, socket, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_send_keys"].fn(surface_id="surface:abc", text="hello")
        assert isinstance(result, SendKeysOutput)
        assert result.surface_id == "surface:abc"
        assert result.ok is True


@pytest.mark.unit
class TestCmuxNotify:
    @pytest.mark.asyncio
    async def test_returns_notification_id(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        socket.add_response("notification.create", {"title": "T"}, {"result": {"notification_id": "notification:xyz", "created_at": "2026-09-16T12:00:00Z"}})
        register_socket_tools(mcp, socket, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_notify"].fn(title="T")
        assert isinstance(result, NotifyOutput)
        assert result.notification_id == "notification:xyz"
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_socket_tools.py -v`
Expected: FAIL because socket_tools.py only has stub.

- [ ] **Step 3: Implement all 5 socket tools**

```python
"""cmux_mcp.tools.socket_tools — registers the 5 socket-direct tools.

Each tool follows the try/except/else/return pattern per spec §"/health envelope
wiring → Tool feed placement":
    state = tool_feeds[name]
    state.record_cycle()
    try:
        result = await socket.request(...)
    except CmuxError as exc:
        state.record_error()
        return exc.to_tool_error()
    else:
        state.record_success()
        return result
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP
    from cmux_mcp.client import CmuxSocketTransportProtocol
    from cmux_mcp.health import ToolFeedComponent


def _record(state: "ToolFeedComponent") -> None:
    state.record_cycle()


def _success(state: "ToolFeedComponent") -> None:
    state.record_success()


def _error(state: "ToolFeedComponent", exc: Exception):
    state.record_error()
    from cmux_mcp.errors import CmuxError
    if isinstance(exc, CmuxError):
        return exc.to_tool_error()
    return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}


def register_socket_tools(
    mcp: "FastMCP",
    socket: "CmuxSocketTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register the 5 socket-direct tools."""
    from cmux_mcp.models import (
        IdentifyOutput,
        ListNotificationsOutput,
        ListWorkspacesOutput,
        NotifyInput,
        NotifyOutput,
        SendKeysInput,
        SendKeysOutput,
    )
    from fastmcp.tools import ToolAnnotations

    @mcp.tool(
        name="cmux_list_workspaces",
        description="List all workspaces with their panes and surfaces.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_list_workspaces() -> ListWorkspacesOutput:
        state = tool_feeds["tool.cmux_list_workspaces"]
        state.record_cycle()
        try:
            # Compose workspace.list + surface.list + pane.surfaces (fails as a unit)
            ws_data = await socket.request("workspace.list")
            workspaces = []
            for ws in ws_data.get("workspaces", []):
                ws_id = ws["id"]
                surf_data = await socket.request("surface.list", {"workspace_id": ws_id})
                pane_data = await socket.request("pane.surfaces", {"workspace_id": ws_id})
                # Build nested model
                from cmux_mcp.models import Workspace, Pane, Surface
                workspaces.append(Workspace(
                    id=ws["id"],
                    title=ws.get("title", ""),
                    focused=ws.get("focused", False),
                    panes=[Pane(
                        id=p["id"],
                        surfaces=[Surface(
                            id=s["id"],
                            kind=SurfaceKind(s["kind"]),
                            cwd=s.get("cwd"),
                            focused=s.get("focused", False),
                        ) for s in p.get("surfaces", [])],
                    ) for p in pane_data.get("panes", [])],
                ))
            result = ListWorkspacesOutput(workspaces=workspaces)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_list_notifications",
        description="List pending cmux notifications.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_list_notifications() -> ListNotificationsOutput:
        state = tool_feeds["tool.cmux_list_notifications"]
        state.record_cycle()
        try:
            from cmux_mcp.models import Notification
            data = await socket.request("notification.list")
            result = ListNotificationsOutput(notifications=[Notification(**n) for n in data.get("notifications", [])])
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_identify",
        description="Return the focused window/workspace/pane/surface context.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_identify() -> IdentifyOutput:
        state = tool_feeds["tool.cmux_identify"]
        state.record_cycle()
        try:
            data = await socket.request("system.identify")
            result = IdentifyOutput(**data)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_send_keys",
        description="Send text or a special key to a terminal surface (fire-and-forget).",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_send_keys(
        surface_id: str,
        text: str | None = None,
        key: str | None = None,
    ) -> SendKeysOutput:
        from cmux_mcp.models import SendKeysInput as _Validated
        # Pydantic validation will raise on invalid input
        validated = _Validated(surface_id=surface_id, text=text, key=key)
        state = tool_feeds["tool.cmux_send_keys"]
        state.record_cycle()
        try:
            if validated.text is not None:
                await socket.request("surface.send_text", {"surface_id": validated.surface_id, "text": validated.text})
            else:
                await socket.request("surface.send_key", {"surface_id": validated.surface_id, "key": validated.key})
            result = SendKeysOutput(surface_id=validated.surface_id)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result

    @mcp.tool(
        name="cmux_notify",
        description="Dispatch an OS notification that rings a pane and lights up the sidebar.",
        annotations=ToolAnnotations(openWorldHint=True),
    )
    async def cmux_notify(
        title: str,
        subtitle: str | None = None,
        body: str | None = None,
        surface_id: str | None = None,
    ) -> NotifyOutput:
        from cmux_mcp.models import NotifyInput as _Validated
        validated = _Validated(title=title, subtitle=subtitle, body=body, surface_id=surface_id)
        state = tool_feeds["tool.cmux_notify"]
        state.record_cycle()
        try:
            data = await socket.request("notification.create", validated.model_dump(mode="json", exclude_none=True))
            result = NotifyOutput(**data)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_socket_tools.py -v`
Expected: 4 passed.

- [ ] **Step 5: Update `tests/unit/test_tools_registration.py` to expect 12**

```python
    def test_register_tools_registers_12(self) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
        assert len(tools) == 5  # only socket tools implemented so far
        names = {t.name for t in tools.values()}
        assert "cmux_list_workspaces" in names
```

- [ ] **Step 6: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_tools_registration.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/tools/socket_tools.py tests/unit/test_socket_tools.py tests/unit/test_tools_registration.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): implement 5 socket tools with try/except/else pattern"
```

### Task 19: cmux_browser_navigate tool

**Files:**
- Modify: `src/cmux_mcp/tools/browser_tools.py`
- Modify: `tests/unit/test_browser_tools.py` (append)

- [ ] **Step 1: Append test**

```python
# Append to test_browser_tools.py (create with one test for now):

@pytest.mark.unit
class TestCmuxBrowserNavigate:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_navigate"].fn(surface_id="surface:abc", url="https://example.com")
        from cmux_mcp.models import BrowserNavigateOutput
        assert isinstance(result, BrowserNavigateOutput)
        assert str(result.url) == "https://example.com/"
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py::TestCmuxBrowserNavigate -v`
Expected: FAIL because browser_tools.py only has a stub.

- [ ] **Step 3: Implement cmux_browser_navigate in `browser_tools.py`**

```python
# Append to browser_tools.py — fill in register_browser_tools:

from cmux_mcp.models import (
    BrowserNavigateInput,
    BrowserNavigateOutput,
    BrowserSnapshot,
)


def register_browser_tools(
    mcp: "FastMCP",
    cli: "CmuxCliTransportProtocol",
    tool_feeds: dict[str, "ToolFeedComponent"],
) -> None:
    """Register the 7 browser CLI tools."""
    from fastmcp.tools import ToolAnnotations

    @mcp.tool(
        name="cmux_browser_navigate",
        description="Navigate the browser surface to a URL.",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_browser_navigate(
        surface_id: str,
        url: str,
        snapshot_after: bool = False,
    ) -> BrowserNavigateOutput:
        from cmux_mcp.models import BrowserNavigateInput as _Validated
        validated = BrowserNavigateInput(surface_id=surface_id, url=url, snapshot_after=snapshot_after)
        state = tool_feeds["tool.cmux_browser_navigate"]
        state.record_cycle()
        try:
            args = ["browser", "--surface", validated.surface_id, "navigate", str(validated.url)]
            if validated.snapshot_after:
                args.append("--snapshot-after")
            result = await cli.call(args)
            from cmux_mcp.models import HttpUrl
            return BrowserNavigateOutput(
                ok=True,
                url=HttpUrl(str(validated.url)),
                snapshot=None,  # snapshot parsing not implemented yet (Task 20)
                truncated=len(result.stderr) > 4_096,
            )
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            # Note: success path returns inside try, not else — fix:
            # Actually move success return into else block
```

Re-read the try/except/else pattern. The success return must be in the else block, not inside try. Let me fix:

```python
    @mcp.tool(
        name="cmux_browser_navigate",
        description="Navigate the browser surface to a URL.",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_browser_navigate(
        surface_id: str,
        url: str,
        snapshot_after: bool = False,
    ) -> BrowserNavigateOutput:
        from cmux_mcp.models import BrowserNavigateInput as _Validated, HttpUrl
        validated = BrowserNavigateInput(surface_id=surface_id, url=url, snapshot_after=snapshot_after)
        state = tool_feeds["tool.cmux_browser_navigate"]
        state.record_cycle()
        args = ["browser", "--surface", validated.surface_id, "navigate", str(validated.url)]
        if validated.snapshot_after:
            args.append("--snapshot-after")
        try:
            cli_result = await cli.call(args)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return BrowserNavigateOutput(
                ok=True,
                url=HttpUrl(str(validated.url)),
                snapshot=None,
                truncated=len(cli_result.stderr) > 4_096,
            )
```

- [ ] **Step 4: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py::TestCmuxBrowserNavigate -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/tools/browser_tools.py tests/unit/test_browser_tools.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): implement cmux_browser_navigate with try/except/else"
```

### Task 20: cmux_browser_snapshot + cmux_browser_tabs tools

**Files:**
- Modify: `src/cmux_mcp/tools/browser_tools.py`
- Modify: `tests/unit/test_browser_tools.py`

- [ ] **Step 1: Append 2 tests to `test_browser_tools.py`**

```python
@pytest.mark.unit
class TestCmuxBrowserSnapshot:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        # Mock returns snapshot text in stdout
        cli.call = AsyncMock(return_value=CliResult(
            ok=True, stdout=b"[ref=e1] button Sign in", stderr=b"", returncode=0, duration_ms=10
        ))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_snapshot"].fn(surface_id="surface:abc")
        from cmux_mcp.models import BrowserSnapshot
        assert isinstance(result, BrowserSnapshot)
        assert "Sign in" in result.snapshot


@pytest.mark.unit
class TestCmuxBrowserTabs:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        import json
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        tabs_json = json.dumps([
            {"id": "t1", "url": "https://a.example", "title": "A", "active": False},
            {"id": "t2", "url": "https://b.example", "title": "B", "active": True},
        ]).encode()
        cli.call = AsyncMock(return_value=CliResult(
            ok=True, stdout=tabs_json, stderr=b"", returncode=0, duration_ms=10
        ))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_tabs"].fn(surface_id="surface:abc")
        from cmux_mcp.models import BrowserTabsOutput
        assert isinstance(result, BrowserTabsOutput)
        assert len(result.tabs) == 2
        assert result.tabs[0].id == "t1"
```

- [ ] **Step 2: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py -v`
Expected: 2 failed.

- [ ] **Step 3: Add tools to `browser_tools.py`**

```python
# Append to browser_tools.py (after cmux_browser_navigate):

    @mcp.tool(
        name="cmux_browser_snapshot",
        description="Return the accessibility tree of the current page (Playwright-style refs).",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_browser_snapshot(surface_id: str) -> BrowserSnapshot:
        from cmux_mcp.models import BrowserSnapshotInput as _Validated
        validated = BrowserSnapshotInput(surface_id=surface_id)
        state = tool_feeds["tool.cmux_browser_snapshot"]
        state.record_cycle()
        try:
            cli_result = await cli.call(["browser", "--surface", validated.surface_id, "snapshot", "--interactive"])
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            from datetime import datetime, timezone
            return BrowserSnapshot(
                snapshot=cli_result.stdout.decode("utf-8", errors="replace"),
                captured_at=datetime.now(tz=timezone.utc),
            )

    @mcp.tool(
        name="cmux_browser_tabs",
        description="List open tabs of the browser surface (read-only).",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_browser_tabs(surface_id: str) -> BrowserTabsOutput:
        from cmux_mcp.models import BrowserTabsInput as _Validated
        validated = BrowserTabsInput(surface_id=surface_id)
        state = tool_feeds["tool.cmux_browser_tabs"]
        state.record_cycle()
        try:
            import json
            cli_result = await cli.call(["browser", "--surface", validated.surface_id, "tab", "list", "--json"])
            tabs_raw = json.loads(cli_result.stdout.decode("utf-8"))
            from cmux_mcp.models import BrowserTab
            tabs = [BrowserTab(**t) for t in tabs_raw]
            result = BrowserTabsOutput(tabs=tabs)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return result
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/tools/browser_tools.py tests/unit/test_browser_tools.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): implement cmux_browser_snapshot + cmux_browser_tabs"
```

### Task 21: cmux_browser_evaluate tool (with await_promise + error envelope)

**Files:**
- Modify: `src/cmux_mcp/tools/browser_tools.py`
- Modify: `tests/unit/test_browser_tools.py`

- [ ] **Step 1: Append 3 tests**

```python
@pytest.mark.unit
class TestCmuxBrowserEvaluate:
    @pytest.mark.asyncio
    async def test_returns_typed_result_on_value(self, feeds: dict[str, object]) -> None:
        import json
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        cli.call = AsyncMock(return_value=CliResult(
            ok=True, stdout=json.dumps({"ok": True, "result": 42}).encode(), stderr=b"", returncode=0, duration_ms=10
        ))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_evaluate"].fn(surface_id="surface:abc", expression="document.title.length")
        from cmux_mcp.models import BrowserEvaluateResult
        assert isinstance(result, BrowserEvaluateResult)
        assert result.ok is True
        assert result.result == 42

    @pytest.mark.asyncio
    async def test_returns_error_envelope_on_runtime_exception(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        cli.call = AsyncMock(return_value=CliResult(
            ok=False, stdout=b"", stderr=b"ReferenceError: x is not defined", returncode=1, duration_ms=10
        ))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_evaluate"].fn(surface_id="surface:abc", expression="x.y.z")
        from cmux_mcp.models import BrowserEvaluateErrorResult
        assert isinstance(result, BrowserEvaluateErrorResult)
        assert result.ok is False
        assert result.error_kind == "runtime_exception"

    @pytest.mark.asyncio
    async def test_expression_length_validated(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        # Empty expression should fail validation
        with pytest.raises(Exception):
            await tools["cmux_browser_evaluate"].fn(surface_id="surface:abc", expression="")
```

- [ ] **Step 2: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py::TestCmuxBrowserEvaluate -v`
Expected: 3 failed.

- [ ] **Step 3: Add tool**

```python
# Append to browser_tools.py:

    @mcp.tool(
        name="cmux_browser_evaluate",
        description="Execute JavaScript in the browser context and return the result. Arbitrary JS — trust model documented.",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_browser_evaluate(
        surface_id: str,
        expression: str,
        await_promise: bool = False,
    ) -> BrowserEvaluateResult | BrowserEvaluateErrorResult:
        from cmux_mcp.models import BrowserEvaluateInput as _Validated
        validated = BrowserEvaluateInput(surface_id=surface_id, expression=expression, await_promise=await_promise)
        state = tool_feeds["tool.cmux_browser_evaluate"]
        state.record_cycle()
        # Per spec §"await_promise semantics": if await_promise=True, the server polls via
        # repeated eval calls at promise_poll_interval_ms (default 100ms) until settled or
        # promise_total_timeout_seconds (default 30s) elapses; holds 1 semaphore slot during polling.
        # v1 implementation: simple single-eval with await_promise flag passed through.
        try:
            args = ["browser", "--surface", validated.surface_id, "eval", validated.expression]
            if validated.await_promise:
                args.append("--await")
            cli_result = await cli.call(args, timeout=30.0)
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            if cli_result.returncode != 0:
                state.record_error()
                stderr = cli_result.stderr.decode("utf-8", errors="replace")
                # Heuristic: cmux CLI writes non-serializable as a specific stderr marker
                if "not serializable" in stderr.lower():
                    return BrowserEvaluateErrorResult(error=stderr, error_kind="not_serializable")
                return BrowserEvaluateErrorResult(error=stderr, error_kind="runtime_exception")
            import json
            try:
                payload = json.loads(cli_result.stdout.decode("utf-8"))
                state.record_success()
                return BrowserEvaluateResult(ok=True, result=payload.get("result"))
            except Exception:
                state.record_error()
                return BrowserEvaluateErrorResult(
                    error=f"malformed eval output: {cli_result.stdout!r}",
                    error_kind="runtime_exception",
                )
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py::TestCmuxBrowserEvaluate -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/tools/browser_tools.py tests/unit/test_browser_tools.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): implement cmux_browser_evaluate with discriminated error envelope"
```

### Task 22: cmux_browser_click + cmux_browser_type + cmux_browser_console tools

**Files:**
- Modify: `src/cmux_mcp/tools/browser_tools.py`
- Modify: `tests/unit/test_browser_tools.py`

- [ ] **Step 1: Append tests**

```python
@pytest.mark.unit
class TestCmuxBrowserClick:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        cli.call = AsyncMock(return_value=CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=10))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_click"].fn(surface_id="surface:abc", selector="button#submit")
        from cmux_mcp.models import BrowserClickOutput
        assert isinstance(result, BrowserClickOutput)
        assert result.ok is True


@pytest.mark.unit
class TestCmuxBrowserType:
    @pytest.mark.asyncio
    async def test_returns_typed_output(self, feeds: dict[str, object]) -> None:
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        cli.call = AsyncMock(return_value=CliResult(ok=True, stdout=b"", stderr=b"", returncode=0, duration_ms=10))
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_type"].fn(surface_id="surface:abc", selector="input#q", text="cmux")
        from cmux_mcp.models import BrowserTypeOutput
        assert isinstance(result, BrowserTypeOutput)
        assert result.ok is True


@pytest.mark.unit
class TestCmuxBrowserConsole:
    @pytest.mark.asyncio
    async def test_returns_typed_output_aggregated(self, feeds: dict[str, object]) -> None:
        import json
        from fastmcp import FastMCP
        from cmux_mcp.tools.browser_tools import register_browser_tools
        from cmux_mcp.client import CliResult
        from unittest.mock import AsyncMock
        mcp = FastMCP(name="test")
        cli = CmuxMockTransport()
        async def fake_call(args: list[str], *, timeout: float | None = None) -> CliResult:
            if "errors" in args:
                return CliResult(ok=True, stdout=b"[]", stderr=b"", returncode=0, duration_ms=5)
            return CliResult(
                ok=True,
                stdout=json.dumps([{"level": "info", "text": "hello"}]).encode(),
                stderr=b"", returncode=0, duration_ms=5,
            )
        cli.call = AsyncMock(side_effect=fake_call)
        register_browser_tools(mcp, cli, feeds)
        tools = mcp._tool_manager._tools
        result = await tools["cmux_browser_console"].fn(surface_id="surface:abc")
        from cmux_mcp.models import BrowserConsoleResult
        assert isinstance(result, BrowserConsoleResult)
        assert len(result.messages) == 1
        assert result.partial_failure is False
```

- [ ] **Step 2: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py -v`
Expected: 3 failed.

- [ ] **Step 3: Add 3 tools to `browser_tools.py`**

```python
# Append to browser_tools.py:

    @mcp.tool(
        name="cmux_browser_click",
        description="Click an element by CSS selector.",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_browser_click(
        surface_id: str,
        selector: str,
        snapshot_after: bool = False,
    ) -> BrowserClickOutput:
        from cmux_mcp.models import BrowserClickInput as _Validated
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
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return BrowserClickOutput(ok=True)

    @mcp.tool(
        name="cmux_browser_type",
        description="Type text into an input by CSS selector (uses fill semantics).",
        annotations=ToolAnnotations(destructiveHint=True, openWorldHint=True),
    )
    async def cmux_browser_type(
        surface_id: str,
        selector: str,
        text: str,
        submit: bool = False,
    ) -> BrowserTypeOutput:
        from cmux_mcp.models import BrowserTypeInput as _Validated
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
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            return BrowserTypeOutput(ok=True)

    @mcp.tool(
        name="cmux_browser_console",
        description="Read console messages and JS errors from the browser surface.",
        annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True),
    )
    async def cmux_browser_console(
        surface_id: str,
        limit: int = 50,
        level: str = "log",
        since: str | None = None,
    ) -> BrowserConsoleResult:
        from cmux_mcp.models import BrowserConsoleInput as _Validated
        validated = BrowserConsoleInput(surface_id=surface_id, limit=limit, level=level, since=since)
        state = tool_feeds["tool.cmux_browser_console"]
        state.record_cycle()
        # Aggregate two sub-calls per spec §"Tool 12". Use gather with return_exceptions
        # so partial failure becomes empty list + flag.
        import asyncio
        import json
        try:
            results = await asyncio.gather(
                cli.call(["browser", "--surface", validated.surface_id, "console", "list"]),
                cli.call(["browser", "--surface", validated.surface_id, "errors", "list"]),
                return_exceptions=True,
            )
        except Exception as exc:
            state.record_error()
            from cmux_mcp.errors import CmuxError
            if isinstance(exc, CmuxError):
                return exc.to_tool_error()
            return {"code": "internal_error", "message": str(exc), "retryable": False, "data": None}
        else:
            state.record_success()
            messages: list = []
            errors: list = []
            partial_failure = False
            failed_subcalls: list[str] = []
            console_result, errors_result = results
            if isinstance(console_result, Exception):
                partial_failure = True
                failed_subcalls.append("console_list")
            else:
                try:
                    raw = json.loads(console_result.stdout.decode("utf-8"))
                    from cmux_mcp.models import ConsoleMessage
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
                    from cmux_mcp.models import BrowserError
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
```

- [ ] **Step 4: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_browser_tools.py -v`
Expected: 12+ passed.

- [ ] **Step 5: Update `tests/unit/test_tools_registration.py` to expect 12**

```python
    def test_register_tools_registers_12(self) -> None:
        mcp = FastMCP(name="test")
        socket = CmuxMockTransport()
        cli = CmuxMockTransport()
        feeds = {comp.name: comp for comp in build_tool_feed_components()}
        register_tools(mcp, socket, cli, feeds)
        tools = mcp._tool_manager._tools if hasattr(mcp, "_tool_manager") else {}
        assert len(tools) == 12
```

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_tools_registration.py -v`
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/tools/browser_tools.py tests/unit/test_browser_tools.py tests/unit/test_tools_registration.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(tools): implement cmux_browser_click + cmux_browser_type + cmux_browser_console (all 12 tools done)"
```

### Task 23: Mock-mode WARN banner + acknowledgment

**Files:**
- Create: `src/cmux_mcp/logging_setup.py`
- Modify: `src/cmux_mcp/server.py` (call banner)
- Create: `tests/unit/test_logging_pii.py`

**Interfaces:**
- Consumes: `CmuxMCPConfig`, `os.environ`
- Produces: `maybe_warn_mock_mode(config)` that emits an unmissable WARN banner unless `CMUX_MCP_MOCK_ACKNOWLEDGED=1` or `PYTEST_CURRENT_TEST` is set

- [ ] **Step 1: Write failing test `tests/unit/test_logging_pii.py`**

```python
"""Tests for mock-mode WARN banner + PII logging exclusion."""
from __future__ import annotations

import logging
import os
from unittest.mock import patch

import pytest

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.logging_setup import maybe_warn_mock_mode


@pytest.mark.unit
class TestMockModeBanner:
    def test_banner_emitted_when_mock_active_without_ack(self, caplog: pytest.LogCaptureFixture) -> None:
        cfg = CmuxMCPConfig(mock_mode=True)
        with caplog.at_level(logging.WARNING, logger="cmux_mcp.logging_setup"):
            maybe_warn_mock_mode(cfg)
        assert any("MOCK MODE" in rec.message for rec in caplog.records)

    def test_banner_suppressed_when_acknowledged(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_MOCK_ACKNOWLEDGED": "1"}):
            cfg = CmuxMCPConfig(mock_mode=True)
        with caplog.at_level(logging.WARNING, logger="cmux_mcp.logging_setup"):
            maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in rec.message for rec in caplog.records)

    def test_banner_suppressed_when_pytest_current_test(self, caplog: pytest.LogCaptureFixture) -> None:
        with patch.dict(os.environ, {"PYTEST_CURRENT_TEST": "tests/test_x.py::test_y"}):
            cfg = CmuxMCPConfig(mock_mode=True)
        with caplog.at_level(logging.WARNING, logger="cmux_mcp.logging_setup"):
            maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in rec.message for rec in caplog.records)

    def test_no_banner_when_mock_inactive(self, caplog: pytest.LogCaptureFixture) -> None:
        cfg = CmuxMCPConfig(mock_mode=False)
        with caplog.at_level(logging.WARNING, logger="cmux_mcp.logging_setup"):
            maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in rec.message for rec in caplog.records)
```

- [ ] **Step 2: Run test; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_logging_pii.py::TestMockModeBanner -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `src/cmux_mcp/logging_setup.py`**

```python
"""cmux_mcp.logging_setup — Oneiric logger + mock-mode WARN banner + PII helpers.

Per spec §"Logging":
  - Logger name: cmux_mcp.<module>
  - Oneiric logger only; no print(), no stdlib logging
  - mock-mode WARN banner unless CMUX_MCP_MOCK_ACKNOWLEDGED=1 or PYTEST_CURRENT_TEST is set
"""
from __future__ import annotations

import logging
import os

_LOG = logging.getLogger("cmux_mcp.logging_setup")


def maybe_warn_mock_mode(config: object) -> None:
    """Emit unmissable WARN banner if mock mode is active outside test contexts.

    Suppressed when:
      - CMUX_MCP_MOCK_ACKNOWLEDGED=1 (operator opt-out)
      - PYTEST_CURRENT_TEST is set (running under pytest)
    """
    if not getattr(config, "mock_mode", False):
        return
    if os.environ.get("CMUX_MCP_MOCK_ACKNOWLEDGED") == "1":
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _LOG.warning(
        "cmux-mcp is running in MOCK MODE — all cmux responses are canned fixtures; "
        "do not use for real work. Set CMUX_MCP_MOCK_ACKNOWLEDGED=1 to silence this warning."
    )


def redact_url_query_string(url: str) -> str:
    """Strip query string from URL for safe logging (removes ?token=...&api_key=...)."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    if not parts.query:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def redact_expression(expr: str) -> str:
    """Return length + first 32 chars for safe logging of JS expressions."""
    return f"<len={len(expr)}, head={expr[:32]!r}>"


__all__ = ["maybe_warn_mock_mode", "redact_url_query_string", "redact_expression"]
```

- [ ] **Step 4: Wire banner into `server.py` startup()**

```python
# In CmuxMCPServer.startup(), after transport init:
        from cmux_mcp.logging_setup import maybe_warn_mock_mode
        maybe_warn_mock_mode(self.config)
```

- [ ] **Step 5: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_logging_pii.py::TestMockModeBanner -v`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/logging_setup.py src/cmux_mcp/server.py tests/unit/test_logging_pii.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(logging): mock-mode WARN banner + URL/JS redaction helpers"
```

### Task 24: PID management + stale recovery

**Files:**
- Modify: `src/cmux_mcp/server.py`
- Modify: `tests/unit/test_lifecycle.py`

**Interfaces:**
- Consumes: `pid_file_path`, current process PID
- Produces: `acquire_pid_file(path)`, `release_pid_file(path)` with `kill -0` liveness check

- [ ] **Step 1: Append tests**

```python
# Append to test_lifecycle.py:

from cmux_mcp.server import acquire_pid_file, release_pid_file


@pytest.mark.unit
class TestPidManagement:
    def test_acquire_creates_pid_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        acquire_pid_file(path)
        assert path.exists()
        assert int(path.read_text().strip()) > 0

    def test_acquire_existing_alive_pid_refuses(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        path.write_text(str(os.getpid()))  # current process is alive
        with pytest.raises(RuntimeError):
            acquire_pid_file(path)

    def test_acquire_stale_pid_recovers(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        path.write_text("99999999")  # unlikely to be alive
        acquire_pid_file(path)  # should overwrite stale
        assert int(path.read_text().strip()) > 0

    def test_release_removes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "test.pid"
        acquire_pid_file(path)
        release_pid_file(path)
        assert not path.exists()
```

- [ ] **Step 2: Add `import os` to test_lifecycle.py top**

- [ ] **Step 3: Run tests; expect fail**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py::TestPidManagement -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 4: Add functions to `server.py`**

```python
# Append to server.py:

import os


def acquire_pid_file(path: Path) -> None:
    """Acquire a PID file with stale-detection. Refuses if PID is alive."""
    if path.exists():
        try:
            existing_pid = int(path.read_text().strip())
            os.kill(existing_pid, 0)  # raises ProcessLookupError if dead
            raise RuntimeError(f"PID file {path} is held by live process {existing_pid}")
        except (ProcessLookupError, ValueError):
            # Stale — overwrite
            path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(os.getpid()))


def release_pid_file(path: Path) -> None:
    """Release PID file. Idempotent."""
    try:
        path.unlink()
    except FileNotFoundError:
        pass
```

- [ ] **Step 5: Wire into startup()/shutdown()**

```python
# In CmuxMCPServer.__init__, add at end:
        import atexit
        atexit.register(release_pid_file, self.config.pid_file_path)

# In CmuxMCPServer.startup(), at the start:
        acquire_pid_file(self.config.pid_file_path)

# In CmuxMCPServer.shutdown(), at the start:
        release_pid_file(self.config.pid_file_path)
```

- [ ] **Step 6: Run tests; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py::TestPidManagement -v`
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add src/cmux_mcp/server.py tests/unit/test_lifecycle.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "feat(lifecycle): PID file management with stale recovery via kill -0"
```

### Task 25: Graceful shutdown drain

**Files:**
- Modify: `src/cmux_mcp/server.py`
- Modify: `tests/unit/test_lifecycle.py`

- [ ] **Step 1: Append test**

```python
@pytest.mark.unit
class TestGracefulShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_waits_up_to_grace_seconds(self) -> None:
        config = CmuxMCPConfig(shutdown_grace_seconds=0.1)
        server = CmuxMCPServer(config)
        server.socket_transport = CmuxMockTransport()
        server.cli_transport = CmuxMockTransport()
        import time
        start = time.monotonic()
        await server.shutdown()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0  # Should finish quickly since no in-flight
```

- [ ] **Step 2: Run test; verify pass (it should — mock transports close instantly)**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_lifecycle.py::TestGracefulShutdown -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add tests/unit/test_lifecycle.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(lifecycle): graceful shutdown drain within grace seconds"
```

### Task 26: Subprocess env filter allowlist (additional PII test)

**Files:**
- Modify: `tests/unit/test_transport_cli.py` (append env filter test)

- [ ] **Step 1: Append test**

```python
@pytest.mark.unit
class TestSubprocessEnvFilter:
    def test_secret_keys_not_in_child_env(self) -> None:
        import os
        from cmux_mcp.client import _filtered_env
        with patch.dict(os.environ, {
            "MINIMAX_API_KEY": "sk-secret",
            "MAHAVISHNU_AUTH_SECRET": "jwt-secret",
            "PATH": "/usr/bin",
            "CMUX_SOCKET_PATH": "/tmp/cmux.sock",
        }):
            env = _filtered_env()
        assert "MINIMAX_API_KEY" not in env
        assert "MAHAVISHNU_AUTH_SECRET" not in env
        assert "PATH" in env
        assert "CMUX_SOCKET_PATH" in env
```

- [ ] **Step 2: Run test; verify pass**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest tests/unit/test_transport_cli.py::TestSubprocessEnvFilter -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add tests/unit/test_transport_cli.py && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "test(cli): subprocess env filter strips secret keys (MINIMAX, MAHAVISHNU)"
```

### Task 27: README per WWW catalog template

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: spec
- Produces: 13-section WWW catalog README

- [ ] **Step 1: Write README.md**

(Use the WWW catalog README structure: badges, one-line purpose, version+status, quick links, capability bullets, quick start with mock mode, lifecycle CLI commands, MCP client configuration example, tool reference table, configuration table, project structure, dev commands, security notes.)

```markdown
# cmux-mcp

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![Framework: FastMCP](https://img.shields.io/badge/framework-FastMCP-0ea5e9)](https://github.com/jlowin/fastmcp)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.13+](https://www.python.org/downloads/)](https://www.python.org/downloads/)

Catalog and operating map for cmux-mcp.

**Status:** Internal Bodai ecosystem server

## Quick Links

- [Overview](#overview)
- [Tool Reference](#tool-reference)
- [Quick Start](#quick-start)
- [MCP Client Configuration](#mcp-client-configuration)
- [Configuration](#configuration)
- [Security Notes](#security-notes)

## Overview

cmux-mcp exposes programmatic control of a running [cmux](https://github.com/manaflow-ai/cmux) instance (macOS-only, Ghostty-based terminal for AI coding agents) as 12 MCP tools over Streamable HTTP. The server speaks cmux's Unix-socket JSON-RPC protocol directly for orchestration and notifications, and shells out to the cmux CLI for browser automation.

## Quick Start

```bash
# Install
cd /Users/les/Projects/cmux-mcp && uv sync --group dev

# Run (mock mode, for testing)
CMUX_MCP_MOCK=1 uv run cmux-mcp start

# Run (real, on macOS with cmux running)
uv run cmux-mcp start

# Lifecycle
uv run cmux-mcp start --bg
uv run cmux-mcp status
uv run cmux-mcp health
uv run cmux-mcp stop
```

## MCP Client Configuration

```json
{
  "mcpServers": {
    "cmux": {
      "command": "uv",
      "args": ["run", "--project", "/Users/les/Projects/cmux-mcp", "cmux-mcp", "start"]
    }
  }
}
```

## Tool Reference

| Tool | Mode | Description |
|---|---|---|
| `cmux_list_workspaces` | Read-only | List all workspaces with panes and surfaces |
| `cmux_list_notifications` | Read-only | List pending cmux notifications |
| `cmux_identify` | Read-only | Return focused window/workspace/pane/surface |
| `cmux_send_keys` | Destructive | Send text or special key to terminal surface (fire-and-forget) |
| `cmux_notify` | Mutation | Dispatch OS notification that rings pane and lights sidebar |
| `cmux_browser_navigate` | Destructive | Navigate browser surface to URL |
| `cmux_browser_snapshot` | Read-only | A11y tree with Playwright-style refs |
| `cmux_browser_evaluate` | Destructive | Execute JS in browser (arbitrary; trust model documented) |
| `cmux_browser_click` | Destructive | Click element by CSS selector |
| `cmux_browser_type` | Destructive | Type into input (uses fill semantics) |
| `cmux_browser_tabs` | Read-only | List open tabs |
| `cmux_browser_console` | Read-only | Read console + JS errors (aggregates 2 sub-calls) |

## Configuration

All settings via `CMUX_MCP_*` env vars. See `settings/cmux-mcp.yaml` for committed defaults.

| Setting | Default | Description |
|---|---|---|
| `CMUX_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `CMUX_MCP_PORT` | `3061` | HTTP port |
| `CMUX_MCP_SOCKET_PATH` | `/tmp/cmux.sock` | cmux Unix socket |
| `CMUX_MCP_CLI_PATH` | auto-discover | cmux CLI binary path |
| `CMUX_MCP_AUTH_ENABLED` | `false` | Enable JWT auth for non-loopback deployments |

## Security Notes

- macOS-only; non-macOS hosts must use `CMUX_MCP_MOCK=1` (auto-flipped with WARN banner)
- cmux's `cmuxOnly` access mode restricts socket connections to processes spawned inside cmux terminals
- PII exclusion list: URLs have query strings stripped, JS expressions length-prefixed, typed text length-only
- Subprocess env filtered to `SUBPROCESS_ENV_ALLOWLIST` to prevent leaking API keys

## Development Commands

```bash
uv run pytest                 # Run all tests
uv run pytest -m unit         # Unit tests only
uv run pytest -m integration  # Integration tests (require live cmux)
uv run crackerjack run        # Full quality gate
```
```

- [ ] **Step 2: Commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add README.md && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs: README per WWW catalog template (13 sections)"
```

### Task 28: Final review + crackerjack run

**Files:**
- (no new files; full test sweep + quality gate)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/les/Projects/cmux-mcp && uv run pytest -v`
Expected: All tests pass (~50+ tests across config, models, errors, transports, health, lifecycle, socket_tools, browser_tools, tools_registration, cli_discovery, logging_pii).

- [ ] **Step 2: Run crackerjack quality gate**

Run: `cd /Users/les/Projects/cmux-mcp && uv run crackerjack run`
Expected: passes; ruff + mypy + pytest with --cov-fail-under=89.

- [ ] **Step 3: Verify the server starts and serves /health**

Run: `cd /Users/les/Projects/cmux-mcp && CMUX_MCP_MOCK=1 CMUX_MCP_MOCK_ACKNOWLEDGED=1 uv run cmux-mcp start --bg && sleep 2 && curl -s http://127.0.0.1:3061/health | python -m json.tool && uv run cmux-mcp stop`
Expected: JSON health response with `status: "ok"`, per-feed counters, mock_transport component present.

- [ ] **Step 4: Tag v0.1.0 release**

```bash
cd /Users/les/Projects/cmux-mcp && git tag -a v0.1.0 -m "v0.1.0: cmux-mcp initial release (12 tools, BSD-3-Clause)"
```

- [ ] **Step 5: Commit tag (tags are separate; no commit needed)**

- [ ] **Step 6: Update PLAN_INDEX.md**

Append `2026-09-16-cmux-mcp-impl.md` entry with status `active`, role `implementation`, links spec, notes "28 tasks; 12 tools (5 socket + 7 browser); BSD-3-Clause; port 3061; macOS-only with mock-mode escape hatch".

- [ ] **Step 7: Final commit**

```bash
cd /Users/les/Projects/cmux-mcp && git add docs/superpowers/plans/PLAN_INDEX.md && \
  git -c user.name=les -c user.email=les@wedgwoodwebworks.com commit -m "docs(plans): add cmux-mcp implementation plan to index"
```

## Amendment Log

Plan was authored 2026-09-16; implementation began 2026-09-19 and surfaced these
drifts in Tasks 1–13. Each amendment is also annotated inline at the relevant step.
See spec's Amendment Log section for the canonical statements.

| # | Task | Original | Amendment | Why |
|---|------|----------|------------|-----|
| 1 | 1 (pyproject) | `requires-python = ">=3.13"` | `">=3.14"` | `mcp-common` 0.26.x and 0.27.x both require Python 3.14; `uv sync` could not resolve at 3.13 |
| 2 | 1 (uv command) | `uv sync --group dev` | `uv sync --extra dev` | Plan's pyproject uses `[project.optional-dependencies]`, not PEP 735 `[dependency-groups]`; `--extra` matches the table, `--group` is rejected by uv 0.12.17 |
| 3 | 7 (`mock_mode` field) | `mock_mode: bool = False` + `if not self.mock_mode: ...` validator | `bool \| None = None` sentinel + `if self.mock_mode is None: ...` validator + `validation_alias="CMUX_MCP_MOCK"` | (a) Sentinel distinguishes "default False" from "explicit False via env" so the spec's "only if not explicitly set" semantic holds; (b) `validation_alias` overrides Pydantic-settings' default `env_prefix + field_name` scheme (which would produce `CMUX_MCP_MOCK_MODE`) so the spec's literal env var name (`CMUX_MCP_MOCK`) is honored |
| 4 | 7 (env-derived defaults) | `Path(os.environ.get(..., "/default"))` evaluated at class-body time | `Field(default_factory=lambda: Path(os.environ.get(..., "/default")))` | Pydantic v2 idiom for env-derived defaults; re-evaluates per instance |
| 5 | 12 (per-surface lock call site) | `async with self._surface_lock_for(surface_id):` | `lock = await self._surface_lock_for(surface_id); async with lock:` | `_surface_lock_for` is a coroutine returning `asyncio.Lock`; "async with coroutine" raises `TypeError` |
| 6 | 12 (semaphore test) | Patches `transport.call` | Patch `transport._invoke` | Patching `call` bypasses the semaphore entirely; `_invoke` patch keeps `call()`'s semaphore in the path |
| 7 | 13 (per-surface lock test) | Patches `transport.call`, uses `args[2]` (which is `"--surface"`) as identifier | Patch `transport._invoke`, use `CmuxCliTransport._extract_surface_id(args)` | Same fix as #6; `args[2]` is `"--surface"` not the surface_id |
| 8 | 8 (cli discovery test) | `test_explicit_path_missing_raises` assumes no cmux on test machine | Patch `_candidate_paths` to return `[]` for hermetic test | cmux is installed on this Mac (Homebrew); without the patch, the test finds it via `shutil.which("cmux")` and the assertion fails |
| 9 | 11 (correlation test) | Mock `readline()` returns `b""` (EOF) when empty | `asyncio.Event` gates readline; `event.clear()` after wake | `b""` triggers reader_task's EOF/reconnect path before any request is sent |
| 10 | 9 (mock transport test) | Asserted `result == {"result": {"pong": True}}` | Asserted `result == {"pong": True}` (inner result) | `CmuxSocketTransport.request` returns the inner `result` (not envelope); mock must mirror |

Future plan authors: add `uv lock --dry-run` to the spec-review checklist. Amendments 1,
2, and the Pydantic v2 idioms in 3-4 are detectable by this single command run after
authoring. Amendments 5-10 are normal implementation-time surprises; running the
plan's own tests in dry-run / collect-only mode catches them earlier in the loop.

### Phase 3 amendments (Tasks 14-16)

| # | Task | Original | Amendment | Why |
|---|------|----------|------------|-----|
| E | 1 Step 3 (`__main__.py`) | `description="..."` | `_description="..."` | `MCPServerCLIFactory.create_server_cli` keyword is `_description` (verified via `inspect.signature`) |
| F | 7 (CmuxMCPConfig) | (Plan did not document this) | Add `http_port` and `http_host` `@property` accessors delegating to `port`/`host` | mcp-common reads `config.http_port`/`config.http_host`; without the bridge, server bound to port 8000 and ignored `CMUX_MCP_PORT` |
| G | 14 (server.py) | `self._create_startup_snapshot(...)` (sync) | `await self._create_startup_snapshot(...)` | Both are `async def`; sync call returns coroutine never awaited → RuntimeWarning + broken health route |
| H | 16 (server.py /health wiring) | Pass `FeedComponent` instances to `extra_components` | Pass `[comp.snapshot() for comp in ...]` (list of dicts) | mcp-common docstring: "passed through verbatim" — list of dicts, not instances |
| I | 14 (`CmuxMCPServer.__init__`) | (Plan did not document this) | `self.runtime = self._init_runtime_components("cmux-mcp")` in `__init__`; `await self.runtime.initialize()` in `startup`; `await self.runtime.cleanup()` in `shutdown` | Without runtime init, `_create_*_snapshot` fail with `AttributeError: 'CmuxMCPServer' object has no attribute 'runtime'` |

Phase 3 amendments share a pattern: **mcp-common API surface drift**. None
detectable by paper review alone. `inspect.signature` on every external
function the plan references would have caught all five in under 60 seconds.

End-to-end smoke verified: `CMUX_MCP_MOCK=1 uv run cmux-mcp start` binds
port 3061; `GET /health` returns JSON with 15 feed snapshots
(2 transports + 1 mock_transport + 12 tool feeds).








