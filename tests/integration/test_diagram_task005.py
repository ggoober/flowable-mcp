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
from flowable_mcp.errors import (
    FlowableDiagramError,
    FlowableNotFoundError,
    FlowableProtocolError,
    FlowableValidationError,
)
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

    # Fetch latest definition for the just-deployed version (Flowable's default sort is asc → would return v1)
    pd_resp = await integration_http.get(
        f"{base}/repository/process-definitions",
        params={"key": _DIAGRAM_PROCESS_KEY, "latest": "true", "size": "1"},
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


@pytest_asyncio.fixture
async def diagram_instance_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    diagram_definition_id: str,
) -> str:
    """Start a fresh process instance per test (function scope avoids cross-test
    teardown races where a session instance could be cancelled by another fixture)."""
    base = integration_settings.base_url
    resp = await integration_http.post(
        f"{base}/runtime/process-instances",
        json={"processDefinitionId": diagram_definition_id},
    )
    resp.raise_for_status()
    instance_id: str = resp.json()["id"]

    yield instance_id

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


# ---------------------------------------------------------------------------
# Extra fixtures for I-06/I-08/I-09 (CMMN) and I-12 (no-DI BPMN)
# ---------------------------------------------------------------------------

_FIXTURE_BPMN_NO_DI = Path(__file__).parent / "fixtures" / "diagram-test-no-di.bpmn20.xml"
_FIXTURE_CMMN = Path(__file__).parent / "fixtures" / "diagram-test.cmmn.xml"
_NO_DI_PROCESS_KEY = "diagram-test-no-di"
_CMMN_CASE_KEY = "diagram-test-case"


@pytest_asyncio.fixture(scope="session")
async def diagram_no_di_definition_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    base = integration_settings.base_url

    resp = await integration_http.get(
        f"{base}/repository/deployments",
        params={"name": "diagram-test-no-di.bpmn20.xml", "size": "20"},
    )
    if resp.status_code == 200:
        for dep in resp.json().get("data", []):
            await integration_http.delete(
                f"{base}/repository/deployments/{dep['id']}", params={"cascade": "true"}
            )

    bpmn = _FIXTURE_BPMN_NO_DI.read_bytes()
    deploy_resp = await integration_http.post(
        f"{base}/repository/deployments",
        files={"file": ("diagram-test-no-di.bpmn20.xml", bpmn, "application/xml")},
    )
    deploy_resp.raise_for_status()
    deployment_id: str = deploy_resp.json()["id"]

    pd_resp = await integration_http.get(
        f"{base}/repository/process-definitions",
        params={"key": _NO_DI_PROCESS_KEY, "latest": "true", "size": "1"},
    )
    pd_resp.raise_for_status()
    data = pd_resp.json().get("data", [])
    assert data, f"No process definition for key={_NO_DI_PROCESS_KEY}"
    definition_id: str = data[0]["id"]

    yield definition_id

    await integration_http.delete(
        f"{base}/repository/deployments/{deployment_id}", params={"cascade": "true"}
    )


def _cmmn_base(base_url: str) -> str:
    """Derive the /cmmn-api root from the BPMN /service base URL."""
    return base_url[: -len("/service")] + "/cmmn-api" if base_url.endswith("/service") else base_url + "/cmmn-api"


