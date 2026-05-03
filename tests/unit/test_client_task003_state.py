"""Unit tests for FlowableClient.set_process_definition_state /
set_process_instance_state (TASK-003, TC-42..TC-56).
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import (
    FlowableConflictError,
    FlowableNotFoundError,
    FlowableServerError,
)
from flowable_mcp.models import ProcessDefinition, ProcessInstance
from tests.unit.conftest import raise_cancelled

_BASE = "http://flowable-test"
_DEF_ID = "order-proc:1:def001"
_INST_ID = "pi-state-001"
_DEF_URL = f"{_BASE}/repository/process-definitions/{_DEF_ID}"
_INST_URL = f"{_BASE}/runtime/process-instances/{_INST_ID}"

_PD_SUSPENDED = {
    "id": _DEF_ID,
    "key": "order-proc",
    "version": 1,
    "deploymentId": "dep-001",
    "suspended": True,
}
_PD_ACTIVE = {**_PD_SUSPENDED, "suspended": False}

_PI_SUSPENDED = {
    "id": _INST_ID,
    "processDefinitionId": "order-proc:1:def001",
    "processDefinitionKey": "order-proc",
    "businessKey": None,
    "tenantId": None,
    "ended": False,
    "suspended": True,
}
_PI_ACTIVE = {**_PI_SUSPENDED, "suspended": False}


# ---------------------------------------------------------------------------
# set_process_definition_state
# ---------------------------------------------------------------------------


# TC-42: suspend → 200 → ProcessDefinition with suspended=True
async def test_client_set_process_definition_state_when_suspend_then_returns_suspended_definition(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_SUSPENDED))
    result = await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")
    assert isinstance(result, ProcessDefinition)
    assert result.suspended is True


# TC-43: activate → 200 → ProcessDefinition with suspended=False
async def test_client_set_process_definition_state_when_activate_then_returns_active_definition(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_ACTIVE))
    result = await flowable_client.set_process_definition_state(_DEF_ID, action="activate")
    assert isinstance(result, ProcessDefinition)
    assert result.suspended is False


# TC-44: 409 → FlowableConflictError
async def test_client_set_process_definition_state_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(409, text="already suspended"))
    with pytest.raises(FlowableConflictError):
        await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")


# TC-45: 404 → FlowableNotFoundError
async def test_client_set_process_definition_state_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")


# TC-46: includeProcessInstances=True in request body
async def test_client_set_process_definition_state_when_include_instances_true_then_body_has_flag(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_SUSPENDED))
    await flowable_client.set_process_definition_state(
        _DEF_ID, action="suspend", include_process_instances=True
    )
    body = json.loads(route.calls[0].request.content)
    assert body["includeProcessInstances"] is True


# TC-47: includeProcessInstances=False in request body (default)
async def test_client_set_process_definition_state_when_include_instances_false_then_body_has_false(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_ACTIVE))
    await flowable_client.set_process_definition_state(_DEF_ID, action="activate")
    body = json.loads(route.calls[0].request.content)
    assert body["includeProcessInstances"] is False


# TC-53: action="suspend" is in request body
async def test_client_set_process_definition_state_when_suspend_then_body_action_is_suspend(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_SUSPENDED))
    await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "suspend"


# TC-54: action="activate" is in request body
async def test_client_set_process_definition_state_when_activate_then_body_action_is_activate(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(200, json=_PD_ACTIVE))
    await flowable_client.set_process_definition_state(_DEF_ID, action="activate")
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "activate"


# TC-55: 500 → FlowableServerError
async def test_client_set_process_definition_state_when_500_then_raises_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(return_value=httpx.Response(500, text="internal error"))
    with pytest.raises(FlowableServerError):
        await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")


# TC-48: CancelledError propagates (PUT → _no_retry)
async def test_client_set_process_definition_state_when_cancelled_then_propagates(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_DEF_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.set_process_definition_state(_DEF_ID, action="suspend")


# ---------------------------------------------------------------------------
# set_process_instance_state
# ---------------------------------------------------------------------------


# TC-49: suspend instance → 200 → ProcessInstance with suspended=True
async def test_client_set_process_instance_state_when_suspend_then_returns_suspended_instance(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_INST_URL).mock(return_value=httpx.Response(200, json=_PI_SUSPENDED))
    result = await flowable_client.set_process_instance_state(_INST_ID, action="suspend")
    assert isinstance(result, ProcessInstance)
    assert result.suspended is True


# TC-50: activate instance → 200 → ProcessInstance with suspended=False
async def test_client_set_process_instance_state_when_activate_then_returns_active_instance(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_INST_URL).mock(return_value=httpx.Response(200, json=_PI_ACTIVE))
    result = await flowable_client.set_process_instance_state(_INST_ID, action="activate")
    assert isinstance(result, ProcessInstance)
    assert result.suspended is False


# TC-51: 409 → FlowableConflictError for instance
async def test_client_set_process_instance_state_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_INST_URL).mock(return_value=httpx.Response(409, text="already suspended"))
    with pytest.raises(FlowableConflictError):
        await flowable_client.set_process_instance_state(_INST_ID, action="suspend")


# TC-52: 404 → FlowableNotFoundError for instance
async def test_client_set_process_instance_state_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_INST_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.set_process_instance_state(_INST_ID, action="activate")


# body contains action
async def test_client_set_process_instance_state_when_suspend_then_body_action_is_suspend(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_INST_URL).mock(return_value=httpx.Response(200, json=_PI_SUSPENDED))
    await flowable_client.set_process_instance_state(_INST_ID, action="suspend")
    body = json.loads(route.calls[0].request.content)
    assert body["action"] == "suspend"


# TC-56: CancelledError propagates for instance (PUT → _no_retry)
async def test_client_set_process_instance_state_when_cancelled_then_propagates(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_INST_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.set_process_instance_state(_INST_ID, action="activate")
