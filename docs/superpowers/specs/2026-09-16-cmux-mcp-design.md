# cmux-mcp Design Spec

> **Status:** active (round-2 criticals applied)
> **Date:** 2026-09-16
> **Spec type:** architectural
> **Decision log:** end of document

## Goal

Build **`cmux-mcp`**, a single MCP server that exposes programmatic control of a running [cmux](https://github.com/manaflow-ai/cmux) instance (the macOS Ghostty-based terminal designed for AI coding agents) as **12 MCP tools** over Streamable HTTP on port 3061. The server speaks cmux's Unix-socket JSON-RPC protocol directly for orchestration and notifications, and shells out to the cmux CLI for browser automation (the only documented path, since cmux's embedded WebKit browser does not expose a remote inspector endpoint).

The server is **per-session**: it must be launched from inside a cmux terminal so the `cmuxOnly` socket access mode permits connections. Lifecycle is managed by the `mcp-common` CLI (start/stop/restart/status/health/version/doctor).

## Background

cmux is a native macOS terminal app (Swift + AppKit, libghostty rendering) built for running multiple AI coding agents in parallel. It exposes a **Unix-socket JSON-RPC API** at `$CMUX_SOCKET_PATH` (default `/tmp/cmux.sock`) for programmatic control. The documented protocol covers `workspace.*`, `surface.*`, `pane.*`, `notification.*`, and `system.*` namespaces. Browser automation is exposed only via the `cmux browser` CLI command family — the embedded WebKit browser does not expose a remote inspector.

Several standalone cmux MCP servers exist in the wild (`jasonraz/cmux-browser-mcp`, `EtanHey/cmuxlayer`, etc.). None follow the WWW catalog pattern (mcp-common lifecycle, Oneiric config, crackerjack quality gate). `cmux-mcp` is the catalog-grade implementation: BSD 3-Clause, port 3061, mock-mode testable on non-macOS hosts.

## Scope

### In v1

- 12 MCP tools (5 socket + 7 browser CLI)
- Streamable HTTP transport on port 3061
- macOS-only runtime; non-macOS hosts fail-fast with `unsupported_platform` unless `CMUX_MCP_MOCK=1`
- Mock-mode test fixture for CI on Linux (explicit opt-in via env var)
- Lifecycle CLI via `mcp-common` (start, stop, restart, status, health, version, doctor)
- Per-session lifecycle: server exits when cmux terminal closes
- /health endpoint aggregates per-transport and per-tool feed state (returns 503 on degraded)
- BSD 3-Clause license

### Out of v1 (deferred to v1.1+)

- **Skill/hook lifecycle** (`manaflow-ai/cmux-skills`, `cmux hooks setup`) — separate capability cluster
- **Cross-Computer cmux coordination** (multi-machine cmux fleet)
- **Direct WebKit Inspector transport** — only when cmux exposes a remote inspector
- **SSH workspace automation** (`cmux ssh`) — defer; CLI wrapper needed
- **Resume-surface bindings** (`cmux surface resume set`) — defer
- **Custom `cmux.json` commands management** — defer until concrete use case
- **Tab mutation tools** (`browser_tab_open`, `browser_tab_close`, `browser_tab_switch`, `browser_tab_reload`) — `browser_tabs` is read-only in v1
- **`surface_read` companion to `send_keys`** — `send_keys` is fire-and-forget in v1; explicit `surface_read` deferred
- **`browser_screenshot` tool** — if/when cmux CLI exposes `screenshot`
- **Server-initiated MCP notifications** for cmux events — v1 is pull-only

## Architecture

```
┌──────────────────────┐     ┌─────────────────────────┐
│  MCP client (Claude  │────▶│   cmux-mcp (FastMCP)    │
│  Desktop, Codex, …)  │     │   http://127.0.0.1:3061 │
└──────────────────────┘     └──────────┬──────────────┘
                                        │
                  ┌─────────────────────┴──────────────────────┐
                  │                                            │
                  ▼                                            ▼
        ┌─────────────────────┐                    ┌─────────────────────┐
        │ CmuxSocketTransport │                    │  CmuxCliTransport   │
        │  asyncio unix sock  │                    │  subprocess cmux …  │
        │  newline-JSON-RPC   │                    │  /Applications/.../ │
        │  multiplexed by id  │                    │  bin/cmux           │
        └──────────┬──────────┘                    └──────────┬──────────┘
                   │                                         │
                   ▼                                         ▼
        ┌─────────────────────┐                    ┌─────────────────────┐
        │  cmux daemon socket │                    │   cmux binary       │
        │  /tmp/cmux.sock     │                    │  (browser subcmds)  │
        └─────────────────────┘                    └─────────────────────┘
```

### Two transport protocols (NOT one)

`CmuxTransport` was the wrong abstraction — the two paths differ in failure modes, retry semantics, observability, and capability expression. They are split:

```python
class CmuxSocketTransport(Protocol):
    """Long-lived unix-socket JSON-RPC client. Multiplexed by id. Retry-safe."""
    async def request(self, method: str, params: dict | None = None,
                      *, timeout: float | None = None) -> dict: ...
    async def aclose(self) -> None: ...
    @property
    def state(self) -> Literal["connected", "reconnecting", "disconnected"]: ...


@dataclass
class CliResult:
    ok: bool
    stdout: bytes
    stderr: bytes
    returncode: int
    duration_ms: int


class CmuxCliTransport(Protocol):
    """Single-shot subprocess. NOT retry-safe — cmux state already mutated."""
    async def call(self, args: Sequence[str], *,
                   timeout: float | None = None) -> CliResult: ...
    async def aclose(self) -> None: ...
    @property
    def active_subprocesses(self) -> int: ...


class CmuxMockTransport:
    """In-process canned responses. Implements both protocols."""
    ...
```

Mock transport implements both protocol shapes so tool code is identical against real and fake.

## Pydantic models

All tool inputs/outputs flow through Pydantic v2 models. Models use modern syntax (`X | None`, `list[str]`, `pathlib.Path`, never `Optional`/`List`).

### Domain models

```python
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from pydantic import BaseModel, Field, HttpUrl

SURFACE_ID_PATTERN = r"^surface:[a-zA-Z0-9_-]+$"
NOTIFICATION_ID_PATTERN = r"^notification:[a-zA-Z0-9_-]+$"


class SurfaceKind(StrEnum):
    TERMINAL = "terminal"
    BROWSER = "browser"


class Surface(BaseModel):
    id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    kind: SurfaceKind
    cwd: str | None = None
    focused: bool = False


class Pane(BaseModel):
    id: Annotated[str, Field(pattern=r"^pane:[a-zA-Z0-9_-]+$")]
    surfaces: list[Surface] = []


class Workspace(BaseModel):
    id: Annotated[str, Field(pattern=r"^workspace:[a-zA-Z0-9_-]+$")]
    title: str
    focused: bool = False
    panes: list[Pane] = []


class Notification(BaseModel):
    id: Annotated[str, Field(pattern=NOTIFICATION_ID_PATTERN)]
    title: str
    subtitle: str | None = None
    body: str | None = None
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)] | None = None
    created_at: datetime
```

### Browser models

```python
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
```

### Tool input models

```python
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
    url: Annotated[HttpUrl, Field(...)]
    snapshot_after: bool = False


class BrowserSnapshotInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]


class BrowserEvaluateInput(BaseModel):
    surface_id: Annotated[str, Field(pattern=SURFACE_ID_PATTERN)]
    expression: Annotated[str, Field(min_length=1, max_length=10_240)]
    await_promise: bool = False


class BrowserEvaluateResult(BaseModel):
    ok: bool
    result: JsonValue | None = None
    error: BrowserError | None = None


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
```

`JsonValue` is defined as `str | int | float | bool | None | list[JsonValue] | dict[str, JsonValue]` to avoid `Any` in tool outputs.

## Tool surface (12 tools)

All 12 tools carry tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). All 12 expose `inputSchema` and `outputSchema` via FastMCP's `@mcp.tool(annotations=..., output_schema=...)`. All 12 emit `HealthFeedState` updates per the `/health` discipline.

