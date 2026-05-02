"""Flowable REST adapter.

Async-only outbound HTTP via httpx.AsyncClient (СТ-5).
Single client instance per lifespan — injected via DI, never module-level (Invariant I5).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from flowable_mcp.config import Settings
from flowable_mcp.errors import (
    FlowableAuthError,
    FlowableConnectionError,
    FlowableNotFoundError,
    FlowableProtocolError,
    FlowableServerError,
)
from flowable_mcp.models import ProcessDefinition

_logger = logging.getLogger(__name__)

# Sentinel for missing dict key (distinguishes missing from null, AC-X2).
_MISSING: object = object()

# Per-page size for auto-pagination — Flowable's documented per-request cap.
_PAGE_SIZE: int = 100
# Hard cap on total items returned across all pages (defence against unbounded
# fetches if Flowable's `total` is unreliable). 10k covers any realistic
# deployment of process definitions; raise if BPM catalogue grows past that.
_MAX_ITEMS: int = 10_000


class FlowableClient:
    """Async adapter for Flowable REST API.

    Args:
        settings: Application settings (base_url, credentials, timeouts).
        http: Pre-configured AsyncClient injected by lifespan (DD-2 / AC-Λ1).
    """

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._settings = settings
        self._http = http
        self._closed: bool = False  # idempotent aclose guard (Invariant I5)

    async def list_process_definitions(
        self,
        *,
        latest: bool = True,
        key: str | None = None,
    ) -> list[ProcessDefinition]:
        """GET /repository/process-definitions with optional latest/key filters.

        Auto-paginates over Flowable's ``start``/``size`` query params and merges
        every page until ``total`` items have been collected (or ``_MAX_ITEMS``
        is hit as a safety cap). Without this loop, Flowable's default page size
        (typically 10) would silently truncate the result for any non-trivial
        catalogue.

        Raises:
            FlowableAuthError: 401/403 — credentials rejected; no retry (AC-Λ3).
            FlowableNotFoundError: 404 — endpoint not found.
            FlowableServerError: 5xx — Flowable internal error.
            FlowableConnectionError: ConnectError/Timeout after transport retries.
            FlowableProtocolError: Malformed response structure (AC-Λ6).
        """
        base_params: dict[str, str] = {"latest": str(latest).lower()}
        if key:  # key="" → omit, same as None (AC-X7)
            base_params["key"] = key

        items: list[dict[object, object]] = []
        start = 0
        while True:
            page_params = {
                **base_params,
                "start": str(start),
                "size": str(_PAGE_SIZE),
            }
            data, total = await self._fetch_definitions_page(page_params)
            items.extend(data)

            if not data:
                break
            if len(items) >= total:
                break
            if len(items) >= _MAX_ITEMS:
                _logger.warning(
                    "flowable list_process_definitions hit _MAX_ITEMS cap; "
                    "result may be truncated",
                    extra={"max_items": _MAX_ITEMS, "total": total},
                )
                break
            start = len(items)

        return [ProcessDefinition.model_validate(item) for item in items]

    async def _fetch_definitions_page(
        self, params: dict[str, str]
    ) -> tuple[list[dict[object, object]], int]:
        """Fetch a single page of process definitions and return (data, total)."""
        t0 = time.perf_counter()
        try:
            resp = await self._http.get(
                f"{self._settings.base_url}/repository/process-definitions",
                params=params,
            )
        except asyncio.CancelledError:
            raise  # propagate — never swallow CancelledError (AC-Λ4, shared-standards §5.2)
        except httpx.TransportError as exc:
            raise FlowableConnectionError(
                f"Connection failed: {type(exc).__name__}"
            ) from exc

        _logger.info(
            "flowable http",
            extra={
                "method": "GET",
                "path": "/repository/process-definitions",
                "status": resp.status_code,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            },
        )

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (401, 403):
                # Credentials must not appear in the error message (Invariant I7, AC-2).
                raise FlowableAuthError(
                    f"Authentication failed ({status})"
                ) from exc
            if status == 404:
                raise FlowableNotFoundError("Endpoint not found") from exc
            body_snippet = exc.response.text[:200]
            raise FlowableServerError(f"Server error {status}: {body_snippet}") from exc

        payload: dict[object, object] = resp.json()
        if not isinstance(payload, dict):
            raise FlowableProtocolError(
                f"expected JSON object at root, got {type(payload).__name__}"
            )
        data = payload.get("data", _MISSING)

        if data is _MISSING:
            raise FlowableProtocolError(
                f"expected 'data' key in response, got keys: {list(payload.keys())}"
            )
        if data is None:
            raise FlowableProtocolError("'data' is null in Flowable response")
        if not isinstance(data, list):
            raise FlowableProtocolError(
                f"expected list at .data, got {type(data).__name__}"
            )

        total_raw = payload.get("total")
        if isinstance(total_raw, int):
            total = total_raw
        else:
            # Defensive fallback: if Flowable omits/garbles `total`, treat the
            # current page as the whole result so the caller gets *something*
            # rather than an infinite loop.
            total = len(data)

        return data, total

    async def aclose(self) -> None:
        """Close the underlying AsyncClient. Idempotent (Invariant I5)."""
        if not self._closed:
            self._closed = True
            await self._http.aclose()
