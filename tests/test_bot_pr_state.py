"""Tests for bot PR state persistence."""

from __future__ import annotations

import pytest

from config import HydraFlowConfig
from models import BotPRSettings
from state import StateTracker


def test_bot_pr_settings_defaults():
    settings = BotPRSettings()
    assert settings.authors == ["dependabot[bot]"]
    assert settings.failure_strategy == "skip"
    assert settings.review_mode == "ci_only"


def test_bot_pr_settings_custom():
    settings = BotPRSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    assert "renovate[bot]" in settings.authors
    assert settings.failure_strategy == "hitl"


def test_bot_pr_settings_validates_strategy():
    with pytest.raises(ValueError):
        BotPRSettings(failure_strategy="invalid")


def test_bot_pr_settings_validates_review_mode():
    with pytest.raises(ValueError):
        BotPRSettings(review_mode="invalid")


def test_state_tracker_bot_pr_settings_roundtrip(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    settings = state.get_bot_pr_settings()
    assert settings.authors == ["dependabot[bot]"]

    new_settings = BotPRSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    state.set_bot_pr_settings(new_settings)

    loaded = state.get_bot_pr_settings()
    assert loaded.authors == ["dependabot[bot]", "renovate[bot]"]
    assert loaded.failure_strategy == "hitl"


def test_state_tracker_bot_pr_processed(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path))
    state = StateTracker(config.state_file)

    assert state.get_bot_pr_processed() == set()
    state.add_bot_pr_processed(42)
    state.add_bot_pr_processed(101)
    assert state.get_bot_pr_processed() == {42, 101}
