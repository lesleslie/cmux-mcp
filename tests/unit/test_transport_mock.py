"""Tests for CmuxMockTransport — fixture-driven canned responses."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from cmux_mcp.client import CliResult, CmuxMockTransport
from cmux_mcp.errors import CmuxProtocolError

FIXTURE_PATH = Path(__file__).parent.parent / "fixtures" / "cmux_responses.yaml"


@pytest.mark.unit
class TestMockTransportSocket:
    @pytest.mark.asyncio
    async def test_system_ping_returns_pong(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        # Mock transport mirrors CmuxSocketTransport.request, which returns
        # the inner `result` (not the full JSON-RPC envelope). See spec §
        # "CmuxSocketTransport — JSON-RPC client state machine".
        result = await transport.request("system.ping")
        assert result == {"pong": True}

    @pytest.mark.asyncio
    async def test_unknown_method_raises_protocol_error(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        with pytest.raises(CmuxProtocolError):
            await transport.request("workspace.unknown")


@pytest.mark.unit
class TestMockTransportCli:
    @pytest.mark.asyncio
    async def test_call_returns_cli_result(self) -> None:
        transport = CmuxMockTransport(fixture_path=FIXTURE_PATH)
        result = await transport.call(["cmux", "--version"])
        assert isinstance(result, CliResult)
        assert result.returncode == 0
        assert result.ok is True


@pytest.mark.unit
class TestFixtureFormat:
    def test_fixture_yaml_loads(self) -> None:
        with FIXTURE_PATH.open() as f:
            data = yaml.safe_load(f)
        assert isinstance(data, list)
        assert all("method" in entry for entry in data)
        assert all("params" in entry for entry in data)
        assert all("response" in entry for entry in data)
