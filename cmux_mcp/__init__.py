"""cmux-mcp: MCP server for cmux terminal automation (macOS only)."""

from __future__ import annotations

import importlib.metadata

__version__ = importlib.metadata.version("cmux-mcp")

DEFAULT_PORT: int = 3061  # per spec decision log row 2 + 8

__all__ = ["DEFAULT_PORT", "__version__"]