### Annotation matrix

| Tool | readOnly | destructive | idempotent | openWorld |
|---|---|---|---|---|
| `cmux_list_workspaces` | true | false | true | true |
| `cmux_list_notifications` | true | false | true | true |
| `cmux_identify` | true | false | true | true |
| `cmux_send_keys` | false | **true** | false | true |
| `cmux_notify` | false | false | false | true |
| `cmux_browser_navigate` | false | **true** | false | true |
| `cmux_browser_snapshot` | true | false | true | true |
| `cmux_browser_evaluate` | false | **true** | false | true |
| `cmux_browser_click` | false | **true** | false | true |
| `cmux_browser_type` | false | **true** | false | true |
| `cmux_browser_tabs` | true | false | true | true |
| `cmux_browser_console` | true | false | true | true |

`browser_evaluate.expression` is annotated `dangerousHint: true` because arbitrary JS can exfiltrate via `fetch` or clobber state; downstream agents that surface cmux-mcp to untrusted callers MUST NOT expose this tool without proxy-side constraints.

### Naming convention

All 12 tools carry the `cmux_` prefix to prevent collision with other MCP servers' tool names (`notify`, `identify`, `send_keys` are all taken by sibling servers). The `browser_` segment groups the 7 browser tools; the bare verbs after `cmux_` apply to the 5 socket tools.

### Streamable HTTP

- Endpoint path: `POST /mcp` (JSON-RPC over HTTP) and `GET /mcp` (SSE for server→client streaming, if any).
- Accept header: `application/json, text/event-stream` (per MCP 2025-06-18).
- `Mcp-Session-Id`: issued once per `initialize` handshake; retained for the cmux-session lifetime. Re-`initialize` within the same session is a no-op.
- Resumability: `none` in v1. Clients must reconnect on disconnect. SSE replay window is not implemented.
- Server→client notifications: not implemented in v1. See "Out of v1" — `notification.list` is pull-only.
- MCP protocol version pinned: `2025-06-18` (supports `outputSchema`, `structuredContent`, tool annotations).

### Error envelope (all 12 tools)

Every tool returns `CallToolResult(content=[TextContent(text=...)], is_error=False)` on success, or `CallToolResult(content=[TextContent(text=...)], is_error=True, structured_content={...})` on failure. The structured error envelope:

```python
class ToolError(BaseModel):
    code: Literal[
        "unsupported_platform",
        "cmux_only_access_denied",
        "cmux_socket_unreachable",
        "cmux_socket_eof_reconnecting",
        "cmux_socket_max_retries_exceeded",
        "cmux_cli_failed",
        "cmux_cli_not_found",
        "cmux_cli_timeout",
        "cmux_protocol_error",
        "browser_eval_runtime_error",
        "browser_selector_not_found",
        "surface_not_found",
        "validation_error",
        "rate_limited",
        "response_truncated",
        "internal_error",
    ]
    message: str
    retryable: bool
    data: dict[str, JsonValue] | None = None
```

Stable error codes are pinned by `test_tool_error_string_mapping` so any wording change surfaces as a test failure.

### Tools (12)

#### 1. `cmux_list_workspaces`

Returns the tree of workspaces → panes → surfaces, including focus metadata.

- **Wraps:** `workspace.list` + `surface.list` + `pane.surfaces` (fails as a unit if any sub-call fails; no partial output)
- **Inputs:** none
- **Output:** `{"workspaces": [Workspace, ...]}`
- **Error codes:** `cmux_socket_unreachable`, `cmux_socket_eof_reconnecting`

#### 2. `cmux_list_notifications`

Lists all pending cmux notifications (ring-around-pane + sidebar).

- **Wraps:** `notification.list`
- **Inputs:** none
- **Output:** `{"notifications": [Notification, ...]}`
- **Error codes:** `cmux_socket_unreachable`, `cmux_socket_eof_reconnecting`

