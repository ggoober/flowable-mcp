"""Unit tests for domain model behaviour introduced in TASK-003."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from flowable_mcp.models import HistoricTaskInstance, Variable
from flowable_mcp.models.variable import VariableList


# ---------------------------------------------------------------------------
# HistoricTaskInstance
# ---------------------------------------------------------------------------


def test_model_historic_task_instance_when_assignee_empty_string_then_coerces_to_none() -> None:
    item = HistoricTaskInstance.model_validate({"id": "t1", "assignee": ""})
    assert item.assignee is None


def test_model_historic_task_instance_when_assignee_none_then_stays_none() -> None:
    item = HistoricTaskInstance.model_validate({"id": "t1", "assignee": None})
    assert item.assignee is None


def test_model_historic_task_instance_when_assignee_non_empty_then_preserved() -> None:
    item = HistoricTaskInstance.model_validate({"id": "t1", "assignee": "alice"})
    assert item.assignee == "alice"


def test_model_historic_task_instance_when_extra_fields_then_ignored() -> None:
    item = HistoricTaskInstance.model_validate({"id": "t1", "unknownField": "x"})
    assert item.id == "t1"


def test_model_historic_task_instance_when_alias_fields_then_mapped_correctly() -> None:
    item = HistoricTaskInstance.model_validate(
        {
            "id": "t1",
            "taskDefinitionKey": "review",
            "processInstanceId": "pi-001",
            "durationInMillis": 5000,
        }
    )
    assert item.task_definition_key == "review"
    assert item.process_instance_id == "pi-001"
    assert item.duration_in_millis == 5000


def test_model_historic_task_instance_when_id_missing_then_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        HistoricTaskInstance.model_validate({"name": "no-id"})


def test_model_historic_task_instance_when_end_time_absent_then_none() -> None:
    """TC-22: in-progress task has no endTime — end_time defaults to None (INV-TASK3-3)."""
    item = HistoricTaskInstance.model_validate({"id": "t1", "startTime": "2024-01-01T00:00:00+0000"})
    assert item.end_time is None


def test_model_historic_task_instance_when_duration_absent_then_none() -> None:
    """TC-23: in-progress task has no durationInMillis — duration_in_millis defaults to None."""
    item = HistoricTaskInstance.model_validate({"id": "t1"})
    assert item.duration_in_millis is None


# ---------------------------------------------------------------------------
# Variable
# ---------------------------------------------------------------------------


def test_model_variable_when_valid_then_fields_set() -> None:
    v = Variable.model_validate({"name": "x", "value": 1, "type": "integer"})
    assert v.name == "x"
    assert v.value == 1
    assert v.type == "integer"


def test_model_variable_when_scope_provided_then_preserved() -> None:
    v = Variable.model_validate(
        {"name": "x", "value": "hi", "type": "string", "scope": "global"}
    )
    assert v.scope == "global"


def test_model_variable_when_scope_absent_then_none() -> None:
    v = Variable.model_validate({"name": "x", "value": True, "type": "boolean"})
    assert v.scope is None


# ---------------------------------------------------------------------------
# VariableList.from_python_dict — type inference (INV-02, INV-04, §4.3)
# ---------------------------------------------------------------------------


def test_variable_list_from_dict_when_bool_true_then_type_boolean() -> None:
    vl = VariableList.from_python_dict({"flag": True})
    assert vl.root[0].type == "boolean"


def test_variable_list_from_dict_when_bool_false_then_type_boolean_not_integer() -> None:
    vl = VariableList.from_python_dict({"enabled": False})
    # bool IS-A int; must be checked BEFORE int (INV-02)
    assert vl.root[0].type == "boolean"


def test_variable_list_from_dict_when_int_then_type_integer() -> None:
    vl = VariableList.from_python_dict({"count": 42})
    assert vl.root[0].type == "integer"


def test_variable_list_from_dict_when_float_then_type_double() -> None:
    vl = VariableList.from_python_dict({"ratio": 3.14})
    assert vl.root[0].type == "double"


def test_variable_list_from_dict_when_str_then_type_string() -> None:
    vl = VariableList.from_python_dict({"label": "hello"})
    assert vl.root[0].type == "string"


def test_variable_list_from_dict_when_none_then_type_string_value_null() -> None:
    vl = VariableList.from_python_dict({"nullable": None})
    assert vl.root[0].type == "string"
    assert vl.root[0].value is None


def test_variable_list_from_dict_when_unsupported_type_then_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unsupported type"):
        VariableList.from_python_dict({"bad": [1, 2, 3]})


def test_variable_list_from_dict_when_empty_key_then_raises_value_error() -> None:
    with pytest.raises(ValueError):
        VariableList.from_python_dict({"": "value"})


def test_variable_list_from_dict_when_mixed_types_then_all_inferred_correctly() -> None:
    vl = VariableList.from_python_dict(
        {"b": True, "n": 7, "f": 1.5, "s": "hi", "null": None}
    )
    by_name = {v.name: v for v in vl.root}
    assert by_name["b"].type == "boolean"
    assert by_name["n"].type == "integer"
    assert by_name["f"].type == "double"
    assert by_name["s"].type == "string"
    assert by_name["null"].type == "string"
