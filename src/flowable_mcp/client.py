"""Flowable REST adapter.

Async-only outbound HTTP via httpx.AsyncClient (СТ-5).
Two injected AsyncClient instances: http_retry (GET/idempotent) and
http_no_retry (POST/DELETE, retries=0) — structural guarantee against
duplicate-create on retry (AC-N1, DD-5, DD-6).
"""

from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from datetime import datetime
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel

from flowable_mcp.errors import (
    FlowableAuthError,
    FlowableConflictError,
    FlowableConnectionError,
    FlowableNotFoundError,
    FlowableProtocolError,
    FlowableServerError,
    FlowableValidationError,
)
from flowable_mcp.models import (
    DeadLetterJob,
    Deployment,
    EventSubscription,
    HistoricProcessInstance,
    HistoricTaskInstance,
    ProcessDefinition,
    ProcessInstance,
    Task,
    Variable,
    VariableList,
)

_logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

_MISSING: object = object()
_PAGE_SIZE: int = 100
_MAX_ITEMS: int = 10_000


def _map_status(exc: httpx.HTTPStatusError) -> Exception:
    """Map HTTP status → typed FlowableError (never raises; caller uses `raise ... from exc`)."""
    status = exc.response.status_code
    if status in (401, 403):
        return FlowableAuthError(f"Authentication failed ({status})")
    if status == 400:
        body = exc.response.text[:500]
        return FlowableValidationError(f"Validation error ({status}): {body}")
    if status == 404:
        return FlowableNotFoundError("Resource not found (404)")
    if status == 409:
        body = exc.response.text[:200]
        return FlowableConflictError(f"Conflict (409): {body}")
    if status >= 500:
        body = exc.response.text[:200]
        return FlowableServerError(f"Server error {status}: {body}")
    body = exc.response.text[:200]
    return FlowableServerError(f"Unexpected status {status}: {body}")


