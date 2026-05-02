"""Tests for tools/admin.py — tool-layer deploy_bpmn validation guards.

TC-083..TC-084 (TASK-002)
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.admin import register


def _make_admin_tools(unit_settings: Settings) -> tuple[dict, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=httpx.BasicAuth(
            unit_settings.username,
            unit_settings.password.get_secret_value(),
        ),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    mock_mcp = MagicMock()
    registered: dict = {}

    def capture_tool():
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool.side_effect = capture_tool
    register(mock_mcp, client)
    return registered, http


# TC-083: invalid base64 → ValueError before any HTTP call
async def test_tool_deploy_bpmn_when_invalid_base64_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_admin_tools(unit_settings)
    try:
        with pytest.raises(ValueError, match="Invalid base64"):
            await tools["deploy_bpmn"](name="test.bpmn", bpmn_base64="not-valid-base64!!!")
    finally:
        await http.aclose()


# TC-084: decoded bytes > 5MB → ValueError before any HTTP call
async def test_tool_deploy_bpmn_when_bpmn_exceeds_5mb_then_raises_value_error(
    unit_settings: Settings,
) -> None:
    tools, http = _make_admin_tools(unit_settings)
    oversized_b64 = base64.b64encode(b"X" * (5 * 1024 * 1024 + 1)).decode()
    try:
        with pytest.raises(ValueError, match="5 MB limit"):
            await tools["deploy_bpmn"](name="huge.bpmn", bpmn_base64=oversized_b64)
    finally:
        await http.aclose()
