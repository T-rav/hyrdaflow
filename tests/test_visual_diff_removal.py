"""Regression tests ensuring legacy dead modules stay removed."""

from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


def test_visual_diff_source_file_is_removed() -> None:
    """Guard against re-introduction of src/visual_diff.py."""
    assert not (_REPO_ROOT / "src" / "visual_diff.py").exists(), (
        "visual_diff.py was re-introduced; delete src/visual_diff.py (superseded by visual_validator.py)."
    )


def test_visual_diff_test_file_is_removed() -> None:
    """Guard against re-introduction of tests/test_visual_diff.py."""
    assert not (_REPO_ROOT / "tests" / "test_visual_diff.py").exists(), (
        "test_visual_diff.py was re-introduced; delete tests/test_visual_diff.py."
    )


def test_scheduler_source_file_is_removed() -> None:
    """Guard against re-introduction of src/scheduler.py."""
    assert not (_REPO_ROOT / "src" / "scheduler.py").exists(), (
        "scheduler.py was re-introduced; delete src/scheduler.py (multi-repo scheduler never integrated)."
    )


def test_pre_issue_tracker_source_file_is_removed() -> None:
    """Guard against re-introduction of src/pre_issue_tracker.py."""
    assert not (_REPO_ROOT / "src" / "pre_issue_tracker.py").exists(), (
        "pre_issue_tracker.py was re-introduced; delete src/pre_issue_tracker.py (local prep issue tracker never integrated)."
    )
