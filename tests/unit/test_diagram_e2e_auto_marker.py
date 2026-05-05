"""Unit-smoke for the diagram_e2e auto-marker hook (TASK-006 §12 mandatory #1).

Verifies that ``conftest.pytest_collection_modifyitems`` derives the
``diagram_e2e`` marker from filename pattern alone — never from a hand-written
``@pytest.mark.diagram_e2e`` decorator. This guards against silent regression
where a forgotten marker would route a diagram test through the in-process
``Client(mcp)`` path and reproduce the TASK-006 hang.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

import pytest

# Reuse the exact pattern compiled in conftest so the test breaks if it drifts.
from tests.e2e.conftest import _DIAGRAM_FILE_PATTERN, pytest_collection_modifyitems


pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    ("filename", "should_match"),
    [
        # Positive cases — must be marked.
        ("test_e2e_diagram_task005.py", True),
        ("test_e2e_diagram_xyz_123.py", True),
        ("test_a_diagram.py", True),  # minimum-shape: test_<x>_diagram<y>.py
        # Negative cases — must NOT be marked.
        ("test_diagram_basic.py", False),  # missing the ``_<category>_`` segment
        ("test_e2e.py", False),
        ("test_e2e_admin.py", False),
        ("test_diagrams_index.py", False),  # plural — not a diagram suite
        ("conftest.py", False),
        ("diagram_test.py", False),  # missing leading test_
        ("test_e2e_DIAGRAM_xyz.py", False),  # case-sensitive (fnmatchcase)
    ],
)
def test_diagram_filename_pattern_matches_expected(filename: str, should_match: bool) -> None:
    assert fnmatch.fnmatchcase(filename, _DIAGRAM_FILE_PATTERN) is should_match, (
        f"{filename!r} vs {_DIAGRAM_FILE_PATTERN!r} → expected match={should_match}"
    )


class _StubItem:
    """Minimal pytest-Item-like object for unit-testing the hook."""

    def __init__(self, fspath: Path) -> None:
        self.fspath = str(fspath)
        self.added_markers: list[str] = []

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        # MarkDecorator has a ``.mark.name`` attribute.
        self.added_markers.append(marker.mark.name)


def test_hook_marks_only_diagram_files_under_e2e_root(tmp_path: Path) -> None:
    """End-to-end smoke: hook reads item.fspath and adds marker only to matches."""
    e2e_root = Path(__file__).parent.parent / "e2e"

    items = [
        _StubItem(e2e_root / "test_e2e_diagram_task005.py"),
        _StubItem(e2e_root / "test_e2e_admin.py"),
        # File outside tests/e2e/ — hook must skip even if name matches.
        _StubItem(tmp_path / "test_e2e_diagram_outside.py"),
    ]

    pytest_collection_modifyitems(config=None, items=items)  # type: ignore[arg-type]

    assert items[0].added_markers == ["diagram_e2e"], (
        f"diagram file under e2e/ should be marked: {items[0].added_markers}"
    )
    assert items[1].added_markers == [], (
        f"non-diagram file should NOT be marked: {items[1].added_markers}"
    )
    assert items[2].added_markers == [], (
        "diagram-named file outside tests/e2e/ must not be marked "
        f"(prevents unit-dir collision): {items[2].added_markers}"
    )
