from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings


async def _purge_deployments_by_name(
    http: httpx.AsyncClient, base_url: str, name: str
) -> None:
    """Delete all existing deployments with the given name (cascade=true).

    Called in fixture setup so a crashed previous test run leaves no stale state.
    """
    resp = await http.get(
        f"{base_url}/repository/deployments", params={"name": name, "size": "50"}
    )
    if resp.status_code == 200:
        data = resp.json().get("data", [])
        for dep in data:
            dep_id = dep.get("id")
            if dep_id:
                await http.delete(
                    f"{base_url}/repository/deployments/{dep_id}",
                    params={"cascade": "true"},
                )


FIXTURE_BPMN = Path(__file__).parent / "fixtures" / "sample.bpmn20.xml"
FIXTURE_USER_TASK_BPMN = Path(__file__).parent / "fixtures" / "user-task-process.bpmn20.xml"
FIXTURE_FAILING_BPMN = Path(__file__).parent / "fixtures" / "failing-service-task.bpmn20.xml"
FIXTURE_MESSAGE_EVENT_BPMN = Path(__file__).parent / "fixtures" / "message-event.bpmn20.xml"
SAMPLE_PROCESS_KEY = "hello-world"
USER_TASK_PROCESS_KEY = "user-task-process"
FAILING_PROCESS_KEY = "failing-service-task"
MESSAGE_EVENT_PROCESS_KEY = "message-event-process"


@pytest.fixture(scope="session")
def integration_settings() -> Settings:
    """Real settings for integration tests — reads from env with local-docker defaults."""
    os.environ.setdefault("FLOWABLE_BASE_URL", "http://localhost:8080/flowable-rest/service")
    os.environ.setdefault("FLOWABLE_USERNAME", "rest-admin")
    os.environ.setdefault("FLOWABLE_PASSWORD", "test")
    return Settings()


@pytest_asyncio.fixture(scope="session")
async def integration_http(integration_settings: Settings) -> httpx.AsyncClient:
    """Session-scoped real httpx.AsyncClient — shared across all integration tests."""
    async with httpx.AsyncClient(
        base_url=integration_settings.base_url + "/",
        auth=httpx.BasicAuth(
            integration_settings.username,
            integration_settings.password.get_secret_value(),
        ),
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def integration_client(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> FlowableClient:
    """Session-scoped real FlowableClient — no mocks."""
    return FlowableClient(http_retry=integration_http, http_no_retry=integration_http)


@pytest_asyncio.fixture(scope="session")
async def deployed_process(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy sample.bpmn20.xml once per session; yield process key; delete on teardown."""
    # Setup-time cleanup: remove any stale deployments from a crashed previous run (§9.5).
    await _purge_deployments_by_name(
        integration_http, integration_settings.base_url, "sample.bpmn20.xml"
    )

    bpmn_content = FIXTURE_BPMN.read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"

    files = {"file": ("sample.bpmn20.xml", bpmn_content, "application/xml")}
    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]

    yield SAMPLE_PROCESS_KEY

    delete_url = f"{integration_settings.base_url}/repository/deployments/{deployment_id}"
    await integration_http.delete(delete_url)


@pytest_asyncio.fixture(scope="session")
async def process_with_user_task(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy user-task-process.bpmn20.xml once; yield process key; delete on teardown."""
    # Setup-time cleanup: remove any stale deployments from a crashed previous run (§9.5).
    await _purge_deployments_by_name(
        integration_http, integration_settings.base_url, "user-task-process.bpmn20.xml"
    )

    bpmn_content = FIXTURE_USER_TASK_BPMN.read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"

    files = {"file": ("user-task-process.bpmn20.xml", bpmn_content, "application/xml")}
    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]

    yield USER_TASK_PROCESS_KEY

    delete_url = f"{integration_settings.base_url}/repository/deployments/{deployment_id}"
    await integration_http.delete(delete_url, params={"cascade": "true"})


@pytest_asyncio.fixture(scope="session")
async def failing_process(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy failing-service-task.bpmn20.xml once; yield process key; delete on teardown."""
    await _purge_deployments_by_name(
        integration_http, integration_settings.base_url, "failing-service-task.bpmn20.xml"
    )

    bpmn_content = FIXTURE_FAILING_BPMN.read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"

    files = {"file": ("failing-service-task.bpmn20.xml", bpmn_content, "application/xml")}
    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]

    yield FAILING_PROCESS_KEY

    delete_url = f"{integration_settings.base_url}/repository/deployments/{deployment_id}"
    await integration_http.delete(delete_url, params={"cascade": "true"})


@pytest_asyncio.fixture(scope="session")
async def message_event_process(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy message-event.bpmn20.xml once; yield process key; delete on teardown."""
    await _purge_deployments_by_name(
        integration_http, integration_settings.base_url, "message-event.bpmn20.xml"
    )

    bpmn_content = FIXTURE_MESSAGE_EVENT_BPMN.read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"

    files = {"file": ("message-event.bpmn20.xml", bpmn_content, "application/xml")}
    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]

    yield MESSAGE_EVENT_PROCESS_KEY

    delete_url = f"{integration_settings.base_url}/repository/deployments/{deployment_id}"
    await integration_http.delete(delete_url, params={"cascade": "true"})
