"""Tests for client.py — task lifecycle methods.

TC-074..TC-078, TC-080 (TASK-002)
"""

from __future__ import annotations

import json

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConflictError, FlowableConnectionError, FlowableValidationError
from flowable_mcp.models import Task

_BASE = "http://flowable-test"
_TASK_URL = f"{_BASE}/runtime/tasks"
_TASK_ID = "task-123"
_TASK_URL_ID = f"{_TASK_URL}/{_TASK_ID}"

_TASK_PAYLOAD = {
    "id": _TASK_ID,
    "processInstanceId": "pi-abc",
    "priority": 50,
    "suspended": False,
}


# TC-074
async def test_client_list_tasks_when_200_then_returns_task_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_TASK_URL).mock(
        return_value=httpx.Response(200, json={"data": [_TASK_PAYLOAD], "total": 1})
    )
    result = await flowable_client.list_tasks()
    assert len(result) == 1
    assert isinstance(result[0], Task)
    assert result[0].id == _TASK_ID


# TC-075
async def test_client_claim_task_when_200_then_returns_none_and_body_correct(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(200))
    result = await flowable_client.claim_task(task_id=_TASK_ID, assignee="u1")
    assert result is None
    body = json.loads(route.calls[0].request.content)
    assert body == {"action": "claim", "assignee": "u1"}


# TC-076
async def test_client_claim_task_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_TASK_URL_ID).mock(
        return_value=httpx.Response(409, text="already claimed")
    )
    with pytest.raises(FlowableConflictError):
        await flowable_client.claim_task(task_id=_TASK_ID, assignee="u1")


# TC-077
async def test_client_complete_task_when_variables_then_body_variables_list_typed_correctly(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(200))
    await flowable_client.complete_task(task_id=_TASK_ID, variables={"approved": True, "score": 42})
    body = json.loads(route.calls[0].request.content)
    assert "variables" in body
    vars_by_name = {v["name"]: v for v in body["variables"]}
    assert vars_by_name["approved"]["type"] == "boolean"
    assert vars_by_name["score"]["type"] == "integer"


# TC-078
async def test_client_delegate_task_when_200_then_returns_none_and_body_correct(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(200))
    result = await flowable_client.delegate_task(task_id=_TASK_ID, assignee="u2")
    assert result is None
    body = json.loads(route.calls[0].request.content)
    assert body == {"action": "delegate", "assignee": "u2"}


# TC-080
async def test_client_list_tasks_when_total_is_non_integer_then_fallback_to_len_data(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_TASK_URL).mock(
        return_value=httpx.Response(200, json={"data": [_TASK_PAYLOAD], "total": "garbage"})
    )
    result = await flowable_client.list_tasks()
    assert len(result) == 1


# claim_task 404 → NotFoundError (existing TC-027 coverage, re-verified)
async def test_client_claim_task_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    from flowable_mcp.errors import FlowableNotFoundError

    respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.claim_task(task_id=_TASK_ID, assignee="u1")


# TC-019
async def test_client_complete_task_when_400_then_raises_validation_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(400, text="invalid variables"))
    with pytest.raises(FlowableValidationError):
        await flowable_client.complete_task(task_id=_TASK_ID, variables={"approved": True})


# TC-023  (POST is non-idempotent → http_no_retry → ConnectError must not be retried)
async def test_client_claim_task_when_connect_error_then_raises_connection_error_exactly_once(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_TASK_URL_ID).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.claim_task(task_id=_TASK_ID, assignee="u1")
    assert respx_mock.calls.call_count == 1


# TC-025  (list_tasks filters → correct query params sent to Flowable)
async def test_client_list_tasks_when_filters_then_query_params_correct(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_TASK_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_tasks(
        process_instance_id="pi-1",
        assignee="alice",
        candidate_group="managers",
        max_results=10,
    )
    params = dict(route.calls[0].request.url.params)
    assert params["processInstanceId"] == "pi-1"
    assert params["assignee"] == "alice"
    assert params["candidateGroup"] == "managers"
    assert params["size"] == "10"


# complete_task 204 → None, resp.json() NOT called
async def test_client_complete_task_when_204_then_returns_none(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_TASK_URL_ID).mock(return_value=httpx.Response(204))
    result = await flowable_client.complete_task(task_id=_TASK_ID)
    assert result is None
