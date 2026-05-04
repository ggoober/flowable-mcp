"""Tests for FlowableClient._paginate, _parse_list, _parse_total, _flowable_iso8601.

TC-U-068..TC-U-073, TC-U-107..TC-U-115, TC-U-123..TC-U-124 (TASK-004)
"""

from __future__ import annotations

import asyncio
import datetime

import httpx
import pytest

from flowable_mcp.client import FlowableClient, _flowable_iso8601
from flowable_mcp.errors import FlowableConnectionError, FlowableProtocolError, FlowableServerError
from flowable_mcp.models.history import HistoricActivityInstance

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"
_PATH = "/history/historic-activity-instances"
_URL = f"{_BASE}{_PATH}"

_ITEM = {"id": "act-1", "activityId": "a1", "activityType": "userTask"}


# ---------------------------------------------------------------------------
# _flowable_iso8601 helper
# ---------------------------------------------------------------------------


# TC-U-123: UTC aware datetime → "Z" suffix, ms precision (no microseconds, no +00:00)
def test_flowable_iso8601_when_utc_datetime_then_z_suffix_and_millis():
    dt = datetime.datetime(2026, 5, 3, 12, 34, 56, 789123, tzinfo=datetime.UTC)
    result = _flowable_iso8601(dt)
    assert result == "2026-05-03T12:34:56.789Z"
    assert result.endswith("Z")
    assert "+00:00" not in result


# TC-U-124: Non-UTC aware datetime → converted to UTC first
def test_flowable_iso8601_when_non_utc_datetime_then_converted_to_utc():
    tz_plus2 = datetime.timezone(datetime.timedelta(hours=2))
    dt = datetime.datetime(2026, 5, 3, 14, 0, 0, 0, tzinfo=tz_plus2)
    result = _flowable_iso8601(dt)
    assert result == "2026-05-03T12:00:00.000Z"


# TC-U-125 (bonus): Naive datetime → treated as already UTC (no tzinfo removal side-effects)
def test_flowable_iso8601_when_naive_datetime_then_no_error_and_z_suffix():
    dt = datetime.datetime(2026, 1, 15, 8, 0, 0, 500000)
    result = _flowable_iso8601(dt)
    assert result.endswith("Z")
    assert "500" in result  # microsecond 500000 → 500ms


# ---------------------------------------------------------------------------
# _parse_list
# ---------------------------------------------------------------------------


# TC-U-107: Non-dict root → FlowableProtocolError
async def test_parse_list_when_root_is_list_then_protocol_error(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableProtocolError, match="expected JSON object"):
        flowable_client._parse_list([], HistoricActivityInstance)


# TC-U-108: Missing "data" key → FlowableProtocolError
async def test_parse_list_when_missing_data_key_then_protocol_error(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableProtocolError, match="'data' key"):
        flowable_client._parse_list({"total": 0}, HistoricActivityInstance)


# TC-U-109: "data" is null → FlowableProtocolError
async def test_parse_list_when_data_is_null_then_protocol_error(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableProtocolError, match="null"):
        flowable_client._parse_list({"data": None, "total": 0}, HistoricActivityInstance)


# TC-U-110: "data" is not a list (is a dict) → FlowableProtocolError
async def test_parse_list_when_data_is_dict_then_protocol_error(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableProtocolError, match="expected list"):
        flowable_client._parse_list({"data": {}, "total": 0}, HistoricActivityInstance)


# ---------------------------------------------------------------------------
# _parse_total
# ---------------------------------------------------------------------------


# TC-U-111: Non-dict root → returns 0
async def test_parse_total_when_root_is_list_then_returns_zero(
    flowable_client: FlowableClient,
) -> None:
    result = flowable_client._parse_total([])
    assert result == 0


# TC-U-112: Missing "total" key → falls back to len(data)
async def test_parse_total_when_total_key_missing_then_falls_back_to_data_length(
    flowable_client: FlowableClient,
) -> None:
    result = flowable_client._parse_total({"data": [_ITEM, _ITEM]})
    assert result == 2


