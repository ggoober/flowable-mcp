"""E2E test for get_process_instance (TASK-002 follow-up)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from ._helpers import extract_single
from .conftest import USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


async def test_e2e_get_process_instance_when_running_then_returns_dto(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    start = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    pi_id: str = extract_single(start)["id"]
    try:
        got = await mcp_client.call_tool(
            "get_process_instance", {"instance_id": pi_id}
        )
        assert not getattr(got, "is_error", False)
        instance = extract_single(got)
        assert instance.get("id") == pi_id
        key = instance.get("processDefinitionKey") or instance.get("process_definition_key")
        assert key == USER_TASK_PROCESS_KEY
        assert instance.get("ended") in (False, None)
    finally:
        await mcp_client.call_tool("cancel_process_instance", {"instance_id": pi_id})
