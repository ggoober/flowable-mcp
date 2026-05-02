"""E2E test stubs for flowable-mcp.

These tests document the end-to-end contract:
  MCP client (stdio) → flowable-mcp server → Flowable REST → MCP response

All tests are marked xfail because E2E infrastructure (stdio MCP client harness)
is not yet specified. They serve as living documentation and will be promoted to
real tests once the E2E setup is defined.

Run with: pytest -m e2e tests/e2e/
"""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.e2e]


# ---------------------------------------------------------------------------
# TC-86 — basic list via MCP stdio roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_bpmn_deployed_then_valid_result() -> None:
    """TC-86: MCP client → stdio server → Flowable → ProcessDefinition[] roundtrip.

    Contract:
    - Invoke tool 'list_process_definitions' via MCP stdio transport.
    - Expect a non-empty JSON array of ProcessDefinition objects.
    - All items must have non-empty id, key, version, deploymentId.
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-87 — tool result is JSON-serialisable ProcessDefinition array
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_result_then_schema_matches_dto() -> None:
    """TC-87: Tool output schema matches ProcessDefinition DTO fields.

    Contract:
    - Invoke 'list_process_definitions' via MCP.
    - Each result item deserialises to ProcessDefinition without validation errors.
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-88 — latest=True parameter forwarded correctly through MCP layer
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_latest_true_param_then_no_duplicate_keys() -> None:
    """TC-88: latest=True passed via MCP tool invocation returns at most one entry per key.

    Contract:
    - Invoke 'list_process_definitions' with argument latest=True via MCP.
    - No two result items share the same key value.
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-89 — key filter parameter forwarded correctly through MCP layer
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_key_provided_then_only_matching() -> None:
    """TC-89: key= filter passed via MCP returns only definitions with that key.

    Contract:
    - Invoke 'list_process_definitions' with argument key='hello-world' via MCP.
    - All returned items have key == 'hello-world'.
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-90 — unknown key returns empty result via MCP
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_unknown_key_then_mcp_returns_empty_array() -> None:
    """TC-90: Non-existent key passed via MCP returns an empty array (not an error).

    Contract:
    - Invoke 'list_process_definitions' with key='no-such-process-xyzzy' via MCP.
    - Result is an empty JSON array [].
    - No MCP error response (isError must be falsy / absent).
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-91 — MCP error response on auth failure
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_list_process_definitions_when_wrong_credentials_then_mcp_returns_error() -> None:
    """TC-91: Wrong credentials configured in server → MCP tool call returns an error response.

    Contract:
    - Server started with invalid FLOWABLE_USERNAME / FLOWABLE_PASSWORD.
    - Invoke 'list_process_definitions' via MCP.
    - Response contains isError=True and a message indicating authentication failure.
    - Message must NOT contain the plaintext password.
    """
    pytest.skip("E2E infrastructure not specified")


# ---------------------------------------------------------------------------
# TC-92 — server stdout stays silent during tool invocation
# ---------------------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.xfail(reason="E2E infra not specified: stdio MCP client needed", strict=False)
async def test_e2e_server_when_tool_invoked_then_stdout_contains_only_json_rpc_frames() -> None:
    """TC-92: Server stdout carries only valid JSON-RPC 2.0 frames — no stray log output.

    Contract:
    - Launch server process with stdio transport.
    - Invoke 'list_process_definitions' tool.
    - Capture all bytes written to stdout of the server process.
    - Each newline-delimited chunk must be a valid JSON-RPC 2.0 object.
    - No plain-text log lines on stdout (СТ-3, shared-standards §8.2).
    """
    pytest.skip("E2E infrastructure not specified")