# TC-U-113: "total" is a string → falls back to len(data)
async def test_parse_total_when_total_is_string_then_falls_back_to_data_length(
    flowable_client: FlowableClient,
) -> None:
    result = flowable_client._parse_total({"data": [_ITEM], "total": "not-an-int"})
    assert result == 1


# ---------------------------------------------------------------------------
# _paginate
# ---------------------------------------------------------------------------


# TC-U-068: Single page (total == len(page)) → (items, False)
async def test_paginate_when_single_page_then_returns_items_and_not_truncated(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ITEM], "total": 1})
    )
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}
    )
    assert len(items) == 1
    assert truncated is False


# TC-U-069: Multi-page (total=150, page_size=100) → all 150 items fetched
async def test_paginate_when_multi_page_then_all_items_fetched(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page1 = [_ITEM] * 100
    page2 = [_ITEM] * 50
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        params = dict(request.url.params)
        start = int(params.get("start", "0"))
        if start == 0:
            call_count += 1
            return httpx.Response(200, json={"data": page1, "total": 150})
        else:
            call_count += 1
            return httpx.Response(200, json={"data": page2, "total": 150})

    respx_mock.get(_URL).mock(side_effect=_handler)
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}, page_size=100
    )
    assert len(items) == 150
    assert truncated is False
    assert call_count == 2


# TC-U-070: max_items cap reached → (items, True) with warning
async def test_paginate_when_max_items_cap_reached_then_truncated_true(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page = [_ITEM] * 10
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": page, "total": 1000})
    )
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}, max_items=10, page_size=10
    )
    assert len(items) == 10
    assert truncated is True


# TC-U-071: Empty first page → ([], False)
async def test_paginate_when_empty_response_then_returns_empty_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}
    )
    assert items == []
    assert truncated is False


# TC-U-072: CancelledError during page fetch → re-raised (not swallowed)
async def test_paginate_when_cancelled_error_during_fetch_then_reraises(
    flowable_client: FlowableClient, respx_mock
) -> None:
    from tests.unit.conftest import raise_cancelled

    respx_mock.get(_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client._paginate("GET", _PATH, HistoricActivityInstance, params={})


# TC-U-073: Connection error during page → FlowableConnectionError re-raised immediately
async def test_paginate_when_connection_error_then_reraises(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client._paginate("GET", _PATH, HistoricActivityInstance, params={})


# TC-U-114: Protocol error during page fetch → FlowableProtocolError raised (no partial result)
async def test_paginate_when_protocol_error_on_second_page_then_raises_not_partial(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page1 = [_ITEM] * 5
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"data": page1, "total": 10})
        return httpx.Response(200, json={"not_data": "oops", "total": 10})

    respx_mock.get(_URL).mock(side_effect=_handler)
    with pytest.raises(FlowableProtocolError):
        await flowable_client._paginate(
            "GET", _PATH, HistoricActivityInstance, params={}, page_size=5
        )


# TC-U-115: Exact boundary — total=200, page_size=100, max_items=200 → (200 items, False)
async def test_paginate_when_exactly_two_pages_and_max_items_exact_then_not_truncated(
    flowable_client: FlowableClient, respx_mock
) -> None:
    page1 = [_ITEM] * 100
    page2 = [_ITEM] * 100

    def _handler(request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        start = int(params.get("start", "0"))
        if start == 0:
            return httpx.Response(200, json={"data": page1, "total": 200})
        return httpx.Response(200, json={"data": page2, "total": 200})

    respx_mock.get(_URL).mock(side_effect=_handler)
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}, max_items=200, page_size=100
    )
    assert len(items) == 200
    assert truncated is False


