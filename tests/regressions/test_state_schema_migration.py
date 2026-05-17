"""Regression: legacy ``state.json`` without ``adversarial_states`` loads cleanly.

The earlier-adversarial pipeline added a new ``adversarial_states: dict``
field to :class:`StateData` (see ``src/models.py``). A field-level default
of ``Field(default_factory=dict)`` keeps existing on-disk state files
parseable — Pydantic fills the default rather than raising. Locking that
behaviour with a regression test so a future refactor (e.g. dropping the
default, switching to a non-optional field) trips CI.

This is a load-bearing schema-evolution contract for the dark-factory
shipping model: legacy state files on long-running operators must roll
forward to the current schema without manual migration.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from models import StateData


def test_legacy_state_without_adversarial_states_loads_empty_dict() -> None:
    legacy_payload = {
        "schema_version": 1,
        "processed_issues": {"1": "ok"},
        "active_workspaces": {},
        "active_branches": {},
        "reviewed_prs": {},
        "hitl_origins": {},
        "hitl_causes": {},
        "hitl_summaries": {},
        "hitl_summary_failures": {},
        "hitl_visual_evidence": {},
        "review_attempts": {},
        "review_feedback": {},
        # No ``adversarial_states`` key — simulating a pre-feature state.json
    }

    data = StateData.model_validate(legacy_payload)

    assert hasattr(data, "adversarial_states")
    assert data.adversarial_states == {}


def test_legacy_state_minimal_payload_loads() -> None:
    """An empty payload should also fill ``adversarial_states`` from default."""
    data = StateData.model_validate({})
    assert data.adversarial_states == {}


def test_round_trip_preserves_adversarial_states() -> None:
    """Round-tripping through ``model_dump`` keeps an empty dict empty."""
    data = StateData()
    payload = data.model_dump()
    assert payload["adversarial_states"] == {}

    reloaded = StateData.model_validate(payload)
    assert reloaded.adversarial_states == {}
