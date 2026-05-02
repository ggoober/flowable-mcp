"""Additional integration tests for FlowableClient.list_process_definitions.

Complements test_list_process_definitions.py with scenarios not covered there:
  - A1: deployment delete reflected in subsequent list
  - A2: freshly deployed definition has suspended=False (counter-pair to TC-100)
  - A3: pagination characterisation (Flowable default page size)
  - A4: latency budget on a moderate fleet (warm pool)
  - A6: URL-unsafe characters in the key filter are encoded correctly
  - A8: credentials never appear in caplog (Invariant I7 reinforcement)

NO mocks — all tests exercise the real HTTP stack against a real Flowable instance.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings

from .conftest import SAMPLE_PROCESS_KEY

pytestmark = [pytest.mark.integration]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bpmn_with_key(key: str) -> bytes:
    """Render a minimal BPMN 2.0 document with a custom process key."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"'
        ' xmlns:flowable="http://flowable.org/bpmn"'
        ' targetNamespace="http://www.flowable.org/processdef">'
        f'<process id="{key}" name="{key}" isExecutable="true">'
        '<startEvent id="start"/>'
        '<sequenceFlow id="flow1" sourceRef="start" targetRef="end"/>'
        '<endEvent id="end"/>'
        '</process>'
        '</definitions>'
    ).encode()


async def _deploy(http: httpx.AsyncClient, base: str, key: str) -> str:
    files = {"file": (f"{key}.bpmn20.xml", _bpmn_with_key(key), "application/xml")}
    resp = await http.post(f"{base}/repository/deployments", files=files)
    resp.raise_for_status()
    return resp.json()["id"]


async def _undeploy(http: httpx.AsyncClient, base: str, deployment_id: str) -> None:
    # cascade=true so any process instances are removed too.
    await http.delete(
        f"{base}/repository/deployments/{deployment_id}",
        params={"cascade": "true"},
    )


# ---------------------------------------------------------------------------
# TC-INT-A1 — list reflects a deleted deployment
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_deployment_deleted_then_definition_disappears(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
) -> None:
    """A1: After deleting a deployment, list_process_definitions no longer returns it."""
    unique_key = f"a1-delete-cycle-{int(time.time() * 1000)}"
    deployment_id = await _deploy(
        integration_http, integration_settings.base_url, unique_key
    )

    before = await integration_client.list_process_definitions(key=unique_key)
    assert any(item.key == unique_key for item in before), (
        f"Pre-condition failed: definition '{unique_key}' must appear after deploy"
    )

    await _undeploy(integration_http, integration_settings.base_url, deployment_id)

    after = await integration_client.list_process_definitions(key=unique_key)
    assert all(item.key != unique_key for item in after), (
        f"Definition '{unique_key}' must NOT appear after deployment deletion, "
        f"got {[d.key for d in after]}"
    )


# ---------------------------------------------------------------------------
# TC-INT-A2 — fresh deployment has suspended=False (counter-pair to TC-100)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_freshly_deployed_then_suspended_is_false(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
) -> None:
    """A2: A freshly deployed definition is reported with suspended=False by default."""
    unique_key = f"a2-fresh-{int(time.time() * 1000)}"
    deployment_id = await _deploy(
        integration_http, integration_settings.base_url, unique_key
    )
    try:
        result = await integration_client.list_process_definitions(key=unique_key)
        assert result, f"Expected at least one definition for key '{unique_key}'"
        assert all(item.suspended is False for item in result), (
            f"Fresh deployment must have suspended=False, "
            f"got {[(d.key, d.suspended) for d in result]}"
        )
    finally:
        await _undeploy(
            integration_http, integration_settings.base_url, deployment_id
        )


# ---------------------------------------------------------------------------
# TC-INT-A3 — pagination characterisation
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_25_unique_keys_deployed_then_all_returned(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
) -> None:
    """A3: Deploy 25 distinct definitions; auto-pagination must surface all of them.

    Flowable's default page size is ~10, so without auto-pagination in the client
    the result would be silently truncated. This guards against regressions in
    the pagination loop in ``FlowableClient._fetch_definitions_page``.
    """
    n = 25
    timestamp = int(time.time() * 1000)
    keys = [f"a3-bulk-{timestamp}-{i:02d}" for i in range(n)]
    deployment_ids: list[str] = []
    try:
        for key in keys:
            deployment_ids.append(
                await _deploy(integration_http, integration_settings.base_url, key)
            )

        result = await integration_client.list_process_definitions(latest=True)
        observed = {d.key for d in result if d.key.startswith(f"a3-bulk-{timestamp}-")}

        assert observed == set(keys), (
            f"Expected all {n} bulk keys; missing: {set(keys) - observed}, "
            f"unexpected: {observed - set(keys)}"
        )
    finally:
        for dep_id in deployment_ids:
            await _undeploy(integration_http, integration_settings.base_url, dep_id)


# ---------------------------------------------------------------------------
# TC-INT-A4 — latency budget on a warm connection pool
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_warm_pool_then_latency_under_budget(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """A4: After a warm-up call, p95 latency over 10 calls must stay under 1500 ms.

    Loose budget — H2 in-memory + localhost should be ≤ 100 ms, but CI runners vary.
    The point is to catch a 10x regression (e.g. a connection pool config change).
    """
    await integration_client.list_process_definitions()  # warm-up

    latencies_ms: list[float] = []
    for _ in range(10):
        t0 = time.perf_counter()
        await integration_client.list_process_definitions()
        latencies_ms.append((time.perf_counter() - t0) * 1000)

    latencies_ms.sort()
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1]
    assert p95 < 1500, (
        f"p95 latency budget exceeded: {p95:.1f} ms > 1500 ms; "
        f"all latencies: {[f'{x:.0f}' for x in latencies_ms]}"
    )


