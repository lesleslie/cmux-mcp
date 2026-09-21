# AGENTS.md

Tool-neutral bootstrap for cmux-mcp. See `CLAUDE.md` for high-level guidance.

## Module Organization

- `cmux_mcp/server.py` — `CmuxMCPServer(BaseOneiricServerMixin)`; FastMCP
  instance, transports, `/health` route, tool wiring.
- `cmux_mcp/client.py` — three transports (`Socket` / `Cli` / `Mock`).
- `cmux_mcp/config.py` — `CmuxMCPConfig(BaseSettings)`. Direct subclass
  for explicit env-var orthogonality.
- `cmux_mcp/health.py` — feed components (`SocketFeedComponent`,
  `BrowserCliFeedComponent`, `MockTransportComponent`, `ToolFeedComponent`).
- `cmux_mcp/tools/socket_tools.py` — 5 socket-direct tools
  (`cmux_list_workspaces`, `cmux_list_notifications`, `cmux_identify`,
  `cmux_send_keys`, `cmux_notify`).
- `cmux_mcp/tools/browser_tools.py` — 7 browser-CLI tools
  (`cmux_browser_navigate`, `cmux_browser_snapshot`, `cmux_browser_tabs`,
  `cmux_browser_evaluate`, `cmux_browser_click`, `cmux_browser_type`,
  `cmux_browser_console`).
- `cmux_mcp/_tools.py` — `register_tools()` (called by `CmuxMCPServer.startup`).
- `cmux_mcp/cli_discovery.py` — auto-detect cmux CLI binary path.
- `cmux_mcp/errors.py` — exception hierarchy (`CmuxError`,
  `CmuxTransportError`, `CmuxProtocolError`, `CmuxTimeoutError`,
  `RateLimitedError`).
- `cmux_mcp/models.py` — Pydantic input/output models + `ConsoleLevel` StrEnum.
- `cmux_mcp/logging_setup.py` — Oneiric logger + `maybe_warn_mock_mode`.

Tests mirror this structure under `tests/unit/`.

## Build, Test, Development

```bash
uv sync --group dev           # install all deps
uv run cmux-mcp start        # boot server (mock or real)
uv run pytest -m unit        # unit tests only (fast)
uv run pytest                # all tests (incl. integration)
uv run crackerjack run       # full quality gate (17 fast + 11 comprehensive hooks)
```

## Coding Style

- Python 3.14+, `from __future__ import annotations` first non-comment line.
- Imports: stdlib → third-party → first-party (`cmux_mcp`).
- Modern syntax: `X | None`, `list[str]`, `pathlib.Path`.
- No `assert` in production code (`cmux_mcp/**`) — use exception hierarchy.
- Prefer `with suppress(...)` over `try/except FileNotFoundError: pass`.
- Use `with suppress(FileNotFoundError)` not `try: ... except ...: pass`.
- Prefer list/dict comprehensions over `for/append` patterns.
- Class-level type annotations satisfy mixin contracts — single declaration
  cascades through usage sites; do NOT sprinkle `# ty: ignore` for the same
  issue across many lines.

## Testing

- Mirror module paths: `cmux_mcp/foo.py` → `tests/unit/test_foo.py`.
- Async tests don't need `@pytest.mark.asyncio` (`asyncio_mode = "auto"`).
- Markers: `unit`, `integration`, `e2e`. Skip `-m "not slow"` for fast
  feedback.
- New MCP tool → must add `tests/integration/test_<tool>_e2e.py`
  (Bodai wiring discipline).

## Commit Conventions

- Conventional commits: `fix(scope): summary`, `feat(scope): summary`,
  `chore(scope): summary`.
- Scope by component: `client`, `server`, `tools`, `config`, `health`,
  `lock`, `layout`.
- Don't bundle unrelated fixes.
- Version bumps and PyPI publishes are user-initiated; flag those steps
  in plans but don't run them without approval.

## Security & Config

- Loopback-only by default; non-loopback requires `CMUX_MCP_AUTH_ENABLED=true`.
- Subprocess env filtered to `SUBPROCESS_ENV_ALLOWLIST` in `client.py`.
- PII redaction helpers exist in `logging_setup.py`; use them for any
  new log statements that touch user input.
- macOS-only real mode; mock mode (`CMUX_MCP_MOCK=1`) is the
  cross-platform fallback.
