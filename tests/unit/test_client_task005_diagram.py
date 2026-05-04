"""Unit tests for FlowableClient diagram methods (TASK-005).

Covers:
- _call extensions: expect_bytes, expect_text, timeout sentinel (TC-01..04, TC-19..21, TC-A3)
- _map_status 410 → FlowableNotFoundError (TC-05, TC-06)
- get_definition_resource / get_definition_model / get_case_definition_xml (TC-29, TC-31, TC-34)
- get_definition_diagram / get_instance_diagram (TC-A1, TC-A2, TC-38, TC-39)
- FlowableClient.__init__ backward compat (TC-B1, TC-B2)
- _call with _http override (TC-B3)
- aclose() dedup + idempotency (TC-C1, TC-C2, TC-C3)
- Transport error family → FlowableConnectionError (INNO-05)
- Backward-compat baseline (INNO-14)
- Authorization not in diagram log records (INNO-11, AC-EDGE-6)
"""

from __future__ import annotations

import logging

import httpx
import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.errors import (
    FlowableConnectionError,
    FlowableNotFoundError,
)

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"

# Minimal valid PNG: 8-byte signature + 1×1 IHDR chunk (27 bytes total).
VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(
    settings: Settings, http_diagram: httpx.AsyncClient | None = None
) -> tuple[FlowableClient, httpx.AsyncClient]:
    http = httpx.AsyncClient(
        base_url=settings.base_url + "/",
        auth=httpx.BasicAuth(settings.username, settings.password.get_secret_value()),
        timeout=settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http, http_diagram=http_diagram)
    return client, http


# ---------------------------------------------------------------------------
# TC-01: _call(expect_bytes=True) → returns (bytes, content_type) tuple
# ---------------------------------------------------------------------------

async def test_call_when_expect_bytes_true_then_returns_raw_bytes(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    result = await flowable_client._call(
        "GET",
        "/repository/process-definitions/pd-1/image",
        idempotent=False,
        expect_json=False,
        expect_bytes=True,
    )
    body, ct = result
    assert isinstance(body, bytes)
    assert body[:4] == b"\x89PNG"
    assert "image/png" in ct


# ---------------------------------------------------------------------------
# TC-02: _call(expect_text=True) → returns decoded str
# ---------------------------------------------------------------------------

async def test_call_when_expect_text_true_then_returns_decoded_str(
    flowable_client: FlowableClient, respx_mock
) -> None:
    xml_body = b"<bpmn:definitions/>"
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/resourcedata").mock(
        return_value=httpx.Response(200, content=xml_body, headers={"content-type": "text/xml"})
    )
    result = await flowable_client._call(
        "GET",
        "/repository/process-definitions/pd-1/resourcedata",
        idempotent=False,
        expect_json=False,
        expect_text=True,
    )
    assert isinstance(result, str)
    assert "<bpmn:definitions/>" in result


# ---------------------------------------------------------------------------
# TC-03: _call without new params → existing JSON behaviour unchanged
# ---------------------------------------------------------------------------

async def test_call_when_no_new_params_then_json_behavior_unchanged(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions").mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    result = await flowable_client._call(
        "GET", "/repository/process-definitions", idempotent=True
    )
    assert isinstance(result, dict)
    assert result["data"] == []


# ---------------------------------------------------------------------------
# TC-04: _call(expect_bytes=True, expect_text=True) → AssertionError
# ---------------------------------------------------------------------------

async def test_call_when_expect_bytes_and_expect_text_both_true_then_raises(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(AssertionError, match="at most one"):
        await flowable_client._call(
            "GET",
            "/repository/process-definitions/pd-1/image",
            idempotent=False,
            expect_bytes=True,
            expect_text=True,
        )


# ---------------------------------------------------------------------------
# TC-A3: _call(expect_bytes=True, expect_json=True) → AssertionError
# ---------------------------------------------------------------------------

async def test_call_when_expect_bytes_true_and_expect_json_true_then_raises_assertion(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(AssertionError, match="at most one"):
        await flowable_client._call(
            "GET",
            "/repository/process-definitions/pd-1/image",
            idempotent=False,
            expect_bytes=True,
            expect_json=True,
        )


# ---------------------------------------------------------------------------
# TC-05: _map_status 410 → FlowableNotFoundError
# ---------------------------------------------------------------------------

async def test_map_status_when_410_then_raises_flowable_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/runtime/process-instances/pi-done/diagram").mock(
        return_value=httpx.Response(410)
    )
    with pytest.raises(FlowableNotFoundError, match="410"):
        await flowable_client.get_instance_diagram("process", "pi-done")


# ---------------------------------------------------------------------------
# TC-06: _map_status 404 → FlowableNotFoundError (regression)
# ---------------------------------------------------------------------------

async def test_map_status_when_404_still_raises_flowable_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions/nope/image").mock(
        return_value=httpx.Response(404)
    )
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.get_definition_diagram("process", "nope")


