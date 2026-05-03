"""Extra integration tests for deployment management (TASK-002 follow-up)."""

from __future__ import annotations

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.errors import FlowableServerError, FlowableValidationError

pytestmark = [pytest.mark.integration]

_MINIMAL_BPMN = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<definitions xmlns="http://www.omg.org/spec/BPMN/20100524/MODEL" targetNamespace="http://test">
  <process id="admin-extra-proc" isExecutable="true"><startEvent id="start"/></process>
</definitions>"""

_INVALID_BPMN = b"<this-is-not-bpmn>oops</this-is-not-bpmn>"


@pytest.mark.integration
async def test_list_deployments_with_name_filter_then_only_matching(
    integration_client: FlowableClient,
    integration_settings,
    integration_http,
) -> None:
    """list_deployments(name_like=...) returns deployments whose name starts with given prefix.

    Flowable nameLike is SQL-LIKE; we deploy with a unique name and filter by full name.
    """
    deployment_id: str | None = None
    upload_name = "admin-extra-filter.bpmn20.xml"
    # Flowable strips the extension from the deployment name on upload.
    stored_name = "admin-extra-filter"
    try:
        d = await integration_client.deploy_bpmn(name=upload_name, bpmn_bytes=_MINIMAL_BPMN)
        deployment_id = d.id

        listed = await integration_client.list_deployments(name_like=stored_name)
        assert listed
        for dep in listed:
            assert dep.name == stored_name
        assert deployment_id in [dep.id for dep in listed]
    finally:
        if deployment_id:
            await integration_http.delete(
                f"{integration_settings.base_url}/repository/deployments/{deployment_id}",
                params={"cascade": "true"},
            )


@pytest.mark.integration
async def test_deploy_bpmn_with_invalid_xml_then_raises_error(
    integration_client: FlowableClient,
) -> None:
    """Invalid BPMN content → server rejects deploy; mapped to typed error.

    Flowable 8.0 returns 500 for malformed XML (XMLStreamException unwrapped),
    not 400, so accept either ValidationError or ServerError.
    """
    with pytest.raises((FlowableValidationError, FlowableServerError)):
        await integration_client.deploy_bpmn(
            name="invalid.bpmn20.xml", bpmn_bytes=_INVALID_BPMN
        )


@pytest.mark.integration
async def test_deploy_bpmn_idempotency_when_same_name_twice_then_creates_two_deployments(
    integration_client: FlowableClient,
    integration_settings,
    integration_http,
) -> None:
    """Two deployments with same name → two distinct deployment IDs (Flowable does not dedupe)."""
    d1 = d2 = None
    try:
        d1 = await integration_client.deploy_bpmn(
            name="dup-name.bpmn20.xml", bpmn_bytes=_MINIMAL_BPMN
        )
        d2 = await integration_client.deploy_bpmn(
            name="dup-name.bpmn20.xml", bpmn_bytes=_MINIMAL_BPMN
        )
        assert d1.id != d2.id
        # Flowable strips extension; both deployments share stored name "dup-name".
        assert d1.name == d2.name == "dup-name"
    finally:
        for dep in (d1, d2):
            if dep:
                await integration_http.delete(
                    f"{integration_settings.base_url}/repository/deployments/{dep.id}",
                    params={"cascade": "true"},
                )