#### 3. `cmux_identify`

Returns the focused window/workspace/pane/surface context.

- **Wraps:** `system.identify`
- **Inputs:** none
- **Output:** `{"window": str, "workspace_id": str, "pane_id": str, "surface_id": str, "kind": SurfaceKind}`
- **Error codes:** `cmux_socket_unreachable`, `cmux_socket_eof_reconnecting`

#### 4. `cmux_send_keys`

Sends text or a special key to a terminal surface. **Fire-and-forget** in v1 — no read companion tool.

- **Wraps:** `surface.send_text` (for text) and `surface.send_key` (for special keys)
- **Inputs:** `SendKeysInput` (exclusive-or enforced via `model_validator`)
- **Output:** `{"ok": true, "surface_id": str}`
- **Error codes:** `validation_error`, `surface_not_found`, `cmux_socket_unreachable`
- **See also:** `surface_read` deferred to v1.1

#### 5. `cmux_notify`

Dispatches an OS notification that rings a pane and lights up the sidebar.

- **Wraps:** `notification.create`
- **Inputs:** `NotifyInput`
- **Output:** `{"notification_id": str, "created_at": datetime}`
- **Error codes:** `validation_error`, `rate_limited` (rate limit: 1/s default, configurable), `cmux_socket_unreachable`

#### 6. `cmux_browser_navigate`

Navigates the browser surface to a URL. `url` must be `http://` or `https://` (Pydantic `HttpUrl` enforces).

- **Wraps:** `cmux browser --surface X navigate <url> [--snapshot-after]`
- **Inputs:** `BrowserNavigateInput`
- **Output:** `{"ok": true, "url": HttpUrl, "snapshot": BrowserSnapshot | None, "truncated": bool}`
- **Error codes:** `validation_error`, `surface_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`, `response_truncated`

#### 7. `cmux_browser_snapshot`

Returns the accessibility tree of the current page.

- **Wraps:** `cmux browser --surface X snapshot --interactive`
- **Inputs:** `BrowserSnapshotInput`
- **Output:** `BrowserSnapshot`
- **Error codes:** `surface_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`, `response_truncated`

#### 8. `cmux_browser_evaluate`

Executes JavaScript in the browser context, returns the result.

- **Wraps:** `cmux browser --surface X eval <js>`
- **Inputs:** `BrowserEvaluateInput` (`expression` length 1-10,240 chars)
- **Output:** `BrowserEvaluateResult` (envelope: `ok` + `result` + `error`)
- **Behavior:**
  - `await_promise: true` awaits top-level Promises (cmux CLI may not natively support — if not, server wraps in `Promise.resolve().then(...)` and polls via `eval` to wait)
  - JS exceptions return `{ok: false, error: {message, stack}}`
  - Non-serializable returns (`undefined`, DOM nodes, functions) are coerced to JSON-serializable or return `{ok: false, error: "not serializable"}`
  - **Trust model:** arbitrary JS executes in the cmux browser context; agents that surface cmux-mcp to untrusted callers MUST NOT expose this tool, or MUST constrain via proxy
- **Error codes:** `validation_error`, `surface_not_found`, `browser_eval_runtime_error`, `cmux_cli_timeout`, `response_truncated`

#### 9. `cmux_browser_click`

Clicks an element by CSS selector.

- **Wraps:** `cmux browser --surface X click <selector> [--snapshot-after]`
- **Inputs:** `BrowserClickInput`
- **Output:** `{"ok": true, "snapshot": BrowserSnapshot | None}`
- **Error codes:** `validation_error`, `surface_not_found`, `browser_selector_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`

#### 10. `cmux_browser_type`

Types text into an input by CSS selector (uses `fill` semantics).

- **Wraps:** `cmux browser --surface X fill <selector> --text <text>`
- **Inputs:** `BrowserTypeInput` (`text` length ≤ 10,240; `submit` adds Enter after fill)
- **Output:** `{"ok": true}`
- **Error codes:** `validation_error`, `surface_not_found`, `browser_selector_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`

#### 11. `cmux_browser_tabs`

Lists the open tabs of the browser surface. **Read-only** in v1 — see "Out of v1" for tab mutation.

- **Wraps:** `cmux browser --surface X tab list --json`
- **Inputs:** `BrowserTabsInput`
- **Output:** `{"tabs": [BrowserTab, ...]}`
- **Error codes:** `surface_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`

#### 12. `cmux_browser_console`

Reads console messages and JS errors from the browser surface. **Aggregates two CLI calls** (`console list` + `errors list`) via `asyncio.gather(..., return_exceptions=True)`; partial-failure semantics: if either sub-call fails, the failing sub-list returns empty (logged at WARN).

- **Wraps:** `cmux browser --surface X console list` + `errors list`
- **Inputs:** `BrowserConsoleInput` (`limit` 1-1000; `level` filter applied client-side after fetch; `since` for de-duplication)
- **Output:** `BrowserConsoleResult`
- **Ordering:** `messages` and `errors` are each ordered by `timestamp` ascending (oldest first). `limit` applied after filtering.
- **Error codes:** `surface_not_found`, `cmux_cli_failed`, `cmux_cli_timeout`, `response_truncated`

## Transport layer details

### CmuxSocketTransport — JSON-RPC client state machine

**Connection lifecycle:**

1. `connect()` opens unix socket; reads `system.ping` once; transitions to `connected`.
2. On EOF: transition to `reconnecting`; spawn backoff loop.
3. Backoff: `min(reconnect_max_delay_seconds, reconnect_initial_delay_seconds * 2 ** attempt) * random.uniform(0, 1)` with `reconnect_max_attempts` ceiling (default 5). After max: transition to `disconnected`; subsequent `request()` calls fail-fast with `cmux_socket_max_retries_exceeded`.
4. While `disconnected`, `/health` reports socket feed as `state: "disconnected"`. Server stays up; agents can recover manually or wait for cmux to come back.
5. `aclose()` cancels pending futures with `CmuxTransportError`, drains, closes.

