"""Tests for cmux_mcp/errors.py — the CmuxError hierarchy."""

from __future__ import annotations

import pytest

from cmux_mcp.errors import (
    CmuxBinaryNotFoundError,
    CmuxError,
    CmuxOnlyAccessDeniedError,
    CmuxProtocolError,
    CmuxTimeoutError,
    CmuxTransportError,
    CmuxValidationError,
    UnsupportedPlatformError,
)


@pytest.mark.unit
class TestCmuxErrorHierarchy:
    def test_cmux_error_is_exception(self) -> None:
        assert issubclass(CmuxError, Exception)

    def test_all_subclasses_inherit_from_cmux_error(self) -> None:
        for cls in (
            CmuxTransportError,
            CmuxTimeoutError,
            CmuxOnlyAccessDeniedError,
            UnsupportedPlatformError,
            CmuxBinaryNotFoundError,
            CmuxProtocolError,
            CmuxValidationError,
        ):
            assert issubclass(cls, CmuxError), (
                f"{cls.__name__} must inherit from CmuxError"
            )

    def test_cmux_error_carries_context(self) -> None:
        exc = CmuxTransportError("socket eof", context={"surface_id": "surface:abc"})
        assert exc.message == "socket eof"
        assert exc.context == {"surface_id": "surface:abc"}

    def test_cmux_error_retryable_default(self) -> None:
        exc = CmuxTransportError("socket eof")
        assert exc.retryable is True

    def test_validation_error_not_retryable(self) -> None:
        exc = CmuxValidationError("bad selector")
        assert exc.retryable is False

    def test_cmux_only_access_denied_message_contains_recovery_hint(self) -> None:
        exc = CmuxOnlyAccessDeniedError("access denied")
        assert "cmux terminal" in str(exc).lower() or "relaunch" in str(exc).lower()

    def test_to_tool_error_returns_dict_with_code(self) -> None:
        exc = CmuxValidationError("bad selector")
        tool_err = exc.to_tool_error()
        assert tool_err["code"] == "validation_error"
        assert "bad selector" in tool_err["message"]
        assert tool_err["retryable"] is False
