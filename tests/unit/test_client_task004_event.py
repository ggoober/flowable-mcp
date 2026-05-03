"""Tests for FlowableClient.list_event_subscriptions pagination (TASK-004).

TC-U-091..TC-U-098
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import EventSubscription

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"
_URL = f"{_BASE}/runtime/event-subscriptions"

_ES_ITEM = {
    "id": "es-1",
    "eventType": "message",
    "eventName": "MyMessage",
    "activityId": "catchEvent1",
    "processDefinitionId": "my-proc:1:abc",
    "processInstanceId": "pi-1",
    "created": "2026-01-01T00:00:00.000Z",
    "tenantId": "",
}


# TC-U-091: event_type filter → eventType= in URL
async def test_client_list_event_subs_when_event_type_filter_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_event_subscriptions(event_type="message")
    url = str(route.calls[0].request.url)
    assert "eventType=message" in url


# TC-U-092: process_definition_key filter → processDefinitionKey= in URL
async def test_client_list_event_subs_when_key_filter_then_param_in_url(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_event_subscriptions(process_definition_key="my-proc")
    url = str(route.calls[0].request.url)
    assert "processDefinitionKey=my-proc" in url


# TC-U-093: No filters → no filter params in URL (only pagination params)
async def test_client_list_event_subs_when_no_filters_then_no_filter_params(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    await flowable_client.list_event_subscriptions()
    url = str(route.calls[0].request.url)
    assert "eventType" not in url
    assert "processDefinitionKey" not in url


# TC-U-094: Returns list of EventSubscription DTO
async def test_client_list_event_subs_when_data_present_then_returns_dto_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ES_ITEM], "total": 1})
    )
    result = await flowable_client.list_event_subscriptions()
    assert len(result) == 1
    assert isinstance(result[0], EventSubscription)
    assert result[0].id == "es-1"


# TC-U-095: Multi-page (201 items, page_size=100) → all 201 items fetched via _paginate
async def test_client_list_event_subs_when_multi_page_then_all_fetched(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page1 = [_ES_ITEM] * 100
    page2 = [_ES_ITEM] * 100
    page3 = [_ES_ITEM] * 1

    def _handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start = int(params.get("start", "0"))
        if start == 0:
            return httpx.Response(200, json={"data": page1, "total": 201})
        elif start == 100:
            return httpx.Response(200, json={"data": page2, "total": 201})
        else:
            return httpx.Response(200, json={"data": page3, "total": 201})

    respx_mock.get(_URL).mock(side_effect=_handler)
    result = await flowable_client.list_event_subscriptions()
    assert len(result) == 201


# TC-U-096: Single page (≤100) → only one HTTP request made
async def test_client_list_event_subs_when_single_page_then_one_request(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page = [_ES_ITEM] * 5
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": page, "total": 5})
    )
    await flowable_client.list_event_subscriptions()
    assert route.call_count == 1


# TC-U-097: CancelledError during pagination → re-raised (not swallowed)
async def test_client_list_event_subs_when_cancelled_then_reraises(
    flowable_client: FlowableClient, respx_mock
) -> None:
    from tests.unit.conftest import raise_cancelled

    respx_mock.get(_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.list_event_subscriptions()


# TC-U-098: Truncated flag discarded — client returns plain list, not tuple
async def test_client_list_event_subs_when_truncated_then_returns_list_not_tuple(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page = [_ES_ITEM] * 5
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": page, "total": 5})
    )
    result = await flowable_client.list_event_subscriptions()
    assert isinstance(result, list)
    assert not isinstance(result, tuple)
