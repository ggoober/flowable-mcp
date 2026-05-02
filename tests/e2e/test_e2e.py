"""End-to-end tests for flowable-mcp.

Covers the full contract:
  MCP client → flowable-mcp server → Flowable REST → MCP response

Two transports are exercised (see ``conftest.py`` for fixtures):
  - In-process ``fastmcp.Client(mcp)`` for the bulk of contract checks.
  - Real subprocess (``python -m flowable_mcp``) for tests where the
    process boundary itself is the subject (СТ-3 stdout silence, EOF shutdown).

Run with: ``pytest -m e2e tests/e2e/``
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastmcp import Client

from .conftest import SAMPLE_PROCESS_KEY, spawn_mcp_subprocess

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]


def _extract_definitions(result) -> list[dict]:
    """Pull a list of ProcessDefinition-shaped dicts out of a CallToolResult.

    fastmcp serialises typed return values into ``structured_content`` (preferred)
    and falls back to JSON in ``content[0].text``.
    """
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return list(structured["result"])
    if isinstance(structured, list):
        return list(structured)

    data = getattr(result, "data", None)
    if isinstance(data, list):
        # fastmcp may return list[ProcessDefinition] — convert to plain dicts.
        return [
            item.model_dump(by_alias=True) if hasattr(item, "model_dump") else item
            for item in data
        ]

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict) and "result" in parsed:
                return list(parsed["result"])
    raise AssertionError(f"Could not extract definitions from result: {result!r}")


# ---------------------------------------------------------------------------
# TC-86 — basic list via MCP roundtrip
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_bpmn_deployed_then_valid_result(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """TC-86: tool returns a non-empty array; every item has id/key/version/deploymentId."""
    result = await mcp_client.call_tool("list_process_definitions", {})
    items = _extract_definitions(result)

    assert items, "Expected at least one process definition after deployment"
    for item in items:
        assert item.get("id"), f"id must be non-empty: {item}"
        assert item.get("key"), f"key must be non-empty: {item}"
        assert isinstance(item.get("version"), int), f"version must be int: {item}"
        assert item.get("deploymentId"), f"deploymentId must be non-empty: {item}"


# ---------------------------------------------------------------------------
# TC-87 — schema matches DTO (every item deserialises to ProcessDefinition)
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_result_then_schema_matches_dto(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """TC-87: each result item matches the ProcessDefinition pydantic schema."""
    from flowable_mcp.models import ProcessDefinition

    result = await mcp_client.call_tool("list_process_definitions", {})
    items = _extract_definitions(result)
    assert items, "Pre-condition: at least one definition expected"

    for item in items:
        # ProcessDefinition has populate_by_name=True so both alias and snake_case work.
        ProcessDefinition.model_validate(item)


# ---------------------------------------------------------------------------
# TC-88 — latest=True forwarded → no duplicate keys
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_latest_true_param_then_no_duplicate_keys(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """TC-88: latest=True passed via MCP returns at most one entry per key."""
    result = await mcp_client.call_tool("list_process_definitions", {"latest": True})
    items = _extract_definitions(result)

    keys = [item["key"] for item in items]
    assert len(keys) == len(set(keys)), (
        f"latest=True must not return duplicate keys; got {keys}"
    )


# ---------------------------------------------------------------------------
# TC-89 — key filter forwarded
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_key_provided_then_only_matching(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """TC-89: key= filter through MCP returns only definitions with that key."""
    result = await mcp_client.call_tool(
        "list_process_definitions", {"key": SAMPLE_PROCESS_KEY}
    )
    items = _extract_definitions(result)

    assert items, f"Expected ≥1 definition for key='{SAMPLE_PROCESS_KEY}'"
    assert all(item["key"] == SAMPLE_PROCESS_KEY for item in items), (
        f"All items must have key='{SAMPLE_PROCESS_KEY}', got {[i['key'] for i in items]}"
    )


# ---------------------------------------------------------------------------
# TC-90 — unknown key returns empty array
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_unknown_key_then_mcp_returns_empty_array(
    mcp_client: Client,
) -> None:
    """TC-90: non-existent key returns an empty array (NOT an MCP error)."""
    result = await mcp_client.call_tool(
        "list_process_definitions", {"key": "no-such-process-xyzzy-99999"}
    )
    assert not getattr(result, "is_error", False), (
        f"Unknown key must NOT produce isError; got {result!r}"
    )
    items = _extract_definitions(result)
    assert items == [], f"Expected empty list for unknown key, got {items}"


# ---------------------------------------------------------------------------
# TC-91 — wrong credentials → MCP error response, no plaintext password
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_wrong_credentials_then_mcp_returns_error(
    e2e_settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TC-91: invalid Basic Auth → tool returns isError; password not echoed."""
    bad_password = "wrong-password-xyz-12345"
    monkeypatch.setenv("FLOWABLE_PASSWORD", bad_password)

    from flowable_mcp.server import mcp

    async with Client(mcp) as client:
        result = await client.call_tool(
            "list_process_definitions", {}, raise_on_error=False
        )

    assert getattr(result, "is_error", False), (
        f"Wrong creds must produce an MCP error response, got {result!r}"
    )
    haystack = json.dumps(
        [getattr(b, "text", "") for b in (result.content or [])]
    )
    assert bad_password not in haystack, (
        "Plaintext password leaked in MCP error response (Invariant I7)"
    )


