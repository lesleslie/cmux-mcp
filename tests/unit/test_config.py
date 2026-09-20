"""Tests for src/cmux_mcp/config.py."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from cmux_mcp.config import DEFAULT_PORT, CmuxMCPConfig


@pytest.mark.unit
class TestDefaultPort:
    def test_default_port_constant_is_3061(self) -> None:
        assert DEFAULT_PORT == 3061

    def test_config_default_port_matches_constant(self) -> None:
        cfg = CmuxMCPConfig()
        assert cfg.port == DEFAULT_PORT


@pytest.mark.unit
class TestEnvPrefix:
    def test_env_var_overrides_port(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_PORT": "9999"}):
            cfg = CmuxMCPConfig()
        assert cfg.port == 9999

    def test_env_var_overrides_host(self) -> None:
        with patch.dict(
            os.environ, {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "true"}
        ):
            cfg = CmuxMCPConfig()
        assert cfg.host == "0.0.0.0"
        assert cfg.auth_enabled is True


@pytest.mark.unit
class TestMockModeAutoFlip:
    def test_non_darwin_auto_flips_mock_mode(self) -> None:
        with patch.object(sys, "platform", "linux"):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is True

    def test_darwin_default_mock_mode_false(self) -> None:
        with patch.object(sys, "platform", "darwin"):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is False

    def test_explicit_mock_mode_true_respected_on_any_platform(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"CMUX_MCP_MOCK": "true"}),
        ):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is True

    def test_explicit_mock_mode_false_on_non_darwin_respected(self) -> None:
        with (
            patch.object(sys, "platform", "linux"),
            patch.dict(os.environ, {"CMUX_MCP_MOCK": "false"}),
        ):
            cfg = CmuxMCPConfig()
        assert cfg.mock_mode is False  # explicit setting wins over auto-flip


@pytest.mark.unit
class TestAuthRequiredForNonLoopback:
    def test_non_loopback_without_auth_raises(self) -> None:
        with (
            patch.object(sys, "platform", "darwin"),
            patch.dict(
                os.environ,
                {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "false"},
                clear=False,
            ),
            pytest.raises(ValueError),
        ):  # Pydantic ValidationError (subclass of ValueError) from model_validator
            CmuxMCPConfig()

    def test_non_loopback_with_auth_allowed(self) -> None:
        with (
            patch.object(sys, "platform", "darwin"),
            patch.dict(
                os.environ,
                {"CMUX_MCP_HOST": "0.0.0.0", "CMUX_MCP_AUTH_ENABLED": "true"},
                clear=False,
            ),
        ):
            cfg = CmuxMCPConfig()
        assert cfg.host == "0.0.0.0"

    def test_loopback_without_auth_allowed(self) -> None:
        with patch.dict(os.environ, {"CMUX_MCP_HOST": "127.0.0.1"}, clear=False):
            cfg = CmuxMCPConfig()
        assert cfg.host == "127.0.0.1"
        assert cfg.auth_enabled is False  # default


@pytest.mark.unit
class TestPidFilePath:
    def test_pid_file_path_uses_xdg_runtime_dir(self, tmp_path: Path) -> None:
        with patch.dict(os.environ, {"XDG_RUNTIME_DIR": str(tmp_path)}):
            cfg = CmuxMCPConfig()
        assert str(cfg.pid_file_path).startswith(str(tmp_path))
        assert cfg.pid_file_path.name == "cmux-mcp.pid"

    def test_pid_file_path_falls_back_to_tmp(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "XDG_RUNTIME_DIR"}
        with patch.dict(os.environ, env, clear=True):
            cfg = CmuxMCPConfig()
        assert "/tmp" in str(cfg.pid_file_path)
