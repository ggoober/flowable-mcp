"""Tests for tools/process.py — register() pattern and tool behaviour."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.process import register


def _make_client(unit_settings: Settings) -> tuple[httpx.AsyncClient, FlowableClient]:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(
            unit_settings.username,
            unit_settings.password.get_secret_value(),
        ),
        timeout=unit_settings.timeout_s,
    )
    return http, FlowableClient(http_retry=http, http_no_retry=http)


def _capture_register(client: FlowableClient) -> dict[str, object]:
    """Call register() with a mock FastMCP and return {name: fn} for registered tools."""
    mock_mcp = MagicMock()
    registered: dict[str, object] = {}

    def capture_tool():
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool.side_effect = capture_tool
    register(mock_mcp, client)
    return registered


# ---------------------------------------------------------------------------
# TC-31: register() wires tools; list_process_definitions returns list
# ---------------------------------------------------------------------------

async def test_tool_register_when_valid_client_then_list_process_definitions_returns_list(
    unit_settings: Settings,
    respx_mock,
) -> None:
    PD_URL = "http://flowable-test/repository/process-definitions"
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    http, client = _make_client(unit_settings)
    tools = _capture_register(client)

    assert "list_process_definitions" in tools
    assert "start_process_instance" in tools
    assert "get_process_instance" in tools
    assert "cancel_process_instance" in tools

    result = await tools["list_process_definitions"]()
    assert result == []
    await http.aclose()


# ---------------------------------------------------------------------------
# TC-38: start_process_instance raises ValueError when both key and id given (I1)
# ---------------------------------------------------------------------------

async def test_tool_start_process_instance_when_both_key_and_id_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    http, client = _make_client(unit_settings)
    tools = _capture_register(client)

    with pytest.raises(ValueError, match="Exactly one"):
        await tools["start_process_instance"](
            process_definition_key="key",
            process_definition_id="id",
        )
    await http.aclose()


# ---------------------------------------------------------------------------
# TC-38b: start_process_instance raises ValueError when neither key nor id given
# ---------------------------------------------------------------------------

async def test_tool_start_process_instance_when_neither_key_nor_id_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    http, client = _make_client(unit_settings)
    tools = _capture_register(client)

    with pytest.raises(ValueError, match="Exactly one"):
        await tools["start_process_instance"]()
    await http.aclose()
