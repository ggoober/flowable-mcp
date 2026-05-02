"""Tests for client.py — deployment methods, including _call_multipart paths.

TC-081..TC-082 + CRIT-2a/b/c (TASK-002)
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import (
    FlowableConflictError,
    FlowableConnectionError,
    FlowableValidationError,
)
from flowable_mcp.models import Deployment

_BASE = "http://flowable-test"
_DEPLOY_URL = f"{_BASE}/repository/deployments"

_DEPLOY_PAYLOAD = {
    "id": "dep-1",
    "name": "order.bpmn20.xml",
    "deploymentTime": "2024-01-01T00:00:00.000+0000",
}

_BPMN = b"<definitions/>"


# TC-081
async def test_client_deploy_bpmn_when_201_then_returns_deployment_dto_with_multipart(
    flowable_client: FlowableClient, respx_mock
) -> None:
    route = respx_mock.post(_DEPLOY_URL).mock(
        return_value=httpx.Response(201, json=_DEPLOY_PAYLOAD)
    )
    result = await flowable_client.deploy_bpmn(name="order.bpmn20.xml", bpmn_bytes=_BPMN)
    assert isinstance(result, Deployment)
    assert result.id == "dep-1"
    assert "multipart/form-data" in route.calls[0].request.headers.get("content-type", "")


# TC-082
async def test_client_deploy_bpmn_when_400_then_raises_validation_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_DEPLOY_URL).mock(
        return_value=httpx.Response(400, text="Invalid BPMN XML")
    )
    with pytest.raises(FlowableValidationError):
        await flowable_client.deploy_bpmn(name="bad.bpmn20.xml", bpmn_bytes=b"not-xml")


# CRIT-2a: _call_multipart 409 → ConflictError
async def test_client_deploy_bpmn_when_409_then_raises_conflict_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_DEPLOY_URL).mock(
        return_value=httpx.Response(409, text="duplicate deployment key")
    )
    with pytest.raises(FlowableConflictError):
        await flowable_client.deploy_bpmn(name="dup.bpmn20.xml", bpmn_bytes=_BPMN)


# CRIT-2b: _call_multipart ConnectError → FlowableConnectionError, call_count == 1 (no retry)
async def test_client_deploy_bpmn_when_connect_error_then_raises_connection_error_once(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.post(_DEPLOY_URL).mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(FlowableConnectionError):
        await flowable_client.deploy_bpmn(name="err.bpmn20.xml", bpmn_bytes=_BPMN)
    assert respx_mock.calls.call_count == 1


# CRIT-2c: _call_multipart CancelledError → propagated unchanged
# respx does not support CancelledError as side_effect; patch at the AsyncClient level
async def test_client_deploy_bpmn_when_cancelled_then_propagates_cancelled_error(
    flowable_client: FlowableClient,
) -> None:
    with patch.object(
        flowable_client._no_retry,
        "request",
        new_callable=AsyncMock,
        side_effect=asyncio.CancelledError(),
    ):
        with pytest.raises(asyncio.CancelledError):
            await flowable_client.deploy_bpmn(name="cancel.bpmn20.xml", bpmn_bytes=_BPMN)
