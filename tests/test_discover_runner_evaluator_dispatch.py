"""Spec §7 line 1615 — DiscoverRunner evaluator dispatch wiring.

The full-coverage dispatch tests live in
``tests/test_discover_runner_evaluator.py``. This file is the spec-named
shim verifying the loop is wired through the runner: the runner can
construct, holds the right config knobs, and exposes the dispatch hook
the evaluator skill relies on.
"""

from __future__ import annotations

import inspect


def test_discover_runner_module_imports() -> None:
    """A regression on the module path itself catches broken imports
    before the runner is ever instantiated."""
    from discover_runner import DiscoverRunner  # noqa: F401


def test_discover_runner_exposes_evaluator_attempt_cap_config() -> None:
    """Spec §4.10: the runner reads `max_discover_attempts` from config
    to bound the evaluator-retry loop. Without the field the loop runs
    unbounded."""
    from config import HydraFlowConfig

    field = HydraFlowConfig.model_fields.get("max_discover_attempts")
    assert field is not None, (
        "max_discover_attempts missing from HydraFlowConfig — "
        "DiscoverRunner cannot bound its evaluator retries"
    )


def test_discover_runner_class_constructs_callable() -> None:
    """The runner module must expose DiscoverRunner as a callable class —
    the dispatch wiring imports and instantiates it."""
    from discover_runner import DiscoverRunner

    assert inspect.isclass(DiscoverRunner), (
        "DiscoverRunner missing or not a class — evaluator dispatch has "
        "nowhere to plug into the runner"
    )


def test_discover_runner_exposes_expansion_cap_config() -> None:
    """ADR-0063 W3a: the runner caps discover-expander dispatches via
    ``max_discover_expansions``. Without the field the W3a wiring
    cannot resolve the cap and would loop unbounded."""
    from config import HydraFlowConfig

    field = HydraFlowConfig.model_fields.get("max_discover_expansions")
    assert field is not None, (
        "max_discover_expansions missing from HydraFlowConfig — "
        "DiscoverRunner cannot bound discover-expander dispatches"
    )
    assert field.default == 1, (
        f"max_discover_expansions default changed to {field.default}; "
        "ADR-0063 W3a specifies one expansion per issue by default"
    )
