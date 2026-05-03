"""Extra integration tests for process instance lifecycle (TASK-002 follow-up)."""

from __future__ import annotations

import contextlib

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError, FlowableValidationError
from flowable_mcp.models import ProcessInstance

pytestmark = [pytest.mark.integration]


@pytest.mark.integration
async def test_start_with_invalid_definition_key_then_raises_validation_error(
    integration_client: FlowableClient,
) -> None:
    """Unknown processDefinitionKey → Flowable returns 400/404; mapped to typed error."""
    with pytest.raises((FlowableValidationError, FlowableNotFoundError)):
        await integration_client.start_process_instance(
            process_definition_key="definitely-does-not-exist-xyz"
        )


@pytest.mark.integration
async def test_get_process_instance_when_unknown_id_then_raises_not_found(
    integration_client: FlowableClient,
) -> None:
    """GET unknown instance id → FlowableNotFoundError."""
    with pytest.raises(FlowableNotFoundError):
        await integration_client.get_process_instance("00000000-0000-0000-0000-000000000000")


@pytest.mark.integration
async def test_get_process_instance_after_start_then_returns_running_state(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """After start, GET returns ProcessInstance with ended=False (still running on user task)."""
    instance_id: str | None = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        instance_id = pi.id
        fetched = await integration_client.get_process_instance(instance_id)
        assert isinstance(fetched, ProcessInstance)
        assert fetched.id == instance_id
        assert fetched.ended is False
        assert fetched.suspended is False
    finally:
        if instance_id:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(instance_id)


@pytest.mark.integration
async def test_cancel_process_instance_when_active_then_get_returns_404(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """After successful cancel, runtime GET returns 404 (instance moved to history).

    Uses process_with_user_task so the instance stays running (waits on user task)
    and cancel meaningfully transitions it from runtime to history.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    await integration_client.cancel_process_instance(pi.id)

    with pytest.raises(FlowableNotFoundError):
        await integration_client.get_process_instance(pi.id)
