# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-09-21

### Fixed

- browser: Handle CmuxMockTransport missing _config in truncate path
- client+server: H7/H9/H10 — counter, JSONDecodeError, PID PermissionError
- client: H8 — surface-lock refcount + eviction (no more lock leak)
- client: Subprocess lifecycle on cancellation + real aclose() (C2+C3)
- errors+README: H5 — missing exception classes + honest README (H6)
- gitignore: Exclude crackerjack tool-output caches (.cache/ + .lycheecache)
- logging: Use Oneiric's structlog-based logger (C7 — CLAUDE.md violation)
- quality: All fast hooks now pass — lint + tc-refs scope fix
- server: Custom /health route returns 503 on degraded (C4)
- tools: Cmux_browser_type returns BrowserTypeOutput (H3)
- tools: Cmux_list_workspaces iterates correct field + adds surface.list (H4)
- tools: H1/H2 — wire max_response_bytes + notify rate limit
- tools: Record_success() reachable in cmux_browser_navigate (C5)
- tools: Tool errors raise ToolError (C6 — was returning plain dict)
- Wire register_tools into startup (C1 — server exposed zero tools)

### Documentation

- plans: Mark cmux-mcp plan + spec shipped (v0.1.0)

### Internal

- deps: Add crackerjack to PEP 735 dependency-groups
- Migrate cmux-mcp from src-layout to flat layout
