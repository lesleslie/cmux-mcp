# cmux-mcp

[![Code style: crackerjack](https://img.shields.io/badge/code%20style-crackerjack-000042)](https://github.com/lesleslie/crackerjack)
[![Runtime: oneiric](https://img.shields.io/badge/runtime-oneiric-6e5494)](https://github.com/lesleslie/oneiric)
[![Framework: FastMCP](https://img.shields.io/badge/framework-FastMCP-0ea5e9)](https://github.com/PrefectHQ/fastmcp)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python: 3.14+](https://www.python.org/downloads/)](https://www.python.org/downloads/)

Catalog and operating map for cmux-mcp.

**Status:** v0.1.0 (initial release — 12 tools, BSD-3-Clause)

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
cd /Users/les/Projects/cmux-mcp && uv sync --extra dev

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
| `CMUX_MCP_MOCK` | unset | `1`/`true` enables mock mode |
| `CMUX_MCP_AUTH_ENABLED` | `false` | Enable JWT auth for non-loopback deployments |

## Security Notes

- macOS-only; non-macOS hosts must use `CMUX_MCP_MOCK=1` (auto-flipped with WARN banner)
- cmux's `cmuxOnly` access mode restricts socket connections to processes spawned inside cmux terminals
- PII redaction helpers (`redact_url_query_string`, `redact_expression`) exist in `logging_setup.py` for future log-site use; v0.1.x ships with no PII-logging call sites by default (deferred)
- Subprocess env filtered to `SUBPROCESS_ENV_ALLOWLIST` to prevent leaking API keys
- Default loopback bind; non-loopback requires `CMUX_MCP_AUTH_ENABLED=true`

## Development Commands

```bash
uv run pytest                 # Run all tests
uv run pytest -m unit         # Unit tests only
uv run pytest -m integration  # Integration tests (require live cmux)
uv run crackerjack run        # Full quality gate
```

Built on [Oneiric](https://github.com/lesleslie/oneiric) for runtime configuration
and [mcp-common](https://github.com/lesleslie/mcp-common) for the FastMCP
baseline. [Crackerjack](https://github.com/lesleslie/crackerjack) gates every commit.
