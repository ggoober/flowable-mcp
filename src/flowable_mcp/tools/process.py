"""Process definition and instance tools.

Application layer: imports fastmcp (Context) but NOT httpx (shared-standards §1).
register(mcp, client) is called once from server.py lifespan (AC-N3).
"""

from __future__ import annotations

from typing import Any

from fastmcp import Context, FastMCP

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import ProcessDefinition, ProcessInstance


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
