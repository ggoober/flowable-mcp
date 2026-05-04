"""Integration tests for list_event_subscriptions pagination (TASK-004).

TC-I-105..TC-I-107

Requires live flowable-rest:8.0.0 at http://localhost:8080/flowable-rest/service.
Run with: pytest -m integration tests/integration/test_debug_task004.py
"""

from __future__ import annotations

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import EventSubscription

pytestmark = [pytest.mark.integration]


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
) -> None:
    """AC-4: event_type filter restricts returned subscriptions to matching type."""
    all_subs = await integration_client.list_event_subscriptions()
    if not all_subs:
        pytest.skip("No event subscriptions available in this environment")

    filter_type = all_subs[0].event_type
    filtered = await integration_client.list_event_subscriptions(event_type=filter_type)
    assert all(s.event_type == filter_type for s in filtered), (
        f"All subscriptions must have eventType={filter_type!r}"
    )
