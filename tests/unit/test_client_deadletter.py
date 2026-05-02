"""Tests for client.py — deadletter job methods.

TC-085..TC-086, TC-037, TC-039, TC-040 (TASK-002)
"""

from __future__ import annotations

import json

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConnectionError, FlowableNotFoundError, FlowableProtocolError
from flowable_mcp.models import DeadLetterJob

_BASE = "http://flowable-test"
_DLJ_URL = f"{_BASE}/management/deadletter-jobs"
_JOB_ID = "dlj-1"

_DLJ_PAYLOAD = {
    "id": _JOB_ID,
    "processInstanceId": "pi-1",
    "executionId": "exec-1",
    "processDefinitionId": "pd:1",
    "retries": 0,
}


# TC-085
async def test_client_list_deadletter_jobs_when_200_then_returns_dto_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_DLJ_URL).mock(
        return_value=httpx.Response(200, json={"data": [_DLJ_PAYLOAD], "total": 1})
    )
    result = await flowable_client.list_deadletter_jobs()
    assert len(result) == 1
    assert isinstance(result[0], DeadLetterJob)
    assert result[0].process_instance_id == "pi-1"


# TC-086  (action="move" per Flowable 8.0 REST — moves job back to executable queue)
async def test_client_retry_deadletter_job_when_200_then_returns_none_and_body_action_move(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(f"{_DLJ_URL}/{_JOB_ID}").mock(
        return_value=httpx.Response(200)
    )
    result = await flowable_client.retry_deadletter_job(_JOB_ID)
    assert result is None
    body = json.loads(route.calls[0].request.content)
    assert body == {"action": "move"}


# TC-037  (non-existent job → FlowableNotFoundError)
async def test_client_retry_deadletter_job_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(f"{_DLJ_URL}/{_JOB_ID}").mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.retry_deadletter_job(_JOB_ID)


# TC-039  (POST is non-idempotent → http_no_retry → ConnectError must not be retried)
async def test_client_retry_deadletter_job_when_connect_error_then_raises_connection_error_exactly_once(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(f"{_DLJ_URL}/{_JOB_ID}").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.retry_deadletter_job(_JOB_ID)
    assert respx_mock.calls.call_count == 1


# TC-040  (data field null/missing in response → FlowableProtocolError)
async def test_client_list_deadletter_jobs_when_data_missing_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_DLJ_URL).mock(
        return_value=httpx.Response(200, json={"total": 0})
    )
    with pytest.raises(FlowableProtocolError):
        await flowable_client.list_deadletter_jobs()
