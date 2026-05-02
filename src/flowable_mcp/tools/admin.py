"""Deployment management tools."""

from __future__ import annotations

import base64
import binascii
import logging

from fastmcp import Context, FastMCP

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import Deployment

_logger = logging.getLogger(__name__)

_BPMN_SIZE_LIMIT = 5 * 1024 * 1024  # 5 MB


def register(mcp: FastMCP, client: FlowableClient) -> None:
    """Register admin/deployment tools onto mcp."""

    @mcp.tool()
    async def list_deployments(
        name_like: str | None = None,
        ctx: Context | None = None,
    ) -> list[Deployment]:
        """List deployments with optional name filter (supports % wildcard)."""
        return await client.list_deployments(name_like=name_like)

    @mcp.tool()
    async def deploy_bpmn(
        name: str,
        bpmn_base64: str,
        ctx: Context | None = None,
    ) -> Deployment:
        """Deploy a BPMN process definition from a base64-encoded XML file.

        name: deployment name (e.g. "order-process.bpmn20.xml").
        bpmn_base64: standard base64-encoded BPMN XML content (≤ 5 MB decoded).
        """
        try:
            bpmn_bytes = base64.b64decode(bpmn_base64, validate=True)
        except binascii.Error as exc:
            _logger.debug("base64 decode failed: %s", exc)
            raise ValueError(f"Invalid base64 content: {exc}") from exc
        if len(bpmn_bytes) > _BPMN_SIZE_LIMIT:
            raise ValueError(
                f"BPMN file exceeds 5 MB limit: {len(bpmn_bytes)} bytes decoded"
            )
        return await client.deploy_bpmn(name=name, bpmn_bytes=bpmn_bytes)
