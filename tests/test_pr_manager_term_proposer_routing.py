"""Verify PRManager skips agent pipeline for hydraflow-ul-proposed PRs."""

from __future__ import annotations

from unittest.mock import MagicMock

from pr_manager import PRManager


def test_term_proposer_pr_detected_via_label() -> None:
    """A PR labelled hydraflow-ul-proposed must be detected by _is_term_proposer_pr."""
    pr_manager = MagicMock(spec=PRManager)
    pr_manager._is_term_proposer_pr = PRManager._is_term_proposer_pr.__get__(pr_manager)

    fake_pr = MagicMock()
    fake_pr.labels = ["hydraflow-ul-proposed"]
    assert pr_manager._is_term_proposer_pr(fake_pr) is True

    other_pr = MagicMock()
    other_pr.labels = ["hydraflow-ready"]
    assert pr_manager._is_term_proposer_pr(other_pr) is False


def test_term_proposer_pr_with_multiple_labels() -> None:
    """Detection should work even when other labels are also present."""
    pr_manager = MagicMock(spec=PRManager)
    pr_manager._is_term_proposer_pr = PRManager._is_term_proposer_pr.__get__(pr_manager)

    fake_pr = MagicMock()
    fake_pr.labels = ["hydraflow-ul-proposed", "documentation", "auto-generated"]
    assert pr_manager._is_term_proposer_pr(fake_pr) is True


def test_term_proposer_pr_with_none_labels() -> None:
    """Handle the case where pr.labels is None gracefully."""
    pr_manager = MagicMock(spec=PRManager)
    pr_manager._is_term_proposer_pr = PRManager._is_term_proposer_pr.__get__(pr_manager)

    fake_pr = MagicMock()
    fake_pr.labels = None
    assert pr_manager._is_term_proposer_pr(fake_pr) is False
