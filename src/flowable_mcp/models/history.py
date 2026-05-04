"""Historic process and activity instance DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class HistoricProcessInstance(BaseModel):
    """DTO for a Flowable historic process instance."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    process_definition_id: str = Field(alias="processDefinitionId")
    # Flowable historic responses may omit processDefinitionKey; derive from id "key:version:uuid".
    process_definition_key: str = Field(default="", alias="processDefinitionKey")
    business_key: str | None = Field(default=None, alias="businessKey")
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    duration_in_millis: int | None = Field(default=None, alias="durationInMillis")
    start_user_id: str | None = Field(default=None, alias="startUserId")
    ended: bool = False
    deleted: bool = False

    @model_validator(mode="after")
    def _fill_definition_key(self) -> "HistoricProcessInstance":
        if not self.process_definition_key and self.process_definition_id:
            head, _, _ = self.process_definition_id.partition(":")
            if head:
                object.__setattr__(self, "process_definition_key", head)
        return self


class HistoricTaskInstance(BaseModel):
    """DTO for a Flowable historic task instance."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    name: str | None = None
    task_definition_key: str | None = Field(default=None, alias="taskDefinitionKey")
    process_instance_id: str | None = Field(default=None, alias="processInstanceId")
    process_definition_id: str | None = Field(default=None, alias="processDefinitionId")
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    duration_in_millis: int | None = Field(default=None, alias="durationInMillis")
    assignee: str | None = Field(default=None)
    delete_reason: str | None = Field(default=None, alias="deleteReason")

    @field_validator("assignee", mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        return None if v == "" else v


class HistoricActivityInstance(BaseModel):
    """DTO for a Flowable historic activity instance."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    activity_id: str = Field(alias="activityId")
    activity_type: str = Field(alias="activityType")
    activity_name: str | None = Field(default=None, alias="activityName")
    process_instance_id: str | None = Field(default=None, alias="processInstanceId")
    process_definition_id: str | None = Field(default=None, alias="processDefinitionId")
    execution_id: str | None = Field(default=None, alias="executionId")
    task_id: str | None = Field(default=None, alias="taskId")
    assignee: str | None = Field(default=None)
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    duration_in_millis: int | None = Field(default=None, alias="durationInMillis")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    called_process_instance_id: str | None = Field(
        default=None, alias="calledProcessInstanceId"
    )

    @field_validator("assignee", mode="before")
    @classmethod
    def _empty_assignee_to_none(cls, v: object) -> object:
        return None if v == "" else v