**Concurrent requests:**

- Single long-lived socket, multiplexed by `id`.
- Outbound: `asyncio.Lock` serializes writes (prevent byte-level interleaving).
- Inbound: `_reader_task` loops `readline()` → `json.loads()` → looks up `asyncio.Future` by `id` → resolves.
- ID generation: monotonic counter paired with a "session epoch" UUID that bumps on reconnect — guarantees no collision across reconnect cycles.

**Cancellation:**

- Client cancels request task → `Future` is cancelled and removed from correlation map → reader task skips cancelled futures (via `Future.cancelled()` check) → cancellation doesn't leak memory or dispatch to dead futures.

**Line framing:**

- cmux protocol is documented as newline-terminated JSON. The transport assumes no `\n` appears inside JSON string values from cmux. If this assumption breaks, switch to Content-Length framing (rare, since cmux owns the protocol).

### CmuxCliTransport — subprocess management

**Per-call contract:**

```python
async def call(self, args: Sequence[str], *, timeout: float | None = None) -> CliResult:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=self._filtered_env(),  # see Security §subprocess-env
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout or self._default_timeout)
    except asyncio.TimeoutError:
        proc.send_signal(SIGTERM)
        try:
            await asyncio.wait_for(proc.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            proc.send_signal(SIGKILL)
            await proc.wait()
        raise CmuxTimeoutError(...)
    return CliResult(
        ok=proc.returncode == 0,
        stdout=stdout,
        stderr=stderr,
        returncode=proc.returncode or 0,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
```

**Concurrency:**

- Global `asyncio.Semaphore(max_concurrent_cli_subprocesses)` (default 8). Prevents fork-bomb on misbehaving agent fan-out.
- Per-surface `asyncio.Lock` keyed by `surface_id`. Serializes concurrent browser ops on the same surface (WebKit doesn't tolerate interleaved commands). Different surfaces run in parallel.

**Cancellation:**

- Calling task cancelled → subprocess killed via SIGTERM (1s grace) → SIGKILL fallback. No zombie `cmux` processes.

**Stderr:**

- Always piped. Always read concurrently with stdout (deadlock-free).
- On non-zero exit, `stderr` truncated to 4 KiB and included in `ToolError.data["stderr"]`.
- On zero exit, `stderr` logged at DEBUG if non-empty.

**Concurrency contract documented in tool descriptions:** cmux browser calls to the same surface_id are serialized; cmux browser calls to different surface_ids may run in parallel.

## Exception hierarchy

```python
class CmuxError(Exception):
    """Base. Carries context dict for /health envelope and structured tool errors."""

class CmuxTransportError(CmuxError):
    """Socket EOF, reconnect failure, malformed JSON."""

class CmuxTimeoutError(CmuxError):
    """Per-call socket or CLI timeout fired."""

class CmuxOnlyAccessDeniedError(CmuxError):
    """Socket access denied by cmuxOnly mode. Recovery: relaunch from inside cmux terminal."""

class UnsupportedPlatformError(CmuxError):
    """Non-darwin without CMUX_MCP_MOCK=1."""

class CmuxBinaryNotFoundError(CmuxError):
    """cmux CLI binary missing or not executable."""

class CmuxProtocolError(CmuxError):
    """cmux returned error.code or malformed JSON-RPC response."""

class CmuxValidationError(CmuxError):
    """Input validation failed (regex, URL, type, length)."""
```

### Error surface split

- **Startup errors** (during `start`): raise and exit non-zero. Surface as `start` exit code + stderr message.
- **Mid-session errors** (during tool call): caught in each tool wrapper, mapped to `ToolError` (per the error envelope above) with `is_error=True`.
- Strings are pinned by `test_tool_error_string_mapping` — any wording change is a test failure.

## Configuration

`CmuxMCPConfig` extends `pydantic_settings.BaseSettings` directly with explicit `SettingsConfigDict`. Per cross-llm-mcp decision log row 24-28, `OneiricMCPConfig(BaseModel)` silently ignores `SettingsConfigDict` overrides; using `BaseSettings` directly is the verified-working pattern.

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class CmuxMCPConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CMUX_MCP_",
        env_file=".env",
        extra="allow",
    )

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT  # see below
    socket_path: Path = Path(os.environ.get("CMUX_SOCKET_PATH", "/tmp/cmux.sock"))
    cmux_cli_path: Path | None = None  # None → auto-discovery (see below)
    socket_short_timeout_seconds: float = 5.0
    socket_long_timeout_seconds: float = 15.0
    cli_timeout_seconds: float = 30.0
    cli_max_concurrent: int = 8
    reconnect_initial_delay_seconds: float = 0.5
    reconnect_max_delay_seconds: float = 30.0
    reconnect_max_attempts: int = 5
    max_response_bytes: int = 1_048_576  # 1 MiB
    notify_rate_limit_per_second: float = 1.0
    mock_mode: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    shutdown_grace_seconds: float = 10.0
    auth_enabled: bool = False  # opt-in for non-loopback deployments
    pid_file_path: Path = Path(
        os.environ.get("XDG_RUNTIME_DIR", "/tmp") + "/cmux-mcp/cmux-mcp.pid"
    )

    @model_validator(mode="after")
    def _mock_mode_auto_on_non_darwin(self) -> "CmuxMCPConfig":
        if not self.mock_mode and sys.platform != "darwin":
            object.__setattr__(self, "mock_mode", True)
        return self
