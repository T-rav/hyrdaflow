"""Tests for Dependabot merge state persistence."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from models import DependabotMergeSettings
from state import StateTracker


def test_dependabot_merge_settings_defaults():
    settings = DependabotMergeSettings()
    assert settings.authors == ["dependabot[bot]", "hydraflow-ul-bot"]
    assert settings.failure_strategy == "skip"
    assert settings.review_mode == "ci_only"


def test_dependabot_merge_settings_custom():
    settings = DependabotMergeSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    assert "renovate[bot]" in settings.authors
    assert settings.failure_strategy == "hitl"


def test_dependabot_merge_settings_validates_strategy():
    with pytest.raises(ValueError):
        DependabotMergeSettings(failure_strategy="invalid")


def test_dependabot_merge_settings_validates_review_mode():
    with pytest.raises(ValueError):
        DependabotMergeSettings(review_mode="invalid")


def test_state_tracker_dependabot_merge_settings_roundtrip(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    settings = state.get_dependabot_merge_settings()
    assert settings.authors == ["dependabot[bot]", "hydraflow-ul-bot"]

    new_settings = DependabotMergeSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    state.set_dependabot_merge_settings(new_settings)

    loaded = state.get_dependabot_merge_settings()
    assert loaded.authors == ["dependabot[bot]", "renovate[bot]"]
    assert loaded.failure_strategy == "hitl"


def test_state_tracker_dependabot_merge_processed(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    assert state.get_dependabot_merge_processed() == set()
    state.add_dependabot_merge_processed(42)
    state.add_dependabot_merge_processed(101)
    assert state.get_dependabot_merge_processed() == {42, 101}
