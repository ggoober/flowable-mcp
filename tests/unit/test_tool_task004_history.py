"""Tests for tools/history.py — list_historic_activity_instances tool behaviour (TASK-004).

TC-U-084..TC-U-085, TC-U-100, TC-U-102, TC-U-104..TC-U-106, TC-U-125..TC-U-126
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.models.history import HistoricActivityInstance
from flowable_mcp.tools.history import register

pytestmark = [pytest.mark.unit]

_ACT_URL = "http://flowable-test/history/historic-activity-instances"
_HIST_TASK_URL = "http://flowable-test/history/historic-task-instances"

_ACT_ITEM = {"id": "act-1", "activityId": "a1", "activityType": "userTask"}
_TASK_ITEM = {"id": "ht-1"}


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


# TC-U-084: Default activity_type="userTask" → activityType=userTask in URL
async def test_tool_list_historic_activity_when_default_type_then_usertask_in_url(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    route = respx_mock.get(_ACT_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        await tools["list_historic_activity_instances"]()
        url = str(route.calls[0].request.url)
        assert "activityType=userTask" in url
    finally:
        await http.aclose()


# TC-U-085: activity_type=None → no activityType param in URL (all activity types returned)
async def test_tool_list_historic_activity_when_type_none_then_no_type_param(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    route = respx_mock.get(_ACT_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        await tools["list_historic_activity_instances"](activity_type=None)
        url = str(route.calls[0].request.url)
        assert "activityType" not in url
    finally:
        await http.aclose()


# TC-U-100: complete_task with naive ISO due_date → task completes (no ValueError raised)
async def test_tool_complete_task_when_naive_iso_due_date_then_completes_without_error(
    unit_settings: Settings, respx_mock
) -> None:
    from flowable_mcp.tools.task import register as task_register

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
    task_register(mock_mcp, client)

    respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        # Naive datetime (no timezone) → no ValueError, just warning
        await registered["complete_task"](task_id="t-1", due_date="2000-01-01T00:00:00")
    finally:
        await http.aclose()


# TC-U-102: complete_task with future ISO due_date → no warning logged
async def test_tool_complete_task_when_future_due_date_then_no_warning(
    unit_settings: Settings, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    from flowable_mcp.tools.task import register as task_register

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
    task_register(mock_mcp, client)

    respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.task"):
            await registered["complete_task"](task_id="t-1", due_date="2099-12-31T00:00:00Z")
        assert not any(r.levelno == logging.WARNING for r in caplog.records)
    finally:
        await http.aclose()


# TC-U-104: complete_task due_date NOT forwarded to Flowable REST (body has only "action")
async def test_tool_complete_task_when_due_date_given_then_not_in_request_body(
    unit_settings: Settings, respx_mock
) -> None:
    from flowable_mcp.tools.task import register as task_register

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
    task_register(mock_mcp, client)

    route = respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        await registered["complete_task"](task_id="t-1", due_date="2000-01-01T00:00:00Z")
        import json
        body = json.loads(route.calls[0].request.content)
        assert "dueDate" not in body
        assert body.get("action") == "complete"
    finally:
        await http.aclose()


# TC-U-105: list_historic_activity_instances → returns list[HistoricActivityInstance]
async def test_tool_list_historic_activity_when_data_present_then_returns_dto_list(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    respx_mock.get(_ACT_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ACT_ITEM], "total": 1})
    )
    try:
        result = await tools["list_historic_activity_instances"]()
        assert len(result) == 1
        assert isinstance(result[0], HistoricActivityInstance)
    finally:
        await http.aclose()


# TC-U-106: list_historic_activity_instances max_results=500 → passes through to client
async def test_tool_list_historic_activity_when_max_results_500_then_no_error(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    respx_mock.get(_ACT_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        result = await tools["list_historic_activity_instances"](max_results=500)
        assert isinstance(result, list)
    finally:
        await http.aclose()


# TC-U-125: list_historic_task_instances tool registered and callable
async def test_tool_list_historic_task_when_called_then_delegates_to_client(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    respx_mock.get(_HIST_TASK_URL).mock(
        return_value=httpx.Response(200, json={"data": [_TASK_ITEM], "total": 1})
    )
    try:
        result = await tools["list_historic_task_instances"]()
        assert isinstance(result, list)
        assert len(result) == 1
    finally:
        await http.aclose()


# TC-U-126: list_historic_task_instances max_results=1 (min boundary) → no error
async def test_tool_list_historic_task_when_max_results_min_then_no_error(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_history_tools(unit_settings)
    route = respx_mock.get(_HIST_TASK_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        result = await tools["list_historic_task_instances"](max_results=1)
        url = str(route.calls[0].request.url)
        assert "size=1" in url
        assert isinstance(result, list)
    finally:
        await http.aclose()
