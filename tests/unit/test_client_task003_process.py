"""Unit tests for FlowableClient.list_process_instances (TASK-003, TC-03..TC-12)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError, FlowableServerError
from flowable_mcp.models import ProcessInstance
from tests.unit.conftest import raise_cancelled

_BASE = "http://flowable-test"
_PI_LIST_URL = f"{_BASE}/runtime/process-instances"

_PI_PAYLOAD = {
    "id": "pi-001",
    "processDefinitionId": "pd:1:xyz",
    "processDefinitionKey": "my-proc",
    "businessKey": None,
    "tenantId": None,
    "ended": False,
    "suspended": False,
}

_LIST_RESPONSE = {"data": [_PI_PAYLOAD], "total": 1}
_EMPTY_RESPONSE = {"data": [], "total": 0}


# TC-06: happy path — 200 with data returns list[ProcessInstance]
async def test_client_list_process_instances_when_200_with_data_then_returns_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_LIST_URL).mock(return_value=httpx.Response(200, json=_LIST_RESPONSE))
    result = await flowable_client.list_process_instances()
    assert len(result) == 1
    assert isinstance(result[0], ProcessInstance)
    assert result[0].id == "pi-001"


# TC-07: empty data array returns empty list
async def test_client_list_process_instances_when_200_with_empty_data_then_returns_empty_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_LIST_URL).mock(return_value=httpx.Response(200, json=_EMPTY_RESPONSE))
    result = await flowable_client.list_process_instances()
    assert result == []


# TC-03: suspended=True encodes as "true" in query string (BUG-R6 guard)
async def test_client_list_process_instances_when_suspended_true_then_query_param_is_true(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances(suspended=True)
    assert route.calls[0].request.url.params["suspended"] == "true"


# TC-04: suspended=False encodes as "false" in query string
async def test_client_list_process_instances_when_suspended_false_then_query_param_is_false(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances(suspended=False)
    assert route.calls[0].request.url.params["suspended"] == "false"


# TC-09: suspended=None means no "suspended" param in URL
async def test_client_list_process_instances_when_suspended_none_then_param_absent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances(suspended=None)
    assert "suspended" not in route.calls[0].request.url.params


# TC-10: all optional filters None → only "size" param is sent
async def test_client_list_process_instances_when_no_filters_then_only_size_param(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances()
    params = dict(route.calls[0].request.url.params)
    assert "size" in params
    assert "processDefinitionKey" not in params
    assert "businessKey" not in params
    assert "suspended" not in params
    assert "involvedUser" not in params


# TC-12: max_results=200 → size=200 in URL
async def test_client_list_process_instances_when_max_results_200_then_size_param_is_200(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances(max_results=200)
    assert route.calls[0].request.url.params["size"] == "200"


# TC-05: 404 → FlowableNotFoundError
async def test_client_list_process_instances_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_LIST_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.list_process_instances()


# TC-11: 503 → FlowableServerError
async def test_client_list_process_instances_when_503_then_raises_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_LIST_URL).mock(return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(FlowableServerError):
        await flowable_client.list_process_instances()


# TC-08: CancelledError propagates (GET → _retry client)
async def test_client_list_process_instances_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_LIST_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.list_process_instances()


# optional filters correctly forwarded
async def test_client_list_process_instances_when_all_filters_set_then_all_params_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_PI_LIST_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_process_instances(
        process_definition_key="order-proc",
        business_key="BK-42",
        suspended=False,
        involved_user="alice",
        max_results=10,
    )
    params = dict(route.calls[0].request.url.params)
    assert params["processDefinitionKey"] == "order-proc"
    assert params["businessKey"] == "BK-42"
    assert params["suspended"] == "false"
    assert params["involvedUser"] == "alice"
    assert params["size"] == "10"
