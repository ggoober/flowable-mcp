"""Process definition tools for Flowable MCP.

Application layer — may import from fastmcp (Context) but not from httpx (shared-standards §1).
Tool functions are registered by server.py via mcp.tool() decorator pattern (DD-1 variant B).
"""

from __future__ import annotations

from fastmcp import Context

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import ProcessDefinition


async def list_process_definitions(
    latest: bool = True,
    key: str | None = None,
    ctx: Context | None = None,
) -> list[ProcessDefinition]:
    """List process definitions from Flowable REST.

    Args:
        latest: Return only the latest version of each definition (default True).
        key: Filter by processDefinitionKey (optional).

    Raises:
        FlowableConnectionError: Flowable unreachable or timeout.
        FlowableAuthError: Basic auth rejected (401/403).
        FlowableServerError: 5xx from Flowable.
        FlowableProtocolError: Malformed response structure.
    """
    client: FlowableClient = ctx.request_context.lifespan_context["client"]  # type: ignore[union-attr]
    return await client.list_process_definitions(latest=latest, key=key)
