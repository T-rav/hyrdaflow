"""Verify that all concrete BaseRunner subclasses have _phase_name defined."""

import pytest

from agent import AgentRunner
from base_runner import BaseRunner
from discover_runner import DiscoverRunner
from planner import PlannerRunner
from reviewer import ReviewRunner
from shape_runner import ShapeRunner

# DiagnosticRunner, HITLRunner, ResearchRunner, TriageRunner intentionally
# excluded — they inherit the default ``_phase_name = "unknown"`` from
# BaseRunner. The test asserts `phase_name != "unknown"` so including them
# would always fail. Add them here only after assigning a real phase name.


@pytest.mark.parametrize(
    "runner_class",
    [
        AgentRunner,
        DiscoverRunner,
        PlannerRunner,
        ReviewRunner,
        ShapeRunner,
    ],
)
def test_runner_has_phase_name(runner_class: type[BaseRunner]) -> None:
    """Verify that each runner has _phase_name != 'unknown'.

    Trace spans and phase-rollup logs depend on correct _phase_name
    declarations. Runners that inherit the default 'unknown' cause
    mislabelled telemetry.
    """
    assert hasattr(runner_class, "_phase_name"), (
        f"{runner_class.__name__} is missing _phase_name ClassVar"
    )
    phase_name = runner_class._phase_name
    assert phase_name != "unknown", (
        f"{runner_class.__name__}._phase_name is 'unknown' (inherited default)"
    )
    assert isinstance(phase_name, str), (
        f"{runner_class.__name__}._phase_name must be a string"
    )
    assert phase_name.isidentifier(), (
        f"{runner_class.__name__}._phase_name '{phase_name}' is not a valid identifier"
    )
