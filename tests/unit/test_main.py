from __future__ import annotations

import sys
from unittest.mock import patch


# ---------------------------------------------------------------------------
# TC-61 — main() invokes mcp.run with banner suppressed and leaves sys.stdout
# attached to the real stdout so JSON-RPC frames reach fd 1 (СТ-3, AC-Λ5).
# ---------------------------------------------------------------------------


def test_main_when_called_then_runs_with_banner_suppressed_and_stdout_untouched():
    from flowable_mcp.__main__ import main

    captured: dict[str, object] = {}

    def fake_run(*, show_banner: bool | None = None, **_: object) -> None:
        captured["show_banner"] = show_banner
        captured["stdout"] = sys.stdout

    with patch("flowable_mcp.server.mcp.run", fake_run):
        main()

    assert captured["show_banner"] is False, (
        "main() must suppress the FastMCP banner — it would otherwise corrupt "
        "the first JSON-RPC frame (СТ-3, AC-Λ5)"
    )
    assert captured["stdout"] is not sys.stderr, (
        "sys.stdout must NOT be redirected to stderr during mcp.run() — "
        "FastMCP writes JSON-RPC frames to sys.stdout"
    )
