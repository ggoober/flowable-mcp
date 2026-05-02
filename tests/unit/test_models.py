from __future__ import annotations

from hypothesis import assume, given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from flowable_mcp.models import ProcessDefinition


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