# ---------------------------------------------------------------------------
# E2E-A1 — Flowable down → connection error surfaces as MCP error
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_flowable_down_then_mcp_returns_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E2E-A1: server pointed at a closed port returns isError; subsequent calls still work."""
    monkeypatch.setenv("FLOWABLE_BASE_URL", "http://127.0.0.1:19999/flowable-rest/service")

    from flowable_mcp.server import mcp

    async with Client(mcp) as client:
        first = await client.call_tool(
            "list_process_definitions", {}, raise_on_error=False
        )
        second = await client.call_tool(
            "list_process_definitions", {}, raise_on_error=False
        )

    assert getattr(first, "is_error", False), "Flowable-down call must return isError"
    assert getattr(second, "is_error", False), "Server must stay alive after a failed call"


# ---------------------------------------------------------------------------
# E2E-A2 — three concurrent tool calls all complete
# ---------------------------------------------------------------------------


async def test_e2e_list_process_definitions_when_three_concurrent_calls_then_all_succeed(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    """E2E-A2: 3 in-flight tool calls over the same MCP session all return non-empty arrays."""
    results = await asyncio.gather(
        *[mcp_client.call_tool("list_process_definitions", {}) for _ in range(3)]
    )
    for r in results:
        items = _extract_definitions(r)
        assert items, "Each concurrent call must return ≥1 definition"


# ---------------------------------------------------------------------------
# E2E-A4 — tools/list advertises list_process_definitions schema
# ---------------------------------------------------------------------------


async def test_e2e_tools_list_when_called_then_advertises_list_process_definitions_schema(
    mcp_client: Client,
) -> None:
    """E2E-A4: tools/list exposes latest:bool + key:str?, NOT ctx."""
    tools = await mcp_client.list_tools()
    by_name = {t.name: t for t in tools}
    assert "list_process_definitions" in by_name, (
        f"Expected 'list_process_definitions' in tools/list, got {list(by_name)}"
    )

    tool = by_name["list_process_definitions"]
    schema = tool.inputSchema or {}
    props = schema.get("properties", {}) or {}

    assert "latest" in props, f"'latest' missing from inputSchema, got {list(props)}"
    assert props["latest"].get("type") == "boolean", (
        f"'latest' must be boolean, got {props['latest']}"
    )
    assert "key" in props, f"'key' missing from inputSchema, got {list(props)}"
    assert "ctx" not in props, "'ctx' must NOT be exposed as a tool parameter"


# ---------------------------------------------------------------------------
# TC-92 — server stdout contains only JSON-RPC frames (real subprocess)
# ---------------------------------------------------------------------------


async def test_e2e_server_when_tool_invoked_then_stdout_contains_only_json_rpc_frames(
    e2e_deployed_process: str,
) -> None:
    """TC-92: every line on stdout is a valid JSON-RPC 2.0 object — no log noise (СТ-3)."""
    async with spawn_mcp_subprocess() as srv:
        await srv.initialize()
        response = await srv.request(
            "tools/call",
            {"name": "list_process_definitions", "arguments": {}},
        )

    assert "result" in response or "error" in response, (
        f"Tool call response must follow JSON-RPC shape, got {response}"
    )

    assert srv.stdout_lines, "Expected at least one stdout line during the session"
    for line in srv.stdout_lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"Non-JSON-RPC line on stdout (СТ-3 violation): {line!r}"
            ) from exc
        assert isinstance(obj, dict), f"stdout frame must be a JSON object: {obj!r}"
        assert obj.get("jsonrpc") == "2.0", (
            f"stdout frame must have jsonrpc='2.0': {obj!r}"
        )


# ---------------------------------------------------------------------------
# E2E-A3 — graceful shutdown when stdin closed
# ---------------------------------------------------------------------------


async def test_e2e_server_when_stdin_closed_after_call_then_exits_cleanly(
    e2e_deployed_process: str,
) -> None:
    """E2E-A3: closing stdin after a successful call leads to exit code 0 within 5s."""
    async with spawn_mcp_subprocess() as srv:
        await srv.initialize()
        response = await srv.request(
            "tools/call",
            {"name": "list_process_definitions", "arguments": {}},
        )
        assert "result" in response, f"Tool call must succeed; got {response}"

        await srv.close_stdin()
        try:
            await asyncio.wait_for(srv.proc.wait(), timeout=5.0)
        except TimeoutError:
            srv.proc.kill()
            raise AssertionError("Server did not exit within 5s after stdin EOF")

        exit_code = srv.proc.returncode
        stderr_text = bytes(srv.stderr_buf).decode("utf-8", errors="replace")

    assert exit_code == 0, (
        f"Expected exit code 0 after stdin EOF, got {exit_code}.\nstderr:\n{stderr_text}"
    )
    assert "Traceback" not in stderr_text, (
        f"Unexpected traceback on stderr during shutdown:\n{stderr_text}"
    )
    assert "ResourceWarning" not in stderr_text, (
        f"ResourceWarning on stderr indicates leaked async resources:\n{stderr_text}"
    )
