"""Unit tests for StdioServer.send / .request guards (TASK-006 fix M1, M4).

Covers TC-U-20..TC-U-21. Uses MagicMock for the asyncio subprocess process so
we don't actually spawn anything — only the guard logic matters.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.e2e.conftest import StdioServer

pytestmark = [pytest.mark.unit]


def _make_server(
    *,
    returncode: int | None = None,
    stdin_closing: bool = False,
    stdout_lines: list[str] | None = None,
    stderr: bytes = b"",
) -> StdioServer:
    proc = MagicMock(spec=asyncio.subprocess.Process)
    proc.returncode = returncode
    proc.pid = 12345
    proc.stdin = MagicMock()
    proc.stdin.is_closing = MagicMock(return_value=stdin_closing)
    proc.stdin.write = MagicMock()
    proc.stdin.drain = AsyncMock(return_value=None)

    stdout_reader = AsyncMock()
    stderr_reader = AsyncMock()

    return StdioServer(
        proc=proc,
        stdout_lines=list(stdout_lines or []),
        stderr_buf=bytearray(stderr),
        _stdout_reader=stdout_reader,
        _stderr_reader=stderr_reader,
    )


async def test_stdio_server_send_when_stdin_is_closing_then_raises_runtime_error() -> None:
    server = _make_server(stdin_closing=True, returncode=None)

    with pytest.raises(RuntimeError, match="closed stdin"):
        await server.send({"jsonrpc": "2.0", "method": "ping"})


async def test_stdio_server_request_when_proc_dead_then_raises_runtime_error_with_rc() -> None:
    server = _make_server(
        returncode=1,
        stdin_closing=False,
        stderr=b"Settings() failed: missing FLOWABLE_PASSWORD",
    )

    with pytest.raises(RuntimeError, match="subprocess exited"):
        await server.request("tools/list")
