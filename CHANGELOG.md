# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-09-26

### Changed

- cmux-mcp: Emit canonical StatusValue in /health body

### Testing

- cmux-mcp: Align TestHealthRegistration with canonical StatusValue

## [0.2.1] - 2026-09-26

### Added

- plugins: Onboard as www-mcp-servers Claude Code plugin

### Fixed

- cmux-mcp: Align config surface with mcp-common 0.30.1 MCPBaseSettings
- cmux-mcp: Drop unused httpx/psutil deps (creosote bloat)

### Documentation

- Consolidate Bodai/Vishnu references to bottom section
- Drop Bodai integration framing and add substrate note
- Rename 'Bodai Ecosystem Position' section to standard footer name
- Update FastMCP badge URL to PrefectHQ org (canonical since v3.0 GA)

### Internal

- cmux-mcp: Refresh uv.lock for mcp-common 0.30.1
- docs: Add CLAUDE.md, AGENTS.md, and QWEN.md
- Sync uv.lock with 0.2.0 bump

## [0.2.0] - 2026-09-21

### Fixed

- browser: Handle CmuxMockTransport missing \_config in truncate path
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
