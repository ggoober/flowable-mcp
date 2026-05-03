"""Extra integration tests for historic process instance query (TASK-002 follow-up)."""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from flowable_mcp.client import FlowableClient

pytestmark = [pytest.mark.integration]


@pytest.mark.integration
async def test_list_historic_with_finished_filter_then_only_completed_instances(
    integration_client: FlowableClient,
    deployed_process: str,
    process_with_user_task: str,
) -> None:
    """finished=True returns only completed/cancelled instances; no still-running ones."""
    running_pi = completed_pi = None
    try:
        # Running instance: stays on user task
        running_pi = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        # Completed instance: hello-world auto-completes (start → end)
        completed_pi = await integration_client.start_process_instance(
            process_definition_key=deployed_process
        )

        finished_only: list = []
        for _ in range(25):
            finished_only = await integration_client.list_historic_process_instances(
                finished=True, max_results=200
            )
            if any(h.id == completed_pi.id for h in finished_only):
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail(f"Completed instance {completed_pi.id!r} did not appear in finished history")

        ids = {h.id for h in finished_only}
        assert completed_pi.id in ids
        assert running_pi.id not in ids
        for h in finished_only:
            assert h.end_time is not None or h.ended is True
    finally:
        if running_pi:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(running_pi.id)


@pytest.mark.integration
async def test_list_historic_with_processDefinitionKey_filter_then_disjoint_sets(
    integration_client: FlowableClient,
    deployed_process: str,
    process_with_user_task: str,
) -> None:
    """processDefinitionKey filter returns only matching definition's instances."""
    pi_a = pi_b = None
    try:
        pi_a = await integration_client.start_process_instance(
            process_definition_key=deployed_process
        )
        pi_b = await integration_client.start_process_instance(
            process_definition_key=process_with_user_task
        )
        # Wait for both to land in history
        for _ in range(25):
            ha = await integration_client.list_historic_process_instances(
                process_definition_key=deployed_process, max_results=200
            )
            hb = await integration_client.list_historic_process_instances(
                process_definition_key=process_with_user_task, max_results=200
            )
            if any(h.id == pi_a.id for h in ha) and any(h.id == pi_b.id for h in hb):
                break
            await asyncio.sleep(0.2)
        else:
            pytest.fail("Historic records for both instances did not appear within 5 seconds")

        ids_a = {h.id for h in ha}
        ids_b = {h.id for h in hb}
        assert pi_a.id in ids_a and pi_a.id not in ids_b
        assert pi_b.id in ids_b and pi_b.id not in ids_a
        for h in ha:
            assert h.process_definition_key == deployed_process
        for h in hb:
            assert h.process_definition_key == process_with_user_task
    finally:
        if pi_b:
            with contextlib.suppress(Exception):
                await integration_client.cancel_process_instance(pi_b.id)
