"""E2E test for list_event_subscriptions (TASK-002 follow-up)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from ._helpers import extract_list

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


async def test_e2e_list_event_subscriptions_then_returns_list(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("list_event_subscriptions", {})
    assert not getattr(result, "is_error", False)
    subs = extract_list(result)
    assert isinstance(subs, list)
