"""Integration tests for task lifecycle tools.

TC-095, TC-099 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConflictError

pytestmark = [pytest.mark.integration]


# TC-053: concurrent claim race → exactly 1 success + 1 ConflictError
@pytest.mark.integration
async def test_claim_task_concurrent_then_exactly_one_success_one_conflict(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-053: Two concurrent claim calls on the same task → 1 succeeds, 1 raises ConflictError."""
    pi = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks, "Process must create at least one user task"
        task_id = tasks[0].id

        results: list[Exception | None] = []

        async def try_claim(assignee: str) -> None:
            try:
                await integration_client.claim_task(task_id=task_id, assignee=assignee)
                results.append(None)
            except FlowableConflictError as exc:
                results.append(exc)

        await asyncio.gather(
            try_claim("user-a"),
            try_claim("user-b"),
        )

        successes = [r for r in results if r is None]
        conflicts = [r for r in results if isinstance(r, FlowableConflictError)]
        assert len(successes) == 1, f"Expected exactly 1 success, got: {results}"
        assert len(conflicts) == 1, f"Expected exactly 1 ConflictError, got: {results}"
    finally:
        if pi:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(pi.id)


# TC-095: list → claim → complete lifecycle
@pytest.mark.integration
async def test_task_lifecycle_list_claim_complete(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-095: Start process with user task; claim the task; complete it; task disappears."""
    instance_id: str | None = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        instance_id = pi.id

        tasks_before = await integration_client.list_tasks(process_instance_id=instance_id)
        assert len(tasks_before) >= 1, "Process must create at least one user task"
        task_id = tasks_before[0].id

        await integration_client.claim_task(task_id=task_id, assignee="integration-test-user")
        await integration_client.complete_task(task_id=task_id)

        tasks_after = await integration_client.list_tasks(process_instance_id=instance_id)
        assert task_id not in [t.id for t in tasks_after]
    finally:
        if instance_id:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(instance_id)


# TC-099: list_tasks with process_instance_id filter returns disjoint sets
@pytest.mark.integration
async def test_list_tasks_with_process_instance_filter_returns_disjoint_sets(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-099: Two separate instances → tasks are disjoint by process_instance_id filter."""
    pi1 = pi2 = None
    try:
        pi1 = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        pi2 = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )

        tasks_pi1 = await integration_client.list_tasks(process_instance_id=pi1.id)
        tasks_pi2 = await integration_client.list_tasks(process_instance_id=pi2.id)

        ids_pi1 = {t.id for t in tasks_pi1}
        ids_pi2 = {t.id for t in tasks_pi2}

        assert ids_pi1.isdisjoint(ids_pi2), (
            f"Task sets for two distinct instances must be disjoint; "
            f"overlap: {ids_pi1 & ids_pi2}"
        )
        for t in tasks_pi1:
            assert t.process_instance_id == pi1.id
    finally:
        for pi in (pi1, pi2):
            if pi:
                with contextlib.suppress(Exception):
                    await integration_client.cancel_process_instance(pi.id)
