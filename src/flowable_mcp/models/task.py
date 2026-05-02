"""User task DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Task(BaseModel):
    """DTO for a Flowable user task."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    name: str | None = None
    assignee: str | None = None

    @field_validator("assignee", mode="before")
    @classmethod
    def _normalise_assignee(cls, v: object) -> object:
        return None if v == "" else v
    owner: str | None = None
    process_instance_id: str = Field(alias="processInstanceId")
    task_definition_key: str | None = Field(default=None, alias="taskDefinitionKey")
    due_date: datetime | None = Field(default=None, alias="dueDate")
    priority: int = 50
    suspended: bool = False
    created: datetime | None = Field(default=None, alias="createTime")
