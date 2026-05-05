"""BPMN/CMMN diagram visualization tools.

Application layer: imports fastmcp but NOT httpx (shared-standards §1).
register(mcp, client, *, png_semaphore, max_png_bytes) is called
once from server.py lifespan (AC-N3, AC-4.3).
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from fastmcp import Context, FastMCP
from mcp.types import ImageContent

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableDiagramError, FlowableNotFoundError, FlowableProtocolError

_logger = logging.getLogger(__name__)


def validate_png_response(
    body: bytes,
    content_type: str,
    max_bytes: int,
) -> None:
    """Guard chain for PNG responses: strict order, early-exit on first violation.

    (a) len(body) == 0             → FlowableDiagramError("empty body")
    (b) "image/png" not in ct     → FlowableDiagramError("unexpected content-type: {ct}")
    (c) body[:4] != b"\\x89PNG"   → FlowableDiagramError("not a PNG: magic bytes mismatch")
    (d) len(body) > max_bytes     → FlowableDiagramError("PNG exceeds max size: {n} > {max}")

    Empty body short-circuits — steps (b)(c)(d) are NOT executed (AC-S2-4, I-4, I-5).
    Content-Type charset suffix accepted via `in`, not `==` (AC-EDGE-3, I-11).
    Pure function: no httpx/fastmcp imports (СТ-1, AC-4.1).
    """
    if len(body) == 0:
        raise FlowableDiagramError("empty body")
    if "image/png" not in content_type.lower():
        raise FlowableDiagramError(f"unexpected content-type: {content_type}")
    if body[:4] != b"\x89PNG":
        raise FlowableDiagramError("not a PNG: magic bytes mismatch")
    if len(body) > max_bytes:
        raise FlowableDiagramError(f"PNG exceeds max size: {len(body)} > {max_bytes}")


def register(
    mcp: FastMCP,
    client: FlowableClient,
    *,
    png_semaphore: asyncio.Semaphore,
    max_png_bytes: int,
) -> None:
    """Register 9 diagram MCP tools. Semaphore acquired inside each PNG tool (AC-4.3, AC-S2-7).

    diagram_timeout_s is not a parameter here — it lives in FlowableClient._diagram_timeout_s
    and is applied automatically by get_definition_diagram / get_instance_diagram (AC-S3-2).
    """

    # ------------------------------------------------------------------
    # BPMN repository tools (3)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_process_definition_xml(
        process_definition_id: str,
        ctx: Context | None = None,
    ) -> str:
        """Get raw BPMN XML for LLM parsing (mermaid, etc.)."""
        raw = await client.get_definition_resource("process", process_definition_id)
        xml_text = raw.strip()
        if not xml_text:
            raise FlowableProtocolError("empty resourcedata response")
        return xml_text

    @mcp.tool()
    async def get_process_definition_model(
        process_definition_id: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get BpmnModel JSON: flowElements, sequenceFlows, lanes, coordinates."""
        return await client.get_definition_model("process", process_definition_id)

    @mcp.tool()
    async def get_process_definition_diagram(
        process_definition_id: str,
        ctx: Context | None = None,
    ) -> ImageContent:
        """Get server-rendered PNG diagram (base64, mimeType='image/png').

        Returns base64-encoded PNG; large diagrams (>2MB) may produce >2.7MB MCP payload.
        """
        async with png_semaphore:
            body, content_type = await client.get_definition_diagram("process", process_definition_id)
        validate_png_response(body, content_type, max_png_bytes)
        data = base64.b64encode(body).decode()
        return ImageContent(type="image", data=data, mimeType="image/png")

    # ------------------------------------------------------------------
    # CMMN repository tools (3)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_case_definition_xml(
        case_definition_id: str,
        ctx: Context | None = None,
    ) -> str:
        """Get raw CMMN XML."""
        raw = await client.get_definition_resource("case", case_definition_id)
        xml_text = raw.strip()
        if not xml_text:
            raise FlowableProtocolError("empty resourcedata response")
        return xml_text

    @mcp.tool()
    async def get_case_definition_model(
        case_definition_id: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get CaseModel JSON."""
        return await client.get_definition_model("case", case_definition_id)

    @mcp.tool()
    async def get_case_definition_diagram(
        case_definition_id: str,
        ctx: Context | None = None,
    ) -> ImageContent:
        """Get server-rendered PNG diagram (base64, mimeType='image/png').

        Returns base64-encoded PNG; large diagrams (>2MB) may produce >2.7MB MCP payload.
        """
        async with png_semaphore:
            body, content_type = await client.get_definition_diagram("case", case_definition_id)
        validate_png_response(body, content_type, max_png_bytes)
        data = base64.b64encode(body).decode()
        return ImageContent(type="image", data=data, mimeType="image/png")

    # ------------------------------------------------------------------
    # Runtime instance tools (2)
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_process_instance_diagram(
        process_instance_id: str,
        ctx: Context | None = None,
    ) -> ImageContent:
        """Get PNG with active activities highlighted (state-aware).

        Returns base64-encoded PNG; large diagrams (>2MB) may produce >2.7MB MCP payload.
        Uses diagram_timeout_s (FLOWABLE_DIAGRAM_TIMEOUT_S, default 30s), not timeout_s.
        """
        async with png_semaphore:
            body, content_type = await client.get_instance_diagram("process", process_instance_id)
        validate_png_response(body, content_type, max_png_bytes)
        data = base64.b64encode(body).decode()
        return ImageContent(type="image", data=data, mimeType="image/png")

    @mcp.tool()
    async def get_case_instance_diagram(
        case_instance_id: str,
        ctx: Context | None = None,
    ) -> ImageContent:
        """Get PNG with active stages/milestones highlighted.

        Returns base64-encoded PNG; large diagrams (>2MB) may produce >2.7MB MCP payload.
        """
        async with png_semaphore:
            body, content_type = await client.get_instance_diagram("case", case_instance_id)
        validate_png_response(body, content_type, max_png_bytes)
        data = base64.b64encode(body).decode()
        return ImageContent(type="image", data=data, mimeType="image/png")

    # ------------------------------------------------------------------
    # Source bundle (1) — S-01
    # ------------------------------------------------------------------

    @mcp.tool()
    async def get_process_definition_source(
        process_definition_id: str,
        ctx: Context | None = None,
    ) -> dict[str, Any]:
        """Get BPMN XML source and JSON model in a single call (parallel fetch).

        Returns: {"definition_id": str, "xml": str, "model": dict | None}
        model is null if /model endpoint returns 404 (pure-code deployment).
        """
        xml_result: list[str] = []
        model_result: list[dict[str, Any] | None] = []

        async def _fetch_xml() -> None:
            raw = await client.get_definition_resource("process", process_definition_id)
            xml_text = raw.strip()
            if not xml_text:
                raise FlowableProtocolError("empty resourcedata response")
            xml_result.append(xml_text)

        async def _safe_model_fetch() -> None:
            try:
                model = await client.get_definition_model("process", process_definition_id)
                model_result.append(model)
            except FlowableNotFoundError:
                # 404 from /model is acceptable — pure-code deployment (AC-4.4, I-6, AC-S1-2)
                model_result.append(None)
            # 5xx and other errors are NOT caught — propagate through TaskGroup (AC-EDGE-7)

        async with asyncio.TaskGroup() as tg:
            tg.create_task(_fetch_xml())
            tg.create_task(_safe_model_fetch())

        return {
            "definition_id": process_definition_id,
            "xml": xml_result[0],
            "model": model_result[0],
        }
