"""Process-related DTOs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProcessDefinition(BaseModel):
    """DTO for a Flowable process definition."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    name: str | None = None
    key: str
    version: int
    deployment_id: str = Field(alias="deploymentId")
    suspended: bool = False


class ProcessInstance(BaseModel):
    """DTO for a Flowable runtime process instance."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    process_definition_id: str = Field(alias="processDefinitionId")
    process_definition_key: str = Field(alias="processDefinitionKey")
    business_key: str | None = Field(default=None, alias="businessKey")
    tenant_id: str | None = Field(default=None, alias="tenantId")
    ended: bool = False
    suspended: bool = False
    start_time: datetime | None = Field(default=None, alias="startTime")
    start_user_id: str | None = Field(default=None, alias="startUserId")
