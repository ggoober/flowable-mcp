"""E2E test for delegate_task (TASK-002 follow-up)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from ._helpers import extract_list, extract_single
from .conftest import USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


async def test_e2e_delegate_task_when_claimed_then_returns_none_and_list_shows_delegate(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    start = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    pi_id: str = extract_single(start)["id"]
    try:
        list_res = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        tasks = extract_list(list_res)
        assert tasks
        task_id = tasks[0].get("id")

        claim = await mcp_client.call_tool(
            "claim_task", {"task_id": task_id, "assignee": "alice"}
        )
        assert not getattr(claim, "is_error", False)

        delegate = await mcp_client.call_tool(
            "delegate_task", {"task_id": task_id, "assignee": "bob"}
        )
        assert not getattr(delegate, "is_error", False)

        list_after = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        tasks_after = extract_list(list_after)
        delegated = next(t for t in tasks_after if t.get("id") == task_id)
        assert delegated.get("assignee") == "bob"
        assert delegated.get("owner") == "alice"
    finally:
        await mcp_client.call_tool("cancel_process_instance", {"instance_id": pi_id})
