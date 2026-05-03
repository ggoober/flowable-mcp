"""Integration tests for historic process instance query.

TC-096 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import asyncio

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import HistoricProcessInstance

pytestmark = [pytest.mark.integration]


# TC-096: cancel → list_historic shows deleted/ended instance
@pytest.mark.integration
async def test_cancel_then_list_historic_shows_ended_instance(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-096: After cancel, history record appears with ended/deleted flag.

    Flowable writes history asynchronously; poll with timeout instead of fixed sleep.
    Uses process_with_user_task so cancel acts on a live runtime instance.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id
    await integration_client.cancel_process_instance(instance_id)

    matching: list[HistoricProcessInstance] = []
    # Flowable history flush can take several seconds; poll up to ~15s.
    # We do NOT filter by processDefinitionKey because Flowable 8.0 returns it
    # as null in historic JSON — server-side key filter would return 0 hits.
    for _ in range(75):
        historic = await integration_client.list_historic_process_instances(
            max_results=500,
        )
        matching = [h for h in historic if h.id == instance_id]
        if matching and matching[0].end_time is not None:
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(
            f"Historic record for instance {instance_id!r} not found or "
            "missing end_time within 15 seconds of cancel"
        )

    record = matching[0]
    assert record.end_time is not None
    assert isinstance(record, HistoricProcessInstance)