```

`DEFAULT_PORT: int = 3061` is exported from `cmux_mcp/__init__.py`. Every other reference to `3061` imports from there. Single source of truth.

### cmux CLI binary discovery

When `cmux_cli_path` is not set, server probes in order:

1. `CMUX_MCP_CLI_PATH` env var (operator override; checked first inside `__init__`)
2. `which cmux` from `$PATH`
3. `/Applications/cmux.app/Contents/Resources/bin/cmux` (Homebrew Cask target)
4. `/opt/homebrew/Caskroom/cmux/*/cmux.app/Contents/Resources/bin/cmux` (latest version, sorted)
5. `/usr/local/Caskroom/cmux/*/cmux.app/Contents/Resources/bin/cmux` (Intel macs)
6. `~/Library/Developer/Xcode/DerivedData/cmux-*/Build/Products/{Debug,Release}/cmux.app/Contents/Resources/bin/cmux` (dev builds)
7. Fail with `cmux_cli_not_found` listing probed paths

`doctor` subcommand runs the same probe and reports the result.

### Mock mode (resolution of contradiction)

- Non-darwin: `mock_mode` auto-flips to `True` via validator (only if not explicitly set). On startup, server logs an unmissable WARN banner to stderr: `cmux-mcp running in MOCK MODE — all cmux responses are canned fixtures; do not use for real work`.
- On darwin: `mock_mode` defaults to `False`. Setting `CMUX_MCP_MOCK=1` triggers the same WARN banner.
- The WARN banner fires if `CMUX_MCP_MOCK=1` AND neither `PYTEST_CURRENT_TEST` nor `CMUX_MCP_MOCK_ACKNOWLEDGED=1` is set.
- `CMUX_MCP_MOCK_ACKNOWLEDGED=1` is the explicit operator opt-out for the WARN (useful for staging demos).

## Lifecycle

### Startup preflight (`start`)

1. Resolve `cmux_cli_path` via discovery (above). Fail fast with `cmux_cli_not_found` if not found.
2. Open socket; read `system.ping`. Fail fast with `cmux_socket_unreachable` if not reachable.
3. Read `system.capabilities`. (Used for preflight sanity; tool surface is static — see "Out of v1" for dynamic capability-gated tools.)
4. Check `pid_file_path`: if it exists and the PID is alive (`kill -0 <pid>` with same start time), refuse with `already_running`. If it exists and PID is dead, remove and proceed. Write new PID file.
5. Bind HTTP, start `BaseOneiricServerMixin.startup()`, log `started`.

### Per-session termination

- Foreground `start`: rely on SIGHUP from controlling terminal → SIGTERM handler → graceful shutdown.
- Background `start --bg`: dropped per-session guarantee. Documented. Operator must `stop` manually.

### Graceful shutdown (`stop`)

1. SIGTERM handler: stop accepting new tool calls.
2. Wait up to `shutdown_grace_seconds` (default 10s) for in-flight tasks.
3. Cancel remaining tasks (subprocesses killed via `CmuxCliTransport.aclose()`).
4. `CmuxSocketTransport.aclose()` (drain pending futures with `CmuxTransportError`).
5. HTTP server stops accepting.
6. Oneiric logger flushes handlers.
7. PID file unlinked via `atexit`.

### Stale PID file recovery

- `start` always runs `kill -0 <pid>` against the PID file. If dead (or doesn't exist), proceeds. If alive with same start time, refuses. (Best-effort: race window where PID is reaped between `kill -0` and start.)
- `atexit` handler unlinks PID file on every exit path.

### Restart

- `restart` SIGTERMs the running server (graceful shutdown above). In-flight tool calls are killed; clients must retry on reconnect.
- Server-initiated MCP `notifications/cancelled` is NOT emitted in v1 (clients see connection drop and retry).

## /health envelope wiring

Per Bodai MCP backend wiring discipline, `/health` aggregates per-tool + per-transport feed state and returns 503 on degraded.

```python
# server.py
register_http_health_route(
    mcp,
    service_name="cmux-mcp",
    version=__version__,
    extra_components=[
        SocketFeedComponent(transport=socket_transport),
        BrowserCliFeedComponent(transport=cli_transport),
        *tool_feed_components,  # 12 HealthFeedState instances, one per tool
    ],
)
```

Per the discipline, each feed carries the four signals: `entities_count`, `last_updated_timestamp`, `errors_total`, `cycles_total`.

**Mock-mode health:** mock transport emits to a separate `mock_transport` component. `/health` reports `mock_mode: true` so dashboards can alert on `mock_transport.cycles_total > 0` in production.

**HTTP status code:**
- 200 OK if all feeds `ok`
- 503 Service Unavailable if any feed `degraded` (socket disconnected, CLI binary missing, or any tool feed has `cycles_total == 0 && errors_total == 0` after 60s warm-up)

**Tool feed placement:** every tool body follows:

```python
async def tool_handler(...):
    state = self.tool_feeds["cmux_browser_click"]
    state.record_cycle()
    try:
        # actual work
        state.record_success()
        return result
    except CmuxError as exc:
        state.record_error()
        return ToolError(code=exc.code, message=str(exc), retryable=exc.retryable).to_call_result()
    finally:
        pass  # state counters persist across calls
