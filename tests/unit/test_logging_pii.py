"""Tests for cmux_mcp/logging_setup.py — mock-mode WARN banner + PII helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from structlog.testing import capture_logs

from cmux_mcp.config import CmuxMCPConfig
from cmux_mcp.logging_setup import (
    maybe_warn_mock_mode,
    redact_expression,
    redact_url_query_string,
)


@pytest.mark.unit
class TestMockModeBanner:
    def test_banner_emitted_when_mock_active_without_ack(self) -> None:
        # Clear PYTEST_CURRENT_TEST so the test simulates a real startup
        # (the var is set by pytest; maybe_warn_mock_mode suppresses in tests).
        # Use structlog.capture_logs() since we now route through Oneiric's
        # structlog-based logger (not stdlib logging, so caplog doesn't see it).
        saved = os.environ.pop("PYTEST_CURRENT_TEST", None)
        try:
            cfg = CmuxMCPConfig(mock_mode=True)
            with capture_logs() as cap:
                maybe_warn_mock_mode(cfg)
        finally:
            if saved is not None:
                os.environ["PYTEST_CURRENT_TEST"] = saved
        assert any("MOCK MODE" in entry["event"] for entry in cap)

    def test_banner_suppressed_when_acknowledged(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_MOCK_ACKNOWLEDGED": "1"}, clear=False):
            cfg = CmuxMCPConfig(mock_mode=True)
            with capture_logs() as cap:
                maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in entry["event"] for entry in cap)

    def test_banner_suppressed_when_pytest_current_test(self) -> None:
        # The real PYTEST_CURRENT_TEST is already set by pytest, so this test
        # verifies the suppression branch without patching anything extra.
        cfg = CmuxMCPConfig(mock_mode=True)
        with capture_logs() as cap:
            maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in entry["event"] for entry in cap)

    def test_no_banner_when_mock_inactive(self) -> None:
        cfg = CmuxMCPConfig(mock_mode=False)
        with capture_logs() as cap:
            maybe_warn_mock_mode(cfg)
        assert not any("MOCK MODE" in entry["event"] for entry in cap)


@pytest.mark.unit
class TestRedaction:
    def test_redact_url_strips_query(self) -> None:
        redacted = redact_url_query_string(
            "https://api.example.com/v1?token=abc&api_key=xyz"
        )
        assert "token" not in redacted
        assert "api_key" not in redacted
        assert redacted.startswith("https://api.example.com/v1")

    def test_redact_url_preserves_fragment(self) -> None:
        redacted = redact_url_query_string("https://api.example.com/v1#section")
        assert "#section" in redacted

    def test_redact_expression_returns_length_and_head(self) -> None:
        red = redact_expression("x" * 100)
        assert red.startswith("<len=100")
        assert "head=" in red
