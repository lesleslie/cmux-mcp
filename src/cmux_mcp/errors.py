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

    def __init__(
        self, message: str = "cmux socket access denied (cmuxOnly mode)", **kw: Any
    ) -> None:
        super().__init__(f"{message} {self._RECOVERY_HINT}", retryable=False, **kw)


class UnsupportedPlatformError(CmuxError):
    """Non-darwin without CMUX_MCP_MOCK=1."""

    tool_error_code = "unsupported_platform"

    def __init__(
        self,
        message: str = "cmux-mcp requires macOS; set CMUX_MCP_MOCK=1 for Linux/Windows CI",
        **kw: Any,
    ) -> None:
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


class CmuxSocketEofReconnectingError(CmuxError):
    """Socket hit EOF mid-flight; transport is reconnecting with backoff.

    Distinct from CmuxTransportError: this means "wait for reconnect" (retryable).
    Review finding H5: spec requires clients distinguish eof-reconnecting from
    unreachable to make retry-or-give-up decisions.
    """

    tool_error_code = "cmux_socket_eof_reconnecting"

    def __init__(
        self, message: str = "cmux socket EOF; reconnecting", **kw: Any
    ) -> None:
        super().__init__(message, retryable=True, **kw)


class CmuxSocketMaxRetriesExceededError(CmuxError):
    """Reconnect attempts exhausted; transport is in 'disconnected' state.

    Clients should NOT auto-retry. Review finding H5.
    """

    tool_error_code = "cmux_socket_max_retries_exceeded"

    def __init__(
        self, message: str = "cmux socket unreachable: max retries exceeded", **kw: Any
    ) -> None:
        super().__init__(message, retryable=False, **kw)


class CmuxCliFailedError(CmuxError):
    """cmux CLI subprocess returned non-zero exit. Distinct from CmuxTimeoutError.

    The subprocess exited, didn't time out. Clients should check the underlying
    stderr in `data` to decide retry semantics. Review finding H5.
    """

    tool_error_code = "cmux_cli_failed"

    def __init__(self, message: str, **kw: Any) -> None:
        super().__init__(message, retryable=False, **kw)


class BrowserEvalRuntimeError(CmuxError):
    """cmux browser eval raised a runtime JS exception."""

    tool_error_code = "browser_eval_runtime_error"


class BrowserSelectorNotFoundError(CmuxError):
    """CSS selector matched zero elements in cmux browser."""

    tool_error_code = "browser_selector_not_found"


class SurfaceNotFoundError(CmuxError):
    """cmux surface_id does not exist."""

    tool_error_code = "surface_not_found"


class RateLimitedError(CmuxError):
    """Per-tool rate limit hit (e.g. cmux_notify notify_rate_limit_per_second)."""

    tool_error_code = "rate_limited"

    def __init__(
        self, message: str = "rate limit exceeded; retry after backoff", **kw: Any
    ) -> None:
        super().__init__(message, retryable=True, **kw)


__all__ = [
    "BrowserEvalRuntimeError",
    "BrowserSelectorNotFoundError",
    "CmuxBinaryNotFoundError",
    "CmuxCliFailedError",
    "CmuxError",
    "CmuxOnlyAccessDeniedError",
    "CmuxProtocolError",
    "CmuxSocketEofReconnectingError",
    "CmuxSocketMaxRetriesExceededError",
    "CmuxTimeoutError",
    "CmuxTransportError",
    "CmuxValidationError",
    "RateLimitedError",
    "SurfaceNotFoundError",
    "UnsupportedPlatformError",
]
