"""Historic process instance DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
