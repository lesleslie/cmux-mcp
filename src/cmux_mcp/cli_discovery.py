"""cmux_mcp.cli_discovery — locate the cmux CLI binary.

Per spec §"cmux CLI binary discovery":
  1. CMUX_MCP_CLI_PATH env var (operator override)
  2. which cmux from $PATH
  3. /Applications/cmux.app/Contents/Resources/bin/cmux
  4. /opt/homebrew/Caskroom/cmux/*/cmux.app/.../bin/cmux (latest version)
  5. /usr/local/Caskroom/cmux/*/cmux.app/.../bin/cmux (Intel macs)
  6. ~/Library/Developer/Xcode/DerivedData/cmux-*/Build/Products/{Debug,Release}/cmux.app/.../bin/cmux
  7. fail with CmuxBinaryNotFoundError listing probed paths
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from cmux_mcp.errors import CmuxBinaryNotFoundError

# Module-level so tests can monkeypatch (see test_cli_discovery.py).
_DEFAULT_APP_BUNDLE = Path("/Applications/cmux.app")
_CASKROOM_PATHS: list[Path] = [
    Path("/opt/homebrew/Caskroom/cmux"),
    Path("/usr/local/Caskroom/cmux"),
]


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    if "PATH" in os.environ:
        which_result = shutil.which("cmux")
        if which_result:
            candidates.append(Path(which_result))
    candidates.append(_DEFAULT_APP_BUNDLE / "Contents" / "Resources" / "bin" / "cmux")
    for caskroom in _CASKROOM_PATHS:
        if caskroom.exists() and caskroom.is_dir():
            # Numeric tuple sort so "10.0.0" sorts after "2.0.0".
            versions = sorted(
                (p for p in caskroom.iterdir() if p.is_dir()),
                key=lambda p: tuple(
                    int(x) if x.isdigit() else 0 for x in p.name.split(".")
                ),
                reverse=True,
            )
            for v in versions:
                candidates.append(
                    v / "cmux.app" / "Contents" / "Resources" / "bin" / "cmux"
                )
    derived = Path.home() / "Library" / "Developer" / "Xcode" / "DerivedData"
    if derived.exists():
        # PERF402: candidates.extend(glob(...)) beats `for d in glob: append`
        # — single C-level call instead of N Python appends.
        candidates.extend(
            derived.glob(
                "cmux-*/Build/Products/Debug/cmux.app/Contents/Resources/bin/cmux"
            ),
        )
        candidates.extend(
            derived.glob(
                "cmux-*/Build/Products/Release/cmux.app/Contents/Resources/bin/cmux"
            ),
        )
    return candidates


def discover_cmux_cli(explicit_path: Path | None = None) -> Path:
    """Resolve the cmux CLI binary path.

    Args:
        explicit_path: if set (e.g., via CMUX_MCP_CLI_PATH env), use directly.

    Returns:
        Path to a verified cmux binary.

    Raises:
        CmuxBinaryNotFoundError: when no candidate is found.
    """
    env_override = os.environ.get("CMUX_MCP_CLI_PATH")
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(explicit_path)
    elif env_override:
        candidates.append(Path(env_override))
    candidates.extend(_candidate_paths())

    for path in candidates:
        if path.exists() and path.is_file() and os.access(path, os.X_OK):
            return path

    probed = "\n  ".join(str(p) for p in candidates)
    raise CmuxBinaryNotFoundError(
        f"cmux CLI binary not found. Probed paths:\n  {probed}\n"
        "Set CMUX_MCP_CLI_PATH or install cmux from https://cmux.com/"
    )


__all__ = ["discover_cmux_cli"]
