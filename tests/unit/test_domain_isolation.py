from __future__ import annotations

import ast
import pathlib


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
# TC-21
# ---------------------------------------------------------------------------

def test_models_when_imported_then_no_httpx_or_fastmcp_dependency():
    models_path = pathlib.Path("src/flowable_mcp/models.py")
    source = models_path.read_text(encoding="utf-8")
    imports = _collect_imports(source)

    assert not any("httpx" in imp for imp in imports), (
        f"models.py must not import httpx; found: {[i for i in imports if 'httpx' in i]}"
    )
    assert not any("fastmcp" in imp for imp in imports), (
        f"models.py must not import fastmcp; found: {[i for i in imports if 'fastmcp' in i]}"
    )


# ---------------------------------------------------------------------------
# TC-22
# ---------------------------------------------------------------------------

def test_errors_when_imported_then_no_httpx_or_fastmcp_dependency():
    errors_path = pathlib.Path("src/flowable_mcp/errors.py")
    source = errors_path.read_text(encoding="utf-8")
    imports = _collect_imports(source)

    assert not any("httpx" in imp for imp in imports), (
        f"errors.py must not import httpx; found: {[i for i in imports if 'httpx' in i]}"
    )
    assert not any("fastmcp" in imp for imp in imports), (
        f"errors.py must not import fastmcp; found: {[i for i in imports if 'fastmcp' in i]}"
    )
