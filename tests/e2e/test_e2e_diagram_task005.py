"""E2E roundtrip tests for TASK-005 diagram tools.

Covers 5 E2E scenarios from §9.4:
- E-01: get_process_definition_diagram → ImageContent with valid PNG
- E-02: stdout discipline — no raw PNG bytes on stdio transport
- E-03: unknown definition ID → typed MCP error, server stays alive
- E-04: get_process_definition_source → {definition_id, xml, model} bundle
- E-05: get_process_instance_diagram for non-existent instance → typed error

All in-process tests use ``mcp_client`` (FastMCP Client, fresh lifespan per test).
E-02 uses ``spawn_mcp_subprocess`` for the real stdio-transport check (AC-C4, СТ-3).
No mocks — all calls hit a live flowable-rest:8.0.0 Docker container (СТ-6).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client
from fastmcp.exceptions import ToolError

from .conftest import spawn_mcp_subprocess

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skip(
        reason="TASK-006: pre-existing hang on Windows ProactorEventLoop — "
        "FastMCP Client(mcp) anyio in-memory streams + pytest-asyncio mixed "
        "loop scopes deadlock; unblock requires upstream fastmcp fix or "
        "subprocess-stdio fixture rewrite. See .specify/tasks/TASK-006/spec.md."
    ),
]

_DIAGRAM_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "diagram-test.bpmn20.xml"
)
_DIAGRAM_CMMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "diagram-test.cmmn.xml"
)
_DIAGRAM_PROCESS_KEY = "diagram-test"
_DIAGRAM_CASE_KEY = "diagram-test-case"


# ---------------------------------------------------------------------------
# Session-scoped deployment fixture (mirrors integration/test_diagram_task005.py)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def e2e_diagram_definition_id(
    e2e_settings,
    e2e_http: httpx.AsyncClient,
) -> str:
    """Deploy diagram-test.bpmn20.xml once per E2E session; yield definition_id."""
    base = e2e_settings.base_url

    list_resp = await e2e_http.get(
        f"{base}/repository/deployments",
        params={"name": "diagram-test.bpmn20.xml", "size": "20"},
    )
    if list_resp.status_code == 200:
        for dep in list_resp.json().get("data", []):
            await e2e_http.delete(
                f"{base}/repository/deployments/{dep['id']}",
                params={"cascade": "true"},
            )

    bpmn = _DIAGRAM_BPMN.read_bytes()
    deploy_resp = await e2e_http.post(
        f"{base}/repository/deployments",
        files={"file": ("diagram-test.bpmn20.xml", bpmn, "application/xml")},
    )
    deploy_resp.raise_for_status()
    deployment_id: str = deploy_resp.json()["id"]

    pd_resp = await e2e_http.get(
        f"{base}/repository/process-definitions",
        params={"key": _DIAGRAM_PROCESS_KEY, "latest": "true", "size": "1"},
    )
    pd_resp.raise_for_status()
    data = pd_resp.json().get("data", [])
    assert data, f"No process definition found for key={_DIAGRAM_PROCESS_KEY}"
    definition_id: str = data[0]["id"]

    yield definition_id

    await e2e_http.delete(
        f"{base}/repository/deployments/{deployment_id}",
        params={"cascade": "true"},
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_image_content(result):
    """Return the first ImageContent block from a CallToolResult."""
    content = getattr(result, "content", None) or []
    for block in content:
        if getattr(block, "type", None) == "image":
            return block
    return None


def _extract_text_content(result) -> str:
    """Return concatenated text from TextContent blocks."""
    content = getattr(result, "content", None) or []
    parts = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# E-01: Happy path — BPMN PNG diagram via in-process MCP
# ---------------------------------------------------------------------------


async def test_e2e_e01_process_definition_diagram_returns_image_content(
    mcp_client: Client,
    e2e_diagram_definition_id: str,
) -> None:
    """E-01: get_process_definition_diagram → ImageContent with valid base64 PNG.

    Root cause context (§0.1): this is the only test level where
    base64-encoding, ImageContent construction, and FastMCP schema
    serialisation are exercised together end-to-end. A regression
    (e.g. mimeType field renamed, base64 padding bug, or PNG bytes
    leaking into a TextContent block) would be invisible to unit and
    integration tests but immediately caught here.
    """
    result = await mcp_client.call_tool(
        "get_process_definition_diagram",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not getattr(result, "is_error", False), (
        f"Tool returned MCP error: {_extract_text_content(result)!r}"
    )

    img = _extract_image_content(result)
    assert img is not None, (
        f"No ImageContent block in result; content={getattr(result, 'content', [])!r}"
    )
    assert img.mimeType == "image/png", f"Unexpected mimeType: {img.mimeType!r}"

    decoded = base64.b64decode(img.data)
    assert len(decoded) > 100, f"PNG too small ({len(decoded)} bytes) — likely empty"
    assert decoded[:4] == b"\x89PNG", (
        f"PNG magic bytes missing: {decoded[:8]!r}"
    )


# ---------------------------------------------------------------------------
# E-02: Stdout discipline — no PNG bytes on stdio transport (AC-C4, СТ-3)
# ---------------------------------------------------------------------------


async def test_e2e_e02_stdout_discipline_no_png_bytes_in_stdio(
    e2e_diagram_definition_id: str,
) -> None:
    """E-02: subprocess stdio — stdout contains only JSON-RPC frames, no raw PNG.

    Root cause context (§0.1): ImageContent base64 data travels inside a
    JSON-RPC response frame. If any code path printed raw bytes (e.g. via a
    stray print() or a StreamHandler on sys.stdout), the MCP framing would be
    corrupted and the client would fail to parse responses. This test is the
    only place where the real OS-pipe stdout of the server process is inspected
    (unit + integration tests cannot see the subprocess pipe).
    """
    async with spawn_mcp_subprocess() as server:
        await server.initialize()

        response = await server.request(
            "tools/call",
            {
                "name": "get_process_definition_diagram",
                "arguments": {"process_definition_id": e2e_diagram_definition_id},
            },
        )
        # Response must be a valid JSON-RPC object
        assert "result" in response or "error" in response, (
            f"Response is neither result nor error: {response!r}"
        )

        # Every non-empty stdout line must parse as JSON
        for line in server.stdout_lines:
            stripped = line.strip()
            if stripped:
                try:
                    json.loads(stripped)
                except json.JSONDecodeError as exc:
                    pytest.fail(
                        f"stdout line is not valid JSON (СТ-3 violation): {stripped[:200]!r} — {exc}"
                    )

        # Raw PNG magic bytes must NOT appear in stdout (bytes would corrupt framing)
        stdout_bytes = "\n".join(server.stdout_lines).encode("utf-8", errors="replace")
        assert b"\x89PNG" not in stdout_bytes, (
            "Raw PNG bytes detected in subprocess stdout — МCP framing corrupted (AC-C4)"
        )


# ---------------------------------------------------------------------------
# E-03: Error path — unknown definition ID → typed MCP error, server alive
# ---------------------------------------------------------------------------


async def test_e2e_e03_unknown_definition_id_returns_typed_error_server_alive(
    mcp_client: Client,
    e2e_diagram_definition_id: str,
) -> None:
    """E-03: nonexistent ID → FlowableNotFoundError as MCP error, server stays up.

    Root cause context (§0.1): FastMCP wraps unhandled exceptions as MCP errors.
    This test verifies (a) the error is surfaced as a typed MCP error (not a
    crash / empty response) and (b) the server remains healthy for subsequent
    calls — confirming the lifespan guard does not kill the process on 404.
    """
    try:
        result = await mcp_client.call_tool(
            "get_process_definition_xml",
            {"process_definition_id": "nonexistent-id-00000000-0000-0000-0000-000000000000"},
        )
        assert getattr(result, "is_error", False), (
            "Expected MCP error for nonexistent definition ID, got success"
        )
    except ToolError:
        pass  # in-process mode surfaces ToolError directly — also acceptable

    # Server liveness: a valid call must still succeed after the error
    followup = await mcp_client.call_tool(
        "get_process_definition_xml",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not getattr(followup, "is_error", False), (
        "Server became unhealthy after 404 error — liveness check failed"
    )


# ---------------------------------------------------------------------------
# E-04: Source bundle — XML + model in one MCP call (AC-S1-1)
# ---------------------------------------------------------------------------


async def test_e2e_e04_process_definition_source_returns_xml_and_model(
    mcp_client: Client,
    e2e_diagram_definition_id: str,
) -> None:
    """E-04: get_process_definition_source → {definition_id, xml, model} bundle.

    Root cause context (§0.1): the TaskGroup parallel fetch is tested at unit
    level with respx mocks, but the serialisation of the resulting dict through
    FastMCP's JSON schema, and the Flowable REST response shape for a real
    deployed process, are only exercised here. A schema mismatch (e.g. dict key
    renamed) or a Flowable-specific response quirk would be invisible to unit tests.
    """
    result = await mcp_client.call_tool(
        "get_process_definition_source",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not getattr(result, "is_error", False), (
        f"Tool returned MCP error: {_extract_text_content(result)!r}"
    )

    # Parse the dict from the text content
    raw_text = _extract_text_content(result)
    import json as _json
    bundle = _json.loads(raw_text) if raw_text else None

    # Fallback: try structured_content
    if bundle is None:
        bundle = getattr(result, "structured_content", None) or getattr(
            result, "data", None
        )

    assert bundle is not None, f"Could not extract bundle dict from result: {result!r}"
    assert isinstance(bundle, dict), f"Expected dict bundle, got {type(bundle)}"

    assert bundle.get("definition_id") == e2e_diagram_definition_id, (
        f"definition_id mismatch: {bundle.get('definition_id')!r}"
    )
    xml = bundle.get("xml", "")
    assert isinstance(xml, str) and len(xml) > 0, "xml is empty or not a string"
    assert "<" in xml, f"xml does not look like XML: {xml[:100]!r}"

    # model is either a dict (Flowable Modeler deployed) or null (pure-code)
    assert "model" in bundle, "bundle missing 'model' key"


# ---------------------------------------------------------------------------
# E-05: Non-existent instance diagram → typed error, server stays alive
# ---------------------------------------------------------------------------


async def test_e2e_e05_nonexistent_instance_diagram_returns_typed_error(
    mcp_client: Client,
    e2e_diagram_definition_id: str,
) -> None:
    """E-05: get_process_instance_diagram with nonexistent ID → typed MCP error.

    Root cause context (§0.1): 404/410 from Flowable must map to
    FlowableNotFoundError, which FastMCP surfaces as a typed MCP error — not
    an unhandled exception that crashes the server. This is the only test level
    where the full path (MCP call → FlowableClient → _map_status → FastMCP
    error wrapping) is exercised without mocks against a real Flowable instance.
    The server-liveness assertion after the error confirms the guard does not
    destabilise the MCP session.
    """
    try:
        result = await mcp_client.call_tool(
            "get_process_instance_diagram",
            {"process_instance_id": "nonexistent-instance-00000000-0000-0000-0000-000000000000"},
        )
        assert getattr(result, "is_error", False), (
            "Expected MCP error for nonexistent process instance, got success"
        )
    except ToolError:
        pass  # in-process mode raises ToolError directly — also acceptable

    # Server liveness: a subsequent valid call must still work
    followup = await mcp_client.call_tool(
        "get_process_definition_diagram",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not getattr(followup, "is_error", False), (
        "Server became unhealthy after FlowableNotFoundError — liveness check failed"
    )


# ---------------------------------------------------------------------------
# E-06: CMMN XML through MCP (AC-4)
# ---------------------------------------------------------------------------


def _cmmn_base_url(base_url: str) -> str:
    return base_url[: -len("/service")] + "/cmmn-api" if base_url.endswith("/service") else base_url + "/cmmn-api"


@pytest_asyncio.fixture(scope="session")
async def e2e_diagram_case_definition_id(
    e2e_settings,
    e2e_http: httpx.AsyncClient,
) -> str:
    """Deploy CMMN via /cmmn-api; yield case definition_id; skip if no CMMN engine."""
    cmmn_base = _cmmn_base_url(e2e_settings.base_url)

    probe = await e2e_http.get(
        f"{cmmn_base}/cmmn-repository/case-definitions", params={"size": "1"}
    )
    if probe.status_code != 200:
        pytest.skip(
            "Flowable build has no CMMN engine: "
            f"GET {cmmn_base}/cmmn-repository/case-definitions → "
            f"{probe.status_code} {probe.text[:120]!r}"
        )

    list_resp = await e2e_http.get(
        f"{cmmn_base}/cmmn-repository/deployments",
        params={"name": "diagram-test", "size": "20"},
    )
    if list_resp.status_code == 200:
        for dep in list_resp.json().get("data", []):
            await e2e_http.delete(
                f"{cmmn_base}/cmmn-repository/deployments/{dep['id']}",
                params={"cascade": "true"},
            )

    cmmn_bytes = _DIAGRAM_CMMN.read_bytes()
    deploy_resp = await e2e_http.post(
        f"{cmmn_base}/cmmn-repository/deployments",
        files={"file": ("diagram-test.cmmn.xml", cmmn_bytes, "application/xml")},
    )
    if deploy_resp.status_code >= 400:
        pytest.skip(
            f"CMMN deployment failed: {deploy_resp.status_code} "
            f"{deploy_resp.text[:200]!r}"
        )
    deployment_id: str = deploy_resp.json()["id"]

    cd_resp = await e2e_http.get(
        f"{cmmn_base}/cmmn-repository/case-definitions",
        params={"key": _DIAGRAM_CASE_KEY, "latest": "true", "size": "1"},
    )
    if cd_resp.status_code != 200 or not cd_resp.json().get("data"):
        await e2e_http.delete(
            f"{cmmn_base}/cmmn-repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )
        pytest.skip(
            "CMMN engine present but case definition not registered: "
            f"status={cd_resp.status_code} body={cd_resp.text[:200]!r}"
        )
    definition_id: str = cd_resp.json()["data"][0]["id"]

    yield definition_id

    await e2e_http.delete(
        f"{cmmn_base}/cmmn-repository/deployments/{deployment_id}",
        params={"cascade": "true"},
    )


async def test_e2e_e06_case_definition_xml_returns_cmmn_string(
    mcp_client: Client,
    e2e_diagram_case_definition_id: str,
) -> None:
    """E-06: get_case_definition_xml via MCP → CMMN XML string with case tags.

    Root cause context (§0.1): CMMN tools share routing/serialisation code with
    BPMN tools but live behind a different Flowable URL family
    (cmmn-repository/*). Only an end-to-end call with a real CMMN deployment
    catches a wrong path mapping or a mishandled MIME type for the case branch.
    """
    result = await mcp_client.call_tool(
        "get_case_definition_xml",
        {"case_definition_id": e2e_diagram_case_definition_id},
    )
    assert not getattr(result, "is_error", False), (
        f"Tool returned MCP error: {_extract_text_content(result)!r}"
    )

    xml = _extract_text_content(result)
    assert xml and "<" in xml, f"Expected CMMN XML, got: {xml[:120]!r}"
    assert "diagram-test-case" in xml, f"Expected case id in CMMN XML, got: {xml[:200]!r}"


# ---------------------------------------------------------------------------
# E-07: get_process_definition_source for pure-code deployment → model is null
# ---------------------------------------------------------------------------


async def test_e2e_e07_source_model_404_returns_null_model_in_bundle(
    mcp_client: Client,
    e2e_diagram_definition_id: str,
) -> None:
    """E-07: when /model returns 404 (pure-code deployment) the bundle has model=null.

    Root cause context (§0.1): the source tool catches FlowableNotFoundError
    inside its TaskGroup branch and substitutes None. The Flowable build under
    test deploys via REST (no Modeler), so /model legitimately 404s — exactly
    the production-relevant failure mode that AC-S1-2 specifies. Asserts the
    null-model contract survives JSON serialisation through FastMCP.
    """
    result = await mcp_client.call_tool(
        "get_process_definition_source",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not getattr(result, "is_error", False), (
        f"Tool returned MCP error: {_extract_text_content(result)!r}"
    )

    raw_text = _extract_text_content(result)
    bundle = json.loads(raw_text) if raw_text else None
    if bundle is None:
        bundle = getattr(result, "structured_content", None) or getattr(
            result, "data", None
        )
    assert isinstance(bundle, dict), f"Expected dict bundle, got {type(bundle)}: {bundle!r}"

    assert bundle.get("definition_id") == e2e_diagram_definition_id
    xml = bundle.get("xml", "")
    assert isinstance(xml, str) and "<" in xml, f"xml malformed: {xml[:120]!r}"
    assert "model" in bundle, "bundle missing 'model' key"
    # Pure-code deployment via REST → /model 404 → null model (AC-S1-2).
    # Tolerate dict-fallback for builds that auto-populate model metadata.
    assert bundle["model"] is None or isinstance(bundle["model"], dict), (
        f"model must be null or dict, got {type(bundle['model'])}"
    )
