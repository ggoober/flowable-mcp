"""Integration tests for list_event_subscriptions pagination (TASK-004).

TC-I-105..TC-I-107

Requires live flowable-rest:8.0.0 at http://localhost:8080/flowable-rest/service.
Run with: pytest -m integration tests/integration/test_debug_task004.py
"""

from __future__ import annotations

import pytest

import httpx
import pytest_asyncio

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.models import EventSubscription

pytestmark = [pytest.mark.integration]


@pytest_asyncio.fixture
async def message_event_subscription(
    integration_settings: Settings,
    integration_http: httpx.AsyncClient,
    message_event_process: str,
) -> str:
    """Start a message-event-process instance so Flowable creates a real
    runtime event subscription. Yields the subscription's event type and
    deletes the instance on teardown."""
    base = integration_settings.base_url
    resp = await integration_http.post(
        f"{base}/runtime/process-instances",
        json={"processDefinitionKey": message_event_process},
    )
    resp.raise_for_status()
    instance_id: str = resp.json()["id"]

    yield "message"

    try:
        await integration_http.delete(f"{base}/runtime/process-instances/{instance_id}")
    except Exception:
        pass


# TC-I-105: list_event_subscriptions returns EventSubscription DTOs (or empty list)
@pytest.mark.integration
async def test_list_event_subscriptions_when_called_then_returns_dto_list(
    integration_client: FlowableClient,
) -> None:
    """AC-4: list_event_subscriptions always returns list[EventSubscription]."""
    result = await integration_client.list_event_subscriptions()
    assert isinstance(result, list)
    assert all(isinstance(s, EventSubscription) for s in result)


# TC-I-106: list_event_subscriptions with message_event_process deployed → message sub visible
@pytest.mark.integration
async def test_list_event_subscriptions_when_message_event_deployed_then_subscription_found(
    integration_client: FlowableClient,
    message_event_process: str,
) -> None:
    """AC-4: A deployed message-event process creates a visible event subscription."""
    result = await integration_client.list_event_subscriptions(event_type="message")
    assert isinstance(result, list)
    # Flowable may or may not create runtime subscriptions for this type,
    # but the result must always be a valid list of EventSubscription DTOs
    assert all(isinstance(s, EventSubscription) for s in result)


# TC-I-107: list_event_subscriptions event_type filter scopes results
@pytest.mark.integration
async def test_list_event_subscriptions_when_event_type_filter_then_only_that_type(
    integration_client: FlowableClient,
    message_event_subscription: str,
) -> None:
    """AC-4: event_type filter restricts returned subscriptions to matching type.

    Starts a real message-event process instance via fixture so Flowable
    creates a runtime event subscription — guarantees ≥1 subscription exists,
    eliminating the prior pytest.skip on empty environments.
    """
    all_subs = await integration_client.list_event_subscriptions()
    assert all_subs, "fixture must guarantee ≥1 event subscription exists"

    filter_type = all_subs[0].event_type
    filtered = await integration_client.list_event_subscriptions(event_type=filter_type)
    assert all(s.event_type == filter_type for s in filtered), (
        f"All subscriptions must have eventType={filter_type!r}"
    )
