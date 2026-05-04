"""Tests for tools/task.py — set_task_due_date tool behaviour (TASK-004).

TC-U-076, TC-U-080..TC-U-081, TC-U-086..TC-U-088
"""

from __future__ import annotations

import datetime
import logging
from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.task import register

pytestmark = [pytest.mark.unit]

_TASK_URL = "http://flowable-test/runtime/tasks/t-99"


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


# TC-U-076: set_task_due_date without timezone → ValueError raised (not forwarded to Flowable)
async def test_tool_set_task_due_date_when_naive_datetime_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_task_tools(unit_settings)
    try:
        naive = datetime.datetime(2030, 1, 1, 12, 0, 0)
        with pytest.raises(ValueError, match="timezone"):
            await tools["set_task_due_date"](task_id="t-99", due_date=naive)
    finally:
        await http.aclose()


# TC-U-080: Future due_date → result dict has no warnings
async def test_tool_set_task_due_date_when_future_date_then_no_warnings(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    try:
        future = datetime.datetime(2099, 12, 31, 23, 59, 59, tzinfo=datetime.UTC)
        result = await tools["set_task_due_date"](task_id="t-99", due_date=future)
        assert result["warnings"] == []
    finally:
        await http.aclose()


# TC-U-081: Return dict has keys: task_id, due_date, warnings
async def test_tool_set_task_due_date_when_called_then_returns_dict_with_required_keys(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    try:
        dt = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
        result = await tools["set_task_due_date"](task_id="t-99", due_date=dt)
        assert "task_id" in result
        assert "due_date" in result
        assert "warnings" in result
        assert result["task_id"] == "t-99"
        assert isinstance(result["warnings"], list)
    finally:
        await http.aclose()


# TC-U-086: Past due_date → WARNING logged
async def test_tool_set_task_due_date_when_past_date_then_warning_logged(
    unit_settings: Settings, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    try:
        past = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.task"):
            await tools["set_task_due_date"](task_id="t-99", due_date=past)
        warning_msgs = [r.message for r in caplog.records if r.levelno == logging.WARNING]
        assert any("past" in m.lower() for m in warning_msgs)
    finally:
        await http.aclose()


# TC-U-087: Past due_date → result["warnings"] contains a non-empty string
async def test_tool_set_task_due_date_when_past_date_then_warnings_list_not_empty(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    try:
        past = datetime.datetime(2000, 6, 15, tzinfo=datetime.UTC)
        result = await tools["set_task_due_date"](task_id="t-99", due_date=past)
        assert len(result["warnings"]) > 0
        assert isinstance(result["warnings"][0], str)
    finally:
        await http.aclose()


# TC-U-088: Future due_date → warnings list is empty
async def test_tool_set_task_due_date_when_future_date_then_warnings_list_empty(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_task_tools(unit_settings)
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    try:
        future = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
        result = await tools["set_task_due_date"](task_id="t-99", due_date=future)
        assert result["warnings"] == []
    finally:
        await http.aclose()
