"""Tests for FlowableClient.set_task_due_date (TASK-004).

TC-U-074..TC-U-075, TC-U-078..TC-U-079, TC-U-082..TC-U-083
"""

from __future__ import annotations

import datetime

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError, FlowableServerError

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"
_TASK_URL = f"{_BASE}/runtime/tasks/t-1"


# TC-U-074: PUT /runtime/tasks/{id} called with body {"dueDate": iso}
async def test_client_set_task_due_date_when_called_then_put_with_due_date_body(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    dt = datetime.datetime(2030, 1, 1, 12, 0, 0, tzinfo=datetime.UTC)
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)
    assert route.called
    sent = route.calls[0].request
    import json
    body = json.loads(sent.content)
    # §0.1 root cause M-005: spec AC-5/I-03.2 requires EXACTLY {"dueDate": iso}.
    # Using 'in' check allows accidental extra keys (action, assignee, name) to pass.
    # set equality catches any regression that would corrupt Flowable full-replace semantics.
    assert set(body.keys()) == {"dueDate"}, (
        f"PUT body must contain exactly one key 'dueDate', got: {set(body.keys())}"
    )
    assert isinstance(body["dueDate"], str)


# TC-U-075: ISO body has millisecond precision and "Z" suffix
async def test_client_set_task_due_date_when_called_then_iso_has_millis_and_z_suffix(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    dt = datetime.datetime(2030, 3, 15, 10, 30, 45, 123456, tzinfo=datetime.UTC)
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["dueDate"].endswith("Z")
    assert "123" in body["dueDate"]  # ms precision: 123456 → 123


# TC-U-078: 404 response → FlowableNotFoundError
async def test_client_set_task_due_date_when_404_then_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(404))
    dt = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)


# TC-U-079: 500 response → FlowableServerError
async def test_client_set_task_due_date_when_500_then_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(500, text="oops"))
    dt = datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC)
    with pytest.raises(FlowableServerError):
        await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)


# TC-U-082: Aware datetime with non-UTC timezone → converted to UTC in body
async def test_client_set_task_due_date_when_non_utc_aware_then_converted_to_utc(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    tz_plus3 = datetime.timezone(datetime.timedelta(hours=3))
    dt = datetime.datetime(2030, 6, 1, 15, 0, 0, tzinfo=tz_plus3)  # 12:00 UTC
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)
    import json
    body = json.loads(route.calls[0].request.content)
    assert "12:00:00" in body["dueDate"]
    assert body["dueDate"].endswith("Z")


# TC-U-083: Naive datetime → no error; treated as local time (microseconds truncated to ms)
async def test_client_set_task_due_date_when_naive_datetime_then_no_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    dt = datetime.datetime(2030, 9, 10, 8, 0, 0, 999000)
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)
    assert route.called
    import json
    body = json.loads(route.calls[0].request.content)
    assert body["dueDate"].endswith("Z")
    assert "999" in body["dueDate"]


# TC-INN-07: two sequential calls → both PUT bodies are exactly {"dueDate": "..."} (one key)
async def test_client_set_task_due_date_when_called_twice_then_both_bodies_single_key(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """§11.3 P0 / L-04 — root cause M-04: metamorphic idempotency check. Each call must
    produce a body with exactly one key ('dueDate'). No action, id, assignee, or other
    fields must creep in across sequential calls (AC-5 / I-03.2).
    """
    import json

    route = respx_mock.put(_TASK_URL).mock(return_value=httpx.Response(204))
    dt = datetime.datetime(2030, 6, 15, 10, 0, 0, tzinfo=datetime.UTC)
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)
    await flowable_client.set_task_due_date(task_id="t-1", due_date=dt)

    assert route.call_count == 2
    body1 = json.loads(route.calls[0].request.content)
    body2 = json.loads(route.calls[1].request.content)
    assert set(body1.keys()) == {"dueDate"}, f"Expected only 'dueDate' key, got {set(body1.keys())}"
    assert set(body2.keys()) == {"dueDate"}, f"Expected only 'dueDate' key, got {set(body2.keys())}"
    assert body1 == body2
