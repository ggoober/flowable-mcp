"""E2E roundtrip tests for TASK-003 monitoring/debug wave 2 tools.

Covers MCP-protocol roundtrips for the 7 tools added in TASK-003:
- list_process_instances
- get_process_variables
- set_process_variable
- list_historic_task_instances
- suspend_process_instance / activate_process_instance
- suspend_process_definition / activate_process_definition
- delete_deployment
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

from flowable_mcp.config import Settings

from .conftest import USER_TASK_PROCESS_KEY

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio(loop_scope="function")]

_FIXTURE_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "sample.bpmn20.xml"
)


def _extract_single(result) -> dict:
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return dict(structured["result"])
    if isinstance(structured, dict):
        return structured

    data = getattr(result, "data", None)
    if data is not None and hasattr(data, "model_dump"):
        return data.model_dump(by_alias=True)
    if isinstance(data, dict):
        return data

    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
    raise AssertionError(f"Could not extract single object from result: {result!r}")


def _extract_list(result) -> list[dict]:
    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if isinstance(structured, dict) and "result" in structured:
        return list(structured["result"])
    if isinstance(structured, list):
        return structured

    data = getattr(result, "data", None)
    if isinstance(data, list):
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
    raise AssertionError(f"Could not extract list from result: {result!r}")


async def _start_instance(mcp_client: Client, **kwargs) -> str:
    payload = {"process_definition_key": USER_TASK_PROCESS_KEY, **kwargs}
    res = await mcp_client.call_tool("start_process_instance", payload)
    assert not getattr(res, "is_error", False), f"start failed: {res!r}"
    return _extract_single(res)["id"]


async def _cancel(mcp_client: Client, instance_id: str) -> None:
    try:
        await mcp_client.call_tool(
            "cancel_process_instance", {"instance_id": instance_id}
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# list_process_instances
# ---------------------------------------------------------------------------


async def test_e2e_list_process_instances_when_running_then_appears_in_list(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    pi_id = await _start_instance(mcp_client)
    try:
        res = await mcp_client.call_tool(
            "list_process_instances",
            {"process_definition_key": USER_TASK_PROCESS_KEY, "max_results": 50},
        )
        assert not getattr(res, "is_error", False)
        items = _extract_list(res)
        ids = [it.get("id") for it in items]
        assert pi_id in ids
    finally:
        await _cancel(mcp_client, pi_id)


async def test_e2e_list_process_instances_when_business_key_filter_then_scopes(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    bk = f"e2e-bk-{uuid.uuid4().hex[:8]}"
    pi_id = await _start_instance(mcp_client, business_key=bk)
    try:
        res = await mcp_client.call_tool(
            "list_process_instances", {"business_key": bk, "max_results": 50}
        )
        assert not getattr(res, "is_error", False)
        items = _extract_list(res)
        assert pi_id in {it.get("id") for it in items}
    finally:
        await _cancel(mcp_client, pi_id)


# ---------------------------------------------------------------------------
# get_process_variables / set_process_variable
# ---------------------------------------------------------------------------


async def test_e2e_get_and_set_process_variable_roundtrip(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    pi_id = await _start_instance(
        mcp_client, variables={"amount": 5, "approved": False}
    )
    try:
        set_res = await mcp_client.call_tool(
            "set_process_variable",
            {"instance_id": pi_id, "var_name": "approved", "value": True},
        )
        assert not getattr(set_res, "is_error", False)
        var = _extract_single(set_res)
        assert var.get("name") == "approved"
        # INV-02: bool inferred as boolean (not integer) over the wire.
        assert var.get("type") == "boolean"

        get_res = await mcp_client.call_tool(
            "get_process_variables", {"instance_id": pi_id}
        )
        assert not getattr(get_res, "is_error", False)
        items = _extract_list(get_res)
        by_name = {it["name"]: it for it in items}
        assert by_name["approved"]["value"] is True
        assert by_name["approved"]["type"] == "boolean"
        assert by_name["amount"]["type"] == "integer"
    finally:
        await _cancel(mcp_client, pi_id)


async def test_e2e_get_process_variables_when_instance_missing_then_is_error(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    """FastMCP surfaces tool exceptions as ToolError on the client side."""
    with pytest.raises(ToolError, match="404"):
        await mcp_client.call_tool(
            "get_process_variables", {"instance_id": f"missing-{uuid.uuid4().hex}"}
        )


# ---------------------------------------------------------------------------
# list_historic_task_instances
# ---------------------------------------------------------------------------


async def test_e2e_list_historic_task_instances_when_completed_then_visible(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    pi_id = await _start_instance(mcp_client)
    list_res = await mcp_client.call_tool(
        "list_tasks", {"process_instance_id": pi_id}
    )
    tasks = _extract_list(list_res)
    assert tasks
    task_id = tasks[0]["id"]

    await mcp_client.call_tool("complete_task", {"task_id": task_id})

    found = None
    for _ in range(75):
        res = await mcp_client.call_tool(
            "list_historic_task_instances",
            {"process_instance_id": pi_id, "finished": True, "max_results": 50},
        )
        assert not getattr(res, "is_error", False)
        items = _extract_list(res)
        match = [it for it in items if it.get("id") == task_id]
        if match and match[0].get("endTime") or match and match[0].get("end_time"):
            found = match[0]
            break
        await asyncio.sleep(0.2)
    assert found is not None, f"historic task {task_id} not visible within 15s"


# ---------------------------------------------------------------------------
# suspend / activate process instance
# ---------------------------------------------------------------------------


async def test_e2e_suspend_then_activate_process_instance_roundtrip(
    mcp_client: Client, e2e_deployed_user_task_process: str
) -> None:
    pi_id = await _start_instance(mcp_client)
    try:
        susp = await mcp_client.call_tool(
            "suspend_process_instance", {"instance_id": pi_id}
        )
        assert not getattr(susp, "is_error", False)
        assert _extract_single(susp).get("suspended") is True

        act = await mcp_client.call_tool(
            "activate_process_instance", {"instance_id": pi_id}
        )
        assert not getattr(act, "is_error", False)
        assert _extract_single(act).get("suspended") is False
    finally:
        await _cancel(mcp_client, pi_id)


# ---------------------------------------------------------------------------
# suspend / activate process definition + delete_deployment
# ---------------------------------------------------------------------------


async def _local_http(settings: Settings) -> httpx.AsyncClient:
    """Build a function-scoped AsyncClient — must be created inside test loop
    because session-scoped fixtures live on a different event loop here."""
    return httpx.AsyncClient(
        auth=httpx.BasicAuth(settings.username, settings.password.get_secret_value()),
        timeout=30.0,
    )


async def test_e2e_suspend_activate_definition_and_delete_deployment_roundtrip(
    mcp_client: Client, e2e_settings: Settings
) -> None:
    """Deploy hello-world ad-hoc → suspend definition → activate → delete deployment via MCP."""
    bpmn = _FIXTURE_BPMN.read_bytes()
    files = {
        "file": (
            f"e2e-task003-{uuid.uuid4().hex[:8]}.bpmn20.xml",
            bpmn,
            "application/xml",
        )
    }
    deployment_id: str | None = None
    async with await _local_http(e2e_settings) as http:
        deploy_resp = await http.post(
            f"{e2e_settings.base_url}/repository/deployments", files=files
        )
        deploy_resp.raise_for_status()
        deployment_id = deploy_resp.json()["id"]

        defs_resp = await http.get(
            f"{e2e_settings.base_url}/repository/process-definitions",
            params={"deploymentId": deployment_id},
        )
        defs_resp.raise_for_status()
        definition_id: str = defs_resp.json()["data"][0]["id"]

        try:
            susp = await mcp_client.call_tool(
                "suspend_process_definition", {"definition_id": definition_id}
            )
            assert not getattr(susp, "is_error", False)
            assert _extract_single(susp).get("suspended") is True

            act = await mcp_client.call_tool(
                "activate_process_definition", {"definition_id": definition_id}
            )
            assert not getattr(act, "is_error", False)
            assert _extract_single(act).get("suspended") is False

            del_res = await mcp_client.call_tool(
                "delete_deployment",
                {"deployment_id": deployment_id, "cascade": False},
            )
            assert not getattr(del_res, "is_error", False)

            # Idempotency check: subsequent delete must surface as ToolError (404).
            with pytest.raises(ToolError, match="404"):
                await mcp_client.call_tool(
                    "delete_deployment",
                    {"deployment_id": deployment_id, "cascade": False},
                )
            deployment_id = None  # already deleted, skip cleanup
        finally:
            if deployment_id is not None:
                try:
                    await http.delete(
                        f"{e2e_settings.base_url}/repository/deployments/{deployment_id}",
                        params={"cascade": "true"},
                    )
                except Exception:
                    pass


async def test_e2e_delete_deployment_when_cascade_true_then_removes_running_instances(
    mcp_client: Client, e2e_settings: Settings
) -> None:
    bpmn_path = (
        Path(__file__).parent.parent
        / "integration"
        / "fixtures"
        / "user-task-process.bpmn20.xml"
    )
    files = {
        "file": (
            f"e2e-task003-cascade-{uuid.uuid4().hex[:8]}.bpmn20.xml",
            bpmn_path.read_bytes(),
            "application/xml",
        )
    }
    deployment_id: str | None = None
    async with await _local_http(e2e_settings) as http:
        deploy_resp = await http.post(
            f"{e2e_settings.base_url}/repository/deployments", files=files
        )
        deploy_resp.raise_for_status()
        deployment_id = deploy_resp.json()["id"]
        try:
            # Start an instance against this fresh deployment (cascade target).
            pi_id = await _start_instance(mcp_client)

            del_res = await mcp_client.call_tool(
                "delete_deployment",
                {"deployment_id": deployment_id, "cascade": True},
            )
            assert not getattr(del_res, "is_error", False)

            # After cascade-delete the instance must be gone too.
            with pytest.raises(ToolError, match="404"):
                await mcp_client.call_tool(
                    "get_process_instance", {"instance_id": pi_id}
                )
            deployment_id = None
        finally:
            if deployment_id is not None:
                try:
                    await http.delete(
                        f"{e2e_settings.base_url}/repository/deployments/{deployment_id}",
                        params={"cascade": "true"},
                    )
                except Exception:
                    pass