```

`try/finally` placement: `record_cycle()` at top, `record_success()` on success, `record_error()` on exception. No outer `try/finally` needed — the cycle counter is recorded in the try and the success/error in the else/except.

## Subprocess management

See § "CmuxCliTransport — subprocess management" above. Summary of guarantees:

- `asyncio.create_subprocess_exec` with `exec`, not shell (no injection vector).
- Per-call timeout via `asyncio.wait_for(proc.communicate(), timeout=...)`.
- SIGTERM grace (1s) → SIGKILL fallback on timeout.
- stderr drained concurrently (no deadlock).
- Global `asyncio.Semaphore(max_concurrent_cli_subprocesses)` caps fan-out.
- Per-surface `asyncio.Lock` serializes same-surface calls.
- Calling task cancellation kills the subprocess.
- Subprocess env filtered to allowlist (see Security).

## Logging

- Logger name: `cmux_mcp.<module>` (per fleet convention). Module-level `_LOG = oneiric.logging.get_logger(__name__)`.
- Oneiric logger only. No stdlib `logging`. No `print()`.
- Levels:
  - `ERROR`: uncaught exceptions, startup failures
  - `WARNING`: mock-mode-in-production, selector misses caught by self-test, partial-result recoveries, stderr non-empty on zero-exit subprocess
  - `INFO`: per-call success (tool name, surface_id, duration_ms, byte size), lifecycle events
  - `DEBUG`: per-poll, per-subprocess-call detail, full stderr

### PII / secret exclusion list

The following input fields are NEVER logged at any level (only metadata: length, surface_id, field name):

- `browser_navigate.url` — log only the URL with query string stripped, OR `{url_sha256: ...}` hash. URLs commonly embed auth tokens (`?token=...&api_key=...`).
- `browser_evaluate.expression` — log only length + first 32 chars (often enough to identify without leaking `document.cookie` reads).
- `browser_type.text` and `cmux_send_keys.text` — log only length.
- `notify.body`, `notify.subtitle` — log only length.
- Browser snapshots, console messages, JS evaluation results — log only length.

`token`, `api_key`, `password`, `secret` substring matches anywhere in input fields trigger ERROR-level redaction log + scrubbing before persistence.

## Mock mode and testing

`CMUX_MCP_MOCK=1` (or auto-enabled on non-darwin) routes all transport calls through `CmuxMockTransport`, which reads canned responses from `tests/fixtures/cmux_responses.yaml`. This allows:

- CI runs on Linux (no cmux required).
- Fast deterministic tests.
- Regression coverage of all 12 tools without a live cmux instance.

### Fixture format

```yaml
# tests/fixtures/cmux_responses.yaml
- method: "workspace.list"
  params: {}  # wildcard
  response:
    result:
      workspaces: [...]
- method: "browser.snapshot"
  params: { "surface_id": "surface:abc" }
  response:
    result:
      snapshot: "..."
```

Mock transport matches on `(method, params)` and returns the canned response. Default fallback: error response with `cmux_protocol_error` code. Override per test via `CmuxMockTransport.add_response(method, params, response)`.

### Test layers

- **Unit tests** (`tests/unit/`): mock transport; cover tool input validation, error mapping, capability gating, lifecycle state machine. Marker: `unit`.
- **Integration tests** (`tests/integration/`): real socket + CLI. Marker: `integration`. Skipped unless `CMUX_MCP_INTEGRATION=1` is set.
- **End-to-end tests** (`tests/e2e/`): full FastMCP HTTP server with mock transport. Marker: `e2e`.

`pytest` config: `asyncio_mode = "auto"` (per fleet convention).

### Named tests (cross-reference anchors)

- `test_cmux_only_socket_denied_raises` — `UnsupportedPlatformError` raised outside cmux
- `test_mock_mode_health_returns_200` — `/health` with mock transport
- `test_tool_health_feed_state_increments_per_call` — `HealthFeedState.cycles_total` updates per tool
- `test_socket_eof_triggers_reconnect_with_backoff` — backoff config respected
- `test_socket_max_retries_exceeded_raises` — `disconnected` state after max retries
- `test_cli_subprocess_timeout_kills_process` — `CmuxCliTransport.call` timeout kills subprocess
- `test_cli_concurrency_semaphore_caps_fanout` — `max_concurrent_cli_subprocesses` enforced
- `test_per_surface_lock_serializes_concurrent_calls` — same-surface serialization
- `test_validation_error_returns_structured_envelope` — `ToolError` shape
- `test_send_keys_exactly_one_of_text_or_key` — `model_validator`
- `test_url_scheme_allowlist_rejects_javascript` — `HttpUrl` validation
- `test_response_truncated_marker_set_when_over_limit` — `max_response_bytes` cap
- `test_stale_pid_file_recovered_on_start` — `kill -0` check + recovery
- `test_graceful_shutdown_drains_inflight` — `shutdown_grace_seconds` respected
- `test_log_excludes_pii_fields` — URL query stripping, expression redaction

## Security

### Access mode (`cmuxOnly`)

cmux's default socket access mode restricts connections to **processes launched inside cmux terminals**. cmux-mcp inherits this. Servers launched from outside cmux are denied at the socket layer; cmux-mcp surfaces this as `cmux_only_access_denied` on `start`. Recovery hint embedded in the error: `Re-run 'cmux-mcp start' from a cmux terminal pane.`

### Input validation

- All tool inputs flow through Pydantic v2 models with `Annotated[str, Field(pattern=...)]` for regex, `Annotated[HttpUrl, Field(...)]` for URLs.
- `surface_id` regex: `^surface:[a-zA-Z0-9_-]+$`.
- `notification_id` regex: `^notification:[a-zA-Z0-9_-]+$`.
- `selector` length 1-1,024 (browser tools).
- `expression` length 1-10,240 (browser_evaluate).
- `text` length ≤ 10,240 (browser_type, send_keys).
- URLs must be `http://` or `https://` (Pydantic `HttpUrl`).

### HTTP auth

- Default: bind to `127.0.0.1` (loopback only). No auth required.
- Opt-in: `CMUX_MCP_AUTH_ENABLED=1` enables mcp-common JWT support. Operator must also set `MAHAVISHNU_AUTH_SECRET`.
- Non-loopback bind (`host=0.0.0.0`) requires `auth_enabled=true`; `start` exits non-zero otherwise.

### Subprocess env

`subprocess_env_allowlist` (hardcoded): `PATH`, `LANG`, `LC_*`, `TMPDIR`, `USER`, `HOME`, `CMUX_SOCKET_PATH`, `CMUX_SURFACE_ID`, `CMUX_WORKSPACE_ID`. Build env dict from `os.environ` filtered by allowlist; pass via `env=` kwarg. Prevents leaking `MINIMAX_API_KEY`, `MAHAVISHNU_AUTH_SECRET`, etc. into cmux subprocesses.

### Output trust model

cmux-mcp does not interpret, sanitize, or filter tool output. Output is passed through verbatim. The MCP client (agent runtime) is responsible for prompt-injection handling. Documented in README.

`browser_evaluate` returns arbitrary JS evaluation results from the cmux browser context. Pages may include prompt-injection attempts in DOM, console, etc. The MCP client must defend.

