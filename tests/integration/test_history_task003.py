"""Integration tests for list_historic_task_instances (TASK-003, AC-3).

Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import HistoricTaskInstance

pytestmark = [pytest.mark.integration]


async def _wait_for_finished_task(
    client: FlowableClient, task_id: str, *, timeout_s: float = 15.0
) -> HistoricTaskInstance:
    """Poll history until the given task_id appears as finished. Fail after timeout."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        historic = await client.list_historic_task_instances(
            finished=True, max_results=200
        )
        match = next(
            (h for h in historic if h.id == task_id and h.end_time is not None), None
        )
        if match is not None:
            return match
        await asyncio.sleep(0.2)
    pytest.fail(f"Historic task {task_id!r} not visible as finished within {timeout_s}s")


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


# (10) AC-3: assignee filter scopes to the matching user
@pytest.mark.integration
async def test_list_historic_task_instances_when_filter_assignee_then_only_matching(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    user_a = f"alice-{uuid.uuid4().hex[:6]}"
    user_b = f"bob-{uuid.uuid4().hex[:6]}"

    pi_a = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    pi_b = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks_a = await integration_client.list_tasks(process_instance_id=pi_a.id)
        tasks_b = await integration_client.list_tasks(process_instance_id=pi_b.id)
        assert tasks_a and tasks_b
        await integration_client.claim_task(tasks_a[0].id, assignee=user_a)
        await integration_client.claim_task(tasks_b[0].id, assignee=user_b)
        await integration_client.complete_task(tasks_a[0].id)
        await integration_client.complete_task(tasks_b[0].id)

        await _wait_for_finished_task(integration_client, tasks_a[0].id)
        await _wait_for_finished_task(integration_client, tasks_b[0].id)

        only_a = await integration_client.list_historic_task_instances(
            assignee=user_a, max_results=200
        )
        ids = {h.id for h in only_a}
        assert tasks_a[0].id in ids
        assert tasks_b[0].id not in ids
        assert all(h.assignee == user_a for h in only_a)
    finally:
        for pi_id in (pi_a.id, pi_b.id):
            try:
                await integration_client.cancel_process_instance(pi_id)
            except Exception:
                pass


# (11) AC-3: finished=False returns running tasks; finished=True excludes them
@pytest.mark.integration
async def test_list_historic_task_instances_when_finished_false_then_running_visible(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks
        running_id = tasks[0].id

        running = await integration_client.list_historic_task_instances(
            process_instance_id=pi.id, finished=False, max_results=50
        )
        finished = await integration_client.list_historic_task_instances(
            process_instance_id=pi.id, finished=True, max_results=50
        )
        assert running_id in {h.id for h in running}
        assert running_id not in {h.id for h in finished}
        assert all(h.end_time is None for h in running)
    finally:
        await integration_client.cancel_process_instance(pi.id)


# (12) AC-3: started_after / started_before time-range filters
@pytest.mark.integration
async def test_list_historic_task_instances_when_time_range_then_filters_by_start(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    boundary = datetime.now(timezone.utc)
    await asyncio.sleep(1.1)  # ensure later instance is strictly after `boundary`

    pi_after = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks_after = await integration_client.list_tasks(process_instance_id=pi_after.id)
        assert tasks_after
        task_after_id = tasks_after[0].id

        # Tasks started AFTER the boundary must include our newly started one.
        result_after = await integration_client.list_historic_task_instances(
            process_instance_id=pi_after.id,
            started_after=boundary,
            max_results=50,
        )
        assert task_after_id in {h.id for h in result_after}

        # Tasks started BEFORE the boundary must NOT include it.
        result_before = await integration_client.list_historic_task_instances(
            process_instance_id=pi_after.id,
            started_before=boundary,
            max_results=50,
        )
        assert task_after_id not in {h.id for h in result_before}
    finally:
        await integration_client.cancel_process_instance(pi_after.id)


# (13) AC-3: max_results clamps the page size
@pytest.mark.integration
async def test_list_historic_task_instances_when_max_results_set_then_caps_page(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    started = []
    try:
        for _ in range(3):
            pi = await integration_client.start_process_instance(
                process_definition_key=process_with_user_task
            )
            started.append(pi.id)

        result = await integration_client.list_historic_task_instances(
            process_definition_key=process_with_user_task,
            finished=False,
            max_results=2,
        )
        assert len(result) <= 2
    finally:
        for pid in started:
            await integration_client.cancel_process_instance(pid)
