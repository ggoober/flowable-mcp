"""Tests for FlowableClient.list_historic_activity_instances (TASK-004).

TC-U-057..TC-U-067
"""

from __future__ import annotations

import asyncio
import datetime

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models.history import HistoricActivityInstance

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"
_URL = f"{_BASE}/history/historic-activity-instances"

_ITEM = {"id": "act-1", "activityId": "a1", "activityType": "userTask"}
_EMPTY_PAGE = {"data": [], "total": 0}


# TC-U-057: activity_type="userTask" filter → activityType=userTask in URL
async def test_client_list_activity_when_activity_type_filter_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(activity_type="userTask")
    url = str(route.calls[0].request.url)
    assert "activityType=userTask" in url


# TC-U-058: process_instance_id filter → processInstanceId=pi-1 in URL
async def test_client_list_activity_when_process_instance_id_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(process_instance_id="pi-1")
    url = str(route.calls[0].request.url)
    assert "processInstanceId=pi-1" in url


# TC-U-059: activity_id filter → activityId=ai-1 in URL
async def test_client_list_activity_when_activity_id_filter_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(activity_id="ai-1")
    url = str(route.calls[0].request.url)
    assert "activityId=ai-1" in url


# TC-U-060: finished=True → finished=true (lowercase) in URL
async def test_client_list_activity_when_finished_true_then_lowercase_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(finished=True)
    url = str(route.calls[0].request.url)
    assert "finished=true" in url
    assert "finished=True" not in url


# TC-U-061: started_after → startedAfter=...ISO... in URL
async def test_client_list_activity_when_started_after_then_iso_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dt = datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=datetime.UTC)
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(started_after=dt)
    url = str(route.calls[0].request.url)
    assert "startedAfter=" in url
    assert "2026-01-01" in url


# TC-U-062: started_before → startedBefore=...ISO... in URL
async def test_client_list_activity_when_started_before_then_iso_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dt = datetime.datetime(2026, 6, 30, 23, 59, 59, tzinfo=datetime.UTC)
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(started_before=dt)
    url = str(route.calls[0].request.url)
    assert "startedBefore=" in url
    assert "2026-06-30" in url


# TC-U-063: No filters provided → only pagination params in URL
async def test_client_list_activity_when_no_filters_then_no_extra_params(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances()
    url = str(route.calls[0].request.url)
    assert "activityType" not in url
    assert "processInstanceId" not in url
    assert "activityId" not in url
    assert "finished" not in url
    assert "startedAfter" not in url
    assert "startedBefore" not in url


# TC-U-064: Returns list of HistoricActivityInstance DTO
async def test_client_list_activity_when_data_present_then_returns_dto_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ITEM, _ITEM], "total": 2})
    )
    result = await flowable_client.list_historic_activity_instances()
    assert len(result) == 2
    assert all(isinstance(item, HistoricActivityInstance) for item in result)
    assert result[0].id == "act-1"


# TC-U-065: max_results=5 caps pagination at 5 items
async def test_client_list_activity_when_max_results_5_then_capped_at_5(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page = [_ITEM] * 5
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": page, "total": 100})
    )
    result = await flowable_client.list_historic_activity_instances(max_results=5)
    assert len(result) == 5


# TC-U-066: Multi-page scenario (101 items, page_size=100) → all items returned
async def test_client_list_activity_when_multi_page_then_all_items_returned(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page1 = [_ITEM] * 100
    page2 = [_ITEM] * 1

    def _handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start = int(params.get("start", "0"))
        if start == 0:
            return httpx.Response(200, json={"data": page1, "total": 101})
        return httpx.Response(200, json={"data": page2, "total": 101})

    respx_mock.get(_URL).mock(side_effect=_handler)
    result = await flowable_client.list_historic_activity_instances(max_results=10000)
    assert len(result) == 101


# TC-U-067: CancelledError during pagination → re-raised (not swallowed)
async def test_client_list_activity_when_cancelled_then_reraises(
    flowable_client: FlowableClient, respx_mock
) -> None:
    from tests.unit.conftest import raise_cancelled

    respx_mock.get(_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.list_historic_activity_instances()


# TC-M05: process_definition_id filter → processDefinitionId= in URL (M-05 fix, AC-1 §12)
async def test_client_list_activity_when_process_definition_id_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """Root cause M-05: AC-1 §12 requires a process definition filter. Flowable endpoint
    /history/historic-activity-instances supports processDefinitionId (not Key). The param
    name in AC-1 ('process_definition_key') was a spec error; correct name per §5.2 is
    processDefinitionId.
    """
    route = respx_mock.get(_URL).mock(return_value=httpx.Response(200, json=_EMPTY_PAGE))
    await flowable_client.list_historic_activity_instances(
        process_definition_id="order-approval:3:abc123"
    )
    url = str(route.calls[0].request.url)
    assert "processDefinitionId=order-approval%3A3%3Aabc123" in url or \
           "processDefinitionId=order-approval:3:abc123" in url