`browser_console` and `browser_snapshot` return page content that may include adversarial text. Documented in README; tool descriptions include a "see also" pointer to MCP client prompt-injection defenses.

### Mock mode security

Mock-mode responses come from committed fixture files in `tests/fixtures/cmux_responses.yaml`. They contain no secrets or PII. Production deployments must never set `CMUX_MCP_MOCK=1`; the server emits an unmissable WARN banner when mock mode is active outside test contexts.

### Logging exclusion

See § "Logging → PII / secret exclusion list" above. Inputs containing `token`, `api_key`, `password`, or `secret` substrings are scrubbed before any log persistence.

## Project structure

```
cmux-mcp/
  cli.py                  # mcp-common lifecycle (start/stop/restart/status/health/version/doctor)
  __main__.py             # entry point: MCPServerCLIFactory.create_server_cli(...)
  config.py               # CmuxMCPConfig (BaseSettings) + DEFAULT_PORT
  client.py               # CmuxSocketTransport, CmuxCliTransport, CmuxMockTransport
  models.py               # Workspace, Surface, Pane, Notification, BrowserSnapshot, etc.
  errors.py               # CmuxError hierarchy
  server.py               # CmuxMCPServer(BaseOneiricServerMixin) + register_http_health_route(...)
  _tools.py               # 12 @mcp.tool() registrations (separate module to break import cycle)
  tools/                  # optional split if _tools.py grows large
    __init__.py
    socket_tools.py       # cmux_list_workspaces, cmux_list_notifications, cmux_identify, cmux_send_keys, cmux_notify
    browser_tools.py      # 7 cmux_browser_* tools
  health.py               # SocketFeedComponent, BrowserCliFeedComponent, MockTransportComponent
  settings/
    cmux-mcp.yaml         # committed defaults
  tests/
    conftest.py
    fixtures/
      cmux_responses.yaml
    unit/
      test_models.py
      test_config.py
      test_transport_socket.py
      test_transport_cli.py
      test_errors.py
      test_health.py
      test_lifecycle.py
      test_socket_tools.py
      test_browser_tools.py
      test_logging_pii.py
    integration/
      test_socket_e2e.py
      test_browser_e2e.py
    e2e/
      test_health_endpoint.py
      test_tool_registration.py
  README.md               # catalog-standard README (13 sections)
  LICENSE                 # BSD 3-Clause
  pyproject.toml          # see Dependencies
```

### `__main__.py` entry point

```python
# cmux_mcp/__main__.py
from mcp_common.cli import MCPServerCLIFactory
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.server import CmuxMCPServer

def main() -> None:
    factory = MCPServerCLIFactory.create_server_cli(
        server_class=CmuxMCPServer,
        config_class=CmuxMCPConfig,
        name="cmux-mcp",
        description="MCP server for cmux terminal automation (macOS only).",
    )
    app = factory.create_app()
    app()


if __name__ == "__main__":
    main()
```

### Server class

```python
# cmux_mcp/server.py
from mcp_common.server import BaseOneiricServerMixin, register_http_health_route
from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.client import CmuxSocketTransport, CmuxCliTransport
from cmux_mcp.health import SocketFeedComponent, BrowserCliFeedComponent
from cmux_mcp._tools import register_tools, build_tool_feed_components
from cmux_mcp import __version__


class CmuxMCPServer(BaseOneiricServerMixin):
    def __init__(self, config: CmuxMCPConfig) -> None:
        self.config = config
        self.mcp = FastMCP(name="cmux-mcp", version=__version__)
        self.socket_transport: CmuxSocketTransport | None = None
        self.cli_transport: CmuxCliTransport | None = None

    async def startup(self) -> None:
        self.socket_transport = await CmuxSocketTransport.connect(self.config)
        self.cli_transport = CmuxCliTransport(self.config)
        register_tools(self.mcp, self.socket_transport, self.cli_transport)
        register_http_health_route(
            self.mcp,
            service_name="cmux-mcp",
            version=__version__,
            extra_components=[
                SocketFeedComponent(self.socket_transport),
                BrowserCliFeedComponent(self.cli_transport),
                *build_tool_feed_components(),
            ],
        )
        self._create_startup_snapshot(custom_components={
            "cmux_socket": self.socket_transport.state,
            "cmux_cli": self.cli_transport.cmux_cli_path,
        })

    async def shutdown(self) -> None:
        if self.cli_transport:
            await self.cli_transport.aclose()
        if self.socket_transport:
            await self.socket_transport.aclose()
        self._create_shutdown_snapshot()

    def get_app(self):
        return self.mcp.http_app()
```

## Dependencies

`pyproject.toml` pins (per fleet convention):