# TC-INN-03: httpx.TimeoutException on page 2 → FlowableConnectionError; no partial result
async def test_paginate_when_timeout_on_second_page_then_raises_no_partial(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§11.3 P0 — root cause M-01: TimeoutException is a subclass of httpx.TransportError
    and must map to FlowableConnectionError exactly like ConnectError. The atomicity
    invariant (no partial result on any transport failure) must hold for all error types.
    """
    page1 = [_ITEM] * 5
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"data": page1, "total": 10})
        raise httpx.TimeoutException("timeout", request=request)

    respx_mock.get(_URL).mock(side_effect=_handler)
    with pytest.raises(FlowableConnectionError):
        await flowable_client._paginate(
            "GET", _PATH, HistoricActivityInstance, params={}, page_size=5
        )
    assert call_count == 2


# TC-INN-08: total=10_001, max_items=10_000, page_size=100 → truncated=True; 101st GET not fired
async def test_paginate_when_total_exceeds_max_items_by_one_then_truncated_at_cap(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§11.3 P0 — root cause M-02: off-by-one at the boundary between 'fetch all' and
    'truncate'. When total == max_items the loop must stop without requesting an extra page;
    when total == max_items + 1 it must cap at max_items and set truncated=True. This test
    confirms the 101st GET is never issued, protecting the httpx connection pool.
    """
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ITEM] * 100, "total": 10_001})
    )
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}, max_items=10_000, page_size=100
    )
    assert len(items) == 10_000
    assert truncated is True
    assert route.call_count == 100  # page 101 must NOT be requested


# TC-U-070-spec: HTTP 500 on first page → FlowableServerError raised; no partial result (I-02.1)
async def test_paginate_when_http500_on_first_page_then_server_error_no_partial(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§0.1 root cause H-002: spec TC-U-070 requires FlowableServerError for HTTP 5xx.
    CancelledError and ProtocolError were covered; HTTP status error was not.
    I-02.1 invariant: no partial result on ANY error, including server errors.
    """
    respx_mock.get(_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))
    with pytest.raises(FlowableServerError):
        await flowable_client._paginate("GET", _PATH, HistoricActivityInstance, params={})


# TC-U-071-spec: HTTP 500 on second page → FlowableServerError; page 1 items not returned (I-02.1)
async def test_paginate_when_http500_on_second_page_then_server_error_page1_discarded(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§0.1 root cause H-002: partial result MUST NOT be returned on error mid-pagination.
    This test verifies that page-1 data is discarded when page-2 returns HTTP 500.
    """
    page1 = [_ITEM] * 5
    call_count = 0

    def _handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={"data": page1, "total": 10})
        return httpx.Response(500, text="Internal Server Error")

    respx_mock.get(_URL).mock(side_effect=_handler)
    with pytest.raises(FlowableServerError):
        await flowable_client._paginate(
            "GET", _PATH, HistoricActivityInstance, params={}, page_size=5
        )
    assert call_count == 2  # page1 fetched, page2 failed


# TC-U-072-spec: boundary total=10_000 exactly → (10000 items, False); exactly 100 HTTP calls
async def test_paginate_when_total_equals_max_items_then_not_truncated_exact_calls(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§0.1 root cause M-001: the check order `len(items) >= total` before
    `len(items) >= max_items` means equal-total stops cleanly without truncation.
    Without this test a bug using `>` instead of `>=` in either condition could go undetected.
    AC-2-EC2: total == max_items → truncated=False, no 101st request.
    """
    route = respx_mock.get(_URL).mock(
        return_value=httpx.Response(200, json={"data": [_ITEM] * 100, "total": 10_000})
    )
    items, truncated = await flowable_client._paginate(
        "GET", _PATH, HistoricActivityInstance, params={}, max_items=10_000, page_size=100
    )
    assert len(items) == 10_000
    assert truncated is False
    assert route.call_count == 100  # exactly 100 pages, no 101st


# TC-U-078-spec: microsecond=500500 → body["dueDate"] ends with ".500Z" (floor, not round)
def test_flowable_iso8601_when_microsecond_500500_then_floor_to_500ms():
    """§0.1 root cause M-002: _flowable_iso8601 must floor (not round) microseconds to ms.
    500500 us → 500 ms (floor). If implementation used round(), 500500 would become 501 ms.
    AC-3-EC1: millisecond precision required in PUT body for Flowable date format.
    """
    dt = datetime.datetime(2030, 1, 1, 12, 0, 0, 500500, tzinfo=datetime.UTC)
    result = _flowable_iso8601(dt)
    assert result.endswith(".500Z"), f"Expected .500Z suffix, got: {result!r}"
    assert ".500500" not in result
    assert ".501" not in result
