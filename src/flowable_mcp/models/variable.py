"""Variable DTOs for Flowable process/task variables."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, RootModel


class Variable(BaseModel):
    """Single Flowable variable with explicit type tag."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    value: str | int | float | bool | None
    type: str  # "string" | "integer" | "double" | "boolean"


class VariableList(RootModel[list[Variable]]):
    """Ordered list of Variables; root-model for direct JSON serialisation."""

    @classmethod
    def from_python_dict(cls, d: dict[str, Any]) -> VariableList:
        """Convert a plain Python dict to a VariableList with inferred Flowable types.

        bool must be checked before int because bool is a subclass of int (I4, AC-3).
        None → type "string", value null (DD-4).
        Unsupported types (set, object, …) → ValueError before any network call (AC-7).
        """
        items: list[Variable] = []
        for k, v in d.items():
            if not isinstance(k, str) or not k:
                raise ValueError(f"Variable key must be a non-empty string, got {k!r}")
            if isinstance(v, bool):
                type_ = "boolean"
            elif isinstance(v, int):
                type_ = "integer"
            elif isinstance(v, float):
                type_ = "double"
            elif isinstance(v, str):
                type_ = "string"
            elif v is None:
                type_ = "string"
            else:
                raise ValueError(
                    f"Variable {k!r} has unsupported type {type(v).__name__!r}; "
                    "only str, int, float, bool, None are allowed"
                )
            items.append(Variable(name=k, value=v, type=type_))
        return cls(root=items)
