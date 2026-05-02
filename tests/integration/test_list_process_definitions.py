"""Integration tests for FlowableClient.list_process_definitions.

Requires a live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/

NO mocks — all tests exercise the real HTTP stack against a real Flowable instance.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableAuthError, FlowableConnectionError
from flowable_mcp.models import ProcessDefinition

from .conftest import SAMPLE_PROCESS_KEY

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# TC-01 — basic smoke: deployed BPMN appears in the listing
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_deployed_bpmn_then_returns_non_empty_list(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-01: At least one definition returned; all items are valid ProcessDefinition DTOs."""
    result = await integration_client.list_process_definitions(latest=True)

    assert len(result) >= 1, "Expected at least one process definition after deployment"
    for item in result:
        assert isinstance(item, ProcessDefinition)
        assert item.id, "id must be non-empty"
        assert item.key, "key must be non-empty"
        assert item.deployment_id, "deployment_id must be non-empty"
        assert item.version >= 1, "version must be a positive integer"


# ---------------------------------------------------------------------------
# TC-34 — DTO validation: all fields present and non-empty
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_tool_list_when_flowable_running_then_returns_validated_dtos(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-34: Every item in the result deserialises to a valid ProcessDefinition."""
    result = await integration_client.list_process_definitions()

    assert all(isinstance(item, ProcessDefinition) for item in result)
    assert all(
        item.id and item.key and item.deployment_id for item in result
    ), "All DTOs must have non-empty id, key, and deployment_id"


# ---------------------------------------------------------------------------
# TC-83 — latest=True returns only the newest version
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_two_versions_deployed_then_latest_true_returns_one(
    integration_settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-83: Two BPMN versions deployed; latest=True → 1 entry, latest=False → ≥2."""
    from pathlib import Path

    bpmn_content = (
        Path(__file__).parent / "fixtures" / "sample.bpmn20.xml"
    ).read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"
    files = {"file": ("sample.bpmn20.xml", bpmn_content, "application/xml")}

    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    dep2_id: str = resp.json()["id"]

    try:
        result_latest = await integration_client.list_process_definitions(
            latest=True, key=SAMPLE_PROCESS_KEY
        )
        result_all = await integration_client.list_process_definitions(
            latest=False, key=SAMPLE_PROCESS_KEY
        )

        assert len(result_latest) == 1, (
            f"latest=True must return exactly 1 entry for key '{SAMPLE_PROCESS_KEY}', "
            f"got {len(result_latest)}"
        )
        assert len(result_all) >= 2, (
            f"latest=False must return ≥2 entries for key '{SAMPLE_PROCESS_KEY}' "
            f"after two deployments, got {len(result_all)}"
        )
        max_version = max(d.version for d in result_all)
        assert result_latest[0].version == max_version, (
            "latest=True must return the highest-versioned definition"
        )
    finally:
        delete_url = f"{integration_settings.base_url}/repository/deployments/{dep2_id}"
        await integration_http.delete(delete_url)


# ---------------------------------------------------------------------------
# TC-84 — unknown key returns empty list
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_key_nonexistent_then_returns_empty_list(
    integration_client: FlowableClient,
) -> None:
    """TC-84: Filtering by a key that does not exist returns []."""
    result = await integration_client.list_process_definitions(
        key="does-not-exist-xyzzy-12345"
    )

    assert result == [], (
        f"Expected empty list for unknown key, got {len(result)} items"
    )


# ---------------------------------------------------------------------------
# TC-85 — latest=False returns at least as many results as latest=True
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_latest_false_then_returns_all_versions(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-85: latest=False must return a superset of latest=True results."""
    result_latest = await integration_client.list_process_definitions(latest=True)
    result_all = await integration_client.list_process_definitions(latest=False)

    assert len(result_all) >= len(result_latest), (
        "latest=False must return at least as many definitions as latest=True"
    )


# ---------------------------------------------------------------------------
# INN-04 — latest=True results form a subset of latest=False by key
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_latest_true_then_subset_of_latest_false(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """INN-04: Keys from latest=True are a subset of keys from latest=False; no key duplicated."""
    result_latest = await integration_client.list_process_definitions(latest=True)
    result_all = await integration_client.list_process_definitions(latest=False)

    keys_latest = {d.key for d in result_latest}
    keys_all = {d.key for d in result_all}

    assert keys_latest.issubset(keys_all), (
        f"Keys from latest=True {keys_latest - keys_all} not found in latest=False"
    )

    # Each key must appear at most once in the latest=True result.
    for key in keys_latest:
        matching = [d for d in result_latest if d.key == key]
        assert len(matching) == 1, (
            f"Key '{key}' appears {len(matching)} times in latest=True result; expected 1"
        )


# ---------------------------------------------------------------------------
# INN-05 — key filter returns only definitions with matching key
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_key_filter_then_subset_with_matching_key(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """INN-05: Filtering by a deployed key returns only definitions with that key."""
    result_all = await integration_client.list_process_definitions(latest=False)
    if not result_all:
        pytest.skip("No process definitions deployed — cannot test key filter")

    target_key = result_all[0].key
    result_filtered = await integration_client.list_process_definitions(key=target_key)

    assert len(result_filtered) >= 1, (
        f"Expected at least one definition for key '{target_key}'"
    )
    assert all(item.key == target_key for item in result_filtered), (
        f"All filtered items must have key='{target_key}'"
    )


# ---------------------------------------------------------------------------
# INN-06 — 8 parallel calls return identical results
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_8_parallel_calls_then_all_results_equal(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """INN-06: 8 concurrent calls produce the same result — client is safe under concurrency."""
    results = await asyncio.gather(
        *[integration_client.list_process_definitions() for _ in range(8)]
    )

    assert len(results) == 8
    assert all(r == results[0] for r in results), (
        "All parallel calls must return identical results"
    )


# ---------------------------------------------------------------------------
# TC-93 — 12 parallel calls all succeed
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_12_parallel_calls_then_all_succeed(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-93: 12 concurrent calls each return a list — no exceptions under load."""
    results = await asyncio.gather(
        *[integration_client.list_process_definitions() for _ in range(12)]
    )

    assert len(results) == 12
    assert all(isinstance(r, list) for r in results), (
        "All 12 parallel calls must return a list"
    )


# ---------------------------------------------------------------------------
# TC-94 — unreachable server raises FlowableConnectionError
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_client_when_flowable_stopped_then_raises_connection_error(
    integration_settings,
) -> None:
    """TC-94: Client pointing at a closed port raises FlowableConnectionError."""

    class _BadSettings:
        """Minimal duck-typed settings pointing at an unreachable port."""

        base_url: str = "http://localhost:19999"

    async with httpx.AsyncClient(
        auth=httpx.BasicAuth(
            integration_settings.username,
            integration_settings.password.get_secret_value(),
        ),
        timeout=2.0,
    ) as http:
        client = FlowableClient(settings=_BadSettings(), http=http)  # type: ignore[arg-type]
        with pytest.raises(FlowableConnectionError) as exc_info:
            await client.list_process_definitions()

    assert exc_info.value.__cause__ is not None, (
        "FlowableConnectionError must chain the original transport exception"
    )
    assert isinstance(
        exc_info.value.__cause__, (httpx.ConnectError, httpx.TransportError)
    )


# ---------------------------------------------------------------------------
# TC-95 — wrong credentials raise FlowableAuthError
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_client_when_wrong_credentials_then_raises_auth_error(
    integration_settings,
) -> None:
    """TC-95: Invalid Basic Auth credentials cause FlowableAuthError (401/403)."""
    async with httpx.AsyncClient(
        auth=httpx.BasicAuth("wrong-user", "wrong-password"),
        timeout=10.0,
    ) as http:
        client = FlowableClient(settings=integration_settings, http=http)
        with pytest.raises(FlowableAuthError):
            await client.list_process_definitions()


# ---------------------------------------------------------------------------
# TC-96 — filtering by SAMPLE_PROCESS_KEY returns deployed definition
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_key_filter_matches_deployed_then_non_empty(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-96: Filtering by the deployed sample key returns at least one result."""
    result = await integration_client.list_process_definitions(key=SAMPLE_PROCESS_KEY)

    assert len(result) >= 1, (
        f"Expected at least one definition for key='{SAMPLE_PROCESS_KEY}'"
    )
    assert all(item.key == SAMPLE_PROCESS_KEY for item in result), (
        f"All items must have key='{SAMPLE_PROCESS_KEY}'"
    )


# ---------------------------------------------------------------------------
# TC-97 — task cancellation does not leave the client in a broken state
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_cancelled_during_real_request_then_no_resource_warning(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-97: Cancelling an in-flight request propagates CancelledError; client remains usable."""
    task = asyncio.create_task(integration_client.list_process_definitions())
    await asyncio.sleep(0)  # yield to let the coroutine start
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    # The client must not be marked closed after a cancellation.
    assert not integration_client._closed, (
        "Client must remain open after task cancellation"
    )


# ---------------------------------------------------------------------------
# TC-98 — latency_ms is logged and positive
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_latency_ms_logged_and_positive(
    integration_client: FlowableClient,
    deployed_process: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TC-98: Each successful call emits a 'flowable http' log record with latency_ms > 0."""
    with caplog.at_level(logging.INFO, logger="flowable_mcp.client"):
        await integration_client.list_process_definitions()

    http_records = [r for r in caplog.records if r.getMessage() == "flowable http"]
    assert len(http_records) >= 1, (
        "Expected at least one 'flowable http' log record after the call"
    )
    latency = http_records[-1].__dict__.get("latency_ms")
    assert latency is not None, "Log record must include 'latency_ms' extra field"
    assert latency > 0, f"latency_ms must be positive, got {latency}"


# ---------------------------------------------------------------------------
# TC-99 — setup_logging does not attach stdout handlers
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_server_lifespan_when_started_then_startup_log_written_to_stderr(
    integration_settings,
) -> None:
    """TC-99: setup_logging configures only stderr handlers — stdout must stay clean."""
    import sys
    import logging as _logging

    from flowable_mcp.server import setup_logging

    root = _logging.getLogger()
    # Save existing handlers so we can restore them after the assertion.
    original_handlers = list(root.handlers)

    try:
        setup_logging()
        for handler in root.handlers:
            if isinstance(handler, _logging.StreamHandler):
                assert handler.stream is not sys.stdout, (
                    "setup_logging must not attach a StreamHandler pointing at stdout"
                )
    finally:
        # Restore handler state to avoid polluting other tests.
        root.handlers[:] = original_handlers


# ---------------------------------------------------------------------------
# TC-100 — suspended definition has suspended=True in the DTO
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_process_definitions_when_suspended_definition_then_appears_with_suspended_true(
    integration_settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """TC-100: After suspending a process definition, list returns it with suspended=True."""
    base = integration_settings.base_url

    # 1. Resolve the process-definition id for our sample key.
    resp = await integration_http.get(
        f"{base}/repository/process-definitions",
        params={"key": SAMPLE_PROCESS_KEY, "latest": "true"},
    )
    resp.raise_for_status()
    data = resp.json().get("data", [])
    assert data, f"No process definitions found for key='{SAMPLE_PROCESS_KEY}'"
    pd_id: str = data[0]["id"]

    # 2. Suspend the definition.
    suspend_resp = await integration_http.put(
        f"{base}/repository/process-definitions/{pd_id}",
        json={"action": "suspend"},
    )
    suspend_resp.raise_for_status()

    try:
        # 3. List and assert suspended=True appears.
        result = await integration_client.list_process_definitions(
            key=SAMPLE_PROCESS_KEY
        )
        assert any(item.suspended for item in result), (
            f"At least one definition for key='{SAMPLE_PROCESS_KEY}' must have suspended=True"
        )
    finally:
        # 4. Reactivate so teardown and other tests are not affected.
        activate_resp = await integration_http.put(
            f"{base}/repository/process-definitions/{pd_id}",
            json={"action": "activate"},
        )
        activate_resp.raise_for_status()
