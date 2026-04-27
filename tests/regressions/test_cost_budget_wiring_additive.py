"""Regression: cost_budget_watcher is wired in all 8 checkpoints.

Locks the wiring so future loop additions don't accidentally remove
cost_budget_watcher from any of: registry, services, constants.js,
_INTERVAL_BOUNDS, _bg_worker_defs, defaults dict, functional area,
worker-list test.
"""

from __future__ import annotations

from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = Path(__file__).resolve().parents[2]


def test_cost_budget_watcher_in_orchestrator_registry() -> None:
    text = (SRC / "orchestrator.py").read_text()
    assert '"cost_budget_watcher": svc.cost_budget_watcher_loop' in text


def test_cost_budget_watcher_in_loop_factories() -> None:
    text = (SRC / "orchestrator.py").read_text()
    assert '("cost_budget_watcher", self._svc.cost_budget_watcher_loop.run)' in text


def test_cost_budget_watcher_in_interval_bounds() -> None:
    text = (SRC / "dashboard_routes" / "_common.py").read_text()
    assert '"cost_budget_watcher"' in text


def test_cost_budget_watcher_in_constants_js() -> None:
    text = (SRC / "ui" / "src" / "constants.js").read_text()
    # EDITABLE_INTERVAL_WORKERS, SYSTEM_WORKER_INTERVALS, BACKGROUND_WORKERS
    assert "'cost_budget_watcher'" in text or '"cost_budget_watcher"' in text
    assert text.count("cost_budget_watcher") >= 3


def test_cost_budget_watcher_in_bg_worker_defaults() -> None:
    text = (SRC / "bg_worker_manager.py").read_text()
    assert '"cost_budget_watcher": 300' in text


def test_cost_budget_watcher_in_functional_areas_yaml() -> None:
    text = (ROOT / "docs" / "arch" / "functional_areas.yml").read_text()
    assert "CostBudgetWatcherLoop" in text


def test_cost_budget_watcher_in_simplenamespace() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / "orchestrator_integration_utils.py"
    ).read_text()
    assert "services.cost_budget_watcher_loop = FakeBackgroundLoop()" in text


def test_cost_budget_watcher_in_loop_registrations_catalog() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "catalog"
        / "loop_registrations.py"
    ).read_text()
    assert '"cost_budget_watcher"' in text
    assert "_build_cost_budget_watcher_loop" in text
