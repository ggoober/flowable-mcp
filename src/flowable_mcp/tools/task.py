"""User task lifecycle tools.

Application layer: imports fastmcp but NOT httpx (shared-standards §1).
"""

from __future__ import annotations

import logging
import datetime as _dt
from datetime import datetime
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import Task

_logger = logging.getLogger(__name__)

_MAX_RESULTS = 200


def register(mcp: FastMCP, client: FlowableClient) -> None:
    """Register all task tools onto mcp."""

    @mcp.tool()
    async def list_tasks(
        process_instance_id: str | None = None,
        assignee: str | None = None,
        candidate_group: str | None = None,
        max_results: Annotated[int, Field(ge=0, le=_MAX_RESULTS)] = 20,
        ctx: Context | None = None,
    ) -> list[Task]:
        """List user tasks with optional filters. max_results hard limit: 200."""
        if max_results > _MAX_RESULTS:
            raise ValueError(f"max_results must be ≤ {_MAX_RESULTS}, got {max_results}")
        return await client.list_tasks(
            process_instance_id=process_instance_id,
            assignee=assignee,
            candidate_group=candidate_group,
            max_results=max_results,
        )

    @mcp.tool()
    async def claim_task(
        task_id: str,
        assignee: str,
        ctx: Context | None = None,
    ) -> None:
        """Claim a user task for the given assignee."""
        await client.claim_task(task_id=task_id, assignee=assignee)

    @mcp.tool()
    async def complete_task(
        task_id: str,
        variables: dict[str, Any] | None = None,
        due_date: str | None = None,
        ctx: Context | None = None,
    ) -> None:
        """Complete a user task, optionally providing output variables.

        due_date: ISO-8601 string. If provided and in the past, a warning is logged
        but execution is NOT blocked (AC-5, S-2).
        """
        if due_date is not None:
            try:
                parsed = datetime.fromisoformat(due_date)
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=_dt.UTC)
                if parsed < datetime.now(tz=_dt.UTC):
                    _logger.warning(
                        "Completing task %s that is past its due date %s",
                        task_id,
                        due_date,
                    )
            except ValueError:
                _logger.debug("Invalid due_date format %r, skipping overdue check", due_date)
        await client.complete_task(task_id=task_id, variables=variables)

    @mcp.tool()
    async def delegate_task(
        task_id: str,
        assignee: str,
        ctx: Context | None = None,
    ) -> None:
        """Delegate a user task to another assignee."""
        await client.delegate_task(task_id=task_id, assignee=assignee)

    @mcp.tool()
    async def set_task_due_date(
        task_id: str,
        due_date: datetime,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Set (or update) the due date of a task without touching other fields.

        Uses a minimal PUT body {"dueDate": iso} to avoid overwriting assignee,
        priority, or name via Flowable's full-replace PUT semantics. [AC-5, AC-6]

        Returns {"task_id", "due_date", "warnings"}.
        Raises ValueError if due_date has no timezone info. [AC-7]
        """
        if due_date.tzinfo is None:
            raise ValueError("due_date must be timezone-aware")

        warnings: list[str] = []
        if due_date < datetime.now(tz=_dt.UTC):
            iso = due_date.isoformat()
            _logger.warning("Setting past due_date %s on task %s", iso, task_id)
            warnings.append(f"due_date is in the past: {iso}")

        await client.set_task_due_date(task_id=task_id, due_date=due_date)
        return {"task_id": task_id, "due_date": due_date.isoformat(), "warnings": warnings}
