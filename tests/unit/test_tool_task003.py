"""Unit tests for tool-layer process tools registered in tools/process.py
(TASK-003, TC-01, TC-02, TC-20, TC-40..TC-41, TC-63..TC-70, INV-07).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.history import register as register_history
from flowable_mcp.tools.process import register as register_process

_BASE = "http://flowable-test"
_PI_LIST_URL = f"{_BASE}/runtime/process-instances"
_DEF_URL_PREFIX = f"{_BASE}/repository/process-definitions"


def _make_tools(unit_settings: Settings, register_fn) -> tuple[dict, httpx.AsyncClient]:
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
    register_fn(mock_mcp, client)
    return registered, http


def _make_process_tools(unit_settings: Settings) -> tuple[dict, httpx.AsyncClient]:
    return _make_tools(unit_settings, register_process)


# TC-40: list_process_instances passes filters to client (smoke via respx)
async def test_tool_list_process_instances_when_filters_set_then_params_forwarded(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_process_tools(unit_settings)
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        await tools["list_process_instances"](
            process_definition_key="order-proc",
            suspended=True,
            max_results=10,
        )
        params = dict(route.calls[0].request.url.params)
        assert params["processDefinitionKey"] == "order-proc"
        assert params["suspended"] == "true"
        assert params["size"] == "10"
    finally:
        await http.aclose()


# TC-41: list_process_instances max_results=1 (min boundary) → size=1
async def test_tool_list_process_instances_when_max_results_1_then_size_is_1(
    unit_settings: Settings, respx_mock
) -> None:
    tools, http = _make_process_tools(unit_settings)
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    try:
        await tools["list_process_instances"](max_results=1)
        assert route.calls[0].request.url.params["size"] == "1"
    finally:
        await http.aclose()


# TC-63: suspend_process_definition with confirm_cascade=True → warning logged
async def test_tool_suspend_process_definition_when_cascade_true_then_warning_logged(
    unit_settings: Settings, respx_mock, caplog
) -> None:
    def_id = "order-proc:1:def001"
    url = f"{_DEF_URL_PREFIX}/{def_id}"
    pd_payload = {
        "id": def_id,
        "key": "order-proc",
        "version": 1,
        "deploymentId": "dep-001",
        "suspended": True,
    }
    tools, http = _make_process_tools(unit_settings)
    respx_mock.put(url).mock(return_value=httpx.Response(200, json=pd_payload))
    try:
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.process"):
            await tools["suspend_process_definition"](
                definition_id=def_id, confirm_cascade=True
            )
        assert any("cascade" in r.message.lower() for r in caplog.records)
    finally:
        await http.aclose()


# TC-64: suspend_process_definition with confirm_cascade=False → no warning logged
async def test_tool_suspend_process_definition_when_cascade_false_then_no_warning(
    unit_settings: Settings, respx_mock, caplog
) -> None:
    def_id = "order-proc:1:def001"
    url = f"{_DEF_URL_PREFIX}/{def_id}"
    pd_payload = {
        "id": def_id,
        "key": "order-proc",
        "version": 1,
        "deploymentId": "dep-001",
        "suspended": True,
    }
    tools, http = _make_process_tools(unit_settings)
    respx_mock.put(url).mock(return_value=httpx.Response(200, json=pd_payload))
    try:
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.process"):
            await tools["suspend_process_definition"](
                definition_id=def_id, confirm_cascade=False
            )
        assert not any(
            "cascade" in r.message.lower()
            for r in caplog.records
            if r.levelno == logging.WARNING
        )
    finally:
        await http.aclose()


# TC-65: activate_process_definition confirm_cascade=True → cascade warning logged
async def test_tool_activate_process_definition_when_cascade_true_then_warning_logged(
    unit_settings: Settings, respx_mock, caplog
) -> None:
    def_id = "order-proc:1:def001"
    url = f"{_DEF_URL_PREFIX}/{def_id}"
    pd_payload = {
        "id": def_id,
        "key": "order-proc",
        "version": 1,
        "deploymentId": "dep-001",
        "suspended": False,
    }
    tools, http = _make_process_tools(unit_settings)
    respx_mock.put(url).mock(return_value=httpx.Response(200, json=pd_payload))
    try:
        with caplog.at_level(logging.WARNING, logger="flowable_mcp.tools.process"):
            await tools["activate_process_definition"](
                definition_id=def_id, confirm_cascade=True
            )
        assert any("cascade" in r.message.lower() for r in caplog.records)
    finally:
        await http.aclose()


# TC-66: suspend_process_definition confirm_cascade=True → includeProcessInstances=true in body
async def test_tool_suspend_process_definition_when_cascade_true_then_body_include_instances_true(
    unit_settings: Settings, respx_mock
) -> None:
    import json

    def_id = "order-proc:1:def001"
    url = f"{_DEF_URL_PREFIX}/{def_id}"
    pd_payload = {
        "id": def_id,
        "key": "order-proc",
        "version": 1,
        "deploymentId": "dep-001",
        "suspended": True,
    }
    tools, http = _make_process_tools(unit_settings)
    route = respx_mock.put(url).mock(return_value=httpx.Response(200, json=pd_payload))
    try:
        await tools["suspend_process_definition"](definition_id=def_id, confirm_cascade=True)
        body = json.loads(route.calls[0].request.content)
        assert body["includeProcessInstances"] is True
    finally:
        await http.aclose()


# TC-01: list_process_instances max_results=0 → ValueError before HTTP (AC-1)
async def test_tool_list_process_instances_when_max_results_0_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_process_tools(unit_settings)
    try:
        with pytest.raises(ValueError):
            await tools["list_process_instances"](max_results=0)
    finally:
        await http.aclose()


# TC-02: list_process_instances max_results=201 → ValueError before HTTP (AC-1)
async def test_tool_list_process_instances_when_max_results_201_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_process_tools(unit_settings)
    try:
        with pytest.raises(ValueError):
            await tools["list_process_instances"](max_results=201)
    finally:
        await http.aclose()


# TC-20: list_historic_task_instances max_results=501 → ValueError before HTTP (AC-3)
async def test_tool_list_historic_task_instances_when_max_results_501_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_tools(unit_settings, register_history)
    try:
        with pytest.raises(ValueError):
            await tools["list_historic_task_instances"](max_results=501)
    finally:
        await http.aclose()


# INV-07: stdout clean when confirm_cascade=True — WARNING goes to stderr only (СТ-3)
async def test_tool_suspend_process_definition_when_cascade_true_then_stdout_clean(
    unit_settings: Settings, respx_mock, capsys
) -> None:
    def_id = "order-proc:1:def001"
    url = f"{_DEF_URL_PREFIX}/{def_id}"
    pd_payload = {
        "id": def_id,
        "key": "order-proc",
        "version": 1,
        "deploymentId": "dep-001",
        "suspended": True,
    }
    tools, http = _make_process_tools(unit_settings)
    respx_mock.put(url).mock(return_value=httpx.Response(200, json=pd_payload))
    try:
        await tools["suspend_process_definition"](definition_id=def_id, confirm_cascade=True)
        captured = capsys.readouterr()
        assert captured.out == ""
    finally:
        await http.aclose()
