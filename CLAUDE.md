# CLAUDE.md

This file provides high-level guidance to Claude Code when working in this repository.
For a shorter, tool-neutral bootstrap, start with `AGENTS.md`.

## Project Overview

**cmux-mcp** is an MCP server that exposes programmatic control of a running
[cmux](https://github.com/manaflow-ai/cmux) instance (macOS-only, Ghostty-based
terminal for AI coding agents) as 12 MCP tools over Streamable HTTP. It speaks
cmux's Unix-socket JSON-RPC protocol directly for orchestration/notification
tools, and shells out to the cmux CLI for browser-automation tools. The
**`cmux-mcp`** component owns port **3061** (see `cmux_mcp/__init__.py`
`DEFAULT_PORT`).

## Quick Start

```bash
uv sync --group dev           # install deps
CMUX_MCP_MOCK=1 uv run cmux-mcp start    # mock mode (any platform)
uv run cmux-mcp start                    # real (macOS + cmux running)
uv run pytest                           # all tests
uv run crackerjack run                  # full quality gate
```

## Architecture

- **`cmux_mcp/server.py`** — `CmuxMCPServer(BaseOneiricServerMixin)`. Owns the
  FastMCP instance, transports, and `/health` route. Custom health route
  returns **503 on degraded** (mcp-common's helper always returns 200; the
  override is intentional per spec §"/health envelope wiring").
- **`cmux_mcp/client.py`** — three transports:
  - `CmuxSocketTransport` — long-lived Unix-socket JSON-RPC (reconnect with
    exponential backoff + jitter).
  - `CmuxCliTransport` — single-shot subprocess calls; per-surface
    `asyncio.Lock` with **refcount eviction** (H8 — `CmuxCliTransport` holds
    `_surface_lock_refs` and drops the lock entry when the refcount hits 0).
    `_release_surface_lock` is `async`; callers must `await` it.
  - `CmuxMockTransport` — in-process canned responses; implements BOTH
    protocol shapes so tool code is identical against real and mock.
- **`cmux_mcp/config.py`** — `CmuxMCPConfig(BaseSettings)` directly (NOT
  `mcp_common.MCPBaseSettings`). Per spec decision log row 5: explicit
  `SettingsConfigDict(env_prefix="CMUX_MCP_")` for orthogonality. Env var
  `CMUX_MCP_MOCK=1` (NOT `CMUX_MCP_MOCK_MODE`) honored via `validation_alias`.
- **`cmux_mcp/health.py`** — feed components. `SocketFeedComponent` and
  `BrowserCliFeedComponent` accept the **mock OR real** transport union
  (`CmuxXxxTransport | CmuxMockTransport`) — the mock implements both
  protocol shapes.
- **`cmux_mcp/tools/{socket,browser}_tools.py`** — the 12 tool registrations.
  Each tool follows `try / except / else`; the success record lives in
  `else:` (mandatory — see `CmuxMCPServer._register_health_route` review
  finding C5).

## Mock Mode

`CMUX_MCP_MOCK=1` flips `_mock_mode_auto_on_non_darwin` to True (with WARN
banner via `maybe_warn_mock_mode`). All three transports become
`CmuxMockTransport`, all 12 tools remain callable, and `/health` still
returns 503 if any tool is never called past `health_warmup_seconds`.

## Configuration

All via `CMUX_MCP_*` env vars. Defaults in `cmux_mcp/config.py`. Settings
files live under `settings/`. `populate_by_name=True` is required — without
it, `CmuxMCPConfig(mock_mode=True)` would silently fall back to the
platform default.

## Quality Gates

```bash
uv run crackerjack run         # full suite: fast + comprehensive hooks
uv run pytest -m unit          # unit tests
uv run pytest -m integration   # integration tests (require live cmux)
```

**Crackerjack profiles**: 17 fast hooks + 11 comprehensive hooks
(verified 2026-09-21; ty, refurb, creosote, etc. all clean).

## Crackerjack-Compliant Code Conventions

