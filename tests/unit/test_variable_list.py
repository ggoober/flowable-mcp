"""Tests for models/variable.py — VariableList.from_python_dict.

TC-061..TC-064 (TASK-002)
"""

from __future__ import annotations

import pytest

from flowable_mcp.models.variable import VariableList


# TC-061
def test_variable_list_when_bool_and_int_then_bool_type_checked_first() -> None:
    d = {"flag": True, "count": 5}
    result = VariableList.from_python_dict(d)
    items = {item.name: item for item in result.root}
    assert items["flag"].type == "boolean"
    assert items["count"].type == "integer"
    assert items["flag"].value is True


# TC-062
def test_variable_list_when_none_value_then_type_is_string_and_value_is_null() -> None:
    d = {"x": None}
    result = VariableList.from_python_dict(d)
    item = result.root[0]
    assert item.type == "string"
    assert item.value is None


# TC-063
def test_variable_list_when_set_value_then_raises_value_error() -> None:
    d: dict = {"bad": {1, 2}}
    with pytest.raises(ValueError, match="unsupported type"):
        VariableList.from_python_dict(d)


# TC-064
def test_variable_list_when_empty_string_key_then_raises_value_error() -> None:
    d: dict = {"": "value"}
    with pytest.raises(ValueError, match="non-empty string"):
        VariableList.from_python_dict(d)
