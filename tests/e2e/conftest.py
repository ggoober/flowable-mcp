"""Shared fixtures for E2E tests.

Two transports are provided:

1. **In-process** via ``fastmcp.Client(mcp)`` — fast, hermetic, covers the
   tool/MCP contract end-to-end for non-diagram tests.

2. **Subprocess stdio** via ``python -m flowable_mcp`` — used for tests where
   the process boundary is the subject (stdout silence per СТ-3, graceful
   shutdown) AND for diagram tests (TASK-006: anyio in-memory streams +
   pytest-asyncio mixed loop scopes deadlock on Windows ProactorEventLoop;
   process boundary eliminates cross-loop binding).

Boundary between the two harnesses is enforced by the ``pytest_collection_modifyitems``
hook below: any file matching ``test_*_diagram*.py`` under ``tests/e2e/`` is
auto-tagged with the ``diagram_e2e`` marker. Combined with ``--strict-markers``
in ``pyproject.toml`` and a CI count check, this turns the convention into a
machine-checkable invariant (TASK-006 §0.1 rule §9.Y).

Both transports require a live ``flowable-rest:8.0.0`` container.
"""

from __future__ import annotations

import asyncio
import fnmatch
import json
import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastmcp import Client

from flowable_mcp.config import Settings


_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Auto-marker hook (TASK-006 §12 mandatory #1, §0.1 rule §9.Y)
# ---------------------------------------------------------------------------


_DIAGRAM_FILE_PATTERN = "test_*_diagram*.py"


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag every diagram e2e test with ``diagram_e2e``.

    Filename pattern is ``test_*_diagram*.py`` under any ``tests/e2e/`` path.
    A forgotten manual marker would silently send a diagram test through the
    in-process path and reproduce the TASK-006 hang, so the marker must be
    derived, not hand-written. Combined with ``--strict-markers`` in
    pyproject.toml, unknown markers raise a collection error.
    """
    e2e_root = Path(__file__).parent.resolve()
    marker = pytest.mark.diagram_e2e
    for item in items:
        item_path = Path(str(item.fspath)).resolve()
        try:
            item_path.relative_to(e2e_root)
        except ValueError:
            continue  # not under tests/e2e/
        # ``fnmatchcase``: case-sensitive on all platforms — Windows ``fnmatch``
        # is case-insensitive by default which would mis-tag ``test_e2e_DIAGRAM_*``
        # variants and break the boundary contract.
        if fnmatch.fnmatchcase(item_path.name, _DIAGRAM_FILE_PATTERN):
            item.add_marker(marker)


FIXTURE_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "sample.bpmn20.xml"
)
FIXTURE_USER_TASK_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "user-task-process.bpmn20.xml"
)
FIXTURE_FAILING_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "failing-service-task.bpmn20.xml"
)
FIXTURE_MESSAGE_EVENT_BPMN = (
    Path(__file__).parent.parent / "integration" / "fixtures" / "message-event.bpmn20.xml"
)
SAMPLE_PROCESS_KEY = "hello-world"
USER_TASK_PROCESS_KEY = "user-task-process"
FAILING_PROCESS_KEY = "failing-service-task"
MESSAGE_EVENT_PROCESS_KEY = "message-event-process"


# ---------------------------------------------------------------------------
# Settings + Flowable bootstrap (mirrors integration/conftest.py)
#
# Single source for default env (subprocess + Settings). Never mutates global
# ``os.environ`` (DA #7: ``os.environ.setdefault`` races with subprocess that
# copies env at spawn time).
# ---------------------------------------------------------------------------

_E2E_ENV_DEFAULTS = {
    "FLOWABLE_BASE_URL": "http://localhost:8080/flowable-rest/service",
    "FLOWABLE_USERNAME": "rest-admin",
    "FLOWABLE_PASSWORD": "test",
}


def _build_e2e_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build env dict for subprocess from ``os.environ`` + E2E defaults.

    Operates on a local copy — never mutates ``os.environ``.
    """
    env = os.environ.copy()
    for key, default in _E2E_ENV_DEFAULTS.items():
        env.setdefault(key, default)
    if overrides:
        env.update(overrides)
    return env


@pytest.fixture(scope="session")
def e2e_settings() -> Settings:
    """Build :class:`Settings` from env + E2E defaults without mutating ``os.environ``."""
    env = _build_e2e_env()
    return Settings(
        base_url=env["FLOWABLE_BASE_URL"],
        username=env["FLOWABLE_USERNAME"],
        password=env["FLOWABLE_PASSWORD"],
    )


@pytest_asyncio.fixture(scope="session")
async def e2e_http(e2e_settings: Settings) -> AsyncGenerator[httpx.AsyncClient, None]:
    async with httpx.AsyncClient(
        auth=httpx.BasicAuth(
            e2e_settings.username, e2e_settings.password.get_secret_value()
        ),
        timeout=30.0,
    ) as client:
        yield client


# ---------------------------------------------------------------------------
# Retry helper for session-scoped deploy fixtures (DA #1: Flowable REST flap
# resilience — single 503 should not bring down the whole session).
# ---------------------------------------------------------------------------


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    files: dict,
    attempts: int = 3,
    base_delay: float = 0.5,
) -> httpx.Response:
    """POST with retry on transient 5xx / connection errors. Raises on last attempt."""
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            resp = await client.post(url, files=files)
            if resp.status_code < 500:
                resp.raise_for_status()
                return resp
            last_exc = httpx.HTTPStatusError(
                f"{resp.status_code} from {url}", request=resp.request, response=resp
            )
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            last_exc = exc
        if attempt < attempts:
            await asyncio.sleep(base_delay * (2 ** (attempt - 1)))
    assert last_exc is not None
    raise last_exc