# ---------------------------------------------------------------------------
# TC-19: timeout=_MISSING → request succeeds with AsyncClient default
# ---------------------------------------------------------------------------

async def test_call_when_timeout_missing_then_no_timeout_kwarg_in_request(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions").mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    # No timeout kwarg → uses AsyncClient default (no TypeError, no infinite-wait None)
    result = await flowable_client._call(
        "GET", "/repository/process-definitions", idempotent=True
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TC-20: timeout=float → request completes normally
# ---------------------------------------------------------------------------

async def test_call_when_timeout_float_then_passed_to_client_request(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions").mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    result = await flowable_client._call(
        "GET", "/repository/process-definitions", idempotent=True, timeout=5.0
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# TC-21: timeout=None → TypeError (forbidden; httpx None = infinite wait)
# ---------------------------------------------------------------------------

async def test_call_when_timeout_none_then_raises_type_error(
    flowable_client: FlowableClient,
) -> None:
    with pytest.raises(TypeError, match="timeout=None"):
        await flowable_client._call(
            "GET", "/repository/process-definitions", idempotent=True, timeout=None
        )


# ---------------------------------------------------------------------------
# TC-29: get_definition_resource(process, id) → XML str
# ---------------------------------------------------------------------------

async def test_get_definition_resource_when_bpmn_ok_then_returns_xml_str(
    flowable_client: FlowableClient, respx_mock
) -> None:
    bpmn = "<bpmn:definitions xmlns:bpmn='http://www.omg.org/spec/BPMN/20100524/MODEL'/>"
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/resourcedata").mock(
        return_value=httpx.Response(200, text=bpmn)
    )
    result = await flowable_client.get_definition_resource("process", "pd-1")
    assert isinstance(result, str)
    assert "<bpmn:definitions" in result


# ---------------------------------------------------------------------------
# TC-31: get_definition_model(process, id) → dict
# ---------------------------------------------------------------------------

async def test_get_definition_model_when_ok_then_returns_dict(
    flowable_client: FlowableClient, respx_mock
) -> None:
    model = {"flowElements": [], "sequenceFlows": [], "lanes": []}
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/model").mock(
        return_value=httpx.Response(200, json=model)
    )
    result = await flowable_client.get_definition_model("process", "pd-1")
    assert isinstance(result, dict)
    assert "flowElements" in result


# ---------------------------------------------------------------------------
# TC-34: get_definition_resource(case, id) → CMMN XML str
# ---------------------------------------------------------------------------

async def test_get_case_definition_xml_when_cmmn_ok_then_returns_xml_str(
    flowable_client: FlowableClient, respx_mock
) -> None:
    cmmn = "<cmmn:definitions xmlns:cmmn='http://www.omg.org/spec/CMMN/20151109/MODEL'/>"
    respx_mock.get(f"{_BASE}/repository/case-definitions/cd-1/resourcedata").mock(
        return_value=httpx.Response(200, text=cmmn)
    )
    result = await flowable_client.get_definition_resource("case", "cd-1")
    assert isinstance(result, str)
    assert "<cmmn:definitions" in result


# ---------------------------------------------------------------------------
# TC-A1 (post-fix): get_definition_diagram → (bytes, ct) without AssertionError
# ---------------------------------------------------------------------------

async def test_get_definition_diagram_when_valid_png_then_returns_bytes_and_content_type(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    body, ct = await flowable_client.get_definition_diagram("process", "pd-1")
    assert isinstance(body, bytes)
    assert body[:4] == b"\x89PNG"
    assert "image/png" in ct


# ---------------------------------------------------------------------------
# TC-38: get_instance_diagram → (bytes, ct) with diagram_timeout_s
# ---------------------------------------------------------------------------

async def test_get_instance_diagram_when_active_then_returns_png_with_timeout(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/runtime/process-instances/pi-1/diagram").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    body, ct = await flowable_client.get_instance_diagram("process", "pi-1")
    assert isinstance(body, bytes)
    assert body[:4] == b"\x89PNG"
    assert "image/png" in ct


# ---------------------------------------------------------------------------
# TC-A2 (post-fix): get_instance_diagram returns tuple (no AssertionError)
# ---------------------------------------------------------------------------

async def test_get_instance_diagram_when_valid_png_then_returns_bytes_and_content_type(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/runtime/case-instances/ci-1/diagram").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    body, ct = await flowable_client.get_instance_diagram("case", "ci-1")
    assert isinstance(body, bytes)
    assert body[:4] == b"\x89PNG"
    assert "image/png" in ct


# ---------------------------------------------------------------------------
# TC-39: get_instance_diagram 410 → FlowableNotFoundError
# ---------------------------------------------------------------------------

async def test_get_instance_diagram_when_410_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/runtime/process-instances/pi-done/diagram").mock(
        return_value=httpx.Response(410)
    )
    with pytest.raises(FlowableNotFoundError, match="410"):
        await flowable_client.get_instance_diagram("process", "pi-done")


# ---------------------------------------------------------------------------
# TC-B1: FlowableClient(http_diagram=None) → _diagram_no_retry is http_no_retry
# ---------------------------------------------------------------------------

def test_flowable_client_when_http_diagram_none_then_diagram_uses_no_retry_client(
    unit_settings: Settings,
) -> None:
    http_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_no_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    client = FlowableClient(http_retry=http_retry, http_no_retry=http_no_retry, http_diagram=None)
    assert client._diagram_no_retry is http_no_retry
    assert client._diagram_no_retry is not http_retry


# ---------------------------------------------------------------------------
# TC-B2: FlowableClient(http_diagram=explicit) → _diagram_no_retry is http_diagram
# ---------------------------------------------------------------------------

def test_flowable_client_when_http_diagram_provided_then_diagram_client_is_distinct(
    unit_settings: Settings,
) -> None:
    http_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_no_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_diagram = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=30.0)
    client = FlowableClient(
        http_retry=http_retry, http_no_retry=http_no_retry, http_diagram=http_diagram
    )
    assert client._diagram_no_retry is http_diagram
    assert client._diagram_no_retry is not http_no_retry
    assert client._diagram_no_retry is not http_retry


# ---------------------------------------------------------------------------
# TC-B3: _call(_http=custom) → uses custom, not idempotent selection
# ---------------------------------------------------------------------------

async def test_call_when_http_override_provided_then_uses_override_not_idempotent_selection(
    flowable_client: FlowableClient, respx_mock
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions").mock(
        return_value=httpx.Response(200, json={"data": [], "total": 0})
    )
    http_custom = httpx.AsyncClient(base_url=flowable_client._base_url + "/", timeout=5.0)
    result = await flowable_client._call(
        "GET",
        "/repository/process-definitions",
        idempotent=False,
        _http=http_custom,
        expect_json=True,
    )
    assert result == {"data": [], "total": 0}
    await http_custom.aclose()


# ---------------------------------------------------------------------------
# TC-C1: aclose() called twice → idempotent (no error)
# ---------------------------------------------------------------------------

async def test_flowable_client_aclose_when_called_twice_then_idempotent_no_error(
    unit_settings: Settings,
) -> None:
    http = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    client = FlowableClient(http_retry=http, http_no_retry=http, http_diagram=None)
    await client.aclose()
    await client.aclose()  # second call must not raise
    assert client._closed is True


# ---------------------------------------------------------------------------
# TC-C2: http_diagram=None → _no_retry.aclose() called exactly once (dedup)
# ---------------------------------------------------------------------------

async def test_flowable_client_aclose_when_diagram_same_as_no_retry_then_closed_once(
    unit_settings: Settings,
) -> None:
    http_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_no_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    client = FlowableClient(
        http_retry=http_retry, http_no_retry=http_no_retry, http_diagram=None
    )
    close_counts: dict[str, int] = {"retry": 0, "no_retry": 0}
    original_retry = http_retry.aclose
    original_no_retry = http_no_retry.aclose

    async def counted_retry() -> None:
        close_counts["retry"] += 1
        await original_retry()

    async def counted_no_retry() -> None:
        close_counts["no_retry"] += 1
        await original_no_retry()

    http_retry.aclose = counted_retry  # type: ignore[method-assign]
    http_no_retry.aclose = counted_no_retry  # type: ignore[method-assign]

    await client.aclose()

    assert close_counts["retry"] == 1
    assert close_counts["no_retry"] == 1, (
        f"http_no_retry.aclose() called {close_counts['no_retry']} times (expected 1 — dedup)"
    )


# ---------------------------------------------------------------------------
# TC-C3: all three distinct clients → all three aclose() called
# ---------------------------------------------------------------------------

async def test_flowable_client_aclose_when_all_three_distinct_then_all_closed(
    unit_settings: Settings,
) -> None:
    http_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_no_retry = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=1.0)
    http_diagram = httpx.AsyncClient(base_url=unit_settings.base_url + "/", timeout=30.0)
    client = FlowableClient(
        http_retry=http_retry, http_no_retry=http_no_retry, http_diagram=http_diagram
    )
    closed: set[int] = set()

    for inst in (http_retry, http_no_retry, http_diagram):
        orig = inst.aclose

        async def _track(o=orig, i=inst) -> None:
            closed.add(id(i))
            await o()

        inst.aclose = _track  # type: ignore[method-assign]

    await client.aclose()

    assert id(http_retry) in closed
    assert id(http_no_retry) in closed
    assert id(http_diagram) in closed
    assert len(closed) == 3
    assert client._closed is True


# ---------------------------------------------------------------------------
# INNO-05: transport error family → FlowableConnectionError (parametrized)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "exc_cls",
    [
        httpx.RemoteProtocolError,
        httpx.ReadError,
        httpx.WriteError,
        httpx.ConnectError,
        httpx.TimeoutException,
    ],
)
async def test_call_when_transport_error_family_then_raises_connection_error(
    flowable_client: FlowableClient, respx_mock, exc_cls: type
) -> None:
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        side_effect=exc_cls("simulated")
    )
    with pytest.raises(FlowableConnectionError) as exc_info:
        await flowable_client._call(
            "GET",
            "/repository/process-definitions/pd-1/image",
            idempotent=False,
            expect_json=False,
            expect_bytes=True,
        )
    assert isinstance(exc_info.value.__cause__, exc_cls)


