from __future__ import annotations

import sys
from unittest.mock import patch


# ---------------------------------------------------------------------------
# TC-61
# ---------------------------------------------------------------------------

def test_main_when_called_then_stdout_redirected_to_stderr_during_run():
    from flowable_mcp.__main__ import main

    captured_stdout_in_run: list[object] = []

    def fake_run():
        captured_stdout_in_run.append(sys.stdout)

    with patch("flowable_mcp.server.mcp.run", fake_run):
        main()

    assert len(captured_stdout_in_run) == 1
    assert captured_stdout_in_run[0] is sys.stderr