@pytest_asyncio.fixture(scope="session")
async def diagram_case_definition_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    cmmn_base = _cmmn_base(integration_settings.base_url)

    # Preflight: probe whether CMMN REST module is present.
    probe = await integration_http.get(
        f"{cmmn_base}/cmmn-repository/case-definitions", params={"size": "1"}
    )
    if probe.status_code != 200:
        pytest.skip(
            "Flowable build has no CMMN engine: "
            f"GET {cmmn_base}/cmmn-repository/case-definitions → "
            f"{probe.status_code} {probe.text[:120]!r}"
        )

    # Purge stale CMMN deployments by name.
    list_resp = await integration_http.get(
        f"{cmmn_base}/cmmn-repository/deployments",
        params={"name": "diagram-test", "size": "20"},
    )
    if list_resp.status_code == 200:
        for dep in list_resp.json().get("data", []):
            await integration_http.delete(
                f"{cmmn_base}/cmmn-repository/deployments/{dep['id']}",
                params={"cascade": "true"},
            )

    cmmn_bytes = _FIXTURE_CMMN.read_bytes()
    deploy_resp = await integration_http.post(
        f"{cmmn_base}/cmmn-repository/deployments",
        files={"file": ("diagram-test.cmmn.xml", cmmn_bytes, "application/xml")},
    )
    if deploy_resp.status_code >= 400:
        pytest.skip(
            f"CMMN deployment failed: {deploy_resp.status_code} "
            f"{deploy_resp.text[:200]!r}"
        )
    deployment_id: str = deploy_resp.json()["id"]

    cd_resp = await integration_http.get(
        f"{cmmn_base}/cmmn-repository/case-definitions",
        params={"key": _CMMN_CASE_KEY, "latest": "true", "size": "1"},
    )
    if cd_resp.status_code != 200 or not cd_resp.json().get("data"):
        await integration_http.delete(
            f"{cmmn_base}/cmmn-repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )
        pytest.skip(
            "CMMN engine present but case definition not registered: "
            f"status={cd_resp.status_code} body={cd_resp.text[:200]!r}"
        )
    definition_id: str = cd_resp.json()["data"][0]["id"]

    yield definition_id

    await integration_http.delete(
        f"{cmmn_base}/cmmn-repository/deployments/{deployment_id}",
        params={"cascade": "true"},
    )


@pytest_asyncio.fixture
async def diagram_case_instance_id(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    diagram_case_definition_id: str,
) -> str:
    cmmn_base = _cmmn_base(integration_settings.base_url)
    resp = await integration_http.post(
        f"{cmmn_base}/cmmn-runtime/case-instances",
        json={"caseDefinitionId": diagram_case_definition_id},
    )
    if resp.status_code >= 400:
        pytest.skip(
            f"Flowable cannot start case instance: "
            f"{resp.status_code} {resp.text[:200]}"
        )
    instance_id: str = resp.json()["id"]

    yield instance_id

    try:
        await integration_http.delete(
            f"{cmmn_base}/cmmn-runtime/case-instances/{instance_id}"
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# I-06: CMMN deployed → get_case_definition_xml returns CMMN XML
# ---------------------------------------------------------------------------

async def test_client_when_cmmn_deployed_then_get_case_definition_xml_returns_xml(
    integration_client: FlowableClient,
    diagram_case_definition_id: str,
) -> None:
    result = await integration_client.get_definition_resource("case", diagram_case_definition_id)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "<" in result
    assert "diagram-test-case" in result


# ---------------------------------------------------------------------------
# I-08: CMMN deployed → get_case_definition_diagram returns valid PNG
# ---------------------------------------------------------------------------

async def test_client_when_cmmn_deployed_then_get_case_definition_diagram_returns_png(
    integration_client: FlowableClient,
    diagram_case_definition_id: str,
) -> None:
    body, content_type = await integration_client.get_definition_diagram(
        "case", diagram_case_definition_id
    )
    assert isinstance(body, bytes)
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-09: active case instance → get_case_instance_diagram returns valid PNG
# ---------------------------------------------------------------------------

async def test_client_when_case_instance_active_then_get_case_instance_diagram_returns_png(
    integration_client: FlowableClient,
    diagram_case_instance_id: str,
) -> None:
    body, content_type = await integration_client.get_instance_diagram(
        "case", diagram_case_instance_id
    )
    assert isinstance(body, bytes)
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-11: 4 concurrent diagram fetches against real Docker complete without error
# ---------------------------------------------------------------------------

async def test_client_when_4_concurrent_diagram_calls_then_all_complete_no_errors(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    """Real Flowable + httpx pool: 4 parallel calls must all return valid PNG.

    Verifies the real concurrency path that unit-level Semaphore._value checks
    cannot exercise (httpx connection pool, server-side back-pressure).
    """
    async def _fetch() -> tuple[bytes, str]:
        return await integration_client.get_definition_diagram(
            "process", diagram_definition_id
        )

    results = await asyncio.gather(*(_fetch() for _ in range(4)))
    assert len(results) == 4
    for body, content_type in results:
        validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
        assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-12: BPMN deployed without DI — guard chain must give clean typed outcome
# ---------------------------------------------------------------------------

async def test_client_when_bpmn_without_di_then_diagram_returns_typed_outcome(
    integration_client: FlowableClient,
    diagram_no_di_definition_id: str,
) -> None:
    """Flowable behavior on missing DI is build-dependent (auto-DI vs 4xx vs empty).

    The contract we enforce: either (a) Flowable auto-generates DI and returns a
    valid PNG, or (b) the call raises a typed FlowableDiagramError /
    FlowableProtocolError / FlowableNotFoundError. No raw bytes leak, no crash.
    """
    try:
        body, content_type = await integration_client.get_definition_diagram(
            "process", diagram_no_di_definition_id
        )
    except (
        FlowableDiagramError,
        FlowableProtocolError,
        FlowableNotFoundError,
        FlowableValidationError,
    ):
        return  # acceptable typed outcome (Flowable 8.x raises 400 "has no image")

    # Auto-DI path: PNG must still pass the guard chain
    validate_png_response(body, content_type, max_bytes=10 * 1024 * 1024)
    assert body[:4] == b"\x89PNG"


# ---------------------------------------------------------------------------
# I-13: snapshot replay — two consecutive PNG calls return guard-valid output
# ---------------------------------------------------------------------------

async def test_client_when_snapshot_replay_then_both_pngs_valid_and_similar_size(
    integration_client: FlowableClient,
    diagram_definition_id: str,
) -> None:
    """Two consecutive PNG fetches: both pass guard chain; sizes within 10%.

    PNG metadata may include non-deterministic bytes (timestamps); we therefore
    compare lengths approximately, not byte-for-byte. Detects gross rendering
    drift between Flowable versions without false positives on benign metadata.
    """
    body1, ct1 = await integration_client.get_definition_diagram(
        "process", diagram_definition_id
    )
    body2, ct2 = await integration_client.get_definition_diagram(
        "process", diagram_definition_id
    )

    validate_png_response(body1, ct1, max_bytes=10 * 1024 * 1024)
    validate_png_response(body2, ct2, max_bytes=10 * 1024 * 1024)

    smaller, larger = sorted([len(body1), len(body2)])
    assert smaller > 0
    assert larger - smaller <= max(1024, smaller // 10), (
        f"PNG size drift suspicious: {len(body1)} vs {len(body2)}"
    )


# ---------------------------------------------------------------------------
# I-14: get_definition_diagram routes through the dedicated diagram client
# ---------------------------------------------------------------------------

async def test_client_when_http_diagram_distinct_then_diagram_route_uses_it(
    integration_settings: Settings,
) -> None:
    """Build a FlowableClient with a separate http_diagram and verify routing.

    httpx.AsyncClient event_hooks count requests on each client. After one
    diagram call we expect: diagram_client.requests == 1, retry_client == 0,
    no_retry_client == 0 — proving AC-4.2 routing on real wire.
    """
    base = integration_settings.base_url
    auth = httpx.BasicAuth(
        integration_settings.username, integration_settings.password.get_secret_value()
    )

    counters = {"retry": 0, "no_retry": 0, "diagram": 0}

    async def _make_hook(label: str):
        async def _on_request(request: httpx.Request) -> None:
            counters[label] += 1
        return _on_request

    retry = httpx.AsyncClient(
        base_url=base + "/", auth=auth, timeout=30.0,
        event_hooks={"request": [await _make_hook("retry")]},
    )
    no_retry = httpx.AsyncClient(
        base_url=base + "/", auth=auth, timeout=30.0,
        event_hooks={"request": [await _make_hook("no_retry")]},
    )
    diagram = httpx.AsyncClient(
        base_url=base + "/", auth=auth, timeout=30.0,
        event_hooks={"request": [await _make_hook("diagram")]},
    )

    routing_fixture = Path(__file__).parent / "fixtures" / "diagram-test-routing.bpmn20.xml"
    routing_key = "diagram-test-routing"
    routing_filename = "diagram-test-routing.bpmn20.xml"

    try:
        bpmn = routing_fixture.read_bytes()
        # purge stale (only this routing file — must NOT touch the session fixture)
        list_resp = await no_retry.get(
            f"{base}/repository/deployments",
            params={"name": routing_filename, "size": "20"},
        )
        if list_resp.status_code == 200:
            for dep in list_resp.json().get("data", []):
                await no_retry.delete(
                    f"{base}/repository/deployments/{dep['id']}",
                    params={"cascade": "true"},
                )
        dep_resp = await no_retry.post(
            f"{base}/repository/deployments",
            files={"file": (routing_filename, bpmn, "application/xml")},
        )
        dep_resp.raise_for_status()
        deployment_id = dep_resp.json()["id"]

        pd_resp = await retry.get(
            f"{base}/repository/process-definitions",
            params={"key": routing_key, "latest": "true", "size": "1"},
        )
        pd_resp.raise_for_status()
        definition_id = pd_resp.json()["data"][0]["id"]

        # Reset counters AFTER setup so we measure only the diagram call
        counters["retry"] = 0
        counters["no_retry"] = 0
        counters["diagram"] = 0

        client = FlowableClient(
            http_retry=retry, http_no_retry=no_retry, http_diagram=diagram
        )
        body, ct = await client.get_definition_diagram("process", definition_id)
        validate_png_response(body, ct, max_bytes=10 * 1024 * 1024)

        assert counters["diagram"] == 1, f"diagram client hit count: {counters}"
        assert counters["retry"] == 0, f"retry client should not be used: {counters}"
        assert counters["no_retry"] == 0, f"no_retry client should not be used: {counters}"

        # Teardown deployment
        await no_retry.delete(
            f"{base}/repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )
    finally:
        await retry.aclose()
        await no_retry.aclose()
        await diagram.aclose()


# ---------------------------------------------------------------------------
# I-07: tiny diagram_timeout_s → real request times out → FlowableConnectionError
# ---------------------------------------------------------------------------

async def test_client_when_diagram_timeout_too_small_then_connection_error_raised(
    integration_settings: Settings,
    diagram_definition_id: str,
) -> None:
    """diagram_timeout_s=0.001 forces httpx ReadTimeout on the real wire.

    Verifies that diagram_timeout_s is actually applied to the outbound request
    (not just stored on the client) and that timeouts surface as a typed
    FlowableConnectionError, not raw httpx exceptions.
    """
    from flowable_mcp.errors import FlowableConnectionError

    base = integration_settings.base_url
    auth = httpx.BasicAuth(
        integration_settings.username, integration_settings.password.get_secret_value()
    )

    async with (
        httpx.AsyncClient(base_url=base + "/", auth=auth, timeout=30.0) as retry,
        httpx.AsyncClient(base_url=base + "/", auth=auth, timeout=30.0) as no_retry,
        httpx.AsyncClient(base_url=base + "/", auth=auth, timeout=30.0) as diagram,
    ):
        client = FlowableClient(
            http_retry=retry,
            http_no_retry=no_retry,
            http_diagram=diagram,
            diagram_timeout_s=0.001,
        )
        with pytest.raises(FlowableConnectionError):
            await client.get_definition_diagram("process", diagram_definition_id)
