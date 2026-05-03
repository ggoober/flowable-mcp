"""Historic process instance query tool."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import HistoricProcessInstance, HistoricTaskInstance

_MAX_RESULTS = 500


def register(mcp: FastMCP, client: FlowableClient) -> None:
    """Register historic query tools onto mcp."""

    @mcp.tool()
    async def list_historic_process_instances(
        process_definition_key: str | None = None,
        business_key: str | None = None,
        started_before: datetime | None = None,
        started_after: datetime | None = None,
        finished: bool | None = None,
        max_results: Annotated[int, Field(ge=0, le=_MAX_RESULTS)] = 100,
        ctx: Context | None = None,
    ) -> list[HistoricProcessInstance]:
        """Query historic process instances with filters. max_results hard limit: 500."""
        if max_results > _MAX_RESULTS:
            raise ValueError(f"max_results must be ≤ {_MAX_RESULTS}, got {max_results}")
        return await client.list_historic_process_instances(
            process_definition_key=process_definition_key,
            business_key=business_key,
            started_before=started_before,
            started_after=started_after,
            finished=finished,
            max_results=max_results,
        )

    @mcp.tool()
    async def list_historic_task_instances(
        process_instance_id: str | None = None,
        assignee: str | None = None,
        process_definition_key: str | None = None,
        finished: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        max_results: Annotated[int, Field(ge=1, le=500)] = 100,
        ctx: Context | None = None,
    ) -> list[HistoricTaskInstance]:
        """Query historic task instances with filters. max_results capped at 500."""
        if not (1 <= max_results <= 500):
            raise ValueError(f"max_results must be in [1, 500], got {max_results}")
        return await client.list_historic_task_instances(
            process_instance_id=process_instance_id,
            assignee=assignee,
            process_definition_key=process_definition_key,
            finished=finished,
            started_after=started_after,
            started_before=started_before,
            max_results=max_results,
        )
