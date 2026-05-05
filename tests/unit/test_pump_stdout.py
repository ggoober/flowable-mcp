"""Unit tests for spawn_mcp_subprocess::pump_stdout chunking (TASK-006 M6 / F-QA-2).

Covers TC-U-08..TC-U-12 from test-scenarios_05_05_26.md.
The pump function is a closure inside ``spawn_mcp_subprocess`` — we re-implement
the same algorithm here against an ``asyncio.StreamReader`` stub. This validates
the algorithmic invariants (chunk split, EOF tail, hard limit) without spawning
a subprocess. The closure cannot be imported, so a thin local copy mirrors the
contract; if ``conftest.py`` deviates, these tests will need updating in lockstep
(documented as a known coupling, see CRITICAL DA #C in spec §12 #7).
"""

from __future__ import annotations

import asyncio

import pytest

# These constants must mirror tests/e2e/conftest.py exactly.
from tests.e2e.conftest import _STDIO_CHUNK_SIZE, _STDOUT_BUFFER_HARD_LIMIT

pytestmark = [pytest.mark.unit]


async def _drive_pump(reader: asyncio.StreamReader) -> list[str]:
    """Run the same algorithm as spawn_mcp_subprocess::pump_stdout against a stub reader."""
    stdout_lines: list[str] = []
    buf = bytearray()
    while True:
        chunk = await reader.read(_STDIO_CHUNK_SIZE)
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
            raise RuntimeError(
                f"stdout buffer overflow (>{_STDOUT_BUFFER_HARD_LIMIT} bytes "
                "without newline) — server framing is broken"
            )
    return stdout_lines


def _stream_with_data(*chunks: bytes, eof: bool = True) -> asyncio.StreamReader:
    reader = asyncio.StreamReader()
    for chunk in chunks:
        reader.feed_data(chunk)
    if eof:
        reader.feed_eof()
    return reader


# ---------------------------------------------------------------------------
# TC-U-08..TC-U-12
# ---------------------------------------------------------------------------


async def test_pump_stdout_when_small_chunk_with_newline_then_single_line_extracted() -> None:
    reader = _stream_with_data(b"hello\n")

    lines = await _drive_pump(reader)

    assert lines == ["hello"]


async def test_pump_stdout_when_chunk_exceeds_64kb_then_line_parsed_correctly() -> None:
    payload = b"X" * 70_000  # exceeds default StreamReader._limit=64KB
    reader = _stream_with_data(payload + b"\n")

    lines = await asyncio.wait_for(_drive_pump(reader), timeout=5.0)

    assert lines == [payload.decode("ascii")]
    assert len(lines[0]) == 70_000


async def test_pump_stdout_when_eof_without_newline_then_partial_line_appended() -> None:
    reader = _stream_with_data(b"partial-no-newline")

    lines = await _drive_pump(reader)

    assert lines == ["partial-no-newline"]


async def test_pump_stdout_when_two_newlines_in_one_chunk_then_two_lines_extracted() -> None:
    reader = _stream_with_data(b"line1\nline2\n")

    lines = await _drive_pump(reader)

    assert lines == ["line1", "line2"]


async def test_pump_stdout_when_buffer_exceeds_hard_limit_then_raises_runtime_error() -> None:
    # Feed slightly more than the 10 MiB limit without any newline so the
    # overflow guard fires.
    big_chunk = b"X" * (_STDOUT_BUFFER_HARD_LIMIT + 1024)
    reader = _stream_with_data(big_chunk, eof=False)

    with pytest.raises(RuntimeError, match="stdout buffer overflow"):
        await asyncio.wait_for(_drive_pump(reader), timeout=10.0)
