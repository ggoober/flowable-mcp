"""E2E roundtrip tests for process instance and task tools.

TC-056  start_process_instance  MCP roundtrip
TC-057  cancel_process_instance MCP roundtrip
TC-058  claim_task + complete_task MCP roundtrip
"""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from .conftest import USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


def _extract_single(result) -> dict:
    """Extract a single object from a CallToolResult."""
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return dict(structured["result"])
    if isinstance(structured, dict):
        return structured

    data = getattr(result, "data", None)
    if data is not None and hasattr(data, "model_dump"):
        return data.model_dump(by_alias=True)
    if isinstance(data, dict):
        return data

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError(f"Could not extract single object from result: {result!r}")


def _extract_list(result) -> list[dict]:
    """Extract a list of objects from a CallToolResult."""
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return list(structured["result"])
    if isinstance(structured, list):
        return structured

    data = getattr(result, "data", None)
    if isinstance(data, list):
        return [
            item.model_dump(by_alias=True) if hasattr(item, "model_dump") else item
            for item in data
        ]

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "result" in parsed:
                return list(parsed["result"])
    raise AssertionError(f"Could not extract list from result: {result!r}")


# ---------------------------------------------------------------------------
# TC-056 — start_process_instance MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_start_process_instance_when_deployed_then_returns_process_instance(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    """TC-056: start_process_instance returns a valid ProcessInstance over MCP."""
    result = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    assert not getattr(result, "is_error", False), (
        f"start_process_instance must not return isError; got {result!r}"
    )
    instance = _extract_single(result)
    assert instance.get("id"), f"ProcessInstance must have non-empty id: {instance}"
    key_field = instance.get("processDefinitionKey") or instance.get("process_definition_key")
    assert key_field == USER_TASK_PROCESS_KEY, (
        f"processDefinitionKey must be '{USER_TASK_PROCESS_KEY}', got {key_field}"
    )

    # cleanup: cancel the started instance to leave Flowable in clean state
    pi_id: str = instance["id"]
    await mcp_client.call_tool("cancel_process_instance", {"process_instance_id": pi_id})


# ---------------------------------------------------------------------------
# TC-057 — cancel_process_instance MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_cancel_process_instance_when_running_then_returns_none(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    """TC-057: cancel_process_instance on a running instance returns no error over MCP."""
    # Start a user-task process — it stays in "running" state waiting for a user task.
    start_result = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    assert not getattr(start_result, "is_error", False), (
        f"Pre-condition: start must succeed; got {start_result!r}"
    )
    pi_id: str = _extract_single(start_result)["id"]

    cancel_result = await mcp_client.call_tool(
        "cancel_process_instance", {"process_instance_id": pi_id}
    )
    assert not getattr(cancel_result, "is_error", False), (
        f"cancel_process_instance must not return isError; got {cancel_result!r}"
    )


# ---------------------------------------------------------------------------
# TC-058 — claim_task + complete_task MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_claim_and_complete_task_when_user_task_process_running_then_succeeds(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    """TC-058: start user-task process → list_tasks → claim → complete task."""
    # Start the user-task process to create a pending task.
    start_result = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    assert not getattr(start_result, "is_error", False), (
        f"Pre-condition: start must succeed; got {start_result!r}"
    )
    pi_id: str = _extract_single(start_result)["id"]

    # List tasks for this process instance.
    list_result = await mcp_client.call_tool(
        "list_tasks", {"process_instance_id": pi_id}
    )
    assert not getattr(list_result, "is_error", False), (
        f"list_tasks must not return isError; got {list_result!r}"
    )
    tasks = _extract_list(list_result)
    assert tasks, f"Expected at least one task for process instance {pi_id}"
    task_id: str = tasks[0].get("id") or tasks[0].get("taskId", "")
    assert task_id, f"Task must have non-empty id: {tasks[0]}"

    # Claim the task.
    claim_result = await mcp_client.call_tool(
        "claim_task", {"task_id": task_id, "assignee": "e2e-user"}
    )
    assert not getattr(claim_result, "is_error", False), (
        f"claim_task must not return isError; got {claim_result!r}"
    )

    # Complete the task.
    complete_result = await mcp_client.call_tool(
        "complete_task", {"task_id": task_id}
    )
    assert not getattr(complete_result, "is_error", False), (
        f"complete_task must not return isError; got {complete_result!r}"
    )
