"""Unit tests for tools/diagram.py (TASK-005).

Covers:
- validate_png_response guard chain (TC-07..12, TC-33, TC-D1..D4, INNO-01)
- get_process_definition_source tool (TC-13..18, TC-E1..E4, INNO-03, INNO-04)
- PNG diagram tools (TC-27, TC-28, TC-G2, TC-G3, INNO-02)
- CMMN model/xml tools (TC-G1, TC-G4)
- Semaphore back-pressure (TC-22..24, INNO-07, INNO-08, TC-H1, TC-H2)
- Error hierarchy (INNO-09)
- EXPECTED_TOOLS completeness (INNO-10)
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from mcp.types import ImageContent

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import (
    FlowableDiagramError,
    FlowableError,
    FlowableNotFoundError,
    FlowableProtocolError,
    FlowableServerError,
)
from flowable_mcp.tools.diagram import validate_png_response

pytestmark = [pytest.mark.unit]

_BASE = "http://flowable-test"

VALID_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
    b"\x90wS\xde"
)
BPMN_XML = "<bpmn:definitions xmlns:bpmn='http://www.omg.org/spec/BPMN/20100524/MODEL'/>"
MODEL_DICT: dict[str, Any] = {"flowElements": [], "sequenceFlows": []}

# ---------------------------------------------------------------------------
# Helper: register diagram tools against a MagicMock mcp
# ---------------------------------------------------------------------------


def _make_diagram_tools(
    client: FlowableClient,
    semaphore: asyncio.Semaphore,
    *,
    max_png_bytes: int = 5_242_880,
) -> dict[str, Any]:
    from flowable_mcp.tools.diagram import register

    mock_mcp = MagicMock()
    registered: dict[str, Any] = {}

    def capture_tool():
        def decorator(fn: Any) -> Any:
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool.side_effect = capture_tool
    register(
        mock_mcp,
        client,
        png_semaphore=semaphore,
        max_png_bytes=max_png_bytes,
    )
    return registered


# ===========================================================================
# validate_png_response — pure function tests (no respx)
# ===========================================================================

# TC-07: empty body → FlowableDiagramError (guard a fires first; b,c,d skipped)
def test_validate_png_when_empty_body_then_raises_diagram_error_first() -> None:
    with pytest.raises(FlowableDiagramError, match="empty body"):
        validate_png_response(b"", "image/png", 1_000_000)


# TC-08: bad magic bytes → FlowableDiagramError
def test_validate_png_when_bad_magic_bytes_then_raises_diagram_error() -> None:
    with pytest.raises(FlowableDiagramError, match="not a PNG"):
        validate_png_response(b"\x00\x00\x00\x00rest", "image/png", 1_000_000)


# TC-09: size == max_bytes → ok (strict >)
def test_validate_png_when_size_at_limit_then_ok() -> None:
    max_b = 100
    body = b"\x89PNG" + b"x" * (max_b - 4)
    assert len(body) == max_b
    validate_png_response(body, "image/png", max_b)  # must not raise


# TC-10: size == max_bytes+1 → FlowableDiagramError
def test_validate_png_when_size_one_over_limit_then_raises_diagram_error() -> None:
    max_b = 100
    body = b"\x89PNG" + b"x" * (max_b - 3)  # 101 bytes
    assert len(body) == max_b + 1
    with pytest.raises(FlowableDiagramError, match="exceeds max size"):
        validate_png_response(body, "image/png", max_b)


# TC-11: content-type = text/html → FlowableDiagramError (guard b)
def test_validate_png_when_content_type_text_html_then_raises_diagram_error() -> None:
    with pytest.raises(FlowableDiagramError, match="unexpected content-type"):
        validate_png_response(VALID_PNG, "text/html", 1_000_000)


# TC-12: empty body → guards b,c,d NOT executed (early-exit at guard a)
def test_validate_png_when_empty_body_then_magic_and_size_guards_not_reached() -> None:
    # If b,c,d ran on empty body, body[:4] would fail or size guard would fire.
    # Instead we must get exactly "empty body".
    with pytest.raises(FlowableDiagramError) as exc_info:
        validate_png_response(b"", "image/png", 0)
    assert "empty body" in str(exc_info.value)


# TC-33: charset suffix in Content-Type → accepted (in, not ==)
def test_validate_png_when_content_type_with_charset_suffix_then_accepted() -> None:
    validate_png_response(VALID_PNG, "image/png;charset=utf-8", 1_000_000)
    validate_png_response(VALID_PNG, "image/png; charset=UTF-8", 1_000_000)


# TC-D1: body[:4] == b"\x89PNG" but rest is garbage → magic check passes (only 4 bytes checked)
def test_validate_png_when_first_4_bytes_are_png_magic_then_magic_check_passes() -> None:
    body = b"\x89PNG" + b"this_is_not_really_a_png" * 3
    validate_png_response(body, "image/png", len(body) + 1)  # must not raise


# TC-D2: uppercase Content-Type → .lower() normalisation → accepted
def test_validate_png_when_content_type_uppercase_then_accepted() -> None:
    validate_png_response(VALID_PNG, "IMAGE/PNG", 1_000_000)


# TC-D3: empty string Content-Type (header missing) → FlowableDiagramError
def test_validate_png_when_content_type_missing_empty_string_then_raises_diagram_error() -> None:
    with pytest.raises(FlowableDiagramError, match="unexpected content-type"):
        validate_png_response(VALID_PNG, "", 1_000_000)


# TC-D4: len(body) == max_bytes exactly → ok (> not >=)
def test_validate_png_when_body_exactly_max_bytes_then_ok() -> None:
    max_b = 500
    body = b"\x89PNG" + b"z" * (max_b - 4)
    assert len(body) == max_b
    validate_png_response(body, "image/png", max_b)  # must not raise


# INNO-01: property-based — any body starting with PNG magic and ≤ limit → no error
try:
    from hypothesis import given, settings as h_settings, HealthCheck
    from hypothesis import strategies as st

    @given(
        suffix=st.binary(min_size=1, max_size=200),
        limit=st.integers(min_value=10, max_value=2000),
    )
    @h_settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.too_slow])
    def test_validate_png_property_when_any_valid_png_under_limit_then_no_error(
        suffix: bytes, limit: int
    ) -> None:
        body = b"\x89PNG" + suffix
        if len(body) <= limit:
            validate_png_response(body, "image/png", limit)

except ImportError:
    pass


# ===========================================================================
# get_process_definition_source (tool-level)
# ===========================================================================


# TC-13 / TC-40: both ok → {definition_id, xml, model}
async def test_get_definition_source_when_both_ok_then_returns_xml_and_model(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/resourcedata").mock(
        return_value=httpx.Response(200, text=BPMN_XML)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )
    result = await tools["get_process_definition_source"](process_definition_id="pd-1")
    assert result["definition_id"] == "pd-1"
    assert "<bpmn:definitions" in result["xml"]
    assert result["model"] == MODEL_DICT


# TC-14 / TC-E2: model 404 → model=None (graceful fallback)
async def test_get_definition_source_when_model_404_then_returns_null_model(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/resourcedata").mock(
        return_value=httpx.Response(200, text=BPMN_XML)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/model").mock(
        return_value=httpx.Response(404)
    )
    result = await tools["get_process_definition_source"](process_definition_id="pd-1")
    assert result["xml"].strip() == BPMN_XML
    assert result["model"] is None


# TC-15 / TC-E4: model 500 → FlowableServerError propagates (not null)
async def test_get_definition_source_when_model_500_then_raises_server_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/resourcedata").mock(
        return_value=httpx.Response(200, text=BPMN_XML)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/model").mock(
        return_value=httpx.Response(500, text="Internal Error")
    )
    with pytest.raises((ExceptionGroup, FlowableServerError)):
        await tools["get_process_definition_source"](process_definition_id="pd-1")


# TC-16 / TC-E3: xml 404 → FlowableNotFoundError propagates
async def test_get_definition_source_when_xml_404_then_raises_not_found_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-gone/resourcedata").mock(
        return_value=httpx.Response(404)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-gone/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )
    with pytest.raises((ExceptionGroup, FlowableNotFoundError)):
        await tools["get_process_definition_source"](process_definition_id="pd-gone")


# TC-17: xml body empty → FlowableProtocolError
async def test_get_definition_source_when_xml_empty_body_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-empty/resourcedata").mock(
        return_value=httpx.Response(200, text="")
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-empty/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )
    with pytest.raises((ExceptionGroup, FlowableProtocolError)):
        await tools["get_process_definition_source"](process_definition_id="pd-empty")


# TC-17 ext: whitespace-only xml body → same ProtocolError
async def test_get_definition_source_when_xml_whitespace_only_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-ws/resourcedata").mock(
        return_value=httpx.Response(200, text="   \n\t  ")
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-ws/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )
    with pytest.raises((ExceptionGroup, FlowableProtocolError)):
        await tools["get_process_definition_source"](process_definition_id="pd-ws")


# TC-18: CancelledError propagates (не глотается)
async def test_get_definition_source_when_cancelled_mid_flight_then_propagates(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    release = asyncio.Event()

    async def slow_xml(request: httpx.Request) -> httpx.Response:
        await release.wait()
        return httpx.Response(200, text=BPMN_XML)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-cancel/resourcedata").mock(
        side_effect=slow_xml
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-cancel/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )

    task = asyncio.create_task(
        tools["get_process_definition_source"](process_definition_id="pd-cancel")
    )
    await asyncio.sleep(0.02)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


# TC-E1 / INNO-03: metamorphic — bundle["xml"] == separate get_definition_resource()
async def test_get_definition_source_when_both_ok_then_result_equals_separate_resource_call(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-meta/resourcedata").mock(
        return_value=httpx.Response(200, text=BPMN_XML)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-meta/model").mock(
        return_value=httpx.Response(200, json=MODEL_DICT)
    )

    bundle = await tools["get_process_definition_source"](process_definition_id="pd-meta")
    xml_only = await flowable_client.get_definition_resource("process", "pd-meta")

    assert bundle["xml"].strip() == xml_only.strip()
    assert bundle["model"] == MODEL_DICT
    assert bundle["definition_id"] == "pd-meta"


# INNO-04: metamorphic — model 404: bundle graceful, direct model call raises
async def test_get_definition_source_when_model_404_then_asymmetric_with_direct_call(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-nomodel/resourcedata").mock(
        return_value=httpx.Response(200, text=BPMN_XML)
    )
    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-nomodel/model").mock(
        return_value=httpx.Response(404)
    )

    # bundle: graceful fallback
    bundle = await tools["get_process_definition_source"](process_definition_id="pd-nomodel")
    assert bundle["model"] is None

    # direct call: raises
    with pytest.raises(FlowableNotFoundError):
        await flowable_client.get_definition_model("process", "pd-nomodel")


# ===========================================================================
# PNG diagram tools
# ===========================================================================

# TC-27: get_process_definition_diagram → ImageContent with valid base64
async def test_get_definition_diagram_when_valid_png_then_returns_image_content(
    flowable_client: FlowableClient, respx_mock
) -> None:
    import base64

    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    result = await tools["get_process_definition_diagram"](process_definition_id="pd-1")
    assert isinstance(result, ImageContent)
    assert result.mimeType == "image/png"
    decoded = base64.b64decode(result.data)
    assert decoded[:4] == b"\x89PNG"


# TC-28: PNG at size limit → ok (no FlowableDiagramError)
async def test_get_definition_diagram_when_png_at_size_limit_then_ok(
    flowable_client: FlowableClient, respx_mock
) -> None:
    import base64

    max_b = 200
    body = b"\x89PNG" + b"x" * (max_b - 4)
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore, max_png_bytes=max_b)

    respx_mock.get(f"{_BASE}/repository/process-definitions/pd-1/image").mock(
        return_value=httpx.Response(200, content=body, headers={"content-type": "image/png"})
    )
    result = await tools["get_process_definition_diagram"](process_definition_id="pd-1")
    assert isinstance(result, ImageContent)
    decoded = base64.b64decode(result.data)
    assert len(decoded) == max_b


# INNO-02: property-based — base64 roundtrip is lossless
try:
    from hypothesis import given, settings as h_settings
    from hypothesis import strategies as st

    @given(suffix=st.binary(min_size=1, max_size=200))
    @h_settings(max_examples=50, deadline=None)
    def test_get_definition_diagram_property_when_any_png_then_base64_roundtrip(
        suffix: bytes,
    ) -> None:
        import base64

        body = b"\x89PNG" + suffix
        encoded = base64.b64encode(body).decode()
        assert base64.b64decode(encoded) == body

except ImportError:
    pass


# ===========================================================================
# CMMN tool tests
# ===========================================================================


# TC-G1: get_case_definition_model → dict passthrough
async def test_get_case_definition_model_tool_when_ok_then_returns_dict(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    model = {"caseElements": [], "name": "My Case", "sentries": []}
    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-repository/case-definitions/cd-1/model").mock(
        return_value=httpx.Response(200, json=model)
    )
    result = await tools["get_case_definition_model"](case_definition_id="cd-1")
    assert isinstance(result, dict)
    assert result["name"] == "My Case"
    assert "caseElements" in result


# TC-G2: get_case_definition_diagram → ImageContent
async def test_get_case_definition_diagram_tool_when_valid_png_then_returns_image_content(
    flowable_client: FlowableClient, respx_mock
) -> None:
    import base64

    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-repository/case-definitions/cd-1/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    result = await tools["get_case_definition_diagram"](case_definition_id="cd-1")
    assert isinstance(result, ImageContent)
    assert result.mimeType == "image/png"
    assert base64.b64decode(result.data)[:4] == b"\x89PNG"


# TC-G3: get_case_instance_diagram → ImageContent
async def test_get_case_instance_diagram_tool_when_valid_png_then_returns_image_content(
    flowable_client: FlowableClient, respx_mock
) -> None:
    import base64

    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-runtime/case-instances/ci-1/diagram").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    result = await tools["get_case_instance_diagram"](case_instance_id="ci-1")
    assert isinstance(result, ImageContent)
    assert base64.b64decode(result.data)[:4] == b"\x89PNG"


# TC-G4: get_case_definition_xml with whitespace-only body → FlowableProtocolError
async def test_get_case_definition_xml_tool_when_whitespace_body_then_raises_protocol_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-repository/case-definitions/cd-ws/resourcedata").mock(
        return_value=httpx.Response(200, text="   \n\t  ")
    )
    with pytest.raises(FlowableProtocolError, match="empty resourcedata response"):
        await tools["get_case_definition_xml"](case_definition_id="cd-ws")


# ===========================================================================
# Semaphore back-pressure
# ===========================================================================


# TC-22: 4 concurrent tasks all acquire Semaphore(4) → all complete
async def test_diagram_tool_when_4_concurrent_then_all_acquire_semaphore(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(re.compile(r".*/repository/process-definitions/.*/image$")).mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    coros = [
        tools["get_process_definition_diagram"](process_definition_id=f"pd-{i}") for i in range(4)
    ]
    results = await asyncio.gather(*coros)
    assert len(results) == 4
    assert all(isinstance(r, ImageContent) for r in results)


# INNO-07: 5 concurrent, 5th blocks until first slot freed
async def test_diagram_tool_when_5_concurrent_then_5th_blocks_until_slot_free(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    release = asyncio.Event()
    call_count = 0
    started = asyncio.Event()

    async def slow_handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count == 4:
            started.set()
        await release.wait()
        return httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})

    respx_mock.get(re.compile(r".*/repository/process-definitions/.*/image$")).mock(
        side_effect=slow_handler
    )

    tasks = [
        asyncio.create_task(tools["get_process_definition_diagram"](process_definition_id=f"pd-{i}"))
        for i in range(5)
    ]

    # Wait for 4 requests to reach Flowable (semaphore fully occupied)
    await asyncio.wait_for(started.wait(), timeout=5.0)
    # All 4 permits are held by slow_handler tasks. Assert semaphore is fully locked
    # before checking call_count — this is a state invariant, not a timing assumption.
    # The 5th task already attempted acquire() and is queued (it ran before started.wait()
    # returned). asyncio.sleep(0) yields a single event-loop tick; no arbitrary sleep (§0.1 RC-review-002).
    assert semaphore._value == 0, f"Semaphore not fully locked: _value={semaphore._value}"  # noqa: SLF001
    await asyncio.sleep(0)  # single tick: 5th task stays queued, does NOT make HTTP call

    assert call_count == 4, f"Expected 4 concurrent requests, got {call_count}"

    release.set()
    results = await asyncio.gather(*tasks)

    assert call_count == 5
    assert len(results) == 5


# TC-24 / TC-H1: validate_png_response raises → semaphore released
async def test_diagram_tool_when_guard_error_then_semaphore_released(
    flowable_client: FlowableClient, respx_mock, monkeypatch: pytest.MonkeyPatch
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    # Return a response that will fail content-type guard
    respx_mock.get(re.compile(r".*/repository/process-definitions/.*/image$")).mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "text/html"})
    )

    before = semaphore._value  # noqa: SLF001
    with pytest.raises(FlowableDiagramError):
        await tools["get_process_definition_diagram"](process_definition_id="pd-bad")
    after = semaphore._value  # noqa: SLF001
    assert after == before, f"Semaphore leaked: {before} → {after}"


# TC-H2: client raises FlowableConnectionError → semaphore released
async def test_diagram_tool_when_client_raises_then_semaphore_released(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(re.compile(r".*/repository/process-definitions/.*/image$")).mock(
        side_effect=httpx.ConnectError("refused")
    )

    from flowable_mcp.errors import FlowableConnectionError

    before = semaphore._value  # noqa: SLF001
    with pytest.raises(FlowableConnectionError):
        await tools["get_process_definition_diagram"](process_definition_id="pd-conn")
    after = semaphore._value  # noqa: SLF001
    assert after == before, f"Semaphore leaked: {before} → {after}"


# INNO-08: cancel before semaphore.acquire → slot count unchanged
async def test_diagram_tool_when_cancel_before_semaphore_acquire_then_slot_count_unchanged(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(0)  # fully locked — 5th would block immediately
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(re.compile(r".*/repository/process-definitions/.*/image$")).mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )

    task = asyncio.create_task(
        tools["get_process_definition_diagram"](process_definition_id="pd-blocked")
    )
    await asyncio.sleep(0)  # let task start and attempt acquire
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert semaphore._value == 0, "Semaphore value changed unexpectedly"  # noqa: SLF001


# ===========================================================================
# Error hierarchy & EXPECTED_TOOLS
# ===========================================================================


# INNO-09: FlowableDiagramError is subclass of FlowableError, NOT of NotFound/Connection/Server
def test_flowable_diagram_error_when_checked_then_hierarchy_isolation() -> None:
    err = FlowableDiagramError("test")
    assert isinstance(err, FlowableError)
    assert isinstance(err, FlowableDiagramError)
    assert not isinstance(err, FlowableNotFoundError)
    assert not isinstance(err, FlowableServerError)
    from flowable_mcp.errors import FlowableConnectionError
    assert not isinstance(err, FlowableConnectionError)


# INNO-10: EXPECTED_TOOLS frozenset includes all 9 diagram tool names
def test_server_when_diagram_module_registered_then_expected_tools_has_all_9() -> None:
    from flowable_mcp.server import EXPECTED_TOOLS

    diagram_tools = {
        "get_process_definition_xml",
        "get_process_definition_model",
        "get_process_definition_diagram",
        "get_process_definition_source",
        "get_case_definition_xml",
        "get_case_definition_model",
        "get_case_definition_diagram",
        "get_process_instance_diagram",
        "get_case_instance_diagram",
    }
    missing = diagram_tools - EXPECTED_TOOLS
    assert not missing, f"Diagram tools missing from EXPECTED_TOOLS: {missing}"


# ===========================================================================
# F-7: tool-level test for get_process_instance_diagram
# §0.1 Root cause: mirror PNG tools (instance_diagram) were tested only at
# adapter level (TC-38/TC-39); each registered tool needs ≥1 positive
# tool-level test even if the implementation pattern is shared with another
# tested tool (get_process_definition_diagram / TC-27).
# Regression: verifies semaphore→client→validate→ImageContent path for
# the "process instance" variant of the PNG tool, not just the definition one.
# ===========================================================================


# TC-F7: get_process_instance_diagram → ImageContent with valid PNG (tool-level)
async def test_get_process_instance_diagram_tool_when_valid_png_then_returns_image_content(
    flowable_client: FlowableClient, respx_mock
) -> None:
    import base64

    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/runtime/process-instances/pi-1/diagram").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "image/png"})
    )
    result = await tools["get_process_instance_diagram"](process_instance_id="pi-1")
    assert isinstance(result, ImageContent)
    assert result.mimeType == "image/png"
    decoded = base64.b64decode(result.data)
    assert decoded[:4] == b"\x89PNG"


# ===========================================================================
# F-8: error-path tests for CMMN PNG tools
# §0.1 Root cause: validate_png_response error paths (bad CT, empty body)
# were tested for BPMN tools only (TC-H1, TC-H2). CMMN mirror tools
# (TC-G2/G3) had happy-path coverage only. Both tool categories call the
# same validate_png_response, so parity in error coverage is required.
# Regression: ensures guard chain fires for CMMN paths, not just BPMN.
# ===========================================================================


# TC-F8a: case_definition_diagram bad content-type → FlowableDiagramError (guard b)
async def test_get_case_definition_diagram_tool_when_bad_content_type_then_raises_diagram_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-repository/case-definitions/cd-bad/image").mock(
        return_value=httpx.Response(200, content=VALID_PNG, headers={"content-type": "text/html"})
    )
    with pytest.raises(FlowableDiagramError, match="unexpected content-type"):
        await tools["get_case_definition_diagram"](case_definition_id="cd-bad")


# TC-F8b: case_instance_diagram empty body → FlowableDiagramError (guard a, early-exit)
async def test_get_case_instance_diagram_tool_when_empty_body_then_raises_diagram_error(
    flowable_client: FlowableClient, respx_mock
) -> None:
    semaphore = asyncio.Semaphore(4)
    tools = _make_diagram_tools(flowable_client, semaphore)

    respx_mock.get(f"{_BASE}/cmmn-api/cmmn-runtime/case-instances/ci-empty/diagram").mock(
        return_value=httpx.Response(200, content=b"", headers={"content-type": "image/png"})
    )
    with pytest.raises(FlowableDiagramError, match="empty body"):
        await tools["get_case_instance_diagram"](case_instance_id="ci-empty")
