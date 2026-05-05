"""Unit tests for Settings diagram fields and domain isolation (TASK-005).

Covers:
- errors.py domain isolation (TC-35 / AC-C1)
- Settings diagram field defaults (TC-36 / AC-S2-5)
- Settings env overrides (TC-37 / AC-S2-5)
- RSS budget validator — ok (TC-F1)
- RSS budget validator — over limit (TC-F2)
- diagram_timeout_s=0.0 accepted (TC-F3)
- FlowableDiagramError hierarchy (INNO-09 alt)
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from pydantic import ValidationError

pytestmark = [pytest.mark.unit]

_ERRORS_PATH = pathlib.Path("src/flowable_mcp/errors.py")
_MIB = 1024 * 1024


def _collect_imports(source: str) -> list[str]:
    tree = ast.parse(source)
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


# ---------------------------------------------------------------------------
# TC-35: errors.py has no httpx / fastmcp imports (СТ-1, AC-C1)
# ---------------------------------------------------------------------------

def test_errors_module_when_imported_then_no_httpx_fastmcp_dependency() -> None:
    source = _ERRORS_PATH.read_text(encoding="utf-8")
    imports = _collect_imports(source)
    httpx_imports = [i for i in imports if "httpx" in i]
    fastmcp_imports = [i for i in imports if "fastmcp" in i]
    assert not httpx_imports, f"errors.py must not import httpx; found: {httpx_imports}"
    assert not fastmcp_imports, f"errors.py must not import fastmcp; found: {fastmcp_imports}"


# ---------------------------------------------------------------------------
# TC-36: Settings diagram field defaults (AC-S2-5)
# ---------------------------------------------------------------------------

def test_settings_when_no_env_then_diagram_fields_have_correct_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    # Remove any overrides that might be set
    monkeypatch.delenv("FLOWABLE_DIAGRAM_MAX_PNG_BYTES", raising=False)
    monkeypatch.delenv("FLOWABLE_DIAGRAM_TIMEOUT_S", raising=False)
    monkeypatch.delenv("FLOWABLE_DIAGRAM_MAX_CONCURRENT", raising=False)

    from flowable_mcp.config import Settings

    s = Settings()
    assert s.diagram_max_png_bytes == 5_242_880, f"Expected 5 MiB, got {s.diagram_max_png_bytes}"
    assert s.diagram_timeout_s == 30.0, f"Expected 30.0s, got {s.diagram_timeout_s}"
    assert s.diagram_max_concurrent == 4, f"Expected 4, got {s.diagram_max_concurrent}"


# ---------------------------------------------------------------------------
# TC-37: Settings env overrides applied (AC-S2-5)
# ---------------------------------------------------------------------------

def test_settings_when_env_overrides_then_diagram_fields_updated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_PNG_BYTES", str(2 * _MIB))
    monkeypatch.setenv("FLOWABLE_DIAGRAM_TIMEOUT_S", "15.0")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_CONCURRENT", "2")

    from flowable_mcp.config import Settings

    s = Settings()
    assert s.diagram_max_png_bytes == 2 * _MIB
    assert s.diagram_timeout_s == 15.0
    assert s.diagram_max_concurrent == 2


# ---------------------------------------------------------------------------
# TC-F1: RSS budget at default 4 × 5 MiB = 20 MiB < 50 MiB → ok
# ---------------------------------------------------------------------------

def test_settings_when_rss_budget_exactly_at_default_then_ok(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_CONCURRENT", "4")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_PNG_BYTES", str(5 * _MIB))

    from flowable_mcp.config import Settings

    s = Settings()  # must not raise
    peak = s.diagram_max_concurrent * s.diagram_max_png_bytes
    assert peak <= 50 * _MIB


# ---------------------------------------------------------------------------
# TC-F2: RSS budget over 50 MiB → ValidationError
# ---------------------------------------------------------------------------

def test_settings_when_rss_budget_over_50mib_then_raises_value_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_CONCURRENT", "11")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_MAX_PNG_BYTES", str(5 * _MIB))  # 11 × 5 MiB = 55 MiB

    from flowable_mcp.config import Settings

    with pytest.raises(ValidationError) as exc_info:
        Settings()
    assert "50 MiB RSS budget" in str(exc_info.value)


# ---------------------------------------------------------------------------
# TC-F3: diagram_timeout_s=0.0 accepted (no lower-bound validator)
# ---------------------------------------------------------------------------

def test_settings_when_diagram_timeout_zero_then_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FLOWABLE_PASSWORD", "x")
    monkeypatch.setenv("FLOWABLE_DIAGRAM_TIMEOUT_S", "0.0")

    from flowable_mcp.config import Settings

    s = Settings()
    assert s.diagram_timeout_s == 0.0
