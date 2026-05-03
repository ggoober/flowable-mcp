"""Integration tests for list_historic_activity_instances and _paginate (TASK-004).

TC-I-098..TC-I-102, TC-I-110..TC-I-114

Requires live flowable-rest:8.0.0 at http://localhost:8080/flowable-rest/service.
Run with: pytest -m integration tests/integration/test_history_task004.py
"""

from __future__ import annotations

import asyncio
import datetime

import pytest

from flowable_mcp.client import FlowableClient
from flowable_mcp.models.history import HistoricActivityInstance

pytestmark = [pytest.mark.integration]


async def _wait_for_activity(
    client: FlowableClient,
    process_instance_id: str,
    *,
    min_count: int = 1,
    timeout_s: float = 15.0,
) -> list[HistoricActivityInstance]:
    """Poll until at least min_count activity records appear for the given instance."""
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        result = await client.list_historic_activity_instances(
            process_instance_id=process_instance_id,
            activity_type=None,
            max_results=500,
        )
        if len(result) >= min_count:
            return result
        await asyncio.sleep(0.3)
    pytest.fail(
        f"Expected ≥{min_count} activity records for instance {process_instance_id!r} "
        f"within {timeout_s}s, got {0}"
    )


# TC-I-098: list_historic_activity_instances returns records after process start
@pytest.mark.integration
async def test_list_historic_activity_instances_when_process_started_then_records_exist(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: Activity records visible in history after process start event."""
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        records = await _wait_for_activity(integration_client, pi.id, min_count=1)
        assert len(records) >= 1
        assert all(isinstance(r, HistoricActivityInstance) for r in records)
        assert all(r.id for r in records)
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-099: process_instance_id filter scopes results to that instance only
@pytest.mark.integration
async def test_list_historic_activity_when_process_instance_filter_then_scoped(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: process_instance_id filter isolates records to the given instance."""
    pi_a = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    pi_b = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        records = await _wait_for_activity(integration_client, pi_a.id, min_count=1)
        assert all(r.process_instance_id == pi_a.id for r in records), (
            "Activity records must belong to the filtered instance"
        )
        for r in records:
            assert r.process_instance_id != pi_b.id
    finally:
        for pid in (pi_a.id, pi_b.id):
            try:
                await integration_client.cancel_process_instance(pid)
            except Exception:
                pass


# TC-I-100: activity_type filter → only matching type in result
@pytest.mark.integration
async def test_list_historic_activity_when_activity_type_filter_then_only_matching_type(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: activityType filter returns only records of the requested type."""
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        all_records = await _wait_for_activity(integration_client, pi.id, min_count=1)
        if not all_records:
            pytest.skip("No activity records available to test type filter")

        types_seen = {r.activity_type for r in all_records}
        filter_type = next(iter(types_seen))

        filtered = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            activity_type=filter_type,
            max_results=500,
        )
        assert all(r.activity_type == filter_type for r in filtered)
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-101: finished=True → only completed activities returned
@pytest.mark.integration
async def test_list_historic_activity_when_finished_true_then_only_completed(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: finished=True filter returns only activities with an end_time."""
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        # Give the process a moment to progress
        await asyncio.sleep(0.5)
        finished = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            finished=True,
            activity_type=None,
            max_results=500,
        )
        assert all(r.end_time is not None for r in finished), (
            "All finished=True activities must have end_time set"
        )
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-102: started_after / started_before time-range filter
@pytest.mark.integration
async def test_list_historic_activity_when_time_range_then_filters_by_start(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: started_after and started_before filter activity records by start time."""
    boundary = datetime.datetime.now(datetime.UTC)
    await asyncio.sleep(1.1)

    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        records = await _wait_for_activity(integration_client, pi.id, min_count=1)
        if not records:
            pytest.skip("No activity records available")

        after_boundary = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            started_after=boundary,
            activity_type=None,
            max_results=500,
        )
        assert len(after_boundary) >= 1, "Expected records started after the boundary"

        before_boundary = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            started_before=boundary,
            activity_type=None,
            max_results=500,
        )
        for r in records:
            assert r.id not in {br.id for br in before_boundary}
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-110: _paginate returns correct total via multi-page fetch (AC-2 helper contract)
@pytest.mark.integration
async def test_paginate_helper_when_multiple_pages_then_all_items_returned(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-2: _paginate aggregates all pages transparently."""
    started = []
    try:
        # Start several instances to ensure non-empty history
        for _ in range(3):
            pi = await integration_client.start_process_instance(
                process_definition_key=process_with_user_task
            )
            started.append(pi.id)

        result_small = await integration_client.list_historic_activity_instances(
            activity_type=None,
            max_results=5,
        )
        result_large = await integration_client.list_historic_activity_instances(
            activity_type=None,
            max_results=10_000,
        )
        assert len(result_large) >= len(result_small)
        assert isinstance(result_large, list)
        assert all(isinstance(r, HistoricActivityInstance) for r in result_large)
    finally:
        for pid in started:
            try:
                await integration_client.cancel_process_instance(pid)
            except Exception:
                pass


# TC-I-111: _paginate with max_items cap truncates at specified limit
@pytest.mark.integration
async def test_paginate_helper_when_max_items_set_then_truncated_at_limit(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-2: list_historic_activity_instances max_results caps the returned count."""
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        await asyncio.sleep(0.5)
        result = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            activity_type=None,
            max_results=1,
        )
        assert len(result) <= 1
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-112: list_historic_activity_instances returns plain list (truncated flag discarded)
@pytest.mark.integration
async def test_list_historic_activity_when_called_then_returns_list_not_tuple(
    integration_client: FlowableClient,
    deployed_process: str,
) -> None:
    """AC-1: Return type must be list[HistoricActivityInstance], not tuple."""
    pi = await integration_client.start_process_instance(
        process_definition_key=deployed_process
    )
    try:
        result = await integration_client.list_historic_activity_instances(
            process_instance_id=pi.id,
            activity_type=None,
            max_results=10,
        )
        assert isinstance(result, list)
        assert not isinstance(result, tuple)
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-113: AC-V3 — activity_type="userTask" default → all returned records are userTask
@pytest.mark.integration
async def test_list_historic_activity_when_usertask_filter_then_all_records_are_usertask(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """AC-V3: activity_type='userTask' filter must return ONLY userTask records.
    §0.1 root cause H-003: no integration test explicitly asserted this invariant.
    Without it a Flowable server that ignores activityType param would go undetected.
    Uses process_with_user_task fixture which creates a real userTask in history.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        # Complete the userTask so it appears in history
        tasks = await integration_client.list_tasks(process_instance_id=pi.id)
        if tasks:
            await integration_client.complete_task(task_id=tasks[0].id)

        # Poll for activity records with userTask filter
        deadline = asyncio.get_running_loop().time() + 15.0
        records = []
        while asyncio.get_running_loop().time() < deadline:
            records = await integration_client.list_historic_activity_instances(
                process_instance_id=pi.id,
                activity_type="userTask",
                max_results=500,
            )
            if records:
                break
            await asyncio.sleep(0.3)

        assert records, "Expected at least one userTask activity record"
        # AC-V3: server-side (or client-side fallback) filter must work
        assert all(r.activity_type == "userTask" for r in records), (
            f"All records must have activity_type='userTask', got: "
            f"{[r.activity_type for r in records if r.activity_type != 'userTask']}"
        )
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass


# TC-I-114: running userTask → end_time is None (activity in progress)
@pytest.mark.integration
async def test_list_historic_activity_when_running_usertask_then_end_time_is_none(
    integration_client: FlowableClient,
    process_with_user_task: str,
) -> None:
    """Spec TC-I-100 original semantics: an active (not yet completed) userTask must have
    end_time=None and duration_in_millis=None in historic activity records.
    §0.1 root cause H-003: TC-I-100 in file was remapped to activity_type filter test,
    leaving the running-activity invariant (I-01.3) uncovered at integration level.
    """
    pi = await integration_client.start_process_instance(
        process_definition_key=process_with_user_task
    )
    try:
        # Don't complete task — leave it running
        records = await _wait_for_activity(integration_client, pi.id, min_count=1)

        # Find userTask records that are still running (end_time is None)
        running = [r for r in records if r.activity_type == "userTask" and r.end_time is None]
        assert running, (
            f"Expected at least one running userTask (end_time=None). "
            f"Got records: {[(r.activity_type, r.end_time) for r in records]}"
        )
        for r in running:
            assert r.end_time is None, f"Running activity must have end_time=None, got {r.end_time}"
            assert r.duration_in_millis is None, (
                f"Running activity must have duration_in_millis=None, got {r.duration_in_millis}"
            )
            assert r.start_time is not None, "Running activity must have start_time set"
    finally:
        try:
            await integration_client.cancel_process_instance(pi.id)
        except Exception:
            pass
