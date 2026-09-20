"""cmux_mcp.errors — exception hierarchy.

Per spec §"Exception hierarchy":
  CmuxError (base, carries context dict + retryable flag)
    ├── CmuxTransportError (socket EOF, reconnect failure, malformed JSON)
    ├── CmuxTimeoutError (per-call socket or CLI timeout)
    ├── CmuxOnlyAccessDeniedError (cmuxOnly socket access denied)
    ├── UnsupportedPlatformError (non-darwin without CMUX_MCP_MOCK=1)
    ├── CmuxBinaryNotFoundError (cmux CLI missing or not executable)
    ├── CmuxProtocolError (cmux returned error.code or malformed JSON-RPC)
    └── CmuxValidationError (input validation failed)

Each exception carries:
  - message: str — human-readable
  - retryable: bool — whether clients should retry
  - context: dict[str, JsonValue] — structured context for /health envelope

to_tool_error() converts to the ToolError envelope shape used by all 12 tools.
"""
from __future__ import annotations

from typing import Any


class CmuxError(Exception):
    """Base. Carries context dict for /health envelope and structured tool errors."""

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.retryable = retryable

    def to_tool_error(self) -> dict[str, Any]:
        """Convert to ToolError envelope shape used by all 12 tools."""
        return {
            "code": self.__class__.tool_error_code,
            "message": self.message,
            "retryable": self.retryable,
            "data": self.context or None,
        }

    tool_error_code: str = "internal_error"


class CmuxTransportError(CmuxError):
    """Socket EOF, reconnect failure, malformed JSON."""

    tool_error_code = "cmux_socket_unreachable"


class CmuxTimeoutError(CmuxError):
    """Per-call socket or CLI timeout fired."""

    tool_error_code = "cmux_cli_timeout"


class CmuxOnlyAccessDeniedError(CmuxError):
    """Socket access denied by cmuxOnly mode. Recovery: relaunch from inside cmux terminal.

    Per spec §"Access mode (cmuxOnly)": the recovery hint is always appended so
    any caller-supplied message reaches the user with the recovery guidance.
    """

    tool_error_code = "cmux_only_access_denied"

    _RECOVERY_HINT = "Re-run 'cmux-mcp start' from a cmux terminal pane."

    def __init__(self, message: str = "cmux socket access denied (cmuxOnly mode)", **kw: Any) -> None:
        super().__init__(f"{message} {self._RECOVERY_HINT}", retryable=False, **kw)


class UnsupportedPlatformError(CmuxError):
    """Non-darwin without CMUX_MCP_MOCK=1."""

    tool_error_code = "unsupported_platform"

    def __init__(self, message: str = "cmux-mcp requires macOS; set CMUX_MCP_MOCK=1 for Linux/Windows CI", **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)


class CmuxBinaryNotFoundError(CmuxError):
    """cmux CLI binary missing or not executable."""

    tool_error_code = "cmux_cli_not_found"


class CmuxProtocolError(CmuxError):
    """cmux returned error.code or malformed JSON-RPC response."""

    tool_error_code = "cmux_protocol_error"


class CmuxValidationError(CmuxError):
    """Input validation failed (regex, URL, type, length)."""

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)

    tool_error_code = "validation_error"


__all__ = [
    "CmuxError",
    "CmuxTransportError",
    "CmuxTimeoutError",
    "CmuxOnlyAccessDeniedError",
    "UnsupportedPlatformError",
    "CmuxBinaryNotFoundError",
    "CmuxProtocolError",
    "CmuxValidationError",
]