---
status: active
role: canonical
date: 2026-09-16
last_reviewed: 2026-09-16
superseded_by: null
topic: cmux-mcp
---

# Plan Index

**Date:** 2026-09-16
**Last reviewed:** 2026-09-16
**Purpose:** Navigation map for cmux-mcp planning documents.

## Status Legend

- `active` — approved and in current use; being executed or applied as policy.
- `complete` — delivered; verification or follow-up may still be open.
- `shipped` — delivered and verified in production; closed.
- `superseded` — replaced by a newer document.
- `draft` — in preparation; not yet approved.

## Plans

| Plan | Date | Status | Role | Spec | Notes |
|---|---|---|---|---|---|
| [2026-09-16-cmux-mcp-impl.md](./2026-09-16-cmux-mcp-impl.md) | 2026-09-16 | active | implementation | [spec](../specs/2026-09-16-cmux-mcp-design.md) | 28 tasks; 12 tools (5 socket + 7 browser); BSD-3-Clause; port 3061; macOS-only with mock-mode escape hatch |

## Specs

| Spec | Date | Status | Topic |
|---|---|---|---|
| [../specs/2026-09-16-cmux-mcp-design.md](../specs/2026-09-16-cmux-mcp-design.md) | 2026-09-16 | complete | cmux-mcp design (after 1 round review + 1 round criticals fix + 1 round-3 spot-check fix) |

## Review Entry Points

- Use this file as the first stop before reviewing plan work.
- Source plan for cmux-mcp is the 2026-09-16 spec; the implementation plan argues from it.
- Round-1 review: 5-agent multi-dim review (3 specialists + 2 random); 21 criticals found and fixed.
- Round-3 spot-check: 2-agent verification (1 specialist + 1 random); 2 criticals + 2 highs + 11 mediums found and fixed.

## Maintenance Rules

- Add new active plans to this index as they are approved.
- When a plan is superseded, leave a pointer in the old file and update its `superseded_by` field.
- Keep status labels aligned with code reality.
