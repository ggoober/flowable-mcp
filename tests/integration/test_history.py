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
    deployed_process: str,
) -> None:
    """TC-096: After cancel, history record appears with ended/deleted flag.

    Flowable writes history asynchronously; poll with timeout instead of fixed sleep.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    instance_id = pi.id
    await integration_client.cancel_process_instance(instance_id)

    matching: list[HistoricProcessInstance] = []
    for _ in range(25):
        historic = await integration_client.list_historic_process_instances(
            process_definition_key=deployed_process
        )
        matching = [h for h in historic if h.id == instance_id]
        if matching and (matching[0].deleted or matching[0].ended):
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(
            f"Historic record for instance {instance_id!r} not found or "
            "not ended within 5 seconds of cancel"
        )

    record = matching[0]
    assert record.deleted is True or record.ended is True
    assert isinstance(record, HistoricProcessInstance)
