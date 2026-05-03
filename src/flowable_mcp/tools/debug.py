"""DeadLetter triage and event subscription tools."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import DeadLetterJob, EventSubscription

_MAX_DEADLETTER = 200


def register(mcp: FastMCP, client: FlowableClient) -> None:
    """Register debug/ops tools onto mcp."""

    @mcp.tool()
    async def list_deadletter_jobs(
        process_definition_key: str | None = None,
        max_results: Annotated[int, Field(ge=0, le=_MAX_DEADLETTER)] = 50,
        ctx: Context | None = None,
    ) -> list[DeadLetterJob]:
        """List deadletter jobs with optional filter. max_results hard limit: 200."""
        if max_results > _MAX_DEADLETTER:
            raise ValueError(f"max_results must be ≤ {_MAX_DEADLETTER}, got {max_results}")
        return await client.list_deadletter_jobs(
            process_definition_key=process_definition_key,
            max_results=max_results,
        )

    @mcp.tool()
    async def retry_deadletter_job(
        job_id: str,
        ctx: Context | None = None,
    ) -> None:
        """Retry a single deadletter job by ID (moves it to execution queue)."""
        await client.retry_deadletter_job(job_id=job_id)

    @mcp.tool()
    async def list_event_subscriptions(
        event_type: str | None = None,
        process_definition_key: str | None = None,
        ctx: Context | None = None,
    ) -> list[EventSubscription]:
        """List active event subscriptions with optional type/key filters.

        If Flowable does not support server-side processDefinitionKey filter,
        an in-tool filter is applied when the result set is ≤ 100 items (S-6 constraint).
        """
        subs = await client.list_event_subscriptions(
            event_type=event_type,
            process_definition_key=process_definition_key,
        )
        # In-tool fallback for processDefinitionKey when Flowable ignores the query param
        if process_definition_key is not None and len(subs) <= 100:
            subs = [
                s for s in subs
                if s.process_definition_id is not None
                and s.process_definition_id.startswith(process_definition_key + ":")
            ]
        return subs
