# cmux-mcp - MCP Server for cmux Terminal Automation

## Project Overview

**cmux-mcp** exposes programmatic control of a running
[cmux](https://github.com/manaflow-ai/cmux) instance (macOS-only,
Ghostty-based terminal for AI coding agents) as 12 MCP tools over
Streamable HTTP. The server speaks cmux's Unix-socket JSON-RPC protocol
directly for orchestration and notification tools, and shells out to the
cmux CLI for browser-automation tools.

Built with:

- **FastMCP**: MCP server framework (port 3061)
- **Oneiric**: Runtime components (logging, lifecycle, health, runtime)
- **mcp-common**: `BaseOneiricServerMixin`, `HealthFeedState`,
  `MCPServerCLIFactory`, `HTTPClientAdapter` (HTTP via oneiric, not httpx)
- **Pydantic** / **pydantic-settings**: input/output models + settings
- **PyYAML**: mock transport fixture loading
- **Python 3.14+**: modern type syntax (`X | None`, `list[str]`,
  `pathlib.Path`)

## Architecture

### Core Components

1. **Server (`cmux_mcp/server.py`)** — `CmuxMCPServer(BaseOneiricServerMixin)`.
   Per-instance FastMCP, owns transports, registers `/health` route with
   **503-on-degraded** semantics, and wires all 12 tools in `startup()`.
   `CmuxMCPServer.startup()` MUST call `register_tools(...)` after transport
   and tool-feed init — otherwise `tools/list` returns `{"tools":[]}`.

2. **Transports (`cmux_mcp/client.py`)** — three transport implementations:
   - `CmuxSocketTransport` — long-lived Unix-socket JSON-RPC client.
     Multiplexed by id; reconnect with exponential backoff + jitter.
   - `CmuxCliTransport` — single-shot subprocess calls. Per-surface
     `asyncio.Lock` with **refcount eviction** (`_surface_lock_refs` dict
     drops the lock entry when the refcount hits 0 — H8 lock-leak fix).
     `_release_surface_lock` is **`async`** (sync-returning-a-coroutine
     was a real runtime bug pre-H8; callers must `await` it).
   - `CmuxMockTransport` — in-process canned responses; implements BOTH
     protocol shapes so tool code is identical against real and mock.

3. **Config (`cmux_mcp/config.py`)** — `CmuxMCPConfig(BaseSettings)`
   **directly** (NOT `mcp_common.MCPBaseSettings`). Per spec decision log
   row 5: explicit `SettingsConfigDict(env_prefix="CMUX_MCP_")` for
   orthogonality and unit-testability. `populate_by_name=True` is
   required — without it, `CmuxMCPConfig(mock_mode=True)` silently falls
   back to the platform default. The env var `CMUX_MCP_MOCK=1` (NOT
   `CMUX_MCP_MOCK_MODE`) is honored via `validation_alias`.

