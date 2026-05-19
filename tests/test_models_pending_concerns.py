from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from src.pending_concerns import (
    AdversarialState,
    Concern,
    ConcernResolution,
    StageRun,
)


def test_concern_minimal_fields_validate():
    c = Concern(
        id="PLAN-COUNCIL-001",
        raised_in_phase="plan",
        raised_in_stage="plan_council",
        severity="HIGH",
        concern="No test for empty input path",
        raised_at=datetime.now(UTC),
        must_address_by="planner",
    )
    assert c.human_required is False


def test_concern_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        Concern(
            id="X",
            raised_in_phase="plan",
            raised_in_stage="x",
            severity="MAYBE",  # invalid
            concern="...",
            raised_at=datetime.now(UTC),
            must_address_by="next",
        )


def test_concern_resolution_kind_categorical():
    valid = {"trivial", "deferred", "addressed-in-code", "addressed-in-test", "ignored"}
    for kind in valid:
        ConcernResolution(
            concern_id="X-001",
            addressed_in_stage="planner",
            resolution="ok",
            addressed_at=datetime.now(UTC),
            resolution_kind=kind,
        )
    with pytest.raises(ValidationError):
        ConcernResolution(
            concern_id="X-001",
            addressed_in_stage="planner",
            resolution="ok",
            addressed_at=datetime.now(UTC),
            resolution_kind="something_else",
        )


def test_adversarial_state_defaults_empty():
    state = AdversarialState(phase="plan", current_stage=None)
    assert state.pending_concerns == []
    assert state.addressed_concerns == []
    assert state.stage_history == []


def test_stage_run_records_oscillation_flag():
    run = StageRun(
        stage="plan_council",
        phase="plan",
        retries=3,
        converged=False,
        concerns_raised=4,
        concerns_forwarded=2,
        oscillation_detected=True,
        duration_ms=12_345,
    )
    assert run.oscillation_detected is True
    assert run.concerns_forwarded == 2


def test_legacy_state_json_without_adversarial_field_loads_cleanly():
    """Schema evolution: old issues without adversarial_state must still load."""
    from src.pending_concerns import AdversarialState

    AdversarialState(phase="discover")
