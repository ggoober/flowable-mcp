"""Integration tests for list_process_instances, get/set_process_variable (TASK-003, AC-1, AC-2).

Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableNotFoundError
from flowable_mcp.models import ProcessInstance, Variable

pytestmark = [pytest.mark.integration]


# AC-1: list_process_instances returns running instances including the newly started one
@pytest.mark.integration
async def test_list_process_instances_when_instance_running_then_appears_in_list(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-1: A started instance appears in list_process_instances results."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id
    try:
        result = await integration_client.list_process_instances(
            process_definition_key=process_with_user_task, max_results=50
        )
        ids = [r.id for r in result]
        assert instance_id in ids
        assert all(isinstance(r, ProcessInstance) for r in result)
    finally:
        await integration_client.cancel_process_instance(instance_id)


# AC-1: list_process_instances with suspended=False excludes suspended instances
@pytest.mark.integration
async def test_list_process_instances_when_filter_suspended_false_then_active_only(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-1: Filter suspended=False returns only active (non-suspended) instances."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id
    try:
        result = await integration_client.list_process_instances(suspended=False, max_results=50)
        assert all(not r.suspended for r in result)
    finally:
        await integration_client.cancel_process_instance(instance_id)


# AC-2: get_process_variables returns list after instance started with variables
@pytest.mark.integration
async def test_get_process_variables_when_instance_started_with_vars_then_returns_list(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-2: Variables set at start are retrievable via get_process_variables."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task,
        variables={"amount": 99, "approved": True},
    )
    instance_id = pi.id
    try:
        variables = await integration_client.get_process_variables(instance_id)
        assert isinstance(variables, list)
        names = [v.name for v in variables]
        assert "amount" in names
        assert all(isinstance(v, Variable) for v in variables)
    finally:
        await integration_client.cancel_process_instance(instance_id)


# AC-2: set_process_variable updates value; subsequent get reflects new value
@pytest.mark.integration
async def test_set_process_variable_when_set_then_value_retrievable(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-2: set_process_variable persists; get_process_variables includes new value."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    instance_id = pi.id
    try:
        result = await integration_client.set_process_variable(
            instance_id, "status", "approved"
        )
        assert isinstance(result, Variable)
        assert result.name == "status"

        variables = await integration_client.get_process_variables(instance_id)
        names = [v.name for v in variables]
        assert "status" in names
    finally:
        await integration_client.cancel_process_instance(instance_id)


# AC-2: get_process_variables on non-existent instance → FlowableNotFoundError
@pytest.mark.integration
async def test_get_process_variables_when_instance_not_found_then_raises_not_found(
    integration_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableNotFoundError):
        await integration_client.get_process_variables("non-existent-pi-id")
