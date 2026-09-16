# cmux-mcp Design Spec

> **Status:** draft (pending review)
> **Date:** 2026-09-16
> **Spec type:** architectural

## Goal

Build **`cmux-mcp`**, a single MCP server that exposes programmatic control of a running [cmux](https://github.com/manaflow-ai/cmux) instance (the macOS Ghostty-based terminal designed for AI coding agents) as **12 MCP tools** over Streamable HTTP. The server speaks cmux's Unix-socket JSON-RPC protocol directly for orchestration and notifications, and shells out to the cmux CLI for browser automation (the only documented path, since cmux's embedded WebKit browser does not expose a remote inspector endpoint).

The server is **per-session**: it must be launched from inside a cmux terminal so the `cmuxOnly` socket access mode permits connections. Lifecycle is managed by the `mcp-common` CLI (start/stop/restart/status/health).

## Background

cmux is a native macOS terminal app (Swift + AppKit, libghostty rendering) built for running multiple AI coding agents in parallel. It exposes a **Unix-socket JSON-RPC API** at `$CMUX_SOCKET_PATH` (default `/tmp/cmux.sock`) for programmatic control. The documented protocol covers `workspace.*`, `surface.*`, `pane.*`, `notification.*`, and `system.*` namespaces. Browser automation is exposed only via the `cmux browser` CLI command family — the embedded WebKit browser does not expose a remote inspector.

Several standalone cmux MCP servers exist in the wild (`jasonraz/cmux-browser-mcp`, `EtanHey/cmuxlayer`, etc.). None follow the WWW catalog pattern (mcp-common lifecycle, Oneiric config, crackerjack quality gate). `cmux-mcp` is the catalog-grade implementation: BSD 3-Clause, port 3061, mock-mode testable on non-macOS hosts.

## Scope

### In v1

- 12 MCP tools (5 socket + 7 browser CLI)
- Streamable HTTP transport on port 3061
- macOS-only runtime; non-macOS hosts start in mock mode (or fail with `unsupported_platform`)
- Mock-mode test fixture for CI on Linux
- Lifecycle CLI via `mcp-common` (start, stop, restart, status, health, version, doctor)
- Per-session lifecycle: server exits when cmux terminal closes
- BSD 3-Clause license

### Out of v1 (deferred to v1.1+)

- Skill/hook lifecycle (`manaflow-ai/cmux-skills`, `cmux hooks setup`) — separate capability cluster
- Cross-Computer cmux coordination (multi-machine cmux fleet) — out of scope until cmux itself ships cloud primitives
- Custom `cmux.json` commands management — defer until concrete use case
- Direct WebKit Inspector transport — only when cmux exposes a remote inspector endpoint
- SSH workspace automation (`cmux ssh`) — defer; CLI wrapper needed
- Resume-surface bindings (`cmux surface resume set`) — defer
- Split-pane and close-workspace orchestration tools — defer; clients can call `cmux` CLI directly

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
        │  CmuxSocketClient   │                    │   CmuxCliClient     │
        │  asyncio unix sock  │                    │  subprocess cmux …  │
        │  newline-JSON-RPC   │                    │  /Applications/.../ │
        └──────────┬──────────┘                    └──────────┬──────────┘
                   │                                         │
                   ▼                                         ▼
        ┌─────────────────────┐                    ┌─────────────────────┐
        │  cmux daemon socket │                    │   cmux binary       │
        │  /tmp/cmux.sock     │                    │  (browser subcmds)  │
        └─────────────────────┘                    └─────────────────────┘
```

### Transport layer

A thin `CmuxTransport` protocol abstracts the two paths:

```python
class CmuxTransport(Protocol):
    async def request(self, method: str, params: dict | None = None) -> dict: ...
    async def aclose(self) -> None: ...
```

Implementations:
- **`CmuxSocketTransport`** — single asyncio unix socket connection; newline-terminated JSON-RPC requests; auto-reconnect on EOF; per-call ID generation; ~5-15ms latency.
- **`CmuxCliTransport`** — `asyncio.create_subprocess_exec` for `cmux browser --surface X <action>`; captures stdout; ~30-100ms latency.
- **`CmuxMockTransport`** — returns canned responses from fixture files; used in unit tests and on non-macOS hosts when `CMUX_MCP_MOCK=1`.

Tools depend on `CmuxTransport` (the protocol), not on the concrete client. This makes test mocking trivial and future swaps (e.g., WebKit Inspector when exposed) a single-file change.

## Tool surface (12 tools)

### Socket-direct tools (5)

#### 1. `list_workspaces`

Returns the tree of workspaces → surfaces → panes, including focus metadata.

- **Wraps:** `workspace.list` + `surface.list` + `pane.surfaces`
- **Inputs:** none
- **Output:** `{"workspaces": [{"id": str, "title": str, "surfaces": [{"id": str, "kind": "terminal"|"browser", "cwd": str|null, "focused": bool}], "pane_id": str}]}`
- **Use case:** situational awareness; find surface IDs for downstream browser/terminal ops

#### 2. `list_notifications`

Lists all pending cmux notifications (ring-around-pane + sidebar).

- **Wraps:** `notification.list`
- **Inputs:** none
- **Output:** `{"notifications": [{"id": str, "title": str, "subtitle": str|null, "body": str|null, "surface_id": str|null, "created_at": str (ISO 8601)}]}`
- **Use case:** agent checking what needs attention

#### 3. `identify`

Returns the focused window/workspace/pane/surface context.

- **Wraps:** `system.identify`
- **Inputs:** none
- **Output:** `{"window": str, "workspace_id": str, "pane_id": str, "surface_id": str, "kind": "terminal"|"browser"}`
- **Use case:** agent determining where to act without specifying IDs

#### 4. `send_keys`

Sends text or a special key to a terminal surface.

- **Wraps:** `surface.send_text` (for text) and `surface.send_key` (for special keys: `enter`, `tab`, `escape`, `backspace`, `delete`, `up`, `down`, `left`, `right`)
- **Inputs:** `surface_id: str`, `text: str | None`, `key: str | None` (exactly one of `text` or `key`)
- **Output:** `{"ok": true, "surface_id": str}`
- **Use case:** drive a CLI agent (Claude Code, Codex) running inside cmux from an MCP client

#### 5. `notify`

Dispatches an OS notification that rings a pane and lights up the sidebar.

- **Wraps:** `notification.create`
- **Inputs:** `title: str`, `subtitle: str | None`, `body: str | None`, `surface_id: str | None`
- **Output:** `{"notification_id": str}`
- **Use case:** long-running task completion; alerting the user from a headless agent

### Browser CLI tools (7)

All browser tools take a `surface_id: str` first argument and route to `cmux browser --surface <id> …`.

#### 6. `browser_navigate`

Navigates the browser surface to a URL.

- **Wraps:** `cmux browser --surface X navigate <url> [--snapshot-after]`
- **Inputs:** `surface_id: str`, `url: str`, `snapshot_after: bool = False`
- **Output:** `{"ok": true, "url": str, "snapshot": a11y_tree | None}`
- **Use case:** open a docs page, sign in to a service, etc.

#### 7. `browser_snapshot`

Returns the accessibility tree of the current page (Playwright-style snapshot→ref pattern).

- **Wraps:** `cmux browser --surface X snapshot --interactive`
- **Inputs:** `surface_id: str`
- **Output:** `{"snapshot": str (text tree with refs like `[ref=e1]`)}`
- **Use case:** agent reads snapshot, then calls `browser_click` / `browser_type` with refs

#### 8. `browser_evaluate`

Executes JavaScript in the browser context, returns the result.

- **Wraps:** `cmux browser --surface X eval <js>`
- **Inputs:** `surface_id: str`, `expression: str`
- **Output:** `{"result": <JSON-serializable value>}`
- **Use case:** arbitrary DOM inspection, form reading, computed styles

#### 9. `browser_click`

Clicks an element by CSS selector.

- **Wraps:** `cmux browser --surface X click <selector> [--snapshot-after]`
- **Inputs:** `surface_id: str`, `selector: str`, `snapshot_after: bool = False`
- **Output:** `{"ok": true, "snapshot": a11y_tree | None}`
- **Use case:** button clicks, link clicks

#### 10. `browser_type`

Types text into an input by CSS selector (uses `fill` semantics, not keystroke simulation).

- **Wraps:** `cmux browser --surface X fill <selector> --text <text>`
- **Inputs:** `surface_id: str`, `selector: str`, `text: str`, `submit: bool = False` (presses Enter after)
- **Output:** `{"ok": true}`
- **Use case:** form filling, search input

#### 11. `browser_tabs`

Lists the open tabs of the browser surface.

- **Wraps:** `cmux browser --surface X tab list --json`
- **Inputs:** `surface_id: str`
- **Output:** `{"tabs": [{"id": str, "url": str, "title": str, "active": bool}]}`
- **Use case:** discovering which tab to act on

#### 12. `browser_console`

Reads console messages and JS errors from the browser surface.

- **Wraps:** `cmux browser --surface X console list` + `errors list`
- **Inputs:** `surface_id: str`, `limit: int = 50`, `level: "all"|"error"|"warning" = "all"`
- **Output:** `{"messages": [{"level": str, "text": str, "source": str|null, "timestamp": str}], "errors": [{"message": str, "stack": str|null}]}`
- **Use case:** debugging a SPA the agent just interacted with

## Configuration

Settings extend `pydantic_settings.BaseSettings` with `env_prefix="CMUX_MCP_"`:

| Setting | Default | Env var | Purpose |
|---|---|---|---|
| `host` | `"127.0.0.1"` | `CMUX_MCP_HOST` | HTTP bind address |
| `port` | `3061` | `CMUX_MCP_PORT` | HTTP port |
| `socket_path` | env `$CMUX_SOCKET_PATH` or `"/tmp/cmux.sock"` | `CMUX_MCP_SOCKET_PATH` | cmux Unix socket |
| `cmux_cli_path` | `"/Applications/cmux.app/Contents/Resources/bin/cmux"` | `CMUX_MCP_CLI_PATH` | cmux CLI binary |
| `socket_timeout_seconds` | `5.0` | `CMUX_MCP_SOCKET_TIMEOUT` | Per-call socket timeout |
| `cli_timeout_seconds` | `30.0` | `CMUX_MCP_CLI_TIMEOUT` | Per-call CLI timeout |
| `mock_mode` | `False` (auto-`True` on non-darwin) | `CMUX_MCP_MOCK` | Force mock transport |
| `log_level` | `"INFO"` | `CMUX_MCP_LOG_LEVEL` | Oneiric logger level |

## Lifecycle

The server is **per-session** by design (must run inside a cmux terminal so `cmuxOnly` access permits it). `mcp-common` lifecycle:

```bash
cmux-mcp start         # validate socket access, bind 3061, foreground
cmux-mcp start --bg    # background, PID-managed
cmux-mcp status        # running / stopped / stale
cmux-mcp health        # JSON health report (entities_count, errors_total, last_updated)
cmux-mcp stop          # graceful shutdown, close socket
cmux-mcp restart
cmux-mcp doctor        # check socket reachability, cmux CLI version, mock mode
```

`start` exits non-zero with a clear error if:
- Running on non-darwin and `mock_mode` is not explicitly enabled
- `$CMUX_SOCKET_PATH` socket is not reachable (cmux not running, or `cmuxOnly` access denied)
- `cmux` CLI binary is not found

## Mock mode and testing

`CMUX_MCP_MOCK=1` (or auto-enabled on non-darwin) routes all transport calls through `CmuxMockTransport`, which reads canned responses from `tests/fixtures/cmux_responses.yaml`. This allows:

- CI runs on Linux (no cmux required)
- Fast deterministic tests
- Regression coverage of all 12 tools without a live cmux instance

Tests are layered:

- **Unit tests** — mock transport; cover tool input validation, error mapping, capability gating
- **Integration tests** — gated on `CMUX_MCP_INTEGRATION=1`; require live cmux socket + CLI; skipped by default in CI
- **Manual smoke protocol** — documented in README; requires `cmux` running locally

## Project structure

```
cmux-mcp/
  cli.py                  # mcp-common lifecycle
  config.py               # Pydantic BaseSettings subclass
  client.py               # CmuxTransport protocol + Socket/CLI/Mock implementations
  models.py               # Workspace, Surface, Pane, Notification, BrowserSnapshot, ConsoleMessage
  server.py               # FastMCP factory + 12 tool registrations
  tools/                  # split per tool group (optional, see below)
    socket_tools.py       # list_workspaces, list_notifications, identify, send_keys, notify
    browser_tools.py      # 7 browser_* tools
  settings/
    cmux-mcp.yaml         # committed defaults
  tests/
    conftest.py
    fixtures/
      cmux_responses.yaml # mock-mode canned responses
    unit/
      test_socket_tools.py
      test_browser_tools.py
      test_transport.py
    integration/
      test_socket_e2e.py
      test_browser_e2e.py
  README.md
  LICENSE                 # BSD 3-Clause
  pyproject.toml
```

## Security

### Access mode (`cmuxOnly`)

cmux's default socket access mode restricts connections to **processes launched inside cmux terminals**. cmux-mcp inherits this: it must be spawned from a cmux terminal session. Servers launched from outside cmux are denied at the socket layer; cmux-mcp surfaces this as a clear `cmux_only_access_denied` error on `start`.

### Input validation

- All tool inputs are validated through Pydantic models before any transport call
- `surface_id` is validated against the regex `^surface:[a-zA-Z0-9_-]+$` (matches cmux's documented format)
- `selector` arguments to `browser_click` / `browser_type` are passed verbatim to the cmux CLI — they're trusted cmux input, not arbitrary shell
- URLs to `browser_navigate` are validated as well-formed `http://` or `https://` URIs before being passed to the CLI

### Logging

- All tool calls are logged at INFO with inputs and timings
- Errors are logged at ERROR via `logger.exception(...)`
- No notification bodies, browser snapshots, or JS evaluation results are logged at INFO (potential PII); only metadata (length, surface_id, duration)

### Mock mode security

Mock-mode responses come from committed fixture files in `tests/fixtures/`. They contain no secrets or PII. Production deployments must never set `CMUX_MCP_MOCK=1` (the server logs a warning if it detects mock mode outside a test context).

## Configuration validation

`start` runs a connection preflight before binding the HTTP port:

1. Check `socket_path` exists and is a Unix socket (not a regular file)
2. Open the socket and send `system.ping`; expect `{"ok": true, "result": {"pong": true}}`
3. Call `system.capabilities` and confirm `workspace.list` is in the response (sanity check that this is a cmux socket, not something else)
4. On browser transport: shell out to `cmux --version` and confirm output
5. On mock mode: skip steps 1-4, log warning

Any preflight failure exits non-zero with a specific error message.

## Limitations

- **macOS only**: hard runtime requirement inherited from cmux. Non-macOS hosts must use mock mode.
- **Per-session**: server lifetime is bounded by the cmux terminal session that launched it. No long-running daemon mode.
- **No remote browser inspector**: browser ops go through the CLI subprocess layer (~30-100ms latency per call).
- **Response schemas undocumented**: most socket methods document request params but not response shapes. v1 uses conservative `dict | None` return types and refines as shape drift is discovered.
- **cmux protocol is GPL-3.0**: cmux-mcp does not link or vendor cmux code; it only speaks the public socket/CLI protocols. Same pattern as `jasonraz/cmux-browser-mcp` (MIT). This is clean from a licensing perspective.

## Open questions

None at design freeze. Items deferred to v1.1+ are listed in **Scope → Out of v1** above.

## Future work

- `CmuxInspectorTransport` when cmux ships a remote WebKit inspector endpoint
- Skill/hook lifecycle tools (`list_skills`, `apply_skill`, `setup_hooks`)
- Split-pane and close-workspace tools (if user demand emerges)
- Cross-Computer cmux fleet coordination (if cmux ships cloud primitives)
- Persistence layer: feed-state aggregation across sessions via Akosha/Dhara

## References

- cmux repo: https://github.com/manaflow-ai/cmux
- cmux docs: https://cmux.com/docs/
- Socket API: https://cmux.com/docs/api
- Browser automation: https://cmux.com/docs/browser-automation
- `jasonraz/cmux-browser-mcp`: precedent CLI-based cmux MCP server
- `manaflow-ai/cmux-skills`: companion skill repo
- WWW catalog pattern: `/Users/les/Projects/www-mcp-servers/README.md`
