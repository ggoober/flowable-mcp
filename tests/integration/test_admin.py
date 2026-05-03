"""Integration tests for deployment management tools.

TC-094 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import Deployment

pytestmark = [pytest.mark.integration]

_MINIMAL_BPMN = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" targetNamespace="http://test">
  <process id="tc094-proc" isExecutable="true"><startEvent id="start"/></process>
</definitions>"""


# TC-094
@pytest.mark.integration
async def test_deploy_bpmn_then_list_deployments_contains_it(
    integration_client: FlowableClient,
    integration_settings,
    integration_http,
) -> None:
    """TC-094: deploy_bpmn → Deployment DTO valid; list_deployments count increases."""
    deployment_id: str | None = None
    try:
        deployment = await integration_client.deploy_bpmn(
            name="tc094-test.bpmn20.xml", bpmn_bytes=_MINIMAL_BPMN
        )
        deployment_id = deployment.id
        assert isinstance(deployment, Deployment)
        assert deployment.id
        # Flowable strips the .bpmn20.xml extension from deployment name on upload.
        assert deployment.name == "tc094-test"
        assert deployment.deployment_time is not None

        # Filter by name to avoid pagination misses on a long-lived Flowable instance.
        deployments = await integration_client.list_deployments(name_like="tc094-test")
        assert deployment.id in [d.id for d in deployments]
    finally:
        if deployment_id:
            await integration_http.delete(
                f"{integration_settings.base_url}/repository/deployments/{deployment_id}",
                params={"cascade": "true"},
            )
