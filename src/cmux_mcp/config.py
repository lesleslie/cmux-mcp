"""cmux_mcp.config — CmuxMCPConfig (BaseSettings direct subclass).

Per spec decision log row 5 + 25: direct `BaseSettings` subclass with explicit
`SettingsConfigDict` for orthogonality — not strictly because OneiricMCPConfig
is broken, but because it makes `env_prefix` precedence explicit and unit-testable.

DEFAULT_PORT is imported from cmux_mcp.__init__ (single source of truth per
spec decision log row 8). Do NOT redefine here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from cmux_mcp import DEFAULT_PORT


def _default_pid_file_path() -> Path:
    """Re-evaluated per instance so tests can patch XDG_RUNTIME_DIR."""
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "cmux-mcp" / "cmux-mcp.pid"


def _default_socket_path() -> Path:
    """Re-evaluated per instance; honors CMUX_SOCKET_PATH if set at import time."""
    return Path(os.environ.get("CMUX_SOCKET_PATH", "/tmp/cmux.sock"))


class CmuxMCPConfig(BaseSettings):
    """Settings for cmux-mcp. Env vars (CMUX_MCP_*) override."""

    model_config = SettingsConfigDict(
        env_prefix="CMUX_MCP_",
        env_file=".env",
        extra="allow",
        # Without this, validation_alias="CMUX_MCP_MOCK" disables field-name
        # input — `CmuxMCPConfig(mock_mode=True)` would silently set mock_mode
        # to the platform default (False on macOS) instead of True. Tests and
        # programmatic callers rely on `mock_mode=True` working.
        populate_by_name=True,
    )

    host: str = "127.0.0.1"
    port: int = DEFAULT_PORT
    socket_path: Path = Field(default_factory=_default_socket_path)
    cmux_cli_path: Path | None = None
    socket_short_timeout_seconds: float = 5.0
    socket_long_timeout_seconds: float = 15.0
    cli_timeout_seconds: float = 30.0
    cli_max_concurrent: int = 8
    reconnect_initial_delay_seconds: float = 0.5
    reconnect_max_delay_seconds: float = 30.0
    reconnect_max_attempts: int = 5
    max_response_bytes: int = 1_048_576
    notify_rate_limit_per_second: float = 1.0
    # Sentinel pattern: None = "use platform default". Explicit True/False via env
    # always wins over auto-detect. See spec decision log row 7 + `_mock_mode_auto_on_non_darwin`.
    # validation_alias overrides the env_prefix-derived "CMUX_MCP_MOCK_MODE" so that
    # the spec's "CMUX_MCP_MOCK=1" env var is honored (Pydantic-settings uses
    # prefix + field name by default; spec text uses prefix + bare "MOCK").
    mock_mode: bool | None = Field(default=None, validation_alias="CMUX_MCP_MOCK")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    shutdown_grace_seconds: float = 10.0
    auth_enabled: bool = False
    pid_file_path: Path = Field(default_factory=_default_pid_file_path)
    health_warmup_seconds: float = 60.0

    @model_validator(mode="after")
    def _mock_mode_auto_on_non_darwin(self) -> "CmuxMCPConfig":
        # None means "no explicit setting" — pick based on platform.
        # An explicit True or False from env wins (per spec decision log row 7).
        if self.mock_mode is None:
            self.mock_mode = sys.platform != "darwin"
        return self

    @model_validator(mode="after")
    def _reject_non_loopback_without_auth(self) -> "CmuxMCPConfig":
        if self.host not in ("127.0.0.1", "::1", "localhost") and not self.auth_enabled:
            raise ValueError(
                f"host={self.host!r} requires auth_enabled=True (loopback-only by default)"
            )
        return self

    # Bridge to mcp-common's BaseOneiricServerMixin, which reads `http_port` and
    # `http_host` (with hasattr guard). Spec decision log row 8 keeps the field
    # names as `port` and `host`; properties expose the mcp-common names without
    # forcing a rename.
    @property
    def http_port(self) -> int:
        return self.port

    @property
    def http_host(self) -> str:
        return self.host


__all__ = ["DEFAULT_PORT", "CmuxMCPConfig"]