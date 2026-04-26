"""scripts/scaffold_loop.py golden-file tests.

Runs the scaffold templates against a fixture name and asserts the
rendered output matches anchored invariants. Catches accidental template
changes (e.g., variable rename, formatter pass) that would otherwise
silently affect all future scaffolded loops.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable.
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))


@pytest.fixture()
def fixture_names() -> dict[str, str]:
    """Names dict for the canonical 'fixture_loop' golden test."""
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    return scaffold_loop._names("fixture_loop")


def test_loop_template_renders_expected(fixture_names: dict[str, str]) -> None:
    """The loop template must include the ADR-0049 in-body kill-switch +
    static config gate + ground-truth class name."""
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    rendered = scaffold_loop._render_templates(fixture_names, "Fixture description.")

    loop_path = next(p for p in rendered if p.name == "fixture_loop_loop.py")
    content = rendered[loop_path]

    # Anchored assertions on stable invariants of the template:
    assert "class FixtureLoopLoop(BaseBackgroundLoop):" in content
    assert "if not self._enabled_cb(self._worker_name):" in content
    assert 'return {"status": "disabled"}' in content
    assert "self._config.fixture_loop_enabled" in content
    assert "self._config.fixture_loop_interval" in content
    assert 'worker_name="fixture_loop"' in content


def test_state_template_renders_expected(fixture_names: dict[str, str]) -> None:
    """The state-mixin template must include the ground-truth class name."""
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    rendered = scaffold_loop._render_templates(fixture_names, "Fixture description.")

    state_path = next(p for p in rendered if p.name == "_fixture_loop.py")
    content = rendered[state_path]

    assert "class FixtureLoopStateMixin:" in content


def test_test_template_renders_expected(fixture_names: dict[str, str]) -> None:
    """The test template must include the four conventional tests
    (worker_name, default_interval, kill_switch, static_config_disable)."""
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    rendered = scaffold_loop._render_templates(fixture_names, "Fixture description.")

    test_path = next(p for p in rendered if p.name == "test_fixture_loop_loop.py")
    content = rendered[test_path]

    assert "def test_worker_name(" in content
    assert "def test_default_interval_from_config(" in content
    assert "async def test_kill_switch_short_circuits(" in content
    assert "async def test_static_config_disable_short_circuits(" in content
    assert "from fixture_loop_loop import FixtureLoopLoop" in content
    assert "HYDRAFLOW_FIXTURE_LOOP_ENABLED" in content


def test_names_helper_produces_expected_variants() -> None:
    """`_names()` is the source of truth for the case variants templates use."""
    from importlib import import_module

    scaffold_loop = import_module("scaffold_loop")
    names = scaffold_loop._names("blarg_monitor")

    assert names["snake"] == "blarg_monitor"
    assert names["pascal"] == "BlargMonitor"
    assert names["name_title"] == "Blarg Monitor"
    assert names["upper"] == "BLARG_MONITOR"
    # `today` is dynamic — just check it's set.
    assert names["today"]
