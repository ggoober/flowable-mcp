"""E2E tests for list_* tools (TASK-002 follow-up)."""

from __future__ import annotations

import base64

import pytest
from fastmcp import Client

from ._helpers import extract_list, extract_single
from .conftest import SAMPLE_PROCESS_KEY, USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]

_MINIMAL_BPMN = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL"
             targetNamespace="http://e2e">
  <process id="e2e-list-proc" isExecutable="true"><startEvent id="start"/></process>
</definitions>"""


async def test_e2e_list_process_definitions_when_deployed_then_includes_key(
    mcp_client: Client, e2e_deployed_process: str
) -> None:
    result = await mcp_client.call_tool("list_process_definitions", {})
    assert not getattr(result, "is_error", False)
    defs = extract_list(result)
    keys = [d.get("key") for d in defs]
    assert SAMPLE_PROCESS_KEY in keys, f"Deployed key must appear in list; got {keys}"


async def test_e2e_list_tasks_with_processInstanceId_filter_returns_subset(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    start_result = await mcp_client.call_tool(
        "start_process_instance",
        {"process_definition_key": USER_TASK_PROCESS_KEY},
    )
    pi_id: str = extract_single(start_result)["id"]
    try:
        list_result = await mcp_client.call_tool(
            "list_tasks", {"process_instance_id": pi_id}
        )
        assert not getattr(list_result, "is_error", False)
        tasks = extract_list(list_result)
        assert tasks
        for t in tasks:
            pi_field = t.get("processInstanceId") or t.get("process_instance_id")
            assert pi_field == pi_id
    finally:
        await mcp_client.call_tool(
            "cancel_process_instance", {"instance_id": pi_id}
        )


async def test_e2e_list_deployments_after_deploy_returns_list_with_id(
    mcp_client: Client,
) -> None:
    bpmn_b64 = base64.b64encode(_MINIMAL_BPMN).decode()
    deploy = await mcp_client.call_tool(
        "deploy_bpmn",
        {"name": "e2e-list-deployments.bpmn20.xml", "bpmn_base64": bpmn_b64},
    )
    assert not getattr(deploy, "is_error", False)
    dep = extract_single(deploy)
    dep_id = dep["id"]

    # Flowable paginates by default; filter by name to avoid missing recent deployments.
    listed = await mcp_client.call_tool(
        "list_deployments", {"name_like": "e2e-list-deployments"}
    )
    assert not getattr(listed, "is_error", False)
    deps = extract_list(listed)
    ids = [d.get("id") for d in deps]
    assert dep_id in ids, f"Deployment {dep_id} missing from filtered list: {ids}"
