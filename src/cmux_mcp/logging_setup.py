"""cmux_mcp.logging_setup — mock-mode WARN banner + PII redaction helpers.

Per spec §"Logging":
  - Logger name: cmux_mcp.<module>
  - Oneiric logger only; no print(), no stdlib logging
  - mock-mode WARN banner unless CMUX_MCP_MOCK_ACKNOWLEDGED=1 or PYTEST_CURRENT_TEST is set
"""

from __future__ import annotations

from oneiric.core.logging import get_logger

_LOG = get_logger("cmux_mcp.logging_setup")


def maybe_warn_mock_mode(config: object) -> None:
    """Emit unmissable WARN banner if mock mode is active outside test contexts.

    Suppressed when:
      - CMUX_MCP_MOCK_ACKNOWLEDGED=1 (operator opt-out)
      - PYTEST_CURRENT_TEST is set (running under pytest)
    """
    import os

    if not getattr(config, "mock_mode", False):
        return
    if os.environ.get("CMUX_MCP_MOCK_ACKNOWLEDGED") == "1":
        return
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _LOG.warning(
        "cmux-mcp is running in MOCK MODE — all cmux responses are canned fixtures; "
        "do not use for real work. Set CMUX_MCP_MOCK_ACKNOWLEDGED=1 to silence this warning."
    )


def redact_url_query_string(url: str) -> str:
    """Strip query string from URL for safe logging (removes ?token=...&api_key=...)."""
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url)
    if not parts.query:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment))


def redact_expression(expr: str) -> str:
    """Return length + first 32 chars for safe logging of JS expressions."""
    return f"<len={len(expr)}, head={expr[:32]!r}>"


__all__ = ["maybe_warn_mock_mode", "redact_expression", "redact_url_query_string"]