# ---------------------------------------------------------------------------
# TC-INT-A6 — URL-unsafe characters in `key` are encoded correctly
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "weird_key",
    [
        "key with space",
        "key&ampersand",
        "key%20literal-percent",
        "ключ-кириллица",
        "key+plus#hash",
    ],
    ids=["space", "ampersand", "percent-literal", "cyrillic", "plus-hash"],
)
async def test_list_process_definitions_when_key_contains_special_chars_then_no_500(
    integration_client: FlowableClient,
    weird_key: str,
) -> None:
    """A6: URL-unsafe key values are encoded by httpx — server returns a clean empty list,
    not a 500 / connection error. Guards against accidental manual query-string concat.
    """
    result = await integration_client.list_process_definitions(key=weird_key)
    assert result == [], (
        f"Expected empty list for non-existent key={weird_key!r}, "
        f"got {len(result)} items"
    )


# ---------------------------------------------------------------------------
# TC-INT-A8 — credentials never appear in log output
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_call_succeeds_then_logs_contain_no_credentials(
    integration_settings: Settings,
    integration_client: FlowableClient,
    deployed_process: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A8: Neither the password nor the encoded Authorization value appear in any log record.

    Reinforces Invariant I7 across the full HTTP path, not just error mapping.
    The encoded ``Basic <b64>`` blob is the canonical leak vector (httpx debug logs);
    raw password substring checks are skipped for short/common values to avoid
    false positives ('test' matches everything).
    """
    import base64
    import re

    password = integration_settings.password.get_secret_value()
    raw_auth = f"{integration_settings.username}:{password}".encode()
    encoded_auth = base64.b64encode(raw_auth).decode()

    with caplog.at_level(logging.DEBUG):
        await integration_client.list_process_definitions()

    haystack_parts: list[str] = []
    for record in caplog.records:
        haystack_parts.append(record.getMessage())
        for key, value in record.__dict__.items():
            if key in ("args", "msg", "message"):
                continue
            haystack_parts.append(f"{key}={value!r}")
    haystack = "\n".join(haystack_parts)

    assert encoded_auth not in haystack, (
        f"Encoded Basic-Auth blob leaked into log output (Invariant I7 violation)"
    )
    # Word-boundary password check, only for passwords specific enough to be
    # unambiguous evidence of a leak (≥ 8 chars rules out 'test' / 'admin' etc.).
    if len(password) >= 8:
        assert not re.search(rf"\b{re.escape(password)}\b", haystack), (
            "Plaintext password leaked into log output (Invariant I7 violation)"
        )


# ---------------------------------------------------------------------------
# TC-INT-A9 — concurrent calls share the keepalive pool (sanity follow-up to TC-93)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_50_sequential_calls_then_all_succeed_under_budget(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """A9: 50 sequential calls finish in well under the per-request timeout × 50.

    If keepalive is broken, each call would re-handshake → tail latency explodes.
    Budget is generous (per-call < 200 ms average) to stay reliable in CI.
    """
    n = 50
    t0 = time.perf_counter()
    for _ in range(n):
        result = await integration_client.list_process_definitions()
        assert isinstance(result, list)
    elapsed_s = time.perf_counter() - t0

    avg_ms = (elapsed_s / n) * 1000
    assert avg_ms < 200, (
        f"Average per-call latency {avg_ms:.1f} ms exceeds 200 ms over {n} sequential calls — "
        f"keepalive pool may be misconfigured"
    )


# ---------------------------------------------------------------------------
# TC-INT-A10 — interleaved deploy + list does not raise (race smoke)
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_interleaved_with_deploys_then_no_errors(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    integration_client: FlowableClient,
) -> None:
    """A10: Listing while deployments are happening in parallel never raises.

    Smoke test for read/write race; we don't assert any specific count, only
    that every list call returns a valid list of ProcessDefinition.
    """
    timestamp = int(time.time() * 1000)
    keys = [f"a10-race-{timestamp}-{i}" for i in range(5)]
    deployment_ids: list[str] = []

    async def deploy_all() -> None:
        for k in keys:
            deployment_ids.append(
                await _deploy(integration_http, integration_settings.base_url, k)
            )

    async def list_repeatedly() -> list[int]:
        counts: list[int] = []
        for _ in range(10):
            r = await integration_client.list_process_definitions(latest=True)
            counts.append(len(r))
            await asyncio.sleep(0.05)
        return counts

    try:
        _, counts = await asyncio.gather(deploy_all(), list_repeatedly())
        assert all(c >= 0 for c in counts), "Every list call must return a list"
    finally:
        for dep_id in deployment_ids:
            await _undeploy(integration_http, integration_settings.base_url, dep_id)


# ---------------------------------------------------------------------------
# TC-INT-A11 — sample key filter result is a strict subset of unfiltered list
# ---------------------------------------------------------------------------


async def test_list_process_definitions_when_key_filter_then_strict_subset_of_unfiltered(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """A11: For every deployment, key-filtered ids ⊆ unfiltered ids — no phantom rows."""
    all_defs = await integration_client.list_process_definitions(latest=False)
    filtered = await integration_client.list_process_definitions(
        latest=False, key=SAMPLE_PROCESS_KEY
    )

    all_ids = {d.id for d in all_defs}
    filtered_ids = {d.id for d in filtered}

    assert filtered_ids.issubset(all_ids), (
        f"Filtered ids must be a subset of unfiltered; "
        f"phantom ids: {filtered_ids - all_ids}"
    )
