"""Tests for tools/task.py — tool-layer behaviour.

TC-079, TC-091..TC-093 (TASK-002)
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConnectionError
from flowable_mcp.config import Settings
from flowable_mcp.tools.task import register


def _make_task_tools(unit_settings: Settings) -> tuple[dict, httpx.AsyncClient]:
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


# TC-015: max_results > 200 → explicit ValueError guard in tool layer
async def test_tool_list_tasks_when_max_results_exceeds_limit_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_task_tools(unit_settings)
    try:
        with pytest.raises(ValueError, match="max_results"):
            await tools["list_tasks"](max_results=201)
    finally:
        await http.aclose()


# TC-079: max_results=0 → size=0, returns []
async def test_tool_list_tasks_when_max_results_zero_then_returns_empty_list(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.get("http://flowable-test/runtime/tasks").mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        result = await tools["list_tasks"](max_results=0)
        assert result == []
    finally:
        await http.aclose()


# TC-091: due_date in past → WARNING logged, task still completes
async def test_tool_complete_task_when_due_date_in_past_then_warning_logged(
    unit_settings: Settings, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.task"):
            await tools["complete_task"](task_id="t-1", due_date="2000-01-01T00:00:00Z")
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("past its due date" in m for m in warning_msgs)
    finally:
        await http.aclose()


# TC-092: due_date invalid ISO → DEBUG logged, task still completes, no WARNING
async def test_tool_complete_task_when_due_date_invalid_iso_then_debug_logged_no_warning(
    unit_settings: Settings, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        with caplog.at_level(logging.DEBUG, logger="flowable_mcp.tools.task"):
            await tools["complete_task"](task_id="t-1", due_date="not-a-date")
        debug_msgs = [r.message for r in caplog.records if r.levelno == logging.DEBUG]
        assert any("Invalid due_date format" in m for m in debug_msgs)
        assert not any(r.levelno == logging.WARNING for r in caplog.records)
    finally:
        await http.aclose()


# TC-093: due_date=None → no overdue-related log entries at any level
async def test_tool_complete_task_when_due_date_none_then_no_overdue_log(
    unit_settings: Settings, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.post("http://flowable-test/runtime/tasks/t-1").mock(
        return_value=httpx.Response(200)
    )
    try:
        with caplog.at_level(logging.DEBUG, logger="flowable_mcp.tools.task"):
            await tools["complete_task"](task_id="t-1", due_date=None)
        overdue_records = [r for r in caplog.records if "due" in r.getMessage().lower()]
        assert overdue_records == []
    finally:
        await http.aclose()
