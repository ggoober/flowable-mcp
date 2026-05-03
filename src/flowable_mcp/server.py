"""FastMCP server: transport layer and lifespan.

Responsibilities:
- configure logging to stderr only (СТ-3, AC-X2, shared-standards §8.2)
- create Settings + two AsyncClients + FlowableClient in lifespan (CC-1, AC-N1)
- register all MCP tools via per-module register() (AC-N3)
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

import httpx
from fastmcp import FastMCP

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools import admin, debug, history, process, task

_logger = logging.getLogger(__name__)

EXPECTED_TOOLS: frozenset[str] = frozenset({
    "list_process_definitions",
    "start_process_instance",
    "get_process_instance",
    "cancel_process_instance",
    "list_tasks",
    "claim_task",
    "complete_task",
    "delegate_task",
    "list_deployments",
    "deploy_bpmn",
    "list_deadletter_jobs",
    "retry_deadletter_job",
    "list_historic_process_instances",
    "list_event_subscriptions",
    "list_process_instances",
    "get_process_variables",
    "set_process_variable",
    "list_historic_task_instances",
    "suspend_process_definition",
    "activate_process_definition",
    "suspend_process_instance",
    "activate_process_instance",
    "delete_deployment",
    "list_historic_activity_instances",
    "set_task_due_date",
})


def setup_logging() -> None:
    """Configure root logger to write to stderr only.

    Idempotent: skips handler setup if root logger already has handlers.
    Raises RuntimeError if any handler writes to stdout — would corrupt MCP stdio (AC-X2).
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            raise RuntimeError(
                "stdout log handler detected — violates MCP stdio protocol (shared-standards §8.2)"
            )


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
    setup_logging()
    settings = Settings()

    async with AsyncExitStack() as stack:
        http_retry = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url=settings.base_url + "/",
                auth=httpx.BasicAuth(settings.username, settings.password.get_secret_value()),
                transport=httpx.AsyncHTTPTransport(retries=max(0, settings.retry_attempts - 1)),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                timeout=settings.timeout_s,
            )
        )
        http_no_retry = await stack.enter_async_context(
            httpx.AsyncClient(
                base_url=settings.base_url + "/",
                auth=httpx.BasicAuth(settings.username, settings.password.get_secret_value()),
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
                timeout=settings.timeout_s,
            )
        )
        client = FlowableClient(http_retry, http_no_retry)
        stack.push_async_callback(client.aclose)  # HC-5: ensure _closed=True on teardown

        # Re-register tools on every lifespan: a fresh FlowableClient is captured
        # by closures inside register(), so previous-session closed clients are not
        # reused. Clear any registrations from a prior lifespan first.
        for tool_name in list(EXPECTED_TOOLS):
            try:
                mcp.remove_tool(tool_name)
            except Exception:
                pass
        for mod in (process, task, history, debug, admin):
            mod.register(mcp, client)

        actual_tools = frozenset(t.name for t in await mcp._list_tools())
        assert actual_tools == EXPECTED_TOOLS, (
            f"Tool set mismatch — extra: {actual_tools - EXPECTED_TOOLS}, "
            f"missing: {EXPECTED_TOOLS - actual_tools}"
        )

        _logger.info("flowable-mcp started, base_url=%s", settings.base_url)
        yield {"client": client}
        _logger.info("flowable-mcp shutdown complete")


mcp = FastMCP("flowable-mcp", lifespan=lifespan)
