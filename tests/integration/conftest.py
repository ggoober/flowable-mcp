from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings


FIXTURE_BPMN = Path(__file__).parent / "fixtures" / "sample.bpmn20.xml"
SAMPLE_PROCESS_KEY = "hello-world"


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
    return FlowableClient(settings=integration_settings, http=integration_http)


@pytest_asyncio.fixture(scope="session")
async def deployed_process(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
) -> str:
    """Deploy sample.bpmn20.xml once per session; yield deployment_id; delete on teardown."""
    bpmn_content = FIXTURE_BPMN.read_bytes()
    deploy_url = f"{integration_settings.base_url}/repository/deployments"

    files = {"file": ("sample.bpmn20.xml", bpmn_content, "application/xml")}
    resp = await integration_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]

    yield deployment_id

    # Teardown: remove deployment so it does not pollute other test runs.
    delete_url = f"{integration_settings.base_url}/repository/deployments/{deployment_id}"
    await integration_http.delete(delete_url)
