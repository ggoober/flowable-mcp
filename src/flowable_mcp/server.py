"""FastMCP server: transport layer and lifespan.

Responsibilities:
- configure logging to stderr only (СТ-3, AC-Λ5, shared-standards §8.2)
- create Settings + AsyncClient + FlowableClient in lifespan
- register all MCP tools
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastmcp import FastMCP

from flowable_mcp.client import FlowableClient
from flowable_mcp.config import Settings
from flowable_mcp.tools.process import list_process_definitions

_logger = logging.getLogger(__name__)


def setup_logging() -> None:
    """Configure root logger to write to stderr only.

    Raises RuntimeError on startup if any handler writes to stdout — that would
    corrupt the MCP stdio protocol channel (shared-standards §8.2, AC-Λ5).
    Idempotent: skips handler setup if root logger already has handlers.
    """
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        root.addHandler(handler)
        root.setLevel(logging.INFO)

    # Startup assert: no handler must point at stdout (Invariant I3).
    for handler in root.handlers:
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stdout:
            raise RuntimeError(
                "stdout log handler detected — violates MCP stdio protocol (shared-standards §8.2)"
            )


@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncGenerator[dict[str, Any], None]:
    setup_logging()
    settings = Settings()
    http = httpx.AsyncClient(
        auth=httpx.BasicAuth(settings.username, settings.password.get_secret_value()),
        # transport-only retry for ConnectError (AC-Λ2, DD-5).
        # retries = retry_attempts - 1 so retry_attempts=1 → 0 retries → 1 total attempt.
        transport=httpx.AsyncHTTPTransport(retries=max(0, settings.retry_attempts - 1)),
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        timeout=settings.timeout_s,
    )
    flowable = FlowableClient(settings=settings, http=http)
    _logger.info("flowable-mcp started, base_url=%s", settings.base_url)
    try:
        yield {"client": flowable}
    finally:
        await flowable.aclose()
        _logger.info("flowable-mcp shutdown complete")


mcp = FastMCP("flowable-mcp", lifespan=lifespan)

# DD-1 variant B: tool functions defined in tools/, registered here.
mcp.tool()(list_process_definitions)
