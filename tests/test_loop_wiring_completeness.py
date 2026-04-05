"""Factory validation: every BaseBackgroundLoop subclass is properly wired.

Auto-discovers loop classes from ``src/*_loop.py``
and verifies they appear in:

1. ``orchestrator.py`` ``bg_loop_registry`` dict
2. ``service_registry.py`` ``ServiceRegistry`` dataclass
3. ``ui/src/constants.js`` ``BACKGROUND_WORKERS`` array
4. ``dashboard_routes/_common.py`` ``_INTERVAL_BOUNDS`` dict

Uses regex-based discovery -- no hardcoded loop lists.

Ref: gh-5905
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"

# ---------------------------------------------------------------------------
# Loops that intentionally lack _INTERVAL_BOUNDS entries.
# These are either non-caretaker pipeline workers, or workers whose intervals
# are managed through a different mechanism (e.g. not dashboard-editable).
# ---------------------------------------------------------------------------
_INTERVAL_BOUNDS_SKIP: set[str] = {
    "github_cache",
}

# Loops that intentionally aren't in the orchestrator bg_loop_registry
# (e.g. GitHubCacheLoop is started separately).
_ORCHESTRATOR_SKIP: set[str] = {
    "github_cache",
}

# Loops that intentionally aren't in BACKGROUND_WORKERS in constants.js
# (e.g. internal loops not shown in the dashboard).
_CONSTANTS_JS_SKIP: set[str] = {
    "github_cache",
    "epic_monitor",
    "runs_gc",
}


def _discover_loops() -> dict[str, str]:
    """Return {worker_name: class_name} for all BaseBackgroundLoop subclasses.

    Scans ``src/*_loop.py`` for classes extending ``BaseBackgroundLoop``,
    then extracts the ``worker_name=`` string from the ``super().__init__()`` call.
    """
    loop_files = sorted(SRC.glob("*_loop.py"))

    result: dict[str, str] = {}
    class_re = re.compile(r"class\s+(\w+)\s*\(.*BaseBackgroundLoop.*\)")
    worker_re = re.compile(r'worker_name\s*=\s*["\'](\w+)["\']')

    for path in loop_files:
        text = path.read_text()
        class_match = class_re.search(text)
        worker_match = worker_re.search(text)
        if class_match and worker_match:
            result[worker_match.group(1)] = class_match.group(1)

    return result


def _parse_bg_loop_registry() -> set[str]:
    """Extract worker_name keys from orchestrator.py's bg_loop_registry dict."""
    text = (SRC / "orchestrator.py").read_text()
    # Match lines like:  "memory_sync": svc.memory_sync_bg,
    return set(re.findall(r'"(\w+)"\s*:\s*svc\.', text))


def _parse_service_registry_fields() -> set[str]:
    """Extract dataclass field type names from ServiceRegistry."""
    text = (SRC / "service_registry.py").read_text()
    # Capture type annotations in the dataclass section
    # e.g.  memory_sync_bg: MemorySyncLoop
    return set(re.findall(r":\s*(\w+Loop)\b", text))


def _parse_constants_js_workers() -> set[str]:
    """Extract worker keys from BACKGROUND_WORKERS in constants.js."""
    path = SRC / "ui" / "src" / "constants.js"
    text = path.read_text()
    # Match:  { key: 'memory_sync', ...
    return set(re.findall(r"key:\s*'(\w+)'", text))


def _parse_interval_bounds() -> set[str]:
    """Extract worker keys from _INTERVAL_BOUNDS in _common.py."""
    path = SRC / "dashboard_routes" / "_common.py"
    text = path.read_text()
    # Match:  "memory_sync": (10, 14400),
    return set(re.findall(r'"(\w+)"\s*:\s*\(', text))


# ---------------------------------------------------------------------------
# Discovery fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def loops() -> dict[str, str]:
    """All discovered {worker_name: class_name} pairs."""
    found = _discover_loops()
    assert found, "No BaseBackgroundLoop subclasses discovered -- is src/ accessible?"
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrchestratorRegistry:
    """Each loop's worker_name must appear in orchestrator.py bg_loop_registry."""

    def test_all_loops_in_registry(self, loops: dict[str, str]) -> None:
        registry_keys = _parse_bg_loop_registry()
        missing = {
            name
            for name in loops
            if name not in registry_keys and name not in _ORCHESTRATOR_SKIP
        }
        assert not missing, (
            f"Loops missing from orchestrator bg_loop_registry: {sorted(missing)}"
        )


class TestServiceRegistryFields:
    """Each loop class must be declared as a field in ServiceRegistry."""

    def test_all_loops_in_service_registry(self, loops: dict[str, str]) -> None:
        field_types = _parse_service_registry_fields()
        missing = {
            cls_name for cls_name in loops.values() if cls_name not in field_types
        }
        assert not missing, (
            f"Loop classes missing from ServiceRegistry dataclass: {sorted(missing)}"
        )


class TestConstantsJsWorkers:
    """Each worker_name must appear in BACKGROUND_WORKERS in constants.js."""

    def test_all_loops_in_constants_js(self, loops: dict[str, str]) -> None:
        js_keys = _parse_constants_js_workers()
        missing = {
            name
            for name in loops
            if name not in js_keys and name not in _CONSTANTS_JS_SKIP
        }
        assert not missing, (
            f"Loops missing from BACKGROUND_WORKERS in constants.js: {sorted(missing)}"
        )


class TestIntervalBounds:
    """Each loop's worker_name must appear in _INTERVAL_BOUNDS (with skip list)."""

    def test_all_loops_in_interval_bounds(self, loops: dict[str, str]) -> None:
        bounds_keys = _parse_interval_bounds()
        missing = {
            name
            for name in loops
            if name not in bounds_keys and name not in _INTERVAL_BOUNDS_SKIP
        }
        assert not missing, (
            f"Loops missing from _INTERVAL_BOUNDS (and not in skip list): {sorted(missing)}"
        )

    def test_skip_list_entries_are_real_loops(self, loops: dict[str, str]) -> None:
        """Ensure skip-list entries refer to actual discovered loops."""
        stale = _INTERVAL_BOUNDS_SKIP - set(loops.keys())
        assert not stale, (
            f"_INTERVAL_BOUNDS_SKIP contains entries that are not real loops: {sorted(stale)}"
        )