4. **Health (`cmux_mcp/health.py`)** — feed components per spec
   §"/health envelope wiring":
   - `SocketFeedComponent(transport: CmuxSocketTransport | CmuxMockTransport)`
   - `BrowserCliFeedComponent(transport: CmuxCliTransport | CmuxMockTransport)`
   - `MockTransportComponent`, `ToolFeedComponent` (one per tool)
   - Each carries `cycles_total`, `last_updated_timestamp`,
     `errors_total`, `entities_count` (mcp-common `HealthFeedState`).
   - `/health` returns **200 healthy / 503 degraded** (custom route —
     mcp-common's helper always returns 200; the override is intentional).

5. **Tools (`cmux_mcp/tools/`)** — 12 tool registrations across two files:
   - `socket_tools.py` — 5 socket-direct tools (`cmux_list_workspaces`,
     `cmux_list_notifications`, `cmux_identify`, `cmux_send_keys`,
     `cmux_notify`).
   - `browser_tools.py` — 7 browser-CLI tools (`cmux_browser_navigate`,
     `cmux_browser_snapshot`, `cmux_browser_tabs`, `cmux_browser_evaluate`,
     `cmux_browser_click`, `cmux_browser_type`, `cmux_browser_console`).
   - Each tool follows `try / except / else`; the success record lives in
     `else:` (mandatory — without it, `/health` reports
     `successes_total=0` forever).

6. **Discovery (`cmux_mcp/cli_discovery.py`)** — auto-detect the cmux CLI
   binary path on macOS.

7. **Errors (`cmux_mcp/errors.py`)** — exception hierarchy:
   `CmuxError` (base), `CmuxTransportError`, `CmuxProtocolError`,
   `CmuxTimeoutError`, `RateLimitedError`. `_as_tool_error` wraps any
   `Exception` as `fastmcp.exceptions.ToolError` for the MCP wire.

## Building and Running

### Installation

```bash
# Using uv (recommended)
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"

# Or using pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Usage

```bash
# Mock mode (any platform — auto-flipped to True on non-macOS with WARN)
CMUX_MCP_MOCK=1 uv run cmux-mcp start

# Real mode (macOS, with cmux daemon running)
uv run cmux-mcp start

# Background
uv run cmux-mcp start --bg

# Lifecycle
uv run cmux-mcp status
uv run cmux-mcp health
uv run cmux-mcp stop
```

### Configuration

Configuration precedence (later overrides earlier):

1. Pydantic field defaults
1. Environment variables `CMUX_MCP_*`
1. `.env` file
1. Programmatic construction (`populate_by_name=True`)

| Env var | Default | Description |
|---|---|---|
| `CMUX_MCP_HOST` | `127.0.0.1` | HTTP bind address |
| `CMUX_MCP_PORT` | `3061` | HTTP port |
| `CMUX_MCP_SOCKET_PATH` | `/tmp/cmux.sock` | cmux Unix socket |
| `CMUX_MCP_CLI_PATH` | auto-discover | cmux CLI binary path |
| `CMUX_MCP_MOCK` | unset | `1`/`true` enables mock mode |
| `CMUX_MCP_AUTH_ENABLED` | `false` | JWT auth for non-loopback |
| `CMUX_MCP_HEALTH_WARMUP_SECONDS` | `60.0` | warmup gate for tool-never-called detection |
| `CMUX_MCP_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |

Loopback-only by default; non-loopback bind requires
`CMUX_MCP_AUTH_ENABLED=true` (enforced by
`_reject_non_loopback_without_auth`).

### MCP Client Configuration

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

## Development Conventions

### Project Structure

```
cmux-mcp/
├── pyproject.toml          # Deps: fastmcp, oneiric, mcp-common, pydantic, pyyaml
├── README.md
├── CLAUDE.md                # Claude-Code-specific guidance
├── AGENTS.md                # Tool-neutral bootstrap
├── QWEN.md                  # This file
├── cmux_mcp/
│   ├── __init__.py          # __version__ + DEFAULT_PORT
│   ├── __main__.py          # CLI entry point
│   ├── cli.py               # Typer-based CLI
│   ├── server.py            # CmuxMCPServer
│   ├── client.py            # Transports
│   ├── config.py            # CmuxMCPConfig
│   ├── health.py            # Feed components
│   ├── errors.py            # Exception hierarchy
│   ├── models.py            # Pydantic IO models + ConsoleLevel
│   ├── logging_setup.py     # Oneiric logger + maybe_warn_mock_mode
│   ├── cli_discovery.py     # cmux CLI auto-detect
│   ├── _tools.py            # register_tools()
│   └── tools/
│       ├── socket_tools.py  # 5 socket-direct tools
│       └── browser_tools.py # 7 browser-CLI tools
├── tests/
│   ├── unit/
│   ├── integration/         # require live cmux
│   └── functional/
├── settings/                # committed defaults
└── docs/
```

### Testing

```bash
pytest                                # All tests
pytest -m unit                        # Unit tests only
pytest -m integration                 # Integration tests (require live cmux)
pytest -m "not slow"                  # Skip slow tests for fast feedback
pytest --cov=cmux_mcp --cov-report=html  # Coverage
```

`asyncio_mode = "auto"` — async tests don't need `@pytest.mark.asyncio`.

### Quality Gates

```bash
crackerjack run          # Full quality suite (17 fast + 11 comprehensive hooks)
pytest                   # Run tests
pytest --cov=cmux_mcp --cov-report=html
```

All hooks pass as of 2026-09-21 (post ty + refurb + creosote fix wave).

### Coding Standards

- Python 3.14+, `from __future__ import annotations` first.
- Imports: stdlib → third-party → first-party (`cmux_mcp`).
- Modern syntax: `X | None`, `list[str]`, `pathlib.Path`.
- No `assert` in `cmux_mcp/**` (bandit B101) — use `cmux_mcp/errors.py`.
- Prefer `with suppress(FileNotFoundError)` over
  `try: ... except FileNotFoundError: pass`.
- `ty` type checker (`# ty: ignore[<code>]`, never bare `# type: ignore`).
- Mass suppressions (>5 per file) are a smell — fix the underlying issue.
- Class-level type annotations satisfy mixin contracts — single declaration
  cascades through usage sites; do NOT sprinkle `# ty: ignore` for the
  same issue across many lines.

## Key Features

1. **12 MCP Tools**: 5 socket-direct + 7 browser-CLI.
1. **Mock Mode**: cross-platform testing without a live cmux daemon.
1. **Tool Feed Instrumentation**: every tool feeds `/health` with cycle /
   success / error metrics.
1. **Per-surface Lock Refcount Eviction**: `_surface_locks` doesn't leak
   over a server's lifetime (H8).
1. **Custom /health Route**: 503-on-degraded semantics (C4 fix).
1. **PII Redaction Helpers**: `redact_url_query_string`,
   `redact_expression` in `logging_setup.py`.
1. **Subprocess Env Allowlist**: prevents leaking API keys to cmux CLI
   subprocesses.
1. **Streamable HTTP Transport**: modern MCP transport.

## Current Status

**Version**: 0.2.0 (post flat-layout migration 2026-09-20)

**Completed**:

- 12 tools implemented and tested (125 unit tests passing).
- Mock mode + auto-detect on non-darwin.
- Crackerjack clean: 17/17 fast hooks, 11/11 comprehensive hooks.
- Flat layout migration (post src-layout).
- GitHub repo created: `github.com/lesleslie/cmux-mcp`.
- CLAUDE.md + AGENTS.md + QWEN.md bootstrapped.

**Planned / In Progress**:

- v0.2.x: PII redaction wired to log call sites (helpers exist; no
  call sites yet by default).
- v0.3.x: Pydantic AI agent adapter integration (oneiric
  `mcp_common.HTTPClientAdapter` already available if HTTP needs arise).
- Production hardening: rate-limit persistence beyond module-level
  module-state variable.

## Development

To contribute to cmux-mcp:

1. Fork the repository.
1. Create a virtual environment: `uv venv`.
1. Install in editable mode: `uv pip install -e ".[dev]"`.
1. Make your changes.
1. Run tests: `uv run pytest`.
1. Run quality gate: `uv run crackerjack run`.
1. Submit changes (pre-1.0 merge policy: merge directly to `main`).
1. **Do not** push without explicit approval.

## Security

- Loopback bind by default; non-loopback requires
  `CMUX_MCP_AUTH_ENABLED=true` (validator in `config.py`).
- Subprocess env filtered to `SUBPROCESS_ENV_ALLOWLIST` in
  `cmux_mcp/client.py` (excludes `MINIMAX_API_KEY`,
  `MAHAVISHNU_AUTH_SECRET`, etc.).
- Pydantic validation on every tool input (`BrowserNavigateInput`,
  `SendKeysInput`, `NotifyInput`, etc.) — surface IDs match
  `SURFACE_ID_PATTERN`, expression length bounded.
- macOS-only real mode; non-macOS hosts must use mock mode.
- No external API keys shipped in the repo; settings under
  `settings/local.yaml` are gitignored.

## Bodai Ecosystem Position

cmux-mcp is the **cmux terminal automation** component. It sits beside:

- **Mahavishnu** (port 8680) — orchestrator; routes work to cmux-mcp.
- **Akosha** (port 8682) — Seer (intelligence, embeddings).
- **Session-Buddy** (port 8678) — Builder (memory).
- **Crackerjack** (port 8676) — Inspector (quality).
- **Bodai Crow** (port 8693) — browser automation bridge.
- **web_reader** (port 8699) — webpage ingestion.

When Mahavishnu routes a task that needs terminal automation, it
delegates to cmux-mcp via MCP. cmux-mcp returns structured results; the
audit trail lives in Akosha's OTel store.
