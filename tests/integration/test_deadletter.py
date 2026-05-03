"""Integration tests for deadletter triage (TASK-002 follow-up).

Note: tests that wait for a real failed job to land in deadletter are marked `slow`
because Flowable's async executor retries 3 times with backoff (~30+ seconds total).
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError
from flowable_mcp.models import DeadLetterJob

pytestmark = [pytest.mark.integration]


@pytest.mark.integration
async def test_list_deadletter_jobs_returns_typed_list(
    integration_client: FlowableClient,
) -> None:
    """list_deadletter_jobs returns a list of DeadLetterJob (possibly empty)."""
    jobs = await integration_client.list_deadletter_jobs()
    assert isinstance(jobs, list)
    for j in jobs:
        assert isinstance(j, DeadLetterJob)


@pytest.mark.integration
async def test_retry_deadletter_job_when_unknown_id_then_raises_not_found(
    integration_client: FlowableClient,
) -> None:
    """retry_deadletter_job with non-existent id → FlowableNotFoundError."""
    with pytest.raises(FlowableNotFoundError):
        await integration_client.retry_deadletter_job("non-existent-job-id-xyz")


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.timeout(120)
async def test_failing_service_task_eventually_appears_in_deadletter(
    integration_client: FlowableClient,
    failing_process: str,
) -> None:
    """Slow: start failing process → after retries, job moves to deadletter."""
    pi = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=failing_process
        )
        deadline = 90.0
        elapsed = 0.0
        sleep_step = 1.5
        matching: list[DeadLetterJob] = []
        while elapsed < deadline:
            jobs = await integration_client.list_deadletter_jobs(
                process_definition_key=failing_process
            )
            matching = [j for j in jobs if j.process_instance_id == pi.id]
            if matching:
                break
            await asyncio.sleep(sleep_step)
            elapsed += sleep_step
        else:
            pytest.fail(
                f"No deadletter job appeared for instance {pi.id} within {deadline}s"
            )
        assert matching[0].exception_message
    finally:
        if pi:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(pi.id)
