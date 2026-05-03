from __future__ import annotations

import asyncio

import httpx
import pytest
from httpx import BasicAuth

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings


def raise_cancelled(_request: httpx.Request) -> httpx.Response:
    """respx side_effect callable that raises asyncio.CancelledError (§9.2 / spec §5)."""
    raise asyncio.CancelledError()

pytestmark = [pytest.mark.unit]


def pytest_collection_modifyitems(items: list) -> None:
    for item in items:
        if "/tests/unit/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.unit)

UNIT_BASE_URL = "http://flowable-test"
UNIT_USERNAME = "test-admin"
UNIT_PASSWORD = "test-pass"
PD_URL = f"{UNIT_BASE_URL}/repository/process-definitions"


@pytest.fixture
def unit_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("FLOWABLE_BASE_URL", UNIT_BASE_URL)
    monkeypatch.setenv("FLOWABLE_USERNAME", UNIT_USERNAME)
    monkeypatch.setenv("FLOWABLE_PASSWORD", UNIT_PASSWORD)
    monkeypatch.delenv("FLOWABLE_RETRY_ATTEMPTS", raising=False)
    monkeypatch.delenv("FLOWABLE_TIMEOUT_S", raising=False)
    return Settings()


@pytest.fixture
async def flowable_client(unit_settings: Settings) -> FlowableClient:
    # base_url with trailing slash so FlowableClient._base_url resolves correctly.
    # In unit tests both retry and no-retry slots share the same client instance;
    # respx intercepts all requests regardless of retry policy.
    http = httpx.AsyncClient(
        base_url=unit_settings.base_url + "/",
        auth=BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(http_retry=http, http_no_retry=http)
    yield client
    await http.aclose()
