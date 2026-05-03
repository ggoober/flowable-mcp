"""Integration tests for list_process_instances, get/set_process_variable (TASK-003, AC-1, AC-2).

Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import uuid

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


# ---------------------------------------------------------------------------
# AC-1 expanded coverage
# ---------------------------------------------------------------------------


# (1) AC-1: business_key filter scopes results
@pytest.mark.integration
async def test_list_process_instances_when_filter_business_key_then_only_matching(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    bk_a = f"bk-a-{uuid.uuid4().hex[:8]}"
    bk_b = f"bk-b-{uuid.uuid4().hex[:8]}"
    pi_a = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task, business_key=bk_a
    )
    pi_b = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task, business_key=bk_b
    )
    try:
        result = await integration_client.list_process_instances(
            business_key=bk_a, max_results=50
        )
        ids = {r.id for r in result}
        assert pi_a.id in ids
        assert pi_b.id not in ids
        assert all(r.business_key == bk_a for r in result)
    finally:
        await integration_client.cancel_process_instance(pi_a.id)
        await integration_client.cancel_process_instance(pi_b.id)


# (2) AC-1: involved_user filter — claim a task → instance becomes involved
@pytest.mark.integration
async def test_list_process_instances_when_filter_involved_user_then_only_matching(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    user_a = f"alice-{uuid.uuid4().hex[:6]}"
    user_b = f"bob-{uuid.uuid4().hex[:6]}"
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        assert tasks
        await integration_client.claim_task(tasks[0].id, assignee=user_a)

        matching = await integration_client.list_process_instances(
            involved_user=user_a, max_results=50
        )
        non_matching = await integration_client.list_process_instances(
            involved_user=user_b, max_results=50
        )
        assert pi.id in {r.id for r in matching}
        assert pi.id not in {r.id for r in non_matching}
    finally:
        await integration_client.cancel_process_instance(pi.id)


# (3) AC-1: suspended=True returns only suspended instances
@pytest.mark.integration
async def test_list_process_instances_when_filter_suspended_true_then_suspended_only(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        await integration_client.set_process_instance_state(pi.id, action="suspend")

        suspended_list = await integration_client.list_process_instances(
            suspended=True, max_results=200
        )
        active_list = await integration_client.list_process_instances(
            suspended=False, max_results=200
        )
        suspended_ids = {r.id for r in suspended_list}
        active_ids = {r.id for r in active_list}

        assert pi.id in suspended_ids
        assert pi.id not in active_ids
        assert all(r.suspended for r in suspended_list)
    finally:
        try:
            await integration_client.set_process_instance_state(pi.id, action="activate")
        except Exception:
            pass
        await integration_client.cancel_process_instance(pi.id)


# (4) AC-1: max_results limits page size
@pytest.mark.integration
async def test_list_process_instances_when_max_results_set_then_caps_returned(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    started = []
    for _ in range(3):
        pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        started.append(pi.id)
    try:
        result = await integration_client.list_process_instances(
            process_definition_key=process_with_user_task, max_results=2
        )
        assert len(result) == 2
    finally:
        for pid in started:
            await integration_client.cancel_process_instance(pid)


# (5) AC-1: filter by non-existent definitionKey returns empty list (not 404)
@pytest.mark.integration
async def test_list_process_instances_when_unknown_definition_key_then_empty(
    integration_client: FlowableClient,
) -> None:
    result = await integration_client.list_process_instances(
        process_definition_key=f"nonexistent-{uuid.uuid4().hex[:8]}", max_results=10
    )
    assert result == []


# ---------------------------------------------------------------------------
# AC-2 expanded coverage (variables)
# ---------------------------------------------------------------------------


# (6) AC-2 / INV-02: type-inference matrix — bool checked before int
@pytest.mark.integration
@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (True, "boolean"),
        (False, "boolean"),
        (42, "integer"),
        (3.14, "double"),
        ("text", "string"),
        (None, "string"),
    ],
)
async def test_set_process_variable_type_inference_matrix(
    integration_client: FlowableClient,
    process_with_user_task: str,
    value: object,
    expected_type: str,
) -> None:
    """INV-02: bool MUST be inferred as boolean (not integer) — bool subclasses int."""
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    var_name = f"v_{uuid.uuid4().hex[:8]}"
    try:
        result = await integration_client.set_process_variable(pi.id, var_name, value)
        assert isinstance(result, Variable)
        assert result.type == expected_type

        variables = await integration_client.get_process_variables(pi.id)
        match = next((v for v in variables if v.name == var_name), None)
        assert match is not None
        assert match.type == expected_type
        assert match.value == value
    finally:
        await integration_client.cancel_process_instance(pi.id)


# (7) AC-2: overwrite semantics — second set replaces first
@pytest.mark.integration
async def test_set_process_variable_when_called_twice_then_value_overwritten(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        await integration_client.set_process_variable(pi.id, "x", 1)
        await integration_client.set_process_variable(pi.id, "x", 2)
        variables = await integration_client.get_process_variables(pi.id)
        match = next((v for v in variables if v.name == "x"), None)
        assert match is not None
        assert match.value == 2
    finally:
        await integration_client.cancel_process_instance(pi.id)


# (8) AC-2: set on non-existent instance → FlowableNotFoundError
@pytest.mark.integration
async def test_set_process_variable_when_instance_missing_then_raises(
    integration_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableNotFoundError):
        await integration_client.set_process_variable(
            "non-existent-pi-id", "x", "y"
        )


# (9) AC-2: overwrite of variable seeded at start_process_instance
@pytest.mark.integration
async def test_set_process_variable_when_overwrites_start_var_then_new_value_visible(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task,
        variables={"amount": 10, "note": "initial"},
    )
    try:
        await integration_client.set_process_variable(pi.id, "amount", 99)
        variables = await integration_client.get_process_variables(pi.id)
        amount = next((v for v in variables if v.name == "amount"), None)
        note = next((v for v in variables if v.name == "note"), None)
        assert amount is not None and amount.value == 99
        assert note is not None and note.value == "initial"
    finally:
        await integration_client.cancel_process_instance(pi.id)
