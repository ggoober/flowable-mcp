"""E2E roundtrip tests for TASK-004 tools.

Covers MCP-protocol roundtrips for the 2 tools added / extended in TASK-004:
- list_historic_activity_instances  (TC-E-049)
- set_task_due_date                 (TC-E-050, TC-E-051)

All tests use the in-process ``mcp_client`` fixture (no subprocess) connected
to a live Flowable Docker 8.0.0 on localhost:8080.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from .conftest import USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


# ---------------------------------------------------------------------------
# Helpers  (mirrors test_e2e_task003.py)
# ---------------------------------------------------------------------------


def _extract_single(result) -> dict:
    """Parse an MCP call result into a single dict.

    Tries structured_content → data → content[*].text → AssertionError.
    """
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
    """Parse an MCP call result into a list of dicts.

    Tries structured_content → data → content[*].text → AssertionError.
    """
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


async def _start_instance(mcp_client: Client, **kwargs) -> str:
    """Start a process instance and return its id."""
    payload = {"process_definition_key": USER_TASK_PROCESS_KEY, **kwargs}
    res = await mcp_client.call_tool("start_process_instance", payload)
    assert not getattr(res, "is_error", False), f"start failed: {res!r}"
    return _extract_single(res)["id"]


async def _cancel(mcp_client: Client, instance_id: str) -> None:
    """Best-effort cancellation of a process instance (swallows all errors)."""
    try:
        await mcp_client.call_tool(
            "cancel_process_instance", {"instance_id": instance_id}
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# TC-E-049 — list_historic_activity_instances MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_tc049_list_historic_activity_instances_roundtrip(
    mcp_client: Client,
    e2e_deployed_user_task_process: str,
) -> None:
    """TC-E-049: MCP params marshalling + JSON serialisation verified end-to-end.

    Root cause context (§0.1): this is the only test level where MCP parameter
    marshalling and JSON serialisation of HistoricActivityInstance are exercised
    together. Unit tests mock the client; integration tests skip the MCP layer.
    Only here can a serialisation regression (e.g. camelCase field alias breaking
    the MCP schema) be detected before it reaches production.
    """
    pi_id = await _start_instance(mcp_client)
    try:
        # Complete the user task so the activity shows up as finished.
        list_res = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        tasks = _extract_list(list_res)
        assert tasks, f"No active tasks found for instance {pi_id}"
        task_id = tasks[0]["id"]
        await mcp_client.call_tool("complete_task", {"task_id": task_id})

        # Poll until the historic activity appears (Flowable commits asynchronously).
        found_items: list[dict] = []
        for _ in range(75):
            res = await mcp_client.call_tool(
                "list_historic_activity_instances",
                {
                    "process_instance_id": pi_id,
                    "activity_type": "userTask",
                    "max_results": 50,
                },
            )
            assert not getattr(res, "is_error", False), f"Tool returned error: {res!r}"
            items = _extract_list(res)
            if items:
                found_items = items
                break
            await asyncio.sleep(0.2)

        assert found_items, (
            f"list_historic_activity_instances returned empty list for instance {pi_id} "
            "after waiting ~15 s"
        )
        # Every returned item must carry the filtered activity type.
        for item in found_items:
            act_type = item.get("activityType") or item.get("activity_type")
            # Guard: if the field is present it must match the requested filter.
            if act_type is not None:
                assert act_type == "userTask", (
                    f"Unexpected activityType {act_type!r} in result — filter not applied"
                )
    finally:
        await _cancel(mcp_client, pi_id)


# ---------------------------------------------------------------------------
# TC-E-050 — set_task_due_date happy path MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_tc050_set_task_due_date_happy_path(
    mcp_client: Client,
    e2e_deployed_user_task_process: str,
) -> None:
    """TC-E-050: End-to-end contract {task_id, due_date, warnings} via MCP transport.

    Root cause context (§0.1): the return contract of set_task_due_date must
    survive FastMCP serialisation (datetime → ISO string) and be verifiable by
    the MCP caller. A regression at the serialisation boundary would silently
    break clients even though unit and integration tests pass.
    """
    pi_id = await _start_instance(mcp_client)
    try:
        list_res = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        tasks = _extract_list(list_res)
        assert tasks, f"No active tasks found for instance {pi_id}"
        task_id = tasks[0]["id"]

        res = await mcp_client.call_tool(
            "set_task_due_date",
            {
                "task_id": task_id,
                "due_date": "2099-06-01T12:00:00+00:00",
            },
        )
        assert not getattr(res, "is_error", False), f"Tool returned unexpected error: {res!r}"

        data = _extract_single(res)
        assert data.get("task_id") == task_id, (
            f"task_id mismatch: expected {task_id!r}, got {data.get('task_id')!r}"
        )
        assert "due_date" in data, f"'due_date' key missing from response: {data}"
        assert data.get("warnings") == [], (
            f"Expected empty warnings list, got {data.get('warnings')!r}"
        )
    finally:
        await _cancel(mcp_client, pi_id)


# ---------------------------------------------------------------------------
# TC-E-051 — set_task_due_date naive datetime → structured error
# ---------------------------------------------------------------------------


async def test_e2e_tc051_set_task_due_date_naive_datetime_raises_error(
    mcp_client: Client,
    e2e_deployed_user_task_process: str,
) -> None:
    """TC-E-051: Naive datetime guard (AC-7) works through the MCP layer.

    Root cause context (§0.1): the ValueError raised inside set_task_due_date
    when timezone info is absent must be surfaced as a structured MCP error —
    not a silent success or an unhandled server crash. This test verifies that
    the guard operates at the MCP transport boundary, not only in unit tests.
    After the error the server must remain healthy (subsequent calls succeed).
    """
    pi_id = await _start_instance(mcp_client)
    try:
        list_res = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        tasks = _extract_list(list_res)
        assert tasks, f"No active tasks found for instance {pi_id}"
        task_id = tasks[0]["id"]

        # Naive ISO string — no timezone suffix.
        try:
            result = await mcp_client.call_tool(
                "set_task_due_date",
                {
                    "task_id": task_id,
                    "due_date": "2099-06-01T12:00:00",
                },
            )
            # FastMCP may surface the error as is_error rather than raising.
            assert getattr(result, "is_error", False), (
                "Expected MCP error for naive datetime input, but got success"
            )
        except ToolError as exc:
            # In-process mode may raise ToolError directly.
            error_text = str(exc).lower()
            assert "timezone" in error_text or "timezone-aware" in error_text, (
                f"ToolError raised but did not mention timezone: {exc!r}"
            )

        # Server liveness check: a subsequent valid call must still succeed.
        followup = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        assert not getattr(followup, "is_error", False), (
            "Server became unhealthy after naive-datetime error"
        )
    finally:
        await _cancel(mcp_client, pi_id)
