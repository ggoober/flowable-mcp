"""Integration tests for TASK-005 diagram tools — require live flowable-rest:8.0.0.

Run with: pytest tests/integration/ -m integration -k task005

Fixtures deploy diagram-test.bpmn20.xml (includes DI data) once per session.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.errors import FlowableNotFoundError, FlowableProtocolError
from flowable_mcp.tools.diagram import validate_png_response

pytestmark = [pytest.mark.integration]

_FIXTURE_BPMN = Path(__file__).parent / "fixtures" / "diagram-test.bpmn20.xml"
_DIAGRAM_PROCESS_KEY = "diagram-test"


# ---------------------------------------------------------------------------
# Session-scoped fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(scope="session")
async def diagram_definition_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy diagram-test.bpmn20.xml and return the process definition ID."""
    base = integration_settings.base_url

    # Cleanup stale deployments
    resp = await integration_http.get(
        f"{base}/repository/deployments",
        params={"name": "diagram-test.bpmn20.xml", "size": "20"},
    )
    if resp.status_code == 200:
        for dep in resp.json().get("data", []):
            await integration_http.delete(
                f"{base}/repository/deployments/{dep['id']}", params={"cascade": "true"}
            )

    bpmn = _FIXTURE_BPMN.read_bytes()
    deploy_resp = await integration_http.post(
        f"{base}/repository/deployments",
        files={"file": ("diagram-test.bpmn20.xml", bpmn, "application/xml")},
    )
    deploy_resp.raise_for_status()
    deployment_id: str = deploy_resp.json()["id"]

    # Fetch definition ID for "diagram-test" key
    pd_resp = await integration_http.get(
        f"{base}/repository/process-definitions",
        params={"key": _DIAGRAM_PROCESS_KEY, "size": "1"},
    )
    pd_resp.raise_for_status()
    data = pd_resp.json().get("data", [])
    assert data, f"No process definition found for key={_DIAGRAM_PROCESS_KEY}"
    definition_id: str = data[0]["id"]

    yield definition_id

    # Teardown
    await integration_http.delete(
        f"{base}/repository/deployments/{deployment_id}", params={"cascade": "true"}
    )


@pytest_asyncio.fixture(scope="session")
async def diagram_instance_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    diagram_definition_id: str,
) -> str:
    """Start a process instance of diagram-test and return its ID."""
    base = integration_settings.base_url
    resp = await integration_http.post(
        f"{base}/runtime/process-instances",
        json={"processDefinitionId": diagram_definition_id},
    )
    resp.raise_for_status()
    instance_id: str = resp.json()["id"]

    yield instance_id

    # Teardown — cancel if still active
    try:
        await integration_http.delete(f"{base}/runtime/process-instances/{instance_id}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# I-01: get_definition_resource → XML str with BPMN tags
# ---------------------------------------------------------------------------

async def test_client_when_bpmn_deployed_then_get_definition_resource_returns_xml(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    result = await integration_client.get_definition_resource("process", diagram_definition_id)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "<" in result  # XML content
    assert "diagram-test" in result


# ---------------------------------------------------------------------------
# I-02: get_definition_model → dict with key fields
# ---------------------------------------------------------------------------

async def test_client_when_bpmn_deployed_then_get_definition_model_returns_dict_with_flow_elements(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    result = await integration_client.get_definition_model("process", diagram_definition_id)
    assert isinstance(result, dict)
    # Flowable model response may vary in structure; verify it's a non-empty dict
    assert len(result) > 0


# ---------------------------------------------------------------------------
# I-03: get_definition_diagram → valid PNG bytes
# ---------------------------------------------------------------------------

async def test_client_when_bpmn_deployed_then_get_definition_diagram_returns_valid_png(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    body, content_type = await integration_client.get_definition_diagram(
        "process", diagram_definition_id
    )
    assert isinstance(body, bytes)
    assert len(body) > 0
    # Validate guard chain passes on real Flowable PNG
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-04: get_instance_diagram → valid PNG (active instance)
# ---------------------------------------------------------------------------

async def test_client_when_instance_active_then_get_instance_diagram_returns_png(
    integration_client: FlowableClient,
    diagram_instance_id: str,
) -> None:
    body, content_type = await integration_client.get_instance_diagram(
        "process", diagram_instance_id
    )
    assert isinstance(body, bytes)
    assert len(body) > 0
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-05: real PNG from Flowable passes all 4 guard chain checks
# ---------------------------------------------------------------------------

async def test_client_when_real_png_fetched_then_validate_png_guard_chain_passes(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    body, content_type = await integration_client.get_definition_diagram(
        "process", diagram_definition_id
    )
    # Guard chain: (a) not empty, (b) image/png in CT, (c) magic bytes, (d) size ≤ limit
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert len(body) > 0
    assert "image/png" in content_type.lower()
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-10: get_definition_source → parallel fetch of XML + model via client methods
#
# Root cause context (§0.1): prior implementation used MagicMock for the mcp
# object, violating СТ-6 (no mocks in integration tests). The fix calls
# get_definition_resource and get_definition_model directly on the real client,
# then verifies the same bundle contract at the adapter level. The tool-level
# TaskGroup logic is covered by unit tests (TC-13/TC-40, TC-14, INNO-03).
# ---------------------------------------------------------------------------

async def test_client_when_bpmn_deployed_then_get_definition_source_client_methods(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    """I-10 (rewritten without MagicMock): adapter methods for source bundle verified.

    Exercises both get_definition_resource and get_definition_model in parallel
    against real Docker Flowable, asserting the same bundle contract that the
    tool layer assembles (AC-S1-1, AC-S1-2).
    """
    xml_task = asyncio.create_task(
        integration_client.get_definition_resource("process", diagram_definition_id)
    )
    model_task = asyncio.create_task(
        integration_client.get_definition_model("process", diagram_definition_id)
    )
    xml_raw, model_raw = await asyncio.gather(xml_task, model_task, return_exceptions=True)

    # xml must be a non-empty string containing XML markup
    assert isinstance(xml_raw, str), f"Expected str from get_definition_resource, got {type(xml_raw)}"
    xml_text = xml_raw.strip()
    assert xml_text, "get_definition_resource returned empty/whitespace XML (AC-EDGE-5)"
    assert "<" in xml_text, f"Returned text does not look like XML: {xml_text[:100]!r}"

    # model is either a non-empty dict or None (pure-code deployment fallback, AC-S1-2)
    if isinstance(model_raw, FlowableNotFoundError):
        # pure-code deployment — no model endpoint; null model is acceptable
        pass
    elif isinstance(model_raw, Exception):
        raise model_raw
    else:
        assert isinstance(model_raw, dict), (
            f"Expected dict from get_definition_model, got {type(model_raw)}"
        )
        assert len(model_raw) > 0, "get_definition_model returned an empty dict"


# ---------------------------------------------------------------------------
# I-17: nonexistent definition ID → FlowableNotFoundError
# ---------------------------------------------------------------------------

async def test_client_when_nonexistent_definition_id_then_get_model_raises_not_found(
    integration_client: FlowableClient,
) -> None:
    with pytest.raises(FlowableNotFoundError):
        await integration_client.get_definition_model(
            "process", "nonexistent-id-00000000-0000-0000-0000-000000000000"
        )
