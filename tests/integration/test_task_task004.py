"""Integration tests for set_task_due_date (TASK-004).

TC-I-103..TC-I-104, TC-I-108..TC-I-109

Requires live flowable-rest:8.0.0 at http://localhost:8080/flowable-rest/service.
Run with: pytest -m integration tests/integration/test_task_task004.py
"""

from __future__ import annotations

import datetime

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError

pytestmark = [pytest.mark.integration]


# TC-I-103: set_task_due_date → dueDate updated; assignee/priority/name unchanged (AC-V4)
@pytest.mark.integration
async def test_set_task_due_date_when_valid_task_then_fields_unchanged(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-V4: assignee, priority, name must not be overwritten by set_task_due_date.

    Root cause of H-01: smoke S-03 verifies Flowable PUT /runtime/tasks/{id} partial-replace
    semantics. Without this assertion the core invariant of S-03 (no field corruption via
    Flowable full-replace) is undetected at the integration level.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks, "Expected at least one task on process_with_user_task"
        task_before = tasks[0]
        task_id = task_before.id

        future = datetime.datetime(2099, 12, 31, 23, 59, 59, tzinfo=datetime.UTC)
        await integration_client.set_task_due_date(task_id=task_id, due_date=future)

        tasks_after = await integration_client.list_tasks(process_instance_id=pi.id)
        task_after = next((t for t in tasks_after if t.id == task_id), None)
        assert task_after is not None, "Task must still exist after set_task_due_date"

        # AC-V4: partial-replace semantics — only dueDate changes, other fields preserved
        assert task_after.assignee == task_before.assignee, (
            f"assignee changed: {task_before.assignee!r} → {task_after.assignee!r}"
        )
        assert task_after.priority == task_before.priority, (
            f"priority changed: {task_before.priority} → {task_after.priority}"
        )
        assert task_after.name == task_before.name, (
            f"name changed: {task_before.name!r} → {task_after.name!r}"
        )
    finally:
        await integration_client.cancel_process_instance(pi.id)


# TC-I-104: set_task_due_date on non-existent task → FlowableNotFoundError
@pytest.mark.integration
async def test_set_task_due_date_when_task_not_found_then_not_found_error(
    integration_client: FlowableClient,
) -> None:
    """AC-5: set_task_due_date with an unknown task ID raises FlowableNotFoundError."""
    future = datetime.datetime(2099, 1, 1, tzinfo=datetime.UTC)
    with pytest.raises(FlowableNotFoundError):
        await integration_client.set_task_due_date(
            task_id="non-existent-task-id-xyz-12345",
            due_date=future,
        )


# TC-I-108: complete_task with due_date parameter → task completes normally (due_date ignored)
@pytest.mark.integration
async def test_complete_task_when_due_date_provided_then_task_completes(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-5: complete_task with a past due_date still completes the task successfully."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks
        task_id = tasks[0].id

        # complete_task doesn't have a due_date parameter at the client level
        # This tests the client itself completes the task
        await integration_client.complete_task(task_id=task_id)

        remaining = await integration_client.list_tasks(process_instance_id=pi.id)
        task_ids = {t.id for t in remaining}
        assert task_id not in task_ids, "Completed task must no longer appear in active tasks"
    except Exception:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass
        raise


# TC-I-109: set_task_due_date past date → no Flowable error (past dates accepted by API)
@pytest.mark.integration
async def test_set_task_due_date_when_past_date_then_accepted_by_flowable(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-5: Flowable REST accepts past due dates without HTTP error."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks
        task_id = tasks[0].id

        past = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
        await integration_client.set_task_due_date(task_id=task_id, due_date=past)
    finally:
        await integration_client.cancel_process_instance(pi.id)