Per crackerjack config (`pyproject.toml` Ruff/mypy/pytest sections) and
project-level conventions:

- `from __future__ import annotations` first non-comment line.
- Imports ordered: stdlib → third-party → first-party (`cmux_mcp`).
- Modern syntax: `X | None`, `list[str]`, `pathlib.Path`. Target Python 3.14.
- No `assert` in `cmux_mcp/**` (bandit B101) — use `cmux_mcp/errors.py`
  exception hierarchy.
- `ty` is the type checker; use `# ty: ignore[<code>]`, never bare
  `# type: ignore`. Mass suppressions (>5 per file) are a smell.
- `BaseOneiricServerMixin.config` is declared as `MCPBaseSettings |
  MCPServerSettings`; `CmuxMCPServer` redeclares it as `config: CmuxMCPConfig`
  at class level to satisfy the contract — that ONE annotation cascades
  fixes through every usage site. Don't add inline `# ty: ignore` for the
  config type — fix the class-level annotation instead.

## MCP Backend Wiring Discipline

Cross-repo rule (canonical source: `mahavishnu/.claude/decisions/mcp-backend-wiring-discipline.md`):

- `/health` returns 503 on degraded; `feed.entities_count`,
  `feed.last_updated_timestamp`, `feed.errors_total`, `feed.cycles_total`
  per tool feed.
- Every tool has `tests/integration/test_<tool>_e2e.py`.
- `CmuxMCPServer._register_health_route` implements the 503 logic; do not
  silently regress to 200.
- `mock_mode` workers with registered tools but no real activity still
  return `ok` (mock feed always healthy).

## Security

- Default loopback bind; non-loopback requires
  `CMUX_MCP_AUTH_ENABLED=true` (enforced by `_reject_non_loopback_without_auth`).
- Subprocess env filtered to `SUBPROCESS_ENV_ALLOWLIST` in
  `cmux_mcp/client.py`; do not remove `MINIMAX_API_KEY` exclusions
  without considering what secrets a cmux CLI subprocess could read.
- PII redaction helpers exist in `logging_setup.py`; v0.1.x ships with no
  PII-logging call sites by default. If you add log statements that handle
  user input, route through `redact_url_query_string` / `redact_expression`.

## Important Architectural Decisions

- **`CmuxMCPConfig` extends `BaseSettings` directly** (NOT `MCPBaseSettings`).
  Per spec decision log row 5 + 25. Class-level `config: CmuxMCPConfig` on
  `CmuxMCPServer` is the load-bearing annotation.
- **`_release_surface_lock` is `async`** — sync-returning-a-coroutine was a
  real runtime bug pre-H8. Callers must `await`.
- **Flat layout** — `cmux_mcp/` at repo root (post 2026-09-20 src→flat
  migration). Don't reintroduce a `src/` directory.
- **Mock transport is protocol-compatible with both** `SocketTransport` and
  `CliTransport` (same `.state` / `.active_subprocesses` attributes +
  same async methods). Feed components accept the union.

## Operational Notes

- **Versioning**: User initiates version bumps (`crackerjack run -p minor`);
  never edit `version` in `pyproject.toml` without explicit go-ahead.
  uv.lock must be regenerated to match.
- **Push policy**: `git push` requires explicit user approval. Add the
  remote once; never push without confirmation.
- **Git author**: `les@wedgwoodwebworks.com` (NOT `.local`).
- **Pre-1.0 merge policy**: all changes merge directly to `main`; no PRs.

## Bodai integration

When installed alongside the [Bodai ecosystem](https://github.com/lesleslie/bodai),
cmux-mcp follows the shared cross-repo conventions: Crackerjack for CI/CD
quality gates, the four mcp-common baseline tools (`discover_tools`,
`get_liveness`, `get_readiness`, `health_check_all`), and the MCP wiring
discipline documented in `mahavishnu/.claude/decisions/mcp-backend-wiring-discipline.md`.
No Bodai-specific code is imported at runtime — integration is purely via
shared conventions.