class FlowableClient:
    """Async adapter for Flowable REST API.

    Args:
        http_retry: AsyncClient for idempotent requests (GET, HEAD); may have transport retries.
        http_no_retry: AsyncClient for non-idempotent requests (POST, DELETE); retries=0.
    """

    def __init__(
        self,
        http_retry: httpx.AsyncClient,
        http_no_retry: httpx.AsyncClient,
    ) -> None:
        self._retry = http_retry
        self._no_retry = http_no_retry
        # Extract base URL so _call can build absolute URLs regardless of whether the
        # AsyncClient was configured with base_url or not.
        self._base_url: str = str(http_retry.base_url).rstrip("/")
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Internal HTTP primitives
    # ------------------------------------------------------------------

    async def _call(
        self,
        method: str,
        path: str,
        *,
        idempotent: bool,
        response_model: type[T] | None = None,
        expect_json: bool = True,
        **kwargs: Any,
    ) -> Any:
        """Single entry point for all HTTP calls (AC-N2).

        path must be slash-prefixed, e.g. "/runtime/process-instances".
        Returns: model instance | raw dict/list | None.
        - 204 No Content → None.
        - expect_json=False → None (fire-and-forget actions).
        - response_model=None + expect_json=True → raw payload dict (list pagination).
        - response_model provided → model_validate(resp.json()).
        """
        client = self._retry if idempotent else self._no_retry
        url = f"{self._base_url}{path}"
        t0 = time.perf_counter()
        try:
            resp = await client.request(method, url, **kwargs)
        except asyncio.CancelledError:
            raise  # I7 / AC-X4: CancelledError before TransportError, never swallowed
        except httpx.TransportError as exc:
            raise FlowableConnectionError(
                f"Connection failed: {type(exc).__name__}"
            ) from exc

        _logger.info(
            "flowable http",
            extra={
                "method": method,
                "path": path,
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            },
        )

        if resp.status_code == 204:
            return None

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _map_status(exc) from exc

        if not expect_json:
            return None

        payload = resp.json()
        if response_model is None:
            return payload
        return response_model.model_validate(payload)

    async def _call_multipart(
        self,
        path: str,
        files: dict[str, Any],
        *,
        response_model: type[T] | None = None,
    ) -> T | None:
        """POST multipart/form-data via http_no_retry (CC-3, retries=0)."""
        url = f"{self._base_url}{path}"
        t0 = time.perf_counter()
        try:
            resp = await self._no_retry.request("POST", url, files=files)
        except asyncio.CancelledError:
            raise
        except httpx.TransportError as exc:
            raise FlowableConnectionError(
                f"Connection failed: {type(exc).__name__}"
            ) from exc

        _logger.info(
            "flowable http",
            extra={
                "method": "POST",
                "path": path,
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            },
        )

        if resp.status_code == 204:
            return None

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _map_status(exc) from exc

        if response_model is None:
            return None
        return response_model.model_validate(resp.json())

    def _parse_list(self, raw: Any, model: type[T]) -> list[T]:
        """Parse Flowable's standard {data: [...], total: N} envelope into a typed list."""
        if not isinstance(raw, dict):
            raise FlowableProtocolError(
                f"expected JSON object at root, got {type(raw).__name__}"
            )
        data = raw.get("data", _MISSING)
        if data is _MISSING:
            raise FlowableProtocolError(
                f"expected 'data' key in response, got keys: {list(raw.keys())}"
            )
        if data is None:
            raise FlowableProtocolError("'data' is null in Flowable response")
        if not isinstance(data, list):
            raise FlowableProtocolError(
                f"expected list at .data, got {type(data).__name__}"
            )
        return [model.model_validate(item) for item in data]

    def _parse_total(self, raw: Any) -> int:
        """Extract total count from Flowable page envelope; fallback to len(data)."""
        if not isinstance(raw, dict):
            return 0
        data = raw.get("data")
        total_raw = raw.get("total")
        if isinstance(total_raw, int):
            return total_raw
        return len(data) if isinstance(data, list) else 0

    # ------------------------------------------------------------------
    # Public API — existing (TASK-001)
    # ------------------------------------------------------------------

    async def list_process_definitions(
        self,
        *,
        latest: bool = True,
        key: str | None = None,
    ) -> list[ProcessDefinition]:
        """GET /repository/process-definitions with auto-pagination."""
        base_params: dict[str, str] = {"latest": str(latest).lower()}
        if key:
            base_params["key"] = key

        items: list[ProcessDefinition] = []
        start = 0
        while True:
            page_params = {**base_params, "start": str(start), "size": str(_PAGE_SIZE)}
            raw = await self._call(
                "GET", "/repository/process-definitions", idempotent=True, params=page_params
            )
            page = self._parse_list(raw, ProcessDefinition)
            items.extend(page)
            total = self._parse_total(raw)

            if not page:
                break
            if len(items) >= total:
                break
            if len(items) >= _MAX_ITEMS:
                _logger.warning(
                    "flowable list_process_definitions hit _MAX_ITEMS cap; result truncated",
                    extra={"max_items": _MAX_ITEMS, "total": total},
                )
                break
            start = len(items)

        return items

    # ------------------------------------------------------------------
    # S-1: Process Instance Lifecycle
    # ------------------------------------------------------------------

    async def start_process_instance(
        self,
        *,
        process_definition_key: str | None = None,
        process_definition_id: str | None = None,
        variables: dict[str, Any] | None = None,
        business_key: str | None = None,
        tenant_id: str | None = None,
    ) -> ProcessInstance:
        body: dict[str, Any] = {}
        if process_definition_key:
            body["processDefinitionKey"] = process_definition_key
        else:
            body["processDefinitionId"] = process_definition_id
        if variables is not None:
            body["variables"] = VariableList.from_python_dict(variables).model_dump()
        if business_key:
            body["businessKey"] = business_key
        if tenant_id:
            body["tenantId"] = tenant_id

        result = await self._call(
            "POST",
            "/runtime/process-instances",
            idempotent=False,
            response_model=ProcessInstance,
            json=body,
        )
        return result  # type: ignore[return-value]

    async def get_process_instance(self, instance_id: str) -> ProcessInstance:
        result = await self._call(
            "GET",
            f"/runtime/process-instances/{instance_id}",
            idempotent=True,
            response_model=ProcessInstance,
        )
        return result  # type: ignore[return-value]

    async def cancel_process_instance(self, instance_id: str) -> None:
        await self._call(
            "DELETE",
            f"/runtime/process-instances/{instance_id}",
            idempotent=False,
            expect_json=False,
        )

    # ------------------------------------------------------------------
    # S-2: User Task Lifecycle
    # ------------------------------------------------------------------

    async def list_tasks(
        self,
        *,
        process_instance_id: str | None = None,
        assignee: str | None = None,
        candidate_group: str | None = None,
        max_results: int = 20,
    ) -> list[Task]:
        params: dict[str, str] = {"size": str(max_results)}
        if process_instance_id:
            params["processInstanceId"] = process_instance_id
        if assignee:
            params["assignee"] = assignee
        if candidate_group:
            params["candidateGroup"] = candidate_group

        raw = await self._call("GET", "/runtime/tasks", idempotent=True, params=params)
        return self._parse_list(raw, Task)

    async def claim_task(self, task_id: str, assignee: str) -> None:
        await self._call(
            "POST",
            f"/runtime/tasks/{task_id}",
            idempotent=False,
            expect_json=False,
            json={"action": "claim", "assignee": assignee},
        )

    async def complete_task(
        self, task_id: str, variables: dict[str, Any] | None = None
    ) -> None:
        body: dict[str, Any] = {"action": "complete"}
        if variables is not None:
            body["variables"] = VariableList.from_python_dict(variables).model_dump()
        await self._call(
            "POST",
            f"/runtime/tasks/{task_id}",
            idempotent=False,
            expect_json=False,
            json=body,
        )

    async def delegate_task(self, task_id: str, assignee: str) -> None:
        await self._call(
            "POST",
            f"/runtime/tasks/{task_id}",
            idempotent=False,
            expect_json=False,
            json={"action": "delegate", "assignee": assignee},
        )

    # ------------------------------------------------------------------
    # S-3: Deployment Management
    # ------------------------------------------------------------------

    async def list_deployments(self, *, name_like: str | None = None) -> list[Deployment]:
        params: dict[str, str] = {}
        if name_like:
            params["nameLike"] = name_like

        raw = await self._call(
            "GET", "/repository/deployments", idempotent=True, params=params
        )
        return self._parse_list(raw, Deployment)

    async def deploy_bpmn(self, name: str, bpmn_bytes: bytes) -> Deployment:
        files = {"file": (name, bpmn_bytes, "application/xml")}
        result = await self._call_multipart(
            "/repository/deployments",
            files=files,
            response_model=Deployment,
        )
        return result  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # S-4: DeadLetter Triage
    # ------------------------------------------------------------------

    async def list_deadletter_jobs(
        self,
        *,
        process_definition_key: str | None = None,
        max_results: int = 50,
    ) -> list[DeadLetterJob]:
        params: dict[str, str] = {"size": str(max_results)}
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key

        raw = await self._call(
            "GET", "/management/deadletter-jobs", idempotent=True, params=params
        )
        return self._parse_list(raw, DeadLetterJob)

    async def retry_deadletter_job(self, job_id: str) -> None:
        await self._call(
            "POST",
            f"/management/deadletter-jobs/{job_id}",
            idempotent=False,
            expect_json=False,
            json={"action": "move"},
        )

    # ------------------------------------------------------------------
    # S-5: Historic Process Instance Query
    # ------------------------------------------------------------------

    async def list_historic_process_instances(
        self,
        *,
        process_definition_key: str | None = None,
        business_key: str | None = None,
        started_before: datetime | None = None,
        started_after: datetime | None = None,
        finished: bool | None = None,
        max_results: int = 100,
    ) -> list[HistoricProcessInstance]:
        params: dict[str, str] = {"size": str(max_results)}
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key
        if business_key:
            params["businessKey"] = business_key
        if started_before is not None:
            params["startedBefore"] = started_before.isoformat()
        if started_after is not None:
            params["startedAfter"] = started_after.isoformat()
        if finished is not None:
            params["finished"] = str(finished).lower()

        raw = await self._call(
            "GET", "/history/historic-process-instances", idempotent=True, params=params
        )
        return self._parse_list(raw, HistoricProcessInstance)

    # ------------------------------------------------------------------
    # S-6: Event Subscriptions
    # ------------------------------------------------------------------

    async def list_event_subscriptions(
        self,
        *,
        event_type: str | None = None,
        process_definition_key: str | None = None,
    ) -> list[EventSubscription]:
        params: dict[str, str] = {}
        if event_type:
            params["eventType"] = event_type
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key

        raw = await self._call(
            "GET", "/runtime/event-subscriptions", idempotent=True, params=params
        )
        return self._parse_list(raw, EventSubscription)

    # ------------------------------------------------------------------
    # TASK-003: Monitoring/Debug wave 2
    # ------------------------------------------------------------------

    async def list_process_instances(
        self,
        *,
        process_definition_key: str | None = None,
        business_key: str | None = None,
        suspended: bool | None = None,
        involved_user: str | None = None,
        max_results: int = 50,
    ) -> list[ProcessInstance]:
        """GET /runtime/process-instances with optional filters (AC-1)."""
        params: dict[str, str] = {"size": str(max_results)}
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key
        if business_key:
            params["businessKey"] = business_key
        if suspended is not None:
            params["suspended"] = str(suspended).lower()
        if involved_user:
            params["involvedUser"] = involved_user

        raw = await self._call(
            "GET", "/runtime/process-instances", idempotent=True, params=params
        )
        return self._parse_list(raw, ProcessInstance)

    async def get_process_variables(self, instance_id: str) -> list[Variable]:
        """GET /runtime/process-instances/{id}/variables — raw JSON array (AC-2, §4.1)."""
        raw = await self._call(
            "GET",
            f"/runtime/process-instances/{instance_id}/variables",
            idempotent=True,
        )
        if not isinstance(raw, list):
            raise FlowableProtocolError(
                f"expected JSON array for variables, got {type(raw).__name__}"
            )
        return [Variable.model_validate(item) for item in raw]

    async def set_process_variable(
        self,
        instance_id: str,
        var_name: str,
        value: str | int | float | bool | None,
        var_type: str | None = None,
    ) -> Variable:
        """PUT /runtime/process-instances/{id}/variables/{encoded_name} (AC-2, §4.2, §4.3)."""
        if var_type is None:
            # bool MUST be checked before int — bool is a subclass of int (§4.3, INV-02)
            if isinstance(value, bool):
                var_type = "boolean"
            elif isinstance(value, int):
                var_type = "integer"
            elif isinstance(value, float):
                var_type = "double"
            elif isinstance(value, str):
                var_type = "string"
            else:
                var_type = "string"  # None → "string" (DD-A2)

        encoded = urllib.parse.quote(var_name, safe="")
        body = {"name": var_name, "value": value, "type": var_type}
        result = await self._call(
            "PUT",
            f"/runtime/process-instances/{instance_id}/variables/{encoded}",
            idempotent=False,
            response_model=Variable,
            json=body,
        )
        return result  # type: ignore[return-value]

    async def list_historic_task_instances(
        self,
        *,
        process_instance_id: str | None = None,
        assignee: str | None = None,
        process_definition_key: str | None = None,
        finished: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        max_results: int = 100,
    ) -> list[HistoricTaskInstance]:
        """GET /history/historic-task-instances with filters (AC-3)."""
        params: dict[str, str] = {"size": str(max_results)}
        if process_instance_id:
            params["processInstanceId"] = process_instance_id
        if assignee:
            params["assignee"] = assignee
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key
        if finished is not None:
            params["finished"] = str(finished).lower()
        if started_after is not None:
            params["startedAfter"] = started_after.isoformat()
        if started_before is not None:
            params["startedBefore"] = started_before.isoformat()

        raw = await self._call(
            "GET", "/history/historic-task-instances", idempotent=True, params=params
        )
        return self._parse_list(raw, HistoricTaskInstance)

    async def set_process_definition_state(
        self,
        definition_id: str,
        *,
        action: Literal["suspend", "activate"],
        include_process_instances: bool = False,
    ) -> ProcessDefinition:
        """PUT /repository/process-definitions/{id} — suspend or activate (AC-4, §4.4)."""
        body = {"action": action, "includeProcessInstances": include_process_instances}
        result = await self._call(
            "PUT",
            f"/repository/process-definitions/{definition_id}",
            idempotent=False,
            response_model=ProcessDefinition,
            json=body,
        )
        return result  # type: ignore[return-value]

    async def set_process_instance_state(
        self,
        instance_id: str,
        *,
        action: Literal["suspend", "activate"],
    ) -> ProcessInstance:
        """PUT /runtime/process-instances/{id} — suspend or activate (AC-4, §4.4)."""
        body = {"action": action}
        result = await self._call(
            "PUT",
            f"/runtime/process-instances/{instance_id}",
            idempotent=False,
            response_model=ProcessInstance,
            json=body,
        )
        return result  # type: ignore[return-value]

    async def delete_deployment(self, deployment_id: str, *, cascade: bool = False) -> None:
        """DELETE /repository/deployments/{id} — 204 No Content (AC-5, §4.4, INV-TASK3-5)."""
        params = {"cascade": str(cascade).lower()}
        await self._call(
            "DELETE",
            f"/repository/deployments/{deployment_id}",
            idempotent=False,
            expect_json=False,
            params=params,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close underlying AsyncClients. Idempotent."""
        if not self._closed:
            self._closed = True
            await self._retry.aclose()
            if self._no_retry is not self._retry:
                await self._no_retry.aclose()
