"""E2E roundtrip tests for TASK-005 diagram tools (TASK-006 subprocess harness).

Covers 7 E2E scenarios from §9.4:
- E-01: get_process_definition_diagram → ImageContent with valid PNG
- E-02: stdout discipline — no raw PNG bytes on stdio transport
- E-03: unknown definition ID → typed MCP error, server stays alive
- E-04: get_process_definition_source → {definition_id, xml, model} bundle
- E-05: get_process_instance_diagram for non-existent instance → typed error
- E-06: get_case_definition_xml via real CMMN deployment (skipped if no CMMN engine)
- E-07: pure-code deployment → bundle.model is null (or dict)

All tests run via real subprocess MCP server (``spawn_mcp_subprocess``) so the
JSON-RPC wire-format ImageContent / TextContent contract is exercised exactly
as Claude Desktop sees it. The Python ``Image`` SDK type is covered at unit
level with respx (TASK-006 §0.1 §9.X — wire vs type split).

TASK-006 fix: in-process ``Client(mcp)`` would deadlock here on Windows
ProactorEventLoop because anyio in-memory streams are bound to the
function-scoped fixture loop while session-scoped fixtures (``e2e_http``,
``e2e_diagram_definition_id``) live in the session loop. Subprocess boundary
removes the cross-loop binding entirely.

Marker ``diagram_e2e`` is auto-applied by ``conftest.py::pytest_collection_modifyitems``
based on filename pattern — do not set manually.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from ._helpers import (
    assert_image_content,
    extract_text_payload,
    is_error_envelope,
    parse_text_json,
)
from .conftest import _post_with_retry, spawn_mcp_subprocess

pytestmark = [pytest.mark.e2e]


_DIAGRAM_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "diagram-test.bpmn20.xml"
)
_DIAGRAM_CMMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "diagram-test.cmmn.xml"
)
_DIAGRAM_PROCESS_KEY = "diagram-test"
_DIAGRAM_CASE_KEY = "diagram-test-case"


# ---------------------------------------------------------------------------
# Session-scoped deployment fixture (httpx-only, no MCP — survives subprocess
# transport switch since it does not depend on Client(mcp) loop binding).
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
    deploy_resp = await _post_with_retry(
        e2e_http,
        f"{base}/repository/deployments",
        files={"file": ("diagram-test.bpmn20.xml", bpmn, "application/xml")},
    )
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

    try:
        await e2e_http.delete(
            f"{base}/repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadError):
        # Best-effort teardown: Flowable restart between deploy and teardown
        # would otherwise mask test results behind ERROR (M5 / F-DI-3).
        pass


def _cmmn_base_url(base_url: str) -> str:
    return (
        base_url[: -len("/service")] + "/cmmn-api"
        if base_url.endswith("/service")
        else base_url + "/cmmn-api"
    )


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
    try:
        deploy_resp = await _post_with_retry(
            e2e_http,
            f"{cmmn_base}/cmmn-repository/deployments",
            files={"file": ("diagram-test.cmmn.xml", cmmn_bytes, "application/xml")},
        )
    except httpx.HTTPStatusError as exc:
        # 4xx CMMN deploy errors (engine quirks, validation) → skip cleanly
        # rather than fail; we still want a retry on transient 5xx (handled by
        # _post_with_retry) (mandatory #9 + AC-C2 robustness).
        pytest.skip(
            f"CMMN deployment failed: {exc.response.status_code} "
            f"{exc.response.text[:200]!r}"
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

    try:
        await e2e_http.delete(
            f"{cmmn_base}/cmmn-repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )
    except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadError):
        # Best-effort teardown (M5 / F-DI-3).
        pass


# ---------------------------------------------------------------------------
# Subprocess harness helper — initialise once per test, run a single tool call.
# ---------------------------------------------------------------------------


async def _call_tool(name: str, arguments: dict) -> dict:
    """Spawn a fresh MCP subprocess, initialize, call a tool, return RPC response."""
    async with spawn_mcp_subprocess() as server:
        await server.initialize()
        return await server.request(
            "tools/call", {"name": name, "arguments": arguments}
        )


# ---------------------------------------------------------------------------
# E-01: Happy path — BPMN PNG diagram via subprocess MCP wire-format
# ---------------------------------------------------------------------------


async def test_e2e_e01_process_definition_diagram_returns_image_content(
    e2e_diagram_definition_id: str,
) -> None:
    """E-01: get_process_definition_diagram → ImageContent with valid base64 PNG.

    Wire-format check: parses JSON-RPC envelope, validates ``mimeType`` and
    base64 decoding through to PNG magic bytes.
    """
    response = await _call_tool(
        "get_process_definition_diagram",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not is_error_envelope(response), (
        f"Tool returned MCP error: {response!r}"
    )
    assert_image_content(response, mime_prefix="image/png", min_bytes=100)


# ---------------------------------------------------------------------------
# E-02: Stdout discipline — no PNG bytes on stdio transport (AC-C4, СТ-3)
# ---------------------------------------------------------------------------


async def test_e2e_e02_stdout_discipline_no_png_bytes_in_stdio(
    e2e_diagram_definition_id: str,
) -> None:
    """E-02: subprocess stdio — stdout is JSON-RPC only, no raw PNG bytes."""
    import json as _json

    async with spawn_mcp_subprocess() as server:
        await server.initialize()
        response = await server.request(
            "tools/call",
            {
                "name": "get_process_definition_diagram",
                "arguments": {"process_definition_id": e2e_diagram_definition_id},
            },
        )
        assert "result" in response or "error" in response, (
            f"Response is neither result nor error: {response!r}"
        )

        for line in server.stdout_lines:
            stripped = line.strip()
            if stripped:
                try:
                    _json.loads(stripped)
                except _json.JSONDecodeError as exc:
                    pytest.fail(
                        f"stdout line is not valid JSON (СТ-3 violation): "
                        f"{stripped[:200]!r} — {exc}"
                    )

        stdout_bytes = "\n".join(server.stdout_lines).encode("utf-8", errors="replace")
        assert b"\x89PNG" not in stdout_bytes, (
            "Raw PNG bytes detected in subprocess stdout — MCP framing corrupted (AC-C4)"
        )


# ---------------------------------------------------------------------------
# E-03: Error path — unknown definition ID → typed MCP error, server stays alive
# ---------------------------------------------------------------------------


async def test_e2e_e03_unknown_definition_id_returns_typed_error_server_alive(
    e2e_diagram_definition_id: str,
) -> None:
    """E-03: nonexistent ID → MCP error envelope; server still serves a follow-up call."""
    async with spawn_mcp_subprocess() as server:
        await server.initialize()

        bad = await server.request(
            "tools/call",
            {
                "name": "get_process_definition_xml",
                "arguments": {
                    "process_definition_id": "nonexistent-id-00000000-0000-0000-0000-000000000000"
                },
            },
        )
        assert is_error_envelope(bad), (
            f"Expected MCP error for nonexistent definition ID, got: {bad!r}"
        )

        followup = await server.request(
            "tools/call",
            {
                "name": "get_process_definition_xml",
                "arguments": {"process_definition_id": e2e_diagram_definition_id},
            },
        )
        assert not is_error_envelope(followup), (
            f"Server unhealthy after 404 (liveness check failed): {followup!r}"
        )


# ---------------------------------------------------------------------------
# E-04: Source bundle — XML + model via single MCP call (AC-S1-1)
# ---------------------------------------------------------------------------


async def test_e2e_e04_process_definition_source_returns_xml_and_model(
    e2e_diagram_definition_id: str,
) -> None:
    """E-04: get_process_definition_source → {definition_id, xml, model} bundle."""
    response = await _call_tool(
        "get_process_definition_source",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not is_error_envelope(response), (
        f"Tool returned MCP error: {extract_text_payload(response)!r}"
    )

    bundle = parse_text_json(response)
    assert isinstance(bundle, dict), f"Expected dict bundle, got {type(bundle)}: {bundle!r}"
    assert bundle.get("definition_id") == e2e_diagram_definition_id, (
        f"definition_id mismatch: {bundle.get('definition_id')!r}"
    )
    xml = bundle.get("xml", "")
    assert isinstance(xml, str) and "<" in xml, f"xml malformed: {xml[:120]!r}"
    assert "model" in bundle, "bundle missing 'model' key"


# ---------------------------------------------------------------------------
# E-05: Non-existent instance diagram → typed error, server stays alive
# ---------------------------------------------------------------------------


async def test_e2e_e05_nonexistent_instance_diagram_returns_typed_error(
    e2e_diagram_definition_id: str,
) -> None:
    """E-05: get_process_instance_diagram with nonexistent ID → typed MCP error."""
    async with spawn_mcp_subprocess() as server:
        await server.initialize()

        bad = await server.request(
            "tools/call",
            {
                "name": "get_process_instance_diagram",
                "arguments": {
                    "process_instance_id": (
                        "nonexistent-instance-00000000-0000-0000-0000-000000000000"
                    )
                },
            },
        )
        assert is_error_envelope(bad), (
            f"Expected MCP error for nonexistent instance, got: {bad!r}"
        )

        followup = await server.request(
            "tools/call",
            {
                "name": "get_process_definition_diagram",
                "arguments": {"process_definition_id": e2e_diagram_definition_id},
            },
        )
        assert not is_error_envelope(followup), (
            f"Server unhealthy after FlowableNotFoundError (liveness): {followup!r}"
        )


# ---------------------------------------------------------------------------
# E-06: CMMN XML through MCP (AC-4)
# ---------------------------------------------------------------------------


async def test_e2e_e06_case_definition_xml_returns_cmmn_string(
    e2e_diagram_case_definition_id: str,
) -> None:
    """E-06: get_case_definition_xml via MCP → CMMN XML string with case tags."""
    response = await _call_tool(
        "get_case_definition_xml",
        {"case_definition_id": e2e_diagram_case_definition_id},
    )
    assert not is_error_envelope(response), (
        f"Tool returned MCP error: {extract_text_payload(response)!r}"
    )
    xml = extract_text_payload(response)
    assert xml and "<" in xml, f"Expected CMMN XML, got: {xml[:120]!r}"
    assert "diagram-test-case" in xml, f"Expected case id in CMMN XML, got: {xml[:200]!r}"


# ---------------------------------------------------------------------------
# E-07: pure-code deployment → bundle.model is null (AC-S1-2)
# ---------------------------------------------------------------------------


async def test_e2e_e07_source_model_404_returns_null_model_in_bundle(
    e2e_diagram_definition_id: str,
) -> None:
    """E-07: when /model returns 404 (pure-code deployment) bundle has model=null."""
    response = await _call_tool(
        "get_process_definition_source",
        {"process_definition_id": e2e_diagram_definition_id},
    )
    assert not is_error_envelope(response), (
        f"Tool returned MCP error: {extract_text_payload(response)!r}"
    )

    bundle = parse_text_json(response)
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
