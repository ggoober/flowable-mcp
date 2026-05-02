"""Historic process instance DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HistoricProcessInstance(BaseModel):
    """DTO for a Flowable historic process instance."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    process_definition_id: str = Field(alias="processDefinitionId")
    process_definition_key: str = Field(alias="processDefinitionKey")
    business_key: str | None = Field(default=None, alias="businessKey")
    start_time: datetime | None = Field(default=None, alias="startTime")
    end_time: datetime | None = Field(default=None, alias="endTime")
    duration_in_millis: int | None = Field(default=None, alias="durationInMillis")
    start_user_id: str | None = Field(default=None, alias="startUserId")
    ended: bool = False
    deleted: bool = False