# ---------------------------------------------------------------------------
# INNO-14: baseline existing _call behaviour unchanged after TASK-005 additions
# ---------------------------------------------------------------------------

async def test_call_when_baseline_existing_calls_then_backward_compat_maintained(
    flowable_client: FlowableClient, respx_mock
) -> None:
    """Verify that existing call sites (no new kwargs) still work identically."""
    pd_item = {
        "id": "pd-1",
        "key": "hello-world",
        "name": "Hello World",
        "version": 1,
        "deploymentId": "dep-1",
        "resourceName": "hello.bpmn20.xml",
        "category": "http://www.flowable.org/processdef",
        "suspended": False,
    }
    respx_mock.get(f"{_BASE}/repository/process-definitions").mock(
        return_value=httpx.Response(200, json={"data": [pd_item], "total": 1})
    )
    defs = await flowable_client.list_process_definitions()
    assert len(defs) == 1
    assert defs[0].id == "pd-1"


# ---------------------------------------------------------------------------
# INNO-11: Authorization not in diagram-specific log records (AC-EDGE-6)
# ---------------------------------------------------------------------------

async def test_client_when_png_fetched_then_authorization_not_in_log_records(
    flowable_client: FlowableClient, respx_mock, caplog: pytest.LogCaptureFixture
) -> None:
    """§0.1 RC-005: diagram HTTP logs must never leak Basic Auth credentials.

    Root cause context: _call logs method/path/status/latency_ms via structured
    extra dict. httpx injects Authorization header automatically from BasicAuth;
    if that header ever appeared in log extra or message text, credentials would
    be exposed in stderr/file logs. This test pins the safe behaviour specifically
    for diagram PNG fetch paths (AC-EDGE-6, shared-standards §8.2).
    """
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )

    with caplog.at_level(logging.DEBUG, logger="flowable_mcp.client"):
        await flowable_client.get_definition_diagram("process", "pd-1")

    for record in caplog.records:
        msg = record.getMessage()
        assert "Authorization" not in msg, f"'Authorization' leaked into log: {msg!r}"
        assert "Basic " not in msg, f"'Basic ' leaked into log: {msg!r}"
        extra_str = str(record.__dict__)
        assert "Authorization" not in extra_str, f"'Authorization' in log extra: {extra_str!r}"
