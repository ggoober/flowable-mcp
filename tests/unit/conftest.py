from __future__ import annotations

import httpx
import pytest
from httpx import BasicAuth

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings

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
    http = httpx.AsyncClient(
        auth=BasicAuth(unit_settings.username, unit_settings.password.get_secret_value()),
        timeout=unit_settings.timeout_s,
    )
    client = FlowableClient(settings=unit_settings, http=http)
    yield client
    await http.aclose()
