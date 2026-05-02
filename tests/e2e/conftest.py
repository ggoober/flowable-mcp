"""Shared fixtures for E2E tests.

Two transports are provided:

1. **In-process** via ``fastmcp.Client(mcp)`` — fast, hermetic, covers the
   tool/MCP contract end-to-end (params marshalling, schema, lifespan).

2. **Subprocess stdio** via ``python -m flowable_mcp`` over a real OS pipe —
   used only for tests where the *process boundary* is the subject (stdout
   silence per СТ-3, graceful shutdown on stdin EOF).

Both transports require a live ``flowable-rest:8.0.0`` container; reuse the
deployment fixture from ``tests/integration/conftest.py`` when possible.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client

from flowable_mcp.config import Settings


FIXTURE_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "sample.bpmn20.xml"
)
SAMPLE_PROCESS_KEY = "hello-world"


# ---------------------------------------------------------------------------
# Settings + Flowable bootstrap (mirrors integration/conftest.py)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    os.environ.setdefault("FLOWABLE_BASE_URL", "http://localhost:8080/flowable-rest/service")
    os.environ.setdefault("FLOWABLE_USERNAME", "rest-admin")
    os.environ.setdefault("FLOWABLE_PASSWORD", "test")
    return Settings()


@pytest_asyncio.fixture(scope="session")
async def e2e_http(e2e_settings: Settings) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        auth=httpx.BasicAuth(
            e2e_settings.username, e2e_settings.password.get_secret_value()
        ),
        timeout=30.0,
    ) as client:
        yield client


@pytest_asyncio.fixture(scope="session")
async def e2e_deployed_process(
    e2e_settings: Settings, e2e_http: httpx.AsyncClient
) -> AsyncGenerator[str, None]:
    bpmn = FIXTURE_BPMN.read_bytes()
    deploy_url = f"{e2e_settings.base_url}/repository/deployments"
    files = {"file": ("sample.bpmn20.xml", bpmn, "application/xml")}
    resp = await e2e_http.post(deploy_url, files=files)
    resp.raise_for_status()
    deployment_id: str = resp.json()["id"]
    try:
        yield deployment_id
    finally:
        await e2e_http.delete(
            f"{e2e_settings.base_url}/repository/deployments/{deployment_id}",
            params={"cascade": "true"},
        )


# ---------------------------------------------------------------------------
# In-process Client(mcp)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(loop_scope="function")
async def mcp_client(e2e_settings: Settings) -> AsyncGenerator[Client, None]:
    """In-process MCP client connected to the real ``mcp`` FastMCP instance.

    Each test gets a fresh session (fresh lifespan → fresh FlowableClient),
    so monkeypatching ``FLOWABLE_*`` env vars before entering this fixture
    is supported.
    """
    # Imported here so a missing FLOWABLE_PASSWORD in the env doesn't break
    # the integration test collection — Settings() runs only inside lifespan.
    from flowable_mcp.server import mcp

    async with Client(mcp) as client:
        yield client


# ---------------------------------------------------------------------------
# Real-subprocess stdio harness
# ---------------------------------------------------------------------------


@dataclass
class StdioServer:
    proc: asyncio.subprocess.Process
    stdout_lines: list[str]
    stderr_buf: bytearray
    _stdout_reader: asyncio.Task[None]
    _stderr_reader: asyncio.Task[None]
    _next_id: int = 0

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def send(self, payload: dict) -> None:
        assert self.proc.stdin is not None
        line = (json.dumps(payload) + "\n").encode("utf-8")
        self.proc.stdin.write(line)
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict | None = None) -> dict:
        rpc_id = self._new_id()
        await self.send(
            {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
        )
        # Read until we see a response with this id.
        deadline = asyncio.get_event_loop().time() + 15.0
        while True:
            timeout = deadline - asyncio.get_event_loop().time()
            if timeout <= 0:
                raise TimeoutError(f"No response for id={rpc_id} within 15s")
            await asyncio.sleep(0.02)
            for raw in list(self.stdout_lines):
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict) and obj.get("id") == rpc_id:
                    return obj

    async def notify(self, method: str, params: dict | None = None) -> None:
        await self.send(
            {"jsonrpc": "2.0", "method": method, "params": params or {}}
        )

    async def initialize(self) -> dict:
        result = await self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "e2e-harness", "version": "0.0.0"},
            },
        )
        await self.notify("notifications/initialized")
        return result

    async def close_stdin(self) -> None:
        if self.proc.stdin is not None and not self.proc.stdin.is_closing():
            self.proc.stdin.close()

    async def aclose(self) -> None:
        await self.close_stdin()
        try:
            await asyncio.wait_for(self.proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            self.proc.kill()
            await self.proc.wait()
        for task in (self._stdout_reader, self._stderr_reader):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass


@asynccontextmanager
async def spawn_mcp_subprocess(
    env_overrides: dict[str, str] | None = None,
) -> AsyncGenerator[StdioServer, None]:
    """Spawn ``python -m flowable_mcp`` and capture stdout/stderr separately."""
    env = os.environ.copy()
    env.setdefault("FLOWABLE_BASE_URL", "http://localhost:8080/flowable-rest/service")
    env.setdefault("FLOWABLE_USERNAME", "rest-admin")
    env.setdefault("FLOWABLE_PASSWORD", "test")
    if env_overrides:
        env.update(env_overrides)

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        "-u",  # unbuffered → stdout is line-flushed for predictable framing
        "-m",
        "flowable_mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    stdout_lines: list[str] = []
    stderr_buf = bytearray()

    async def pump_stdout() -> None:
        assert proc.stdout is not None
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            stdout_lines.append(line.decode("utf-8", errors="replace").rstrip("\n"))

    async def pump_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(4096)
            if not chunk:
                break
            stderr_buf.extend(chunk)

    server = StdioServer(
        proc=proc,
        stdout_lines=stdout_lines,
        stderr_buf=stderr_buf,
        _stdout_reader=asyncio.create_task(pump_stdout()),
        _stderr_reader=asyncio.create_task(pump_stderr()),
    )
    try:
        yield server
    finally:
        await server.aclose()
