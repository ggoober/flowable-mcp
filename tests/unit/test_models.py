from __future__ import annotations

from hypothesis import assume, given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from flowable_mcp.models import (
    DeadLetterJob,
    EventSubscription,
    HistoricProcessInstance,
    ProcessDefinition,
    ProcessInstance,
    Task,
)


def test_process_definition_when_camel_case_deployment_id_then_alias_maps_correctly() -> None:
    payload = {
        "id": "pd-1", "key": "proc", "version": 1,
        "deploymentId": "dep-42", "suspended": False,
    }
    pd = ProcessDefinition.model_validate(payload)
    assert pd.deployment_id == "dep-42"


def test_process_definition_when_extra_fields_in_response_then_dto_parses_without_error() -> None:
    payload = {
        "id": "pd-1",
        "key": "proc",
        "version": 1,
        "deploymentId": "dep-1",
        "newField": "v",
        "anotherField": 123,
    }
    pd = ProcessDefinition.model_validate(payload)
    assert pd.id == "pd-1"
    assert "newField" not in pd.model_dump()


def test_process_definition_when_dump_by_alias_then_returns_camel_case_key() -> None:
    payload = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    pd = ProcessDefinition.model_validate(payload)
    dumped = pd.model_dump(by_alias=True)
    assert "deploymentId" in dumped
    assert "deployment_id" not in dumped


def test_process_definition_when_name_is_null_then_field_is_none() -> None:
    payload = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    pd = ProcessDefinition.model_validate(payload)
    assert pd.name is None


def test_process_definition_when_validated_via_v2_api_then_no_validation_error() -> None:
    payload = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    pd = ProcessDefinition.model_validate(payload)
    result = pd.model_dump()
    assert isinstance(result, dict)


def test_process_definition_when_future_extra_field_added_then_dto_does_not_crash() -> None:
    payload = {
        "id": "pd-1",
        "key": "proc",
        "version": 1,
        "deploymentId": "dep-1",
        "futureField": "val",
        "anotherNew": 999,
    }
    pd = ProcessDefinition.model_validate(payload)
    assert pd.id == "pd-1"
    assert "futureField" not in pd.model_dump()


def test_process_definition_when_suspended_field_absent_then_defaults_to_false() -> None:
    payload = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    pd = ProcessDefinition.model_validate(payload)
    assert pd.suspended is False


def test_process_definition_when_name_absent_then_defaults_to_none() -> None:
    payload = {"id": "pd-1", "key": "proc", "version": 1, "deploymentId": "dep-1"}
    pd = ProcessDefinition.model_validate(payload)
    assert pd.name is None


@given(st.text(min_size=1), st.text(min_size=1), st.integers(min_value=1))
@h_settings(max_examples=50)
def test_process_definition_property_alias_roundtrip_idempotent(
    dep_id: str, key: str, version: int
) -> None:
    payload = {"id": "x", "key": key, "version": version, "deploymentId": dep_id}
    pd = ProcessDefinition.model_validate(payload)
    dumped = pd.model_dump(by_alias=True)
    pd2 = ProcessDefinition.model_validate(dumped)
    assert pd == pd2


@given(st.text(min_size=1))
@h_settings(max_examples=50)
def test_process_definition_property_deployment_id_always_populated(dep_id: str) -> None:
    payload = {"id": "x", "key": "k", "version": 1, "deploymentId": dep_id}
    pd = ProcessDefinition.model_validate(payload)
    assert pd.deployment_id == dep_id


@given(st.text(min_size=1), st.integers())
@h_settings(max_examples=50)
def test_process_definition_property_unknown_fields_ignored(
    field_name: str, value: int
) -> None:
    assume(field_name not in {"id", "key", "version", "deploymentId", "name", "suspended"})
    payload = {"id": "x", "key": "k", "version": 1, "deploymentId": "d", field_name: value}
    ProcessDefinition.model_validate(payload)


# ---------------------------------------------------------------------------
# TC-012 — ProcessInstance alias roundtrip
# ---------------------------------------------------------------------------

@given(st.text(min_size=1), st.text(min_size=1), st.text(min_size=1))
@h_settings(max_examples=50)
def test_process_instance_property_alias_roundtrip_idempotent(
    pid: str, pd_id: str, pd_key: str
) -> None:
    payload = {
        "id": pid,
        "processDefinitionId": pd_id,
        "processDefinitionKey": pd_key,
    }
    pi = ProcessInstance.model_validate(payload)
    dumped = pi.model_dump(by_alias=True)
    pi2 = ProcessInstance.model_validate(dumped)
    assert pi == pi2


# ---------------------------------------------------------------------------
# TC-024 — Task alias roundtrip (includes createTime alias fix)
# ---------------------------------------------------------------------------

@given(st.text(min_size=1), st.text(min_size=1))
@h_settings(max_examples=50)
def test_task_property_alias_roundtrip_idempotent(tid: str, pi_id: str) -> None:
    payload = {"id": tid, "processInstanceId": pi_id}
    t = Task.model_validate(payload)
    dumped = t.model_dump(by_alias=True)
    t2 = Task.model_validate(dumped)
    assert t == t2


def test_task_when_create_time_alias_then_maps_to_created_field() -> None:
    payload = {
        "id": "t-1",
        "processInstanceId": "pi-1",
        "createTime": "2024-01-15T10:00:00Z",
    }
    t = Task.model_validate(payload)
    assert t.created is not None
    assert t.created.year == 2024


# ---------------------------------------------------------------------------
# TC-034 — DeadLetterJob alias roundtrip
# ---------------------------------------------------------------------------

@given(st.text(min_size=1), st.text(min_size=1), st.text(min_size=1), st.text(min_size=1))
@h_settings(max_examples=50)
def test_deadletter_job_property_alias_roundtrip_idempotent(
    jid: str, pi_id: str, exec_id: str, pd_id: str
) -> None:
    payload = {
        "id": jid,
        "processInstanceId": pi_id,
        "executionId": exec_id,
        "processDefinitionId": pd_id,
    }
    dlj = DeadLetterJob.model_validate(payload)
    dumped = dlj.model_dump(by_alias=True)
    dlj2 = DeadLetterJob.model_validate(dumped)
    assert dlj == dlj2


# ---------------------------------------------------------------------------
# TC-044 — HistoricProcessInstance alias roundtrip
# ---------------------------------------------------------------------------

@given(st.text(min_size=1), st.text(min_size=1), st.text(min_size=1))
@h_settings(max_examples=50)
def test_historic_process_instance_property_alias_roundtrip_idempotent(
    hid: str, pd_id: str, pd_key: str
) -> None:
    payload = {
        "id": hid,
        "processDefinitionId": pd_id,
        "processDefinitionKey": pd_key,
    }
    hpi = HistoricProcessInstance.model_validate(payload)
    dumped = hpi.model_dump(by_alias=True)
    hpi2 = HistoricProcessInstance.model_validate(dumped)
    assert hpi == hpi2


# ---------------------------------------------------------------------------
# TC-046 — EventSubscription alias roundtrip
# ---------------------------------------------------------------------------

@given(st.text(min_size=1), st.text(min_size=1))
@h_settings(max_examples=50)
def test_event_subscription_property_alias_roundtrip_idempotent(
    eid: str, etype: str
) -> None:
    payload = {"id": eid, "eventType": etype}
    es = EventSubscription.model_validate(payload)
    dumped = es.model_dump(by_alias=True)
    es2 = EventSubscription.model_validate(dumped)
    assert es == es2
