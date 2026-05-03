"""Tests for client.py — historic process instance methods.

TC-087..TC-088 (TASK-002)
"""

from __future__ import annotations

import datetime

import httpx

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import HistoricProcessInstance

_BASE = "http://flowable-test"
_HIST_URL = f"{_BASE}/history/historic-process-instances"

_HIST_PAYLOAD = {
    "id": "hist-1",
    "processDefinitionId": "pd:1:xyz",
    "processDefinitionKey": "my-proc",
    "ended": True,
    "deleted": False,
}


# TC-087: finished=True → param value is "true" (lowercase), NOT "True" (Python repr)
async def test_client_list_historic_when_finished_true_then_param_is_lowercase_true(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_HIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_historic_process_instances(finished=True)
    url = str(route.calls[0].request.url)
    assert "finished=true" in url
    assert "finished=True" not in url


# TC-088: started_before=datetime → "startedBefore=...ISO..." in URL
async def test_client_list_historic_when_started_before_provided_then_iso_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    cutoff = datetime.datetime(2024, 6, 15, 12, 0, 0, tzinfo=datetime.UTC)
    route = respx_mock.get(_HIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_historic_process_instances(started_before=cutoff)
    url = str(route.calls[0].request.url)
    assert "startedBefore=" in url
    assert "2024-06-15" in url


# TC-043: processDefinitionKey filter → query param forwarded, no in-memory filtering
async def test_client_list_historic_when_process_definition_key_then_param_forwarded_to_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_HIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_historic_process_instances(process_definition_key="my-proc")
    url = str(route.calls[0].request.url)
    assert "processDefinitionKey=my-proc" in url


# Return type: valid HistoricProcessInstance DTO
async def test_client_list_historic_when_data_present_then_returns_dto_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_HIST_URL).mock(
        return_value=httpx.Response(200, json={"data": [_HIST_PAYLOAD], "total": 1})
    )
    result = await flowable_client.list_historic_process_instances()
    assert len(result) == 1
    assert isinstance(result[0], HistoricProcessInstance)
    assert result[0].id == "hist-1"
