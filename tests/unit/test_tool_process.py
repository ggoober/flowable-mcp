from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.process import list_process_definitions


# ---------------------------------------------------------------------------
# TC-38 (same as TC-30)
# ---------------------------------------------------------------------------

async def test_tool_list_when_ctx_none_then_raises_attribute_error():
    with pytest.raises(AttributeError):
        await list_process_definitions(ctx=None)


# ---------------------------------------------------------------------------
# TC-31
# ---------------------------------------------------------------------------

async def test_tool_list_when_valid_ctx_then_no_exception(
    unit_settings: Settings,
    respx_mock,
):
    PD_URL = "http://flowable-test/repository/process-definitions"
    respx_mock.get(PD_URL).mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    http = httpx.AsyncClient(
        auth=httpx.BasicAuth(
            unit_settings.username,
            unit_settings.password.get_secret_value(),
        ),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(settings=unit_settings, http=http)

    mock_ctx = MagicMock()
    mock_ctx.request_context.lifespan_context = {"client": client}

    try:
        result = await list_process_definitions(ctx=mock_ctx)
    finally:
        await http.aclose()

    assert isinstance(result, list)
