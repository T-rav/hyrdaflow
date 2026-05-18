"""Regression test: StateData must silently ignore unknown fields on load.

Rationale: state.json is written by one version of HydraFlow and read by
another. Older state files may contain fields that have since been removed,
and newer state files may contain fields not yet known to an older build
running from a checkpoint. The ``extra='ignore'`` config on StateData is the
load-bearing guard. If it is ever changed to ``extra='forbid'``, every
restart from a state file containing an unknown field would raise a
``ValidationError`` and crash the pipeline.

This test loads a state dict containing an unknown field and asserts that
StateData parses it without raising an exception.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import StateData  # noqa: E402


class TestStateDataExtraFields:
    """StateData must not raise on extra fields in the persisted dict."""

    def test_unknown_top_level_field_is_ignored(self) -> None:
        """A field that does not exist on StateData must be silently dropped."""
        payload = {
            "schema_version": 1,
            "unknown_field_from_the_future": "some_value",
        }
        # Must not raise ValidationError or any other exception.
        data = StateData.model_validate(payload)
        assert data.schema_version == 1
        assert not hasattr(data, "unknown_field_from_the_future")

    def test_multiple_unknown_fields_are_all_ignored(self) -> None:
        """Multiple unknown fields are all silently dropped."""
        payload = {
            "schema_version": 1,
            "ghost_field_alpha": 42,
            "ghost_field_beta": {"nested": True},
            "ghost_field_gamma": [1, 2, 3],
        }
        data = StateData.model_validate(payload)
        assert data.schema_version == 1

    def test_extra_ignore_is_explicitly_configured(self) -> None:
        """model_config must declare extra='ignore' — not rely on Pydantic default.

        This test guards against a silent regression where someone sets
        extra='forbid' or removes the explicit declaration, relying on the
        Pydantic v2 default (which *happens* to be 'ignore' today but is not
        guaranteed to stay that way and may be overridden by a base class).
        """
        config = StateData.model_config
        assert config.get("extra") == "ignore", (
            "StateData.model_config must set extra='ignore' explicitly. "
            "Without it, a future Pydantic upgrade or base-class change could "
            "flip the behaviour and break restarts from older state files."
        )

    def test_round_trip_with_extra_field_in_json(self) -> None:
        """model_validate_json must also tolerate unknown fields in JSON."""
        json_str = (
            '{"schema_version": 1, "retired_old_field": "whatever", '
            '"another_removed_field": 99}'
        )
        data = StateData.model_validate_json(json_str)
        assert data.schema_version == 1
