"""Process definition and instance tools.

Application layer: imports fastmcp (Context) but NOT httpx (shared-standards §1).
register(mcp, client) is called once from server.py lifespan (AC-N3).
"""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import ProcessDefinition, ProcessInstance, Variable

_logger = logging.getLogger(__name__)


def register(mcp: FastMCP, client: FlowableClient) -> None:
    """Register all process tools onto mcp, closing over client (DI via closure)."""

    @mcp.tool()
    async def list_process_definitions(
        latest: bool = True,
        key: str | None = None,
        ctx: Context | None = None,
    ) -> list[ProcessDefinition]:
        """List process definitions from Flowable."""
        return await client.list_process_definitions(latest=latest, key=key)

    @mcp.tool()
    async def start_process_instance(
        process_definition_key: str | None = None,
        process_definition_id: str | None = None,
        variables: dict[str, Any] | None = None,
        business_key: str | None = None,
        tenant_id: str | None = None,
        ctx: Context | None = None,
    ) -> ProcessInstance:
        """Start a new process instance by definition key OR definition ID (XOR, I1)."""
        has_key = bool(process_definition_key)
        has_id = bool(process_definition_id)
        if has_key == has_id:
            raise ValueError(
                "Exactly one of process_definition_key or process_definition_id must be provided"
            )
        return await client.start_process_instance(
            process_definition_key=process_definition_key,
            process_definition_id=process_definition_id,
            variables=variables,
            business_key=business_key,
            tenant_id=tenant_id,
        )

    @mcp.tool()
    async def get_process_instance(
        instance_id: str,
        ctx: Context | None = None,
    ) -> ProcessInstance:
        """Get a single runtime process instance by ID."""
        return await client.get_process_instance(instance_id)

    @mcp.tool()
    async def cancel_process_instance(
        instance_id: str,
        ctx: Context | None = None,
    ) -> None:
        """Cancel (delete) an active process instance."""
        await client.cancel_process_instance(instance_id)

    @mcp.tool()
    async def list_process_instances(
        process_definition_key: str | None = None,
        business_key: str | None = None,
        suspended: bool | None = None,
        involved_user: str | None = None,
        max_results: Annotated[int, Field(ge=1, le=200)] = 50,
        ctx: Context | None = None,
    ) -> list[ProcessInstance]:
        """List runtime process instances with optional filters. max_results capped at 200."""
        if not (1 <= max_results <= 200):
            raise ValueError(f"max_results must be in [1, 200], got {max_results}")
        return await client.list_process_instances(
            process_definition_key=process_definition_key,
            business_key=business_key,
            suspended=suspended,
            involved_user=involved_user,
            max_results=max_results,
        )

    @mcp.tool()
    async def get_process_variables(
        instance_id: str,
        ctx: Context | None = None,
    ) -> list[Variable]:
        """Get all variables for a runtime process instance."""
        return await client.get_process_variables(instance_id)

    @mcp.tool()
    async def set_process_variable(
        instance_id: str,
        var_name: str,
        value: str | int | float | bool | None,
        var_type: str | None = None,
        ctx: Context | None = None,
    ) -> Variable:
        """Set a single variable on a runtime process instance. var_type inferred if omitted."""
        return await client.set_process_variable(instance_id, var_name, value, var_type)

    @mcp.tool()
    async def suspend_process_definition(
        definition_id: str,
        confirm_cascade: bool = False,
        ctx: Context | None = None,
    ) -> ProcessDefinition:
        """Suspend a process definition, optionally cascading to all running instances."""
        if confirm_cascade:
            _logger.warning(
                "cascade suspend on definition %s — all running instances will be suspended",
                definition_id,
            )
        return await client.set_process_definition_state(
            definition_id,
            action="suspend",
            include_process_instances=confirm_cascade,
        )

    @mcp.tool()
    async def activate_process_definition(
        definition_id: str,
        confirm_cascade: bool = False,
        ctx: Context | None = None,
    ) -> ProcessDefinition:
        """Activate a previously suspended process definition."""
        if confirm_cascade:
            _logger.warning(
                "cascade activate on definition %s — all suspended instances will be activated",
                definition_id,
            )
        return await client.set_process_definition_state(
            definition_id,
            action="activate",
            include_process_instances=confirm_cascade,
        )

    @mcp.tool()
    async def suspend_process_instance(
        instance_id: str,
        ctx: Context | None = None,
    ) -> ProcessInstance:
        """Suspend a single runtime process instance."""
        return await client.set_process_instance_state(instance_id, action="suspend")

    @mcp.tool()
    async def activate_process_instance(
        instance_id: str,
        ctx: Context | None = None,
    ) -> ProcessInstance:
        """Activate a suspended process instance."""
        return await client.set_process_instance_state(instance_id, action="activate")