async def _deploy_bpmn(
    e2e_settings: Settings,
    e2e_http: httpx.AsyncClient,
    fixture_path: Path,
) -> AsyncGenerator[str, None]:
    bpmn = fixture_path.read_bytes()
    deploy_url = f"{e2e_settings.base_url}/repository/deployments"
    files = {"file": (fixture_path.name, bpmn, "application/xml")}
    resp = await _post_with_retry(e2e_http, deploy_url, files=files)
    deployment_id: str = resp.json()["id"]
    try:
        yield deployment_id
    finally:
        try:
            await e2e_http.delete(
                f"{e2e_settings.base_url}/repository/deployments/{deployment_id}",
                params={"cascade": "true"},
            )
        except (httpx.HTTPStatusError, httpx.ConnectError, httpx.ReadError) as exc:
            # Best-effort teardown — Flowable restart between deploy and
            # cleanup must not mask test results behind ERROR (M5 / F-DI-3).
            _LOG.warning("teardown DELETE %s failed: %r", deployment_id, exc)


@pytest_asyncio.fixture(scope="session")
async def e2e_deployed_process(
    e2e_settings: Settings, e2e_http: httpx.AsyncClient
) -> AsyncGenerator[str, None]:
    async for deployment_id in _deploy_bpmn(e2e_settings, e2e_http, FIXTURE_BPMN):
        yield deployment_id


@pytest_asyncio.fixture(scope="session")
async def e2e_deployed_failing_process(
    e2e_settings: Settings, e2e_http: httpx.AsyncClient
) -> AsyncGenerator[str, None]:
    async for deployment_id in _deploy_bpmn(e2e_settings, e2e_http, FIXTURE_FAILING_BPMN):
        yield deployment_id


@pytest_asyncio.fixture(scope="session")
async def e2e_deployed_message_event_process(
    e2e_settings: Settings, e2e_http: httpx.AsyncClient
) -> AsyncGenerator[str, None]:
    async for deployment_id in _deploy_bpmn(e2e_settings, e2e_http, FIXTURE_MESSAGE_EVENT_BPMN):
        yield deployment_id


