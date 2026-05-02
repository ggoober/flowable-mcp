"""Integration tests for event subscription listing.

TC-097 (TASK-002). Requires live flowable-rest:8.0.0 Docker container.
Run with: pytest -m integration tests/integration/
"""

from __future__ import annotations

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models import EventSubscription

pytestmark = [pytest.mark.integration]


# TC-097: list_event_subscriptions returns list of valid DTOs
@pytest.mark.integration
async def test_list_event_subscriptions_returns_valid_dto_list(
    integration_client: FlowableClient,
) -> None:
    """TC-097: list_event_subscriptions returns a list; each item is a valid EventSubscription."""
    result = await integration_client.list_event_subscriptions()
    assert isinstance(result, list)
    for item in result:
        assert isinstance(item, EventSubscription)
        assert item.id
        assert item.event_type
