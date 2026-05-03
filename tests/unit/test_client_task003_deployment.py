"""Unit tests for FlowableClient.delete_deployment (TASK-003, TC-57..TC-62, TC-40)."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConflictError, FlowableNotFoundError, FlowableServerError
from tests.unit.conftest import raise_cancelled

_BASE = "http://flowable-test"
_DEP_ID = "dep-001"
_DEP_URL = f"{_BASE}/repository/deployments/{_DEP_ID}"


# TC-57: 204 → returns None
async def test_client_delete_deployment_when_204_then_returns_none(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_DEP_URL).mock(return_value=httpx.Response(204))
    result = await flowable_client.delete_deployment(_DEP_ID)
    assert result is None


# TC-58: 404 → FlowableNotFoundError
async def test_client_delete_deployment_when_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_DEP_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.delete_deployment(_DEP_ID)


# TC-59: cascade=True → query param "cascade=true"
async def test_client_delete_deployment_when_cascade_true_then_query_param_is_true(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.delete(_DEP_URL).mock(return_value=httpx.Response(204))
    await flowable_client.delete_deployment(_DEP_ID, cascade=True)
    assert route.calls[0].request.url.params["cascade"] == "true"


# TC-60: cascade=False → query param "cascade=false" (default)
async def test_client_delete_deployment_when_cascade_false_then_query_param_is_false(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.delete(_DEP_URL).mock(return_value=httpx.Response(204))
    await flowable_client.delete_deployment(_DEP_ID, cascade=False)
    assert route.calls[0].request.url.params["cascade"] == "false"


# TC-61: 500 → FlowableServerError
async def test_client_delete_deployment_when_500_then_raises_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_DEP_URL).mock(return_value=httpx.Response(500, text="internal error"))
    with pytest.raises(FlowableServerError):
        await flowable_client.delete_deployment(_DEP_ID)


# TC-40: 409 → FlowableConflictError (active instances without cascade)
async def test_client_delete_deployment_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_DEP_URL).mock(
        return_value=httpx.Response(409, text="deployment has active process instances")
    )
    with pytest.raises(FlowableConflictError):
        await flowable_client.delete_deployment(_DEP_ID)


# TC-62: CancelledError propagates (DELETE → _no_retry)
async def test_client_delete_deployment_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.delete(_DEP_URL).mock(side_effect=raise_cancelled)
    with pytest.raises(asyncio.CancelledError):
        await flowable_client.delete_deployment(_DEP_ID)


# deployment_id with special chars is forwarded as-is (no extra encoding at client layer)
async def test_client_delete_deployment_when_id_with_colon_then_url_contains_id(
    flowable_client: FlowableClient, respx_mock
) -> None:
    dep_id = "dep:v2:abc"
    url = f"{_BASE}/repository/deployments/{dep_id}"
    respx_mock.delete(url).mock(return_value=httpx.Response(204))
    result = await flowable_client.delete_deployment(dep_id)
    assert result is None
