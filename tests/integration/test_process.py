"""Integration tests for process instance lifecycle.

TC-098 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import contextlib

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConflictError, FlowableNotFoundError
from flowable_mcp.models import ProcessInstance

pytestmark = [pytest.mark.integration]


# TC-049: cancel idempotency — second cancel raises ConflictError or NotFoundError
@pytest.mark.integration
async def test_cancel_process_instance_twice_then_second_raises_error(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-049: Cancel an instance twice; second attempt must raise Conflict or NotFound.

    Uses process_with_user_task (stays on user task) so the first cancel
    transitions a live runtime instance, not an already-completed one.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    await integration_client.cancel_process_instance(pi.id)

    with pytest.raises((FlowableConflictError, FlowableNotFoundError)):
        await integration_client.cancel_process_instance(pi.id)


# TC-098: start with mixed-type variables → get returns valid DTO
@pytest.mark.integration
async def test_start_with_variables_then_get_returns_valid_dto(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-098: Start instance with bool/int/None variables; get returns matching ProcessInstance.

    Uses process_with_user_task so the runtime GET succeeds (instance still alive
    on the user task; hello-world auto-completes and would 404 immediately).
    """
    instance_id: str | None = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task,
            variables={"approved": True, "amount": 42, "note": None},
        )
        instance_id = pi.id
        assert isinstance(pi, ProcessInstance)
        assert pi.id

        fetched = await integration_client.get_process_instance(instance_id)
        assert fetched.id == instance_id
        assert fetched.process_definition_key == process_with_user_task
    finally:
        if instance_id:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(instance_id)
