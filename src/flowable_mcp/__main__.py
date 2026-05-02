"""Entry point for stdio MCP transport.

The MCP stdio protocol requires stdout to carry ONLY JSON-RPC 2.0 frames
(СТ-3, AC-Λ5). Two guards keep that invariant:

1. ``setup_logging`` (in ``server.py``) routes log handlers to ``sys.stderr``
   only and asserts at startup that no handler points at ``sys.stdout``.
2. The FastMCP startup banner is suppressed via ``show_banner=False`` —
   FastMCP writes that banner to stdout and would otherwise corrupt the
   first frame.

A previous version unconditionally redirected ``sys.stdout`` to ``sys.stderr``
to defend against stray ``print`` calls; that defeats the protocol entirely
because FastMCP's stdio transport writes JSON-RPC frames to ``sys.stdout``.
"""

from __future__ import annotations


def main() -> None:
    from flowable_mcp.server import mcp

    mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
