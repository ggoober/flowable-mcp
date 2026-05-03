"""Extra integration tests for event subscription tools (TASK-002 follow-up)."""

from __future__ import annotations

import contextlib

import pytest

from flowable_mcp.client import FlowableClient

pytestmark = [pytest.mark.integration]


@pytest.mark.integration
async def test_list_event_subscriptions_with_processDefinitionKey_filter_then_only_matching(
    integration_client: FlowableClient,
    message_event_process: str,
) -> None:
    """Process with intermediate message catch event creates an EventSubscription;
    list_event_subscriptions(process_definition_key=...) returns only its subs."""
    pi = None
    try:
        pi = await integration_client.start_process_instance(
            process_definition_key=message_event_process
        )
        # Filter by definition key (in-tool fallback handles processDefinitionKey)
        subs = await integration_client.list_event_subscriptions(
            process_definition_key=message_event_process
        )
        # The intermediate message event creates a subscription tied to this instance
        matching = [s for s in subs if s.process_instance_id == pi.id]
        assert matching, f"Expected at least one event sub for instance {pi.id}; got {subs}"
        for s in matching:
            assert s.event_type == "message"
            assert s.event_name == "testMessage"
    finally:
        if pi:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(pi.id)
