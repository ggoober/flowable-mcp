"""Unit tests for FlowableClient.get_process_variables / set_process_variable
(TASK-003, TC-13..TC-27, INV-02, INV-04).

set_process_variable uses PUT on the plural /variables endpoint with a
single-element JSON-array body (Flowable upsert semantics) — the per-name
endpoint returns 404 if the variable doesn't yet exist.
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
    FlowableProtocolError,
)
from flowable_mcp.models import Variable
from tests.unit.conftest import raise_cancelled

_BASE = "http://flowable-test"
_INSTANCE_ID = "pi-var-001"
_VARS_URL = f"{_BASE}/runtime/process-instances/{_INSTANCE_ID}/variables"

_VAR_PAYLOAD = {"name": "amount", "value": 42, "type": "integer", "scope": "global"}


# ---------------------------------------------------------------------------
# get_process_variables
# ---------------------------------------------------------------------------


# TC-13: 200 + JSON array → list[Variable]
async def test_client_get_process_variables_when_200_with_array_then_returns_list(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_VARS_URL).mock(return_value=httpx.Response(200, json=[_VAR_PAYLOAD]))
    result = await flowable_client.get_process_variables(_INSTANCE_ID)
    assert len(result) == 1
    assert isinstance(result[0], Variable)
    assert result[0].name == "amount"
    assert result[0].value == 42


# TC-14: 200 + empty JSON array → []
async def test_client_get_process_variables_when_200_with_empty_array_then_returns_empty(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_VARS_URL).mock(return_value=httpx.Response(200, json=[]))
    result = await flowable_client.get_process_variables(_INSTANCE_ID)
    assert result == []


# TC-15: response is a JSON object (not array) → FlowableProtocolError (§4.1)
async def test_client_get_process_variables_when_response_is_object_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_VARS_URL).mock(
        return_value=httpx.Response(200, json={"data": [_VAR_PAYLOAD], "total": 1})
    )
    with pytest.raises(FlowableProtocolError, match="expected JSON array"):
        await flowable_client.get_process_variables(_INSTANCE_ID)


# TC-16: 404 → FlowableNotFoundError
async def test_client_get_process_variables_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_VARS_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.get_process_variables(_INSTANCE_ID)


# TC-17: CancelledError propagates (GET → _retry)
async def test_client_get_process_variables_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(_VARS_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.get_process_variables(_INSTANCE_ID)


# ---------------------------------------------------------------------------
# set_process_variable — type inference (§4.3, INV-02, INV-04)
# ---------------------------------------------------------------------------


def _mock_upsert_response(name: str, value, type_: str) -> httpx.Response:
    """Flowable's PUT /variables returns an array of upserted entries."""
    return httpx.Response(200, json=[{"name": name, "value": value, "type": type_}])


# TC-18: bool=True → type="boolean" NOT "integer" (INV-02, INV-04: bool before int)
async def test_client_set_process_variable_when_bool_true_then_type_is_boolean(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("flag", True, "boolean")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "flag", True)
    body = json.loads(route.calls[0].request.content)
    assert isinstance(body, list) and len(body) == 1
    assert body[0]["type"] == "boolean"
    assert body[0]["value"] is True
    assert body[0]["name"] == "flag"


# TC-19: int (non-bool) → type="integer"
async def test_client_set_process_variable_when_int_then_type_is_integer(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("count", 7, "integer")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "count", 7)
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "integer"


# TC-20: float → type="double"
async def test_client_set_process_variable_when_float_then_type_is_double(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("ratio", 3.14, "double")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "ratio", 3.14)
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "double"


# TC-21: str → type="string"
async def test_client_set_process_variable_when_str_then_type_is_string(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("label", "hi", "string")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "label", "hi")
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "string"


# TC-22: None → type="string" (DD-A2)
async def test_client_set_process_variable_when_none_then_type_is_string(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("nullable", None, "string")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "nullable", None)
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "string"
    assert body[0]["value"] is None


# TC-23: var_name with special chars — name carried in body, not URL
async def test_client_set_process_variable_when_special_chars_in_name_then_in_body(
    flowable_client: FlowableClient, respx_mock
) -> None:
    var_name = "order/status"
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response(var_name, "new", "string")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, var_name, "new")
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body[0]["name"] == var_name


# TC-24: 200 response → returns Variable DTO
async def test_client_set_process_variable_when_200_then_returns_variable(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("x", "hello", "string")
    )
    result = await flowable_client.set_process_variable(_INSTANCE_ID, "x", "hello")
    assert isinstance(result, Variable)
    assert result.name == "x"


# TC-25: 404 → FlowableNotFoundError
async def test_client_set_process_variable_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_VARS_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.set_process_variable(_INSTANCE_ID, "x", "v")


# TC-26: 409 → FlowableConflictError
async def test_client_set_process_variable_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_VARS_URL).mock(return_value=httpx.Response(409, text="conflict"))
    with pytest.raises(FlowableConflictError):
        await flowable_client.set_process_variable(_INSTANCE_ID, "x", "v")


# TC-27: explicit var_type overrides auto-inference
async def test_client_set_process_variable_when_explicit_type_then_body_uses_that_type(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("num", "42", "string")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "num", 42, var_type="string")
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "string"


# INV-04: bool False is NOT classified as integer=0
async def test_client_set_process_variable_when_bool_false_then_type_is_boolean_not_integer(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response("enabled", False, "boolean")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, "enabled", False)
    body = json.loads(route.calls[0].request.content)
    assert body[0]["type"] == "boolean"
    assert body[0]["value"] is False


# CancelledError propagates (PUT → _no_retry)
async def test_client_set_process_variable_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.put(_VARS_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.set_process_variable(_INSTANCE_ID, "x", "v")


# Special-name passthrough — name preserved verbatim in body for arbitrary inputs
@pytest.mark.parametrize("var_name", ["my var", "%test%", "unicode-α", "with#hash"])
async def test_client_set_process_variable_name_passthrough(
    var_name: str,
    flowable_client: FlowableClient,
    respx_mock,
) -> None:
    route = respx_mock.put(_VARS_URL).mock(
        return_value=_mock_upsert_response(var_name, "v", "string")
    )
    await flowable_client.set_process_variable(_INSTANCE_ID, var_name, "v")
    assert route.called
    body = json.loads(route.calls[0].request.content)
    assert body[0]["name"] == var_name
