"""Unit tests for FlowableClient.list_historic_task_instances (TASK-003, TC-29..TC-39)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError, FlowableServerError
from flowable_mcp.models import HistoricTaskInstance
from tests.unit.conftest import raise_cancelled

_BASE = "http://flowable-test"
_HTI_URL = f"{_BASE}/history/historic-task-instances"

_HTI_PAYLOAD = {
    "id": "task-hist-001",
    "name": "Review",
    "taskDefinitionKey": "review-task",
    "processInstanceId": "pi-001",
    "processDefinitionId": "order:1:xyz",
    "startTime": "2024-01-10T09:00:00.000+0000",
    "endTime": "2024-01-10T10:00:00.000+0000",
    "durationInMillis": 3600000,
    "assignee": "alice",
    "deleteReason": None,
}

_LIST_RESPONSE = {"data": [_HTI_PAYLOAD], "total": 1}
_EMPTY_RESPONSE = {"data": [], "total": 0}


# TC-29: happy path — 200 with data returns list[HistoricTaskInstance]
async def test_client_list_historic_task_instances_when_200_with_data_then_returns_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HTI_URL).mock(return_value=httpx.Response(200, json=_LIST_RESPONSE))
    result = await flowable_client.list_historic_task_instances()
    assert len(result) == 1
    assert isinstance(result[0], HistoricTaskInstance)
    assert result[0].id == "task-hist-001"
    assert result[0].assignee == "alice"


# TC-30: 200 + empty data → []
async def test_client_list_historic_task_instances_when_200_empty_then_returns_empty_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HTI_URL).mock(return_value=httpx.Response(200, json=_EMPTY_RESPONSE))
    result = await flowable_client.list_historic_task_instances()
    assert result == []


# TC-31: finished=True → query param "finished=true"
async def test_client_list_historic_task_instances_when_finished_true_then_param_is_true(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(finished=True)
    assert route.calls[0].request.url.params["finished"] == "true"


# TC-32: finished=False → query param "finished=false"
async def test_client_list_historic_task_instances_when_finished_false_then_param_is_false(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(finished=False)
    assert route.calls[0].request.url.params["finished"] == "false"


# TC-33: finished=None → "finished" param absent from URL
async def test_client_list_historic_task_instances_when_finished_none_then_param_absent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(finished=None)
    assert "finished" not in route.calls[0].request.url.params


# TC-34: started_after → ISO string in params
async def test_client_list_historic_task_instances_when_started_after_then_iso_param_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(started_after=dt)
    # Flowable historic-task-instances uses `taskCreatedAfter`, not `startedAfter`,
    # in Flowable-accepted ISO-8601 (millis + 'Z').
    assert (
        route.calls[0].request.url.params["taskCreatedAfter"]
        == "2024-01-01T12:00:00.000Z"
    )


# TC-35: started_before → ISO string in params
async def test_client_list_historic_task_instances_when_started_before_then_iso_param_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dt = datetime(2024, 3, 31, 23, 59, 59, tzinfo=UTC)
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(started_before=dt)
    assert (
        route.calls[0].request.url.params["taskCreatedBefore"]
        == "2024-03-31T23:59:59.000Z"
    )


# TC-36: 404 → FlowableNotFoundError
async def test_client_list_historic_task_instances_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HTI_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.list_historic_task_instances()


# TC-37: 503 → FlowableServerError
async def test_client_list_historic_task_instances_when_503_then_raises_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HTI_URL).mock(return_value=httpx.Response(503, text="unavailable"))
    with pytest.raises(FlowableServerError):
        await flowable_client.list_historic_task_instances()


# TC-38: CancelledError propagates (GET → _retry)
async def test_client_list_historic_task_instances_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HTI_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.list_historic_task_instances()


# TC-39: all filters set → all params forwarded
async def test_client_list_historic_task_instances_when_all_filters_then_all_params_sent(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dt_after = datetime(2024, 1, 1, tzinfo=UTC)
    dt_before = datetime(2024, 12, 31, tzinfo=UTC)
    route = respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json=_EMPTY_RESPONSE)
    )
    await flowable_client.list_historic_task_instances(
        process_instance_id="pi-999",
        assignee="bob",
        process_definition_key="order-proc",
        finished=True,
        started_after=dt_after,
        started_before=dt_before,
        max_results=25,
    )
    params = dict(route.calls[0].request.url.params)
    assert params["processInstanceId"] == "pi-999"
    assert params["taskAssignee"] == "bob"
    assert params["processDefinitionKey"] == "order-proc"
    assert params["finished"] == "true"
    assert params["taskCreatedAfter"] == "2024-01-01T00:00:00.000Z"
    assert params["taskCreatedBefore"] == "2024-12-31T00:00:00.000Z"
    assert params["size"] == "25"


# assignee="" in Flowable response → model maps to None (field_validator)
async def test_client_list_historic_task_instances_when_assignee_empty_string_then_none(
    flowable_client: FlowableClient, respx_mock
) -> None:
    payload = {**_HTI_PAYLOAD, "assignee": ""}
    respx_mock.get(_HTI_URL).mock(
        return_value=httpx.Response(200, json={"data": [payload], "total": 1})
    )
    result = await flowable_client.list_historic_task_instances()
    assert result[0].assignee is None
