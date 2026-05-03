"""Tests for HistoricActivityInstance DTO (TASK-004).

TC-U-049..TC-U-056, TC-U-119..TC-U-122
"""

from __future__ import annotations

import datetime

import pytest
from pydantic import ValidationError

from flowable_mcp.models.history import HistoricActivityInstance

pytestmark = [pytest.mark.unit]

_MINIMAL = {"id": "act-1", "activityId": "a1", "activityType": "userTask"}


# TC-U-049: Minimal valid payload → success, required fields populated + round-trip
def test_hai_when_minimal_valid_payload_then_model_validated():
    """§0.1 root cause M-004: spec requires full round-trip: parse → serialize → compare.
    Without it a breaking alias change could pass parse but silently corrupt serialization.
    """
    hai = HistoricActivityInstance.model_validate(_MINIMAL)
    assert hai.id == "act-1"
    assert hai.activity_id == "a1"
    assert hai.activity_type == "userTask"
    # Round-trip: serialize with by_alias=True must reproduce original payload keys
    dumped = hai.model_dump(by_alias=True, exclude_none=True)
    assert dumped["id"] == "act-1"
    assert dumped["activityId"] == "a1"
    assert dumped["activityType"] == "userTask"
    # Original camelCase keys must be present in the dumped output
    assert set(_MINIMAL.keys()) <= set(dumped.keys()), (
        f"Round-trip keys mismatch: expected {set(_MINIMAL.keys())} ⊆ {set(dumped.keys())}"
    )


# TC-U-050: Missing `id` → ValidationError
def test_hai_when_missing_id_then_validation_error():
    with pytest.raises(ValidationError):
        HistoricActivityInstance.model_validate({"activityId": "a1", "activityType": "userTask"})


# TC-U-051: Missing `activityId` → ValidationError
def test_hai_when_missing_activity_id_then_validation_error():
    with pytest.raises(ValidationError):
        HistoricActivityInstance.model_validate({"id": "act-1", "activityType": "userTask"})


# TC-U-052: Missing `activityType` → ValidationError
def test_hai_when_missing_activity_type_then_validation_error():
    with pytest.raises(ValidationError):
        HistoricActivityInstance.model_validate({"id": "act-1", "activityId": "a1"})


# TC-U-053: Camel-case aliases deserialise correctly
def test_hai_when_camelcase_json_then_aliases_map_to_snake_case():
    payload = {
        "id": "act-2",
        "activityId": "startEvent1",
        "activityType": "startEvent",
        "activityName": "Start",
        "processInstanceId": "pi-1",
        "processDefinitionId": "pd:1:abc",
        "executionId": "ex-1",
        "taskId": "t-1",
        "startTime": "2026-01-01T00:00:00.000Z",
        "endTime": "2026-01-01T00:01:00.000Z",
        "durationInMillis": 60000,
        "tenantId": "tenant-1",
        "calledProcessInstanceId": "cpi-1",
    }
    hai = HistoricActivityInstance.model_validate(payload)
    assert hai.activity_name == "Start"
    assert hai.process_instance_id == "pi-1"
    assert hai.process_definition_id == "pd:1:abc"
    assert hai.execution_id == "ex-1"
    assert hai.task_id == "t-1"
    assert hai.duration_in_millis == 60000
    assert hai.tenant_id == "tenant-1"
    assert hai.called_process_instance_id == "cpi-1"


# TC-U-054: assignee="" → None (field_validator)
def test_hai_when_assignee_empty_string_then_normalised_to_none():
    payload = {**_MINIMAL, "assignee": ""}
    hai = HistoricActivityInstance.model_validate(payload)
    assert hai.assignee is None


# TC-U-055: activity_name has no empty-string normalisation — remains ""
def test_hai_when_activity_name_empty_string_then_kept_as_is():
    payload = {**_MINIMAL, "activityName": ""}
    hai = HistoricActivityInstance.model_validate(payload)
    assert hai.activity_name == ""


# TC-U-056: extra fields silently ignored (extra="ignore")
def test_hai_when_extra_fields_present_then_no_validation_error():
    payload = {**_MINIMAL, "unknownField": "value", "anotherExtra": 42}
    hai = HistoricActivityInstance.model_validate(payload)
    assert hai.id == "act-1"


# TC-U-119: Frozen model — mutation raises AttributeError or ValidationError
def test_hai_when_frozen_then_mutation_raises():
    hai = HistoricActivityInstance.model_validate(_MINIMAL)
    with pytest.raises((ValidationError, AttributeError, TypeError)):
        hai.activity_type = "changed"


# TC-U-120: Optional temporal fields accepted when provided
def test_hai_when_temporal_fields_provided_then_parsed_as_datetime():
    payload = {
        **_MINIMAL,
        "startTime": "2026-03-01T10:00:00.000Z",
        "endTime": "2026-03-01T10:05:00.000Z",
        "durationInMillis": 300000,
    }
    hai = HistoricActivityInstance.model_validate(payload)
    assert isinstance(hai.start_time, datetime.datetime)
    assert isinstance(hai.end_time, datetime.datetime)
    assert hai.duration_in_millis == 300000


# TC-U-121: All optional fields default to None when not provided
def test_hai_when_only_required_fields_then_optionals_are_none():
    hai = HistoricActivityInstance.model_validate(_MINIMAL)
    assert hai.activity_name is None
    assert hai.process_instance_id is None
    assert hai.process_definition_id is None
    assert hai.execution_id is None
    assert hai.task_id is None
    assert hai.assignee is None
    assert hai.start_time is None
    assert hai.end_time is None
    assert hai.duration_in_millis is None
    assert hai.tenant_id is None
    assert hai.called_process_instance_id is None


# TC-U-122: model_dump(by_alias=True) produces camel-case keys
def test_hai_when_dumped_by_alias_then_camelcase_keys():
    payload = {**_MINIMAL, "activityName": "Start", "processInstanceId": "pi-1"}
    hai = HistoricActivityInstance.model_validate(payload)
    dumped = hai.model_dump(by_alias=True)
    assert "activityId" in dumped
    assert "activityType" in dumped
    assert "activityName" in dumped
    assert "processInstanceId" in dumped
    assert "activity_id" not in dumped
