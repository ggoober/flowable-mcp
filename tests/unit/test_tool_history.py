"""Tests for tools/history.py — tool-layer behaviour.

TC-041..TC-042 (TASK-002)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.history import register

_HIST_URL = "http://flowable-test/history/historic-process-instances"


def _make_history_tools(unit_settings: Settings) -> tuple[dict, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(
            unit_settings.username,
            unit_settings.password.get_secret_value(),
        ),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    mock_mcp = MagicMock()
    registered: dict = {}

    def capture_tool():
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool.side_effect = capture_tool
    register(mock_mcp, client)
    return registered, http


# TC-041: max_results > 500 → explicit ValueError guard
async def test_tool_list_historic_when_max_results_exceeds_limit_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_history_tools(unit_settings)
    try:
        with pytest.raises(ValueError, match="max_results"):
            await tools["list_historic_process_instances"](max_results=501)
    finally:
        await http.aclose()


# TC-042: boundary values {0, 1, 500} → correct size param sent to API
@pytest.mark.parametrize("limit", [0, 1, 500])
async def test_tool_list_historic_when_boundary_max_results_then_size_param_correct(
    unit_settings: Settings, respx_mock, limit: int
) -> None:
    tools, http = _make_history_tools(unit_settings)
    route = respx_mock.get(_HIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        await tools["list_historic_process_instances"](max_results=limit)
        url = str(route.calls[0].request.url)
        assert f"size={limit}" in url
    finally:
        await http.aclose()
