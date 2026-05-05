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
    HistoricActivityInstance,
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


# Sentinel — distinguishes "no timeout override" from 0.0 or None.
# Separate from _MISSING to avoid confusion with the list-parse sentinel.
class _TimeoutMissing:
    """Sentinel type for _call timeout parameter."""


_TIMEOUT_MISSING = _TimeoutMissing()


def _flowable_iso8601(dt: datetime) -> str:
    """Format datetime in Flowable-accepted ISO-8601: millisecond precision + 'Z' for UTC.

    Flowable's Java parser rejects microsecond precision and `+00:00` style offsets
    on some endpoints (e.g. /history/historic-task-instances). Output looks like
    `2026-05-03T07:16:45.771Z`.
    """
    if dt.tzinfo is not None:
        from datetime import timezone

        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f".{millis:03d}Z"


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
    if status == 410:
        return FlowableNotFoundError("Resource not found or completed (410)")
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
        http_diagram: AsyncClient for diagram endpoints; retries=0 (AC-4.2, DD-7).
            Falls back to http_no_retry when None (backward-compat).
        diagram_timeout_s: per-request timeout for diagram PNG fetches (AC-S3-2).
    """

    def __init__(
        self,
        http_retry: httpx.AsyncClient,
        http_no_retry: httpx.AsyncClient,
        http_diagram: httpx.AsyncClient | None = None,
        diagram_timeout_s: float = 30.0,
    ) -> None:
        self._retry = http_retry
        self._no_retry = http_no_retry
        self._diagram_no_retry = http_diagram if http_diagram is not None else http_no_retry
        self._diagram_timeout_s = diagram_timeout_s
        # Extract base URL so _call can build absolute URLs regardless of whether the
        # AsyncClient was configured with base_url or not.
        self._base_url: str = str(http_retry.base_url).rstrip("/")
        # CMMN endpoints in flowable-rest live under /cmmn-api (not /service).
        # Derive the sibling root by swapping the trailing /service segment.
        if self._base_url.endswith("/service"):
            self._cmmn_base_url: str = self._base_url[: -len("/service")] + "/cmmn-api"
        else:
            self._cmmn_base_url = self._base_url + "/cmmn-api"
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
        expect_bytes: bool = False,
        expect_text: bool = False,
        timeout: object = _TIMEOUT_MISSING,
        _http: httpx.AsyncClient | None = None,
        **kwargs: Any,
    ) -> Any:
        """Single entry point for all HTTP calls (AC-N2).

        path must be slash-prefixed, e.g. "/runtime/process-instances".
        Returns: model instance | raw dict/list | None | bytes | str.
        - 204 No Content → None.
        - expect_json=False → None (fire-and-forget actions).
        - expect_bytes=True → (bytes, content_type: str) tuple (AC-S2-6).
        - expect_text=True → decoded str (AC-S1-4).
        - response_model=None + expect_json=True → raw payload dict (list pagination).
        - response_model provided → model_validate(resp.json()).
        - timeout=_TIMEOUT_MISSING → AsyncClient-level default used.
        - timeout=None → TypeError (httpx None = infinite wait, I-1, AC-S3-2).
        - _http: explicit AsyncClient override; bypasses idempotent selection (AC-4.2).
        """
        if timeout is None:
            raise TypeError("timeout=None is forbidden; pass _TIMEOUT_MISSING for no override")
        assert sum([expect_json, expect_bytes, expect_text]) <= 1, (
            "_call: at most one of expect_json/expect_bytes/expect_text may be True (I-3, AC-EDGE-2)"
        )

        client = _http if _http is not None else (self._retry if idempotent else self._no_retry)
        # Absolute URLs (used for CMMN /cmmn-api endpoints) bypass the BPMN base URL.
        url = path if path.startswith(("http://", "https://")) else f"{self._base_url}{path}"

        if timeout is not _TIMEOUT_MISSING:
            kwargs["timeout"] = timeout

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

        if expect_bytes:
            return (resp.content, resp.headers.get("content-type", ""))

        if expect_text:
            return resp.content.decode(resp.encoding or "utf-8")

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

    async def _paginate(
        self,
        method: str,
        path: str,
        model: type[T],
        *,
        params: dict[str, str],
        max_items: int = _MAX_ITEMS,
        page_size: int = _PAGE_SIZE,
    ) -> tuple[list[T], bool]:
        """Fetch all pages from a Flowable list endpoint.

        Returns (items, truncated). truncated=True iff len(items) reached max_items
        before all server items were fetched. Any FlowableError re-raises immediately
        — no partial result is returned. [AC-2, AC-3]
        """
        items: list[T] = []
        start = 0
        while True:
            remaining = max_items - len(items)
            if remaining <= 0:
                _logger.warning(
                    "_paginate hit max_items cap",
                    extra={"max_items": max_items},
                )
                return items[:max_items], True
            size = min(page_size, remaining)
            page_params = {**params, "start": str(start), "size": str(size)}
            try:
                raw = await self._call(method, path, idempotent=True, params=page_params)
            except asyncio.CancelledError:
                raise  # I-02.2: CancelledError must never be swallowed
            # Any FlowableError propagates here without partial result — I-02.1
            page = self._parse_list(raw, model)
            items.extend(page[:remaining])
            total = self._parse_total(raw)
            if not page or len(items) >= total:
                return items, False
            if len(items) >= max_items:
                _logger.warning(
                    "_paginate hit max_items cap",
                    extra={"max_items": max_items, "total": total},
                )
                return items[:max_items], True
            start = len(items)

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
            params["startedBefore"] = _flowable_iso8601(started_before)
        if started_after is not None:
            params["startedAfter"] = _flowable_iso8601(started_after)
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

        items, _ = await self._paginate(
            "GET", "/runtime/event-subscriptions", EventSubscription, params=params
        )
        return items

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
        """Upsert a single variable on a process instance (AC-2, §4.2, §4.3).

        Uses PUT on the plural /variables endpoint with a single-element array
        body — Flowable treats that as create-or-update. The single-name PUT
        (.../variables/{name}) returns 404 if the variable does not yet exist,
        so it cannot serve as a generic "set".
        """
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

        body = [{"name": var_name, "value": value, "type": var_type}]
        raw = await self._call(
            "PUT",
            f"/runtime/process-instances/{instance_id}/variables",
            idempotent=False,
            json=body,
        )
        # Flowable returns the array of upserted variables; pick ours.
        # When value is None Flowable may omit the `type` field in the response,
        # so fall back to the type we sent.
        if isinstance(raw, list) and raw:
            for item in raw:
                if isinstance(item, dict) and item.get("name") == var_name:
                    item.setdefault("type", var_type)
                    return Variable.model_validate(item)
            first = dict(raw[0]) if isinstance(raw[0], dict) else {}
            first.setdefault("type", var_type)
            return Variable.model_validate(first)
        return Variable(name=var_name, value=value, type=var_type)

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
            params["taskAssignee"] = assignee
        if process_definition_key:
            params["processDefinitionKey"] = process_definition_key
        if finished is not None:
            params["finished"] = str(finished).lower()
        if started_after is not None:
            params["taskCreatedAfter"] = _flowable_iso8601(started_after)
        if started_before is not None:
            params["taskCreatedBefore"] = _flowable_iso8601(started_before)

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
    # TASK-004: v0.3 Monitoring/Debug wave 3
    # ------------------------------------------------------------------

    async def list_historic_activity_instances(
        self,
        *,
        process_instance_id: str | None = None,
        process_definition_id: str | None = None,
        activity_type: str | None = None,
        activity_id: str | None = None,
        finished: bool | None = None,
        started_after: datetime | None = None,
        started_before: datetime | None = None,
        max_results: int = 1000,
    ) -> list[HistoricActivityInstance]:
        """GET /history/historic-activity-instances via _paginate (DD-1, AC-4)."""
        params: dict[str, str] = {}
        if activity_type is not None:
            params["activityType"] = activity_type
        if process_instance_id is not None:
            params["processInstanceId"] = process_instance_id
        if process_definition_id is not None:
            params["processDefinitionId"] = process_definition_id
        if activity_id is not None:
            params["activityId"] = activity_id
        if finished is not None:
            params["finished"] = str(finished).lower()
        # Flowable 8.0.0 silently ignores startedBefore/startedAfter on both
        # GET and POST /query for historic-activity-instances — filter client-side.
        items, _ = await self._paginate(
            "GET",
            "/history/historic-activity-instances",
            HistoricActivityInstance,
            params=params,
            max_items=max_results,
        )
        if started_after is not None:
            items = [r for r in items if r.start_time is not None and r.start_time > started_after]
        if started_before is not None:
            items = [r for r in items if r.start_time is not None and r.start_time < started_before]
        return items

    async def set_task_due_date(self, task_id: str, due_date: datetime) -> None:
        """PUT /runtime/tasks/{id} with minimal body {"dueDate": iso}. [AC-5]"""
        body = {"dueDate": _flowable_iso8601(due_date)}
        await self._call(
            "PUT",
            f"/runtime/tasks/{task_id}",
            idempotent=False,
            expect_json=False,
            json=body,
        )

    # ------------------------------------------------------------------
    # TASK-005: Diagram / Source endpoints
    # ------------------------------------------------------------------

    def _definition_resource_path(
        self, definition_type: Literal["process", "case"], definition_id: str, suffix: str
    ) -> str:
        """Build the absolute URL for definition resource endpoints.

        BPMN lives under /service/repository, CMMN under /cmmn-api/cmmn-repository.
        """
        if definition_type == "case":
            return (
                f"{self._cmmn_base_url}/cmmn-repository/case-definitions/"
                f"{definition_id}/{suffix}"
            )
        return f"/repository/process-definitions/{definition_id}/{suffix}"

    def _instance_diagram_path(
        self, instance_type: Literal["process", "case"], instance_id: str
    ) -> str:
        """Build the absolute URL for instance diagram endpoints (BPMN vs CMMN)."""
        if instance_type == "case":
            return (
                f"{self._cmmn_base_url}/cmmn-runtime/case-instances/"
                f"{instance_id}/diagram"
            )
        return f"/runtime/process-instances/{instance_id}/diagram"

    async def get_definition_resource(
        self,
        definition_type: Literal["process", "case"],
        definition_id: str,
    ) -> str:
        """GET {definition resource} → raw text.

        BPMN: /repository/process-definitions/{id}/resourcedata.
        CMMN: /cmmn-api/cmmn-repository/case-definitions/{id}/resourcedata.
        No .strip() here — whitespace handling is at tool level (AC-4.5, I-15).
        """
        path = self._definition_resource_path(definition_type, definition_id, "resourcedata")
        result = await self._call(
            "GET",
            path,
            idempotent=True,
            expect_json=False,
            expect_text=True,
            _http=self._diagram_no_retry,
        )
        return result  # type: ignore[return-value]

    async def get_definition_model(
        self,
        definition_type: Literal["process", "case"],
        definition_id: str,
    ) -> dict[str, Any]:
        """GET {definition model} → raw dict (BPMN /repository or CMMN /cmmn-api)."""
        path = self._definition_resource_path(definition_type, definition_id, "model")
        result = await self._call(
            "GET",
            path,
            idempotent=True,
            expect_json=True,
            _http=self._diagram_no_retry,
        )
        return result  # type: ignore[return-value]

    async def get_definition_diagram(
        self,
        definition_type: Literal["process", "case"],
        definition_id: str,
    ) -> tuple[bytes, str]:
        """GET {definition image} → (raw PNG bytes, content-type).

        Validation happens in the tool layer (DD-6, AC-4.1).
        """
        path = self._definition_resource_path(definition_type, definition_id, "image")
        result = await self._call(
            "GET",
            path,
            idempotent=True,
            expect_json=False,
            expect_bytes=True,
            timeout=self._diagram_timeout_s,
            _http=self._diagram_no_retry,
        )
        return result  # type: ignore[return-value]

    async def get_instance_diagram(
        self,
        instance_type: Literal["process", "case"],
        instance_id: str,
    ) -> tuple[bytes, str]:
        """GET {instance diagram} → (raw PNG bytes, content-type).

        BPMN: /runtime/process-instances/{id}/diagram.
        CMMN: /cmmn-api/cmmn-runtime/case-instances/{id}/diagram.
        410 Gone → FlowableNotFoundError (AC-S3-4, I-10).
        """
        path = self._instance_diagram_path(instance_type, instance_id)
        result = await self._call(
            "GET",
            path,
            idempotent=True,
            expect_json=False,
            expect_bytes=True,
            timeout=self._diagram_timeout_s,
            _http=self._diagram_no_retry,
        )
        return result  # type: ignore[return-value]

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
            if self._diagram_no_retry is not self._no_retry and self._diagram_no_retry is not self._retry:
                await self._diagram_no_retry.aclose()
