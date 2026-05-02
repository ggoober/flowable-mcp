"""DeadLetter job DTO."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeadLetterJob(BaseModel):
    """DTO for a Flowable deadletter job."""

    model_config = ConfigDict(frozen=True, populate_by_name=True, extra="ignore")

    id: str
    process_instance_id: str = Field(alias="processInstanceId")
    execution_id: str = Field(alias="executionId")
    process_definition_id: str = Field(alias="processDefinitionId")
    exception_message: str | None = Field(default=None, alias="exceptionMessage")
    retries: int = 0