@pytest_asyncio.fixture(scope="session")
async def e2e_deployed_user_task_process(
    e2e_settings: Settings, e2e_http: httpx.AsyncClient
) -> AsyncGenerator[str, None]:
    async for deployment_id in _deploy_bpmn(e2e_settings, e2e_http, FIXTURE_USER_TASK_BPMN):
        yield deployment_id


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


# 10 MiB — well above any expected JSON-RPC envelope (PNG diagrams up to
# Settings.diagram_max_png_bytes = 5 MiB → base64 ≈ 6.7 MiB; +overhead).
_STDOUT_BUFFER_HARD_LIMIT = 10 * 1024 * 1024
_STDIO_CHUNK_SIZE = 64 * 1024  # raw read chunk; bypasses StreamReader._limit (DA #C)
_REQUEST_DEADLINE_S = 15.0  # per-RPC timeout
_REQUEST_POLL_INTERVAL_S = 0.02  # poll between pump pushes
_GRACEFUL_SHUTDOWN_TIMEOUT_S = 2.0  # mandatory #5
_PUMP_DRAIN_TIMEOUT_S = 1.0
_STDIN_DRAIN_TIMEOUT_S = 5.0  # M1: bounded write so dead subprocess fails fast


@dataclass
class StdioServer:
    proc: asyncio.subprocess.Process
    stdout_lines: list[str]
    stderr_buf: bytearray
    _stdout_reader: asyncio.Task[None]
    _stderr_reader: asyncio.Task[None]
    _next_id: int = 0
    _seen_lines: int = 0
    _request_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def send(self, payload: dict) -> None:
        # M1 (F-T-1): write into a closed pipe is a programmer error on a dead
        # subprocess; raise eagerly with diagnostics instead of letting drain()
        # hang on Win ProactorEventLoop.
        if self.proc.stdin is None or self.proc.stdin.is_closing():
            raise RuntimeError(
                f"send() into closed stdin (proc.returncode={self.proc.returncode!r})"
            )
        line = (json.dumps(payload) + "\n").encode("utf-8")
        self.proc.stdin.write(line)
        await asyncio.wait_for(
            self.proc.stdin.drain(), timeout=_STDIN_DRAIN_TIMEOUT_S
        )

    async def request(self, method: str, params: dict | None = None) -> dict:
        # Lock serialises requests so ``_seen_lines`` cursor stays consistent.
        async with self._request_lock:
            rpc_id = self._new_id()
            await self.send(
                {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
            )
            loop = asyncio.get_running_loop()  # H2 (F-A-1): get_event_loop() deprecated
            deadline = loop.time() + _REQUEST_DEADLINE_S
            while True:
                # M4 (F-E-2): fast-fail if subprocess has already exited; the
                # response will never arrive, so block-waiting 15s wastes time
                # and hides the real cause (e.g. Settings() bootstrap failure).
                if self.proc.returncode is not None:
                    tail = bytes(self.stderr_buf[-1000:])
                    raise RuntimeError(
                        f"subprocess exited (rc={self.proc.returncode}) before "
                        f"id={rpc_id}; stderr tail: {tail!r}"
                    )
                if loop.time() >= deadline:
                    raise TimeoutError(
                        f"No response for id={rpc_id} within {_REQUEST_DEADLINE_S}s"
                    )
                while self._seen_lines < len(self.stdout_lines):
                    raw = self.stdout_lines[self._seen_lines]
                    self._seen_lines += 1
                    try:
                        obj = json.loads(raw)
                    except json.JSONDecodeError:
                        # Non-JSON output on stdio is a СТ-3 violation; do not
                        # silently swallow it (DA #8). Record as breadcrumb so
                        # tests that check stdout discipline can detect it.
                        self.stderr_buf.extend(
                            b"[stdio-non-json]: "
                            + raw.encode("utf-8", errors="replace")
                            + b"\n"
                        )
                        continue
                    if isinstance(obj, dict) and obj.get("id") == rpc_id:
                        return obj
                await asyncio.sleep(_REQUEST_POLL_INTERVAL_S)

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
        # Mandatory #10 / DA #3 — chosen strategy is "subprocess kill → OS
        # closes stdout/stderr pipes → pump tasks unblock on empty-bytes EOF",
        # NOT "explicit pipe close before wait()". The two are functionally
        # equivalent here because we never rely on Task.cancel() to wake an
        # IOCP read on Windows ProactorEventLoop (which is unreliable).
        #
        # 1) Signal EOF on stdin → server should exit gracefully.
        await self.close_stdin()

        # 2) Wait for graceful shutdown (per mandatory #5: 2.0s timeout).
        try:
            await asyncio.wait_for(
                self.proc.wait(), timeout=_GRACEFUL_SHUTDOWN_TIMEOUT_S
            )
        except TimeoutError:
            self.proc.kill()
            # H3 (F-B-2): defensive timeout on the post-kill wait — on Windows
            # a hard kill almost always returns immediately, but if IOCP wedges
            # we must not block the entire test session indefinitely.
            try:
                await asyncio.wait_for(
                    self.proc.wait(), timeout=_GRACEFUL_SHUTDOWN_TIMEOUT_S
                )
            except TimeoutError:
                _LOG.error(
                    "subprocess (pid=%s) did not exit within %.1fs after kill()",
                    self.proc.pid,
                    _GRACEFUL_SHUTDOWN_TIMEOUT_S,
                )

        # 3) Subprocess is dead → stdout/stderr pipes return EOF naturally,
        #    and pump tasks finish on their own. Drain with a short timeout.
        for task in (self._stdout_reader, self._stderr_reader):
            try:
                await asyncio.wait_for(task, timeout=_PUMP_DRAIN_TIMEOUT_S)
            except TimeoutError:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            except asyncio.CancelledError:
                pass


@asynccontextmanager
async def spawn_mcp_subprocess(
    env_overrides: dict[str, str] | None = None,
) -> AsyncGenerator[StdioServer, None]:
    """Spawn ``python -m flowable_mcp`` and capture stdout/stderr separately.

    DA #C fix: ``pump_stdout`` reads raw chunks and splits on ``\\n`` instead
    of ``StreamReader.readline()`` whose default ``_limit=64*1024`` would raise
    ``LimitOverrunError`` on JSON-RPC envelopes carrying base64 PNG payloads
    (~50–200 KB inline).
    """
    env = _build_e2e_env(env_overrides)

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
        """Read stdout as raw chunks, split into newline-terminated lines.

        Uses ``read(N)`` instead of ``readline()`` to bypass the 64 KiB
        ``StreamReader._limit`` (DA #C). Lines are accumulated in an unbounded
        buffer (capped by ``_STDOUT_BUFFER_HARD_LIMIT`` to prevent OOM if the
        server emits a stuck non-newline-terminated stream).
        """
        assert proc.stdout is not None
        buf = bytearray()
        while True:
            chunk = await proc.stdout.read(_STDIO_CHUNK_SIZE)
            if not chunk:
                if buf:
                    stdout_lines.append(buf.decode("utf-8", errors="replace"))
                break
            buf.extend(chunk)
            while True:
                nl = buf.find(b"\n")
                if nl < 0:
                    break
                line = bytes(buf[:nl])
                del buf[: nl + 1]
                stdout_lines.append(line.decode("utf-8", errors="replace"))
            if len(buf) > _STDOUT_BUFFER_HARD_LIMIT:
                _LOG.error(
                    "spawn_mcp_subprocess: stdout buffer exceeded %d bytes "
                    "without newline; aborting pump",
                    _STDOUT_BUFFER_HARD_LIMIT,
                )
                raise RuntimeError(
                    f"stdout buffer overflow (>{_STDOUT_BUFFER_HARD_LIMIT} bytes "
                    "without newline) — server framing is broken"
                )

    async def pump_stderr() -> None:
        assert proc.stderr is not None
        while True:
            chunk = await proc.stderr.read(_STDIO_CHUNK_SIZE)
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
