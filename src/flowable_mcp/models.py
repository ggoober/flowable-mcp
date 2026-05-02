"""Pydantic v2 domain DTOs.

Domain-only module: no httpx, no fastmcp imports allowed (Invariant I2, СТ-1).
All DTOs use pydantic v2 API only: model_validate / model_dump / model_dump_json (СТ-4).
"""

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
