"""Event subscription DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class EventSubscription(BaseModel):
    """DTO for a Flowable runtime event subscription."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    event_type: str = Field(alias="eventType")
    event_name: str | None = Field(default=None, alias="eventName")
    activity_id: str | None = Field(default=None, alias="activityId")
    process_instance_id: str | None = Field(default=None, alias="processInstanceId")
    process_definition_id: str | None = Field(default=None, alias="processDefinitionId")
    created: datetime | None = None
