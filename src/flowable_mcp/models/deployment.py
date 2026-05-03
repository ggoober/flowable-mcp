"""Deployment DTO."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Deployment(BaseModel):
    """DTO for a Flowable deployment."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    name: str
    deployment_time: datetime = Field(alias="deploymentTime")
    tenant_id: str | None = Field(default=None, alias="tenantId")