```toml
[project]
name = "cmux-mcp"
version = "0.1.0"
description = "MCP server for cmux terminal automation"
requires-python = ">=3.13"
license = "BSD-3-Clause"
authors = [
    {name = "Les Leslie", email = "les@wedgwoodwebworks.com"},
]
dependencies = [
    "fastmcp>=3.4.0,<5",
    "oneiric>=0.21.0",
    "mcp-common>=0.26.0,<0.27.0",
    "pydantic>=2.13.4",
    "pydantic-settings>=2",
    "httpx>=0.27",
    "psutil>=7.2.2",
    "pyyaml>=6",
]

[project.scripts]
cmux-mcp = "cmux_mcp.__main__:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

Each `.py` source file starts with `from __future__ import annotations`. Public functions carry Google-style docstrings.

## Limitations

- **macOS only**: hard runtime requirement inherited from cmux. Non-macOS hosts require explicit `CMUX_MCP_MOCK=1` opt-in; otherwise `start` fails with `UnsupportedPlatformError`.
- **Per-session foreground**: server lifetime is bounded by the cmux terminal session that launched it (SIGHUP). Background `start --bg` drops this guarantee.
- **No remote browser inspector**: browser ops go through the CLI subprocess layer (~30-100ms latency per call). Direct WebKit Inspector transport is deferred until cmux exposes one.
- **Polling for notifications**: `cmux_list_notifications` is pull-only. Server-initiated MCP notifications are out of v1.
- **Fire-and-forget `cmux_send_keys`**: no read companion tool. `surface_read` deferred to v1.1.
- **Static tool surface**: 12 tools are always registered. Capability-gated dynamic tools deferred.
- **Response schemas partially documented**: most cmux socket methods document request params but not response shapes. Tool outputs use typed Pydantic models where the shape is stable; loose `dict[str, JsonValue]` where shape drift is observed. Drift is logged at WARN; clients should expect extra fields.
- **cmux protocol is GPL-3.0**: cmux-mcp is BSD 3-Clause. cmux-mcp does not link, vendor, or reimplement cmux code. It speaks the documented socket protocol (a wire format) and shells out to the public `cmux` CLI binary. This is the same approach as `jasonraz/cmux-browser-mcp` (MIT, 2024). "Mere aggregation" — not derivative work.

## Open questions

None at design freeze. Items deferred to v1.1+ are listed in **Scope → Out of v1** above.

## Future work

- Skill/hook lifecycle tools (`cmux_list_skills`, `cmux_apply_skill`, `cmux_setup_hooks`)
- `surface_read` companion to `cmux_send_keys` (synchronous control loop)
- Browser tab mutation tools (`cmux_browser_tab_open`, `_close`, `_switch`, `_reload`)
- `browser_screenshot` tool (if/when cmux CLI exposes `screenshot`)
- `CmuxInspectorTransport` when/if cmux ships a remote WebKit inspector endpoint
- Cross-Computer cmux fleet coordination (when cmux ships cloud primitives)
- Server-initiated MCP notifications for cmux events (push model)
- Dynamic tool surface gated on `system.capabilities`
- Persistence layer: feed-state aggregation across sessions via Akosha/Dhara

## References

- cmux repo: https://github.com/manaflow-ai/cmux
- cmux docs: https://cmux.com/docs/
- Socket API: https://cmux.com/docs/api
- Browser automation: https://cmux.com/docs/browser-automation
- `jasonraz/cmux-browser-mcp`: precedent CLI-based cmux MCP server
- `manaflow-ai/cmux-skills`: companion skill repo
- WWW catalog pattern: `/Users/les/Projects/www-mcp-servers/README.md`
- Cross-llm-mcp sibling spec: `/Users/les/Projects/cross-llm-mcp/docs/superpowers/specs/2026-09-16-cross-llm-mcp-design.md`
- Bodai MCP wiring discipline: `/Users/les/Projects/mahavishnu/.claude/decisions/mcp-backend-wiring-discipline.md`

## Decision log

1. **License (BSD 3-Clause)** — matches WWW catalog precedent (excalidraw-mcp, css-mcp, mailgun-mcp, etc.). cmux is GPL-3.0; cmux-mcp does not link or vendor cmux code. "Mere aggregation" rationale per `gpl-subprocess-aggregation.md` memory.
2. **Default port 3061** — next free slot in WWW catalog after css-mcp (3050), excalidraw (3032), langsmith (3048), archive-org (3054), scapy (3056). Port collision-checked against existing fleet.
3. **Hybrid transport (socket + CLI)** — socket-direct for documented `workspace.*`/`surface.*`/`pane.*`/`notification.*`/`system.*` (low latency, multiplexed); CLI subprocess for browser (only documented path; cmux's WebKit browser does not expose a remote inspector).
4. **`CmuxSocketTransport` + `CmuxCliTransport` as two Protocols** — not unified `CmuxTransport`. Failure modes, retry semantics, observability differ; one abstraction would lose critical distinctions.
5. **`BaseSettings` direct subclass for config** — per cross-llm-mcp decision log row 24-28. `OneiricMCPConfig(BaseModel)` silently ignores `SettingsConfigDict` overrides; `BaseSettings` with explicit `SettingsConfigDict(env_prefix=…, env_file=…, extra=…)` is the verified-working pattern.
6. **`cmux_` prefix on all 12 tools** — prevents collision with sibling servers' `notify`, `identify`, `send_keys`. Catalog convention from cross-llm-mcp's naming pattern.
7. **Mock-mode auto-flip on non-darwin WITH unmissable WARN banner** — resolves the contradiction (line 25 vs line 27 vs line 297 of original spec). Non-macOS is a development convenience, not a production deployment.
8. **DEFAULT_PORT as module constant in `__init__.py`** — single source of truth for port discovery (per cross-llm-mcp decision log row 25). Required by Bodai MCP wiring discipline.
9. **`register_http_health_route` with per-tool + per-transport `HealthFeedState`** — per Bodai MCP backend wiring discipline. Without this, `/health` lies about feed state (per `mcp-surface-health-illusion` memory).
10. **Named tests as cross-reference anchors** — listed in § "Named tests" above. Each is a test that pins a specific spec claim. Cross-references from the spec body land on these names.
11. **Lifecycle detection on SIGHUP (foreground only)** — `start --bg` explicitly drops the per-session guarantee. Documented in § "Per-session termination".
12. **Resource limits: `max_response_bytes`, `cli_max_concurrent`, `notify_rate_limit_per_second`** — all defaults pinned in config. Fork-bomb protection and PII logging exclusion work together.
13. **`CmuxMockTransport` implements BOTH protocols** — tool code is identical against real and fake transports.
14. **`from __future__ import annotations` in every source file** — per Bodai CLAUDE.md convention.
15. **Tool annotations on every tool** — per MCP 2025-03-26 spec. Without annotations, MCP clients can't render safety hints or pre-filter mutations.
16. **`outputSchema` + `structuredContent` on every tool** — per MCP 2025-06-18 spec. Avoids stringly-typed double-parse.
17. **Streamable HTTP pinned to MCP 2025-06-18** — supports annotations, `outputSchema`, `structuredContent`. Resumability deferred.
