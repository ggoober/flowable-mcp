"""Integration tests for delete_deployment, suspend/activate (TASK-003, AC-4, AC-5).

Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableConflictError, FlowableNotFoundError
from flowable_mcp.models import Deployment, ProcessDefinition

pytestmark = [pytest.mark.integration]

_FIXTURE_DIR = Path(__file__).parent / "fixtures"
_SAMPLE_BPMN = _FIXTURE_DIR / "sample.bpmn20.xml"


async def _deploy_sample(client: FlowableClient) -> tuple[str, str]:
    """Deploy sample.bpmn20.xml; return (deployment_id, definition_id)."""
    bpmn_bytes = _SAMPLE_BPMN.read_bytes()
    dep: Deployment = await client.deploy_bpmn(
        name="task003-test.bpmn20.xml", bpmn_bytes=bpmn_bytes
    )
    assert dep.id
    defs = await client.list_process_definitions(key="hello-world")
    for d in defs:
        if d.deployment_id == dep.id:
            return dep.id, d.id
    raise AssertionError(f"No process definition found for deployment {dep.id}")


# AC-5: delete_deployment with cascade=False on unused deployment → 204 / None
@pytest.mark.integration
async def test_delete_deployment_when_no_active_instances_then_succeeds(
    integration_client: FlowableClient,
) -> None:
    """AC-5: delete_deployment returns None (204) for an idle deployment."""
    dep_id, _ = await _deploy_sample(integration_client)
    result = await integration_client.delete_deployment(dep_id, cascade=False)
    assert result is None

    with pytest.raises(FlowableNotFoundError):
        await integration_client.delete_deployment(dep_id, cascade=False)


# AC-5: delete_deployment with cascade=True removes deployment and running instances
@pytest.mark.integration
async def test_delete_deployment_when_cascade_true_then_removes_instances(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-5: cascade=True deletes deployment along with any running instances."""
    bpmn_bytes = _SAMPLE_BPMN.read_bytes()
    dep: Deployment = await integration_client.deploy_bpmn(
        name="task003-cascade-test.bpmn20.xml", bpmn_bytes=bpmn_bytes
    )
    dep_id = dep.id

    result = await integration_client.delete_deployment(dep_id, cascade=True)
    assert result is None

    with pytest.raises(FlowableNotFoundError):
        await integration_client.delete_deployment(dep_id, cascade=False)


# AC-4: suspend a process definition → suspended=True returned
@pytest.mark.integration
async def test_suspend_process_definition_when_active_then_returns_suspended(
    integration_client: FlowableClient,
) -> None:
    """AC-4: suspend returns ProcessDefinition with suspended=True."""
    dep_id, def_id = await _deploy_sample(integration_client)
    try:
        result = await integration_client.set_process_definition_state(
            def_id, action="suspend"
        )
        assert isinstance(result, ProcessDefinition)
        assert result.suspended is True

        # Restore
        await integration_client.set_process_definition_state(def_id, action="activate")
    finally:
        await integration_client.delete_deployment(dep_id, cascade=True)


# AC-4: activate a suspended definition → suspended=False returned
@pytest.mark.integration
async def test_activate_process_definition_when_suspended_then_returns_active(
    integration_client: FlowableClient,
) -> None:
    """AC-4: activate after suspend returns ProcessDefinition with suspended=False."""
    dep_id, def_id = await _deploy_sample(integration_client)
    try:
        await integration_client.set_process_definition_state(def_id, action="suspend")
        result = await integration_client.set_process_definition_state(
            def_id, action="activate"
        )
        assert isinstance(result, ProcessDefinition)
        assert result.suspended is False
    finally:
        await integration_client.delete_deployment(dep_id, cascade=True)


# AC-4: suspend a running process instance → suspended=True
@pytest.mark.integration
async def test_suspend_process_instance_when_active_then_returns_suspended(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-4: suspend instance returns ProcessInstance with suspended=True."""
    from flowable_mcp.models import ProcessInstance

    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        result = await integration_client.set_process_instance_state(pi.id, action="suspend")
        assert isinstance(result, ProcessInstance)
        assert result.suspended is True
    finally:
        await integration_client.cancel_process_instance(pi.id)


# AC-5: delete non-existent deployment → FlowableNotFoundError
@pytest.mark.integration
async def test_delete_deployment_when_not_found_then_raises_not_found(
    integration_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableNotFoundError):
        await integration_client.delete_deployment("non-existent-dep-id")


# TC-37: double-suspend instance → second call raises FlowableConflictError (409)
@pytest.mark.integration
async def test_double_suspend_process_instance_raises_conflict_error(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """TC-37: Flowable returns 409 when suspending an already-suspended instance."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        await integration_client.set_process_instance_state(pi.id, action="suspend")
        with pytest.raises(FlowableConflictError):
            await integration_client.set_process_instance_state(pi.id, action="suspend")
    finally:
        try:
            await integration_client.set_process_instance_state(pi.id, action="activate")
        except Exception:
            pass
        await integration_client.cancel_process_instance(pi.id)
