"""E2E tests for deadletter triage tools (TASK-002 follow-up)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from ._helpers import extract_list

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


async def test_e2e_list_deadletter_jobs_returns_list_dto(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("list_deadletter_jobs", {})
    assert not getattr(result, "is_error", False)
    jobs = extract_list(result)
    assert isinstance(jobs, list)


async def test_e2e_retry_deadletter_job_when_unknown_id_then_is_error(
    mcp_client: Client,
) -> None:
    """Unknown job_id surfaces as ToolError (FlowableNotFoundError mapped through MCP)."""
    from fastmcp.exceptions import ToolError

    with pytest.raises(ToolError):
        await mcp_client.call_tool(
            "retry_deadletter_job", {"job_id": "non-existent-job-xyz"}
        )
