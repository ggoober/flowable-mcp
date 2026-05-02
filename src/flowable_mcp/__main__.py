"""Entry point for stdio MCP transport.

redirect_stdout → stderr before mcp.run() so that no library code can accidentally
write to stdout and corrupt the JSON-RPC 2.0 stdio channel (DD-7, AC-Λ5).
"""

import contextlib
import sys


def main() -> None:
    from flowable_mcp.server import mcp

    with contextlib.redirect_stdout(sys.stderr):
        mcp.run()


if __name__ == "__main__":
    main()
