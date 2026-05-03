"""Integration tests for list_historic_task_instances (TASK-003, AC-3).

Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import asyncio

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import HistoricTaskInstance

pytestmark = [pytest.mark.integration]


# AC-3: list_historic_task_instances returns task history after completing a user task
@pytest.mark.integration
async def test_list_historic_task_instances_when_task_completed_then_appears_in_history(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-3: Completed task appears in list_historic_task_instances with end_time set."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id

    tasks = await integration_client.list_tasks(process_instance_id=instance_id)
    assert tasks, "Expected at least one user task on process_with_user_task"
    task_id = tasks[0].id

    await integration_client.complete_task(task_id)

    matching: list[HistoricTaskInstance] = []
    for _ in range(75):
        historic = await integration_client.list_historic_task_instances(
            process_instance_id=instance_id, finished=True, max_results=50
        )
        matching = [h for h in historic if h.id == task_id]
        if matching and matching[0].end_time is not None:
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(
            f"Historic task record {task_id!r} not found in finished tasks within 15s"
        )

    record = matching[0]
    assert isinstance(record, HistoricTaskInstance)
    assert record.end_time is not None
    assert record.process_instance_id == instance_id


# AC-3: filter by process_instance_id returns only tasks for that instance
@pytest.mark.integration
async def test_list_historic_task_instances_when_filtered_by_instance_id_then_only_that_instance(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-3: process_instance_id filter scopes results to that instance."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id
    try:
        result = await integration_client.list_historic_task_instances(
            process_instance_id=instance_id, max_results=50
        )
        assert isinstance(result, list)
        for item in result:
            assert item.process_instance_id == instance_id
    finally:
        await integration_client.cancel_process_instance(instance_id)
