"""Tests for tools/debug.py — list_event_subscriptions in-tool filter.

TC-089..TC-090 + TC-EXT-1 / CRIT-1 (TASK-002)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.debug import register

_ES_URL = "http://flowable-test/runtime/event-subscriptions"


def _make_debug_tools(unit_settings: Settings) -> tuple[dict, httpx.AsyncClient]:
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


# TC-032: max_results > 200 → explicit ValueError guard in tool layer
async def test_tool_list_deadletter_jobs_when_max_results_exceeds_limit_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_debug_tools(unit_settings)
    try:
        with pytest.raises(ValueError, match="max_results"):
            await tools["list_deadletter_jobs"](max_results=201)
    finally:
        await http.aclose()


# TC-089: key filter, len(subs) ≤ 100 → in-tool filter applied
async def test_tool_list_event_subscriptions_when_key_filter_le_100_then_filtered(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_debug_tools(unit_settings)
    _MATCHING = {"id": "es-1", "eventType": "message", "processDefinitionId": "my-proc:1:abc"}
    _NON_MATCHING = {"id": "es-2", "eventType": "signal", "processDefinitionId": "other-proc:1:xyz"}
    respx_mock.get(_ES_URL).mock(
        return_value=httpx.Response(200, json={"data": [_MATCHING, _NON_MATCHING], "total": 2})
    )
    try:
        result = await tools["list_event_subscriptions"](process_definition_key="my-proc")
        assert len(result) == 1
        assert result[0].id == "es-1"
    finally:
        await http.aclose()


# TC-090 (updated): len(subs) > 100 → client-side filter IS applied via _paginate (AC-4 fix)
async def test_tool_list_event_subscriptions_when_subs_gt_100_then_filter_applied(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_debug_tools(unit_settings)
    subs_data = [
        {"id": f"es-{i}", "eventType": "message", "processDefinitionId": "my-proc:1:abc"}
        for i in range(100)
    ]
    subs_data.append(
        {"id": "es-100", "eventType": "signal", "processDefinitionId": "other-proc:1:xyz"}
    )
    respx_mock.get(_ES_URL).mock(
        return_value=httpx.Response(200, json={"data": subs_data, "total": 101})
    )
    try:
        result = await tools["list_event_subscriptions"](process_definition_key="my-proc")
        # Now filter is unconditional (AC-4): only 100 my-proc items pass, other-proc excluded
        assert len(result) == 100
        assert all(
            s.process_definition_id is not None and s.process_definition_id.startswith("my-proc:")
            for s in result
        )
    finally:
        await http.aclose()


# TC-EXT-1 (CRIT-1): substring false positive — key="proc" MUST NOT match "other-proc:1:xyz"
# Fixed: replaced `key in id` with `id.startswith(key + ":")` in tools/debug.py
async def test_tool_list_event_subscriptions_when_key_is_prefix_of_different_key_then_not_matched(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_debug_tools(unit_settings)
    _ITEM = {"id": "es-1", "eventType": "message", "processDefinitionId": "other-proc:1:xyz"}
    respx_mock.get(_ES_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ITEM], "total": 1})
    )
    try:
        result = await tools["list_event_subscriptions"](process_definition_key="proc")
        assert len(result) == 0, (
            "key='proc' must NOT match processDefinitionId='other-proc:1:xyz'; "
            "fix the substring filter to use startswith semantics"
        )
    finally:
        await http.aclose()
