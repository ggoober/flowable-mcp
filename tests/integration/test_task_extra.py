"""Extra integration tests for user task lifecycle (TASK-002 follow-up)."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from flowable_mcp.client import FlowableClient

pytestmark = [pytest.mark.integration]


@pytest.mark.integration
async def test_list_tasks_with_assignee_filter_then_only_matching(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """After claim, list_tasks(assignee=...) returns only tasks of that assignee."""
    pi1 = pi2 = None
    try:
        pi1 = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        pi2 = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        tasks_pi1 = await integration_client.list_tasks(process_instance_id=pi1.id)
        assert tasks_pi1
        target_id = tasks_pi1[0].id

        await integration_client.claim_task(task_id=target_id, assignee="filter-test-user")

        listed = await integration_client.list_tasks(assignee="filter-test-user")
        ids = {t.id for t in listed}
        assert target_id in ids, f"Claimed task must appear in assignee filter; got {ids}"
        for t in listed:
            assert t.assignee == "filter-test-user"
    finally:
        for pi in (pi1, pi2):
            if pi:
                with contextlib.suppress(Exception):
                    await integration_client.cancel_process_instance(pi.id)


@pytest.mark.integration
async def test_complete_task_with_variables_then_history_contains_them(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """complete_task with variables → process completes; historic record present."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id

    tasks = await integration_client.list_tasks(process_instance_id=instance_id)
    assert tasks
    task_id = tasks[0].id

    await integration_client.claim_task(task_id=task_id, assignee="completer")
    await integration_client.complete_task(
        task_id=task_id, variables={"approved": True, "score": 7}
    )

    matching: list = []
    for _ in range(25):
        historic = await integration_client.list_historic_process_instances(
            process_definition_key=process_with_user_task
        )
        matching = [h for h in historic if h.id == instance_id]
        if matching and (matching[0].ended or matching[0].end_time is not None):
            break
        await asyncio.sleep(0.2)
    else:
        pytest.fail(
            f"Historic record for completed instance {instance_id!r} did not appear"
        )

    record = matching[0]
    assert record.ended is True or record.end_time is not None


@pytest.mark.integration
async def test_delegate_task_when_assigned_then_owner_becomes_original_assignee(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """After claim+delegate, task.owner=original assignee, task.assignee=delegate."""
    pi = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks
        task_id = tasks[0].id

        await integration_client.claim_task(task_id=task_id, assignee="alice")
        await integration_client.delegate_task(task_id=task_id, assignee="bob")

        listed = await integration_client.list_tasks(process_instance_id=pi.id)
        delegated = next(t for t in listed if t.id == task_id)
        assert delegated.owner == "alice"
        assert delegated.assignee == "bob"
    finally:
        if pi:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(pi.id)
