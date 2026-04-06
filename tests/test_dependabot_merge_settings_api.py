"""Tests for Dependabot merge settings API."""

from __future__ import annotations

import pytest

from models import DependabotMergeSettings


def test_dependabot_merge_settings_defaults():
    settings = DependabotMergeSettings()
    data = settings.model_dump()
    assert data["authors"] == ["dependabot[bot]"]
    assert data["failure_strategy"] == "skip"
    assert data["review_mode"] == "ci_only"


def test_dependabot_merge_settings_rejects_invalid_strategy():
    with pytest.raises(ValueError):
        DependabotMergeSettings(failure_strategy="nope")


def test_dependabot_merge_settings_rejects_invalid_review_mode():
    with pytest.raises(ValueError):
        DependabotMergeSettings(review_mode="nope")


def test_dependabot_merge_settings_partial_update():
    """Simulate the PATCH-like update the endpoint does."""
    current = DependabotMergeSettings()
    update = current.model_dump()
    update["failure_strategy"] = "hitl"
    new = DependabotMergeSettings(**update)
    assert new.failure_strategy == "hitl"
    assert new.authors == ["dependabot[bot]"]  # unchanged


# Caretaker settings endpoint tests covered by test_dependabot_merge_settings_api.py
