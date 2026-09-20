"""Tests for cmux_mcp/cli_discovery.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from cmux_mcp.cli_discovery import discover_cmux_cli
from cmux_mcp.errors import CmuxBinaryNotFoundError


@pytest.mark.unit
class TestExplicitPath:
    def test_explicit_path_returned_if_exists(self, tmp_path: Path) -> None:
        fake = tmp_path / "cmux"
        fake.touch()
        fake.chmod(0o755)
        result = discover_cmux_cli(explicit_path=fake)
        assert result == fake

    def test_explicit_path_missing_raises(self, tmp_path: Path) -> None:
        # Patch out other probe sources so the test is hermetic on developer
        # systems that have cmux installed (which would otherwise be found and
        # mask the missing-explicit-path error).
        with (
            patch("cmux_mcp.cli_discovery._candidate_paths", return_value=[]),
            pytest.raises(CmuxBinaryNotFoundError),
        ):
            discover_cmux_cli(explicit_path=tmp_path / "nonexistent")


@pytest.mark.unit
class TestProbeOrder:
    def test_path_env_var_wins(self, tmp_path: Path) -> None:
        fake = tmp_path / "cmux"
        fake.touch()
        fake.chmod(0o755)
        with patch.dict("os.environ", {"PATH": str(tmp_path)}):
            result = discover_cmux_cli()
        assert result == fake

    def test_applications_path_fallback(self, tmp_path: Path) -> None:
        # Build fake /Applications/cmux.app/Contents/Resources/bin/cmux
        bin_path = (
            tmp_path / "Applications" / "cmux.app" / "Contents" / "Resources" / "bin"
        )
        bin_path.mkdir(parents=True)
        cmux = bin_path / "cmux"
        cmux.touch()
        cmux.chmod(0o755)
        with (
            patch(
                "cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE",
                tmp_path / "Applications" / "cmux.app",
            ),
            patch.dict("os.environ", {"PATH": ""}, clear=False),
        ):
            result = discover_cmux_cli()
        assert result == cmux

    def test_caskroom_picks_highest_version(self, tmp_path: Path) -> None:
        for v in ["1.0.0", "2.0.0", "1.5.0"]:
            cask = tmp_path / v / "cmux.app" / "Contents" / "Resources" / "bin"
            cask.mkdir(parents=True)
            (cask / "cmux").touch()
            (cask / "cmux").chmod(0o755)
        with (
            patch("cmux_mcp.cli_discovery._CASKROOM_PATHS", [tmp_path]),
            patch.dict("os.environ", {"PATH": ""}, clear=False),
            patch("cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE", Path("/nonexistent")),
        ):
            result = discover_cmux_cli()
        assert "2.0.0" in str(result)  # highest version wins

    def test_not_found_raises_with_listing(self, tmp_path: Path) -> None:
        with (
            patch(
                "cmux_mcp.cli_discovery._DEFAULT_APP_BUNDLE",
                tmp_path / "nonexistent-app",
            ),
            patch(
                "cmux_mcp.cli_discovery._CASKROOM_PATHS",
                [tmp_path / "nonexistent-cask"],
            ),
            patch.dict("os.environ", {"PATH": ""}, clear=False),
            pytest.raises(CmuxBinaryNotFoundError) as exc_info,
        ):
            discover_cmux_cli()
        msg = str(exc_info.value)
        assert "Probed paths" in msg or "probed" in msg.lower()
        assert "CMUX_MCP_CLI_PATH" in msg
