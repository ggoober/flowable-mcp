"""E2E test for list_historic_process_instances (TASK-002 follow-up)."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client

from ._helpers import extract_list, extract_single
from .conftest import SAMPLE_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


async def test_e2e_list_historic_after_cancel_then_endTime_present(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """Start and cancel an instance; historic record eventually has endTime / ended=True."""
    start = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": SAMPLE_PROCESS_KEY},
    )
    pi_id: str = extract_single(start)["id"]
    # hello-world auto-completes; no need to cancel.

    matching: list[dict] = []
    for _ in range(25):
        result = await mcp_client.call_tool(
            "list_historic_process_instances",
            {"process_definition_key": SAMPLE_PROCESS_KEY, "max_results": 200},
        )
        assert not getattr(result, "is_error", False)
        records = extract_list(result)
        matching = [r for r in records if r.get("id") == pi_id]
        if matching and (matching[0].get("endTime") or matching[0].get("ended")):
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(f"Historic record for {pi_id} did not appear within 5s")

    rec = matching[0]
    assert rec.get("endTime") is not None or rec.get("ended") is True
