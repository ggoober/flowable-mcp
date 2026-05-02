"""Tests for client.py — process instance methods.

TC-065..TC-073 + MAJ-5 (TASK-002)
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import (
    FlowableConflictError,
    FlowableConnectionError,
    FlowableNotFoundError,
    FlowableValidationError,
)
from flowable_mcp.models import ProcessInstance

_BASE = "http://flowable-test"
_PI_URL = f"{_BASE}/runtime/process-instances"
_PI_ID = "pi-abc-123"
_PI_URL_ID = f"{_PI_URL}/{_PI_ID}"

_PI_PAYLOAD = {
    "id": _PI_ID,
    "processDefinitionId": "pd:1:xyz",
    "processDefinitionKey": "my-proc",
    "businessKey": None,
    "tenantId": None,
    "ended": False,
    "suspended": False,
}


# TC-065
async def test_client_start_process_instance_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_PI_URL).mock(return_value=httpx.Response(409, text="already exists"))
    with pytest.raises(FlowableConflictError):
        await flowable_client.start_process_instance(process_definition_key="my-proc")


# TC-066
async def test_client_start_process_instance_when_400_then_raises_validation_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_PI_URL).mock(return_value=httpx.Response(400, text="invalid input"))
    with pytest.raises(FlowableValidationError):
        await flowable_client.start_process_instance(process_definition_key="my-proc")


# TC-067
async def test_client_start_process_instance_when_variables_bool_and_int_then_body_typed_correctly(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_PI_URL).mock(
        return_value=httpx.Response(201, json=_PI_PAYLOAD)
    )
    await flowable_client.start_process_instance(
        process_definition_key="my-proc",
        variables={"flag": True, "n": 1},
    )
    body = json.loads(route.calls[0].request.content)
    vars_by_name = {v["name"]: v for v in body["variables"]}
    assert vars_by_name["flag"]["type"] == "boolean"
    assert vars_by_name["n"]["type"] == "integer"


# TC-068
async def test_client_start_process_instance_when_business_key_empty_then_absent_from_body(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_PI_URL).mock(
        return_value=httpx.Response(201, json=_PI_PAYLOAD)
    )
    await flowable_client.start_process_instance(
        process_definition_key="my-proc", business_key=""
    )
    body = json.loads(route.calls[0].request.content)
    assert "businessKey" not in body


# TC-069
async def test_client_get_process_instance_when_200_then_returns_dto(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_URL_ID).mock(return_value=httpx.Response(200, json=_PI_PAYLOAD))
    result = await flowable_client.get_process_instance(_PI_ID)
    assert isinstance(result, ProcessInstance)
    assert result.id == _PI_ID


# TC-070
async def test_client_get_process_instance_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_PI_URL_ID).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.get_process_instance(_PI_ID)


# TC-071
async def test_client_cancel_process_instance_when_204_then_returns_none(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_PI_URL_ID).mock(return_value=httpx.Response(204))
    result = await flowable_client.cancel_process_instance(_PI_ID)
    assert result is None


# TC-072
async def test_client_cancel_process_instance_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_PI_URL_ID).mock(
        return_value=httpx.Response(409, text="already ended")
    )
    with pytest.raises(FlowableConflictError):
        await flowable_client.cancel_process_instance(_PI_ID)


# TC-073
async def test_client_cancel_process_instance_when_connect_error_then_raises_connection_error_once(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_PI_URL_ID).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.cancel_process_instance(_PI_ID)
    assert respx_mock.calls.call_count == 1


# MAJ-5: HTTP 200 (not only 201) also returns a valid ProcessInstance
async def test_client_start_process_instance_when_200_then_returns_process_instance(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_PI_URL).mock(return_value=httpx.Response(200, json=_PI_PAYLOAD))
    result = await flowable_client.start_process_instance(process_definition_key="my-proc")
    assert isinstance(result, ProcessInstance)
    assert result.id == _PI_ID


# TC-003
async def test_client_start_process_instance_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_PI_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.start_process_instance(process_definition_key="no-such-key")


# TC-009
async def test_client_cancel_process_instance_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_PI_URL_ID).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.cancel_process_instance(_PI_ID)


# TC-005  (POST is non-idempotent → http_no_retry → ConnectError must not be retried)
async def test_client_start_process_instance_when_connect_error_then_raises_connection_error_exactly_once(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_PI_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.start_process_instance(process_definition_key="my-proc")
    assert respx_mock.calls.call_count == 1


# CancelledError propagates (respx can't raise it — patch AsyncClient.request directly)
async def test_client_start_process_instance_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient,
) -> None:
    with patch.object(
        flowable_client._no_retry,
        "request",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError(),
    ):
        with pytest.raises(asyncio.CancelledError):
            await flowable_client.start_process_instance(process_definition_key="my-proc")
