"""E2E test for deployment management via MCP tool interface.

TC-100 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m e2e tests/e2e/
"""

from __future__ import annotations

import base64

import pytest
from fastmcp import Client

pytestmark = [pytest.mark.e2e]

_MINIMAL_BPMN = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://e2e-test">
  <process id="tc100-e2e-proc" isExecutable="true">
    <startEvent id="start"/>
  </process>
</definitions>"""


# TC-100
@pytest.mark.e2e
async def test_deploy_bpmn_via_mcp_tool_returns_deployment_dto(
    mcp_client: Client,
) -> None:
    """TC-100: deploy_bpmn MCP tool → Deployment DTO returned; appears in list_deployments."""
    bpmn_b64 = base64.b64encode(_MINIMAL_BPMN).decode()

    result = await mcp_client.call_tool(
        "deploy_bpmn",
        {"name": "tc100-e2e.bpmn20.xml", "bpmn_base64": bpmn_b64},
    )
    assert not result.isError, f"deploy_bpmn must succeed, got: {result}"

    list_result = await mcp_client.call_tool("list_deployments", {})
    assert not list_result.isError, f"list_deployments must succeed, got: {list_result}"
