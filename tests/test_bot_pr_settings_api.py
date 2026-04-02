"""Tests for bot PR settings API."""

from __future__ import annotations

import pytest

from models import BotPRSettings


def test_bot_pr_settings_defaults():
    settings = BotPRSettings()
    data = settings.model_dump()
    assert data["authors"] == ["dependabot[bot]"]
    assert data["failure_strategy"] == "skip"
    assert data["review_mode"] == "ci_only"


def test_bot_pr_settings_rejects_invalid_strategy():
    with pytest.raises(ValueError):
        BotPRSettings(failure_strategy="nope")


def test_bot_pr_settings_rejects_invalid_review_mode():
    with pytest.raises(ValueError):
        BotPRSettings(review_mode="nope")


def test_bot_pr_settings_partial_update():
    """Simulate the PATCH-like update the endpoint does."""
    current = BotPRSettings()
    update = current.model_dump()
    update["failure_strategy"] = "hitl"
    new = BotPRSettings(**update)
    assert new.failure_strategy == "hitl"
    assert new.authors == ["dependabot[bot]"]  # unchanged


# Caretaker settings endpoint tests covered by test_bot_pr_settings_api.py
