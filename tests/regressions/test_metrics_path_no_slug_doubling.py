"""Regression test for slice #5.6 (PR #8801) — metrics path slug-doubling.

Bug: ``get_metrics_cache_dir()`` produced ``<data_root>/<repo_slug>/metrics/<repo_slug>``
because it appended ``metrics / repo_slug`` to ``state_file.parent`` (which is already
the repo-scoped directory ``<data_root>/<repo_slug>/``).

Expected behaviour after fix:
  - ``get_metrics_cache_dir(config)`` returns a path where the repo slug appears
    exactly once.
  - The path ends with ``<repo_slug>/metrics``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import HydraFlowConfig  # noqa: E402
from metrics_manager import get_metrics_cache_dir  # noqa: E402


@pytest.mark.parametrize(
    "repo",
    [
        "owner/repo",
        "org-name/my-repo",
        "T-rav/hydraflow",
    ],
)
def test_repo_slug_appears_exactly_once_in_metrics_path(
    tmp_path: Path, repo: str
) -> None:
    """``get_metrics_cache_dir`` must not double the repo slug in the path.

    Before the fix, the function produced:
        ``<data_root>/<repo_slug>/metrics/<repo_slug>``

    After the fix, it produces:
        ``<data_root>/<repo_slug>/metrics``
    """
    config = HydraFlowConfig(data_root=tmp_path, repo=repo)
    result = get_metrics_cache_dir(config)

    repo_slug = repo.replace("/", "-")
    result_str = str(result)

    occurrences = result_str.count(repo_slug)
    assert occurrences == 1, (
        f"Expected repo slug '{repo_slug}' to appear exactly once in metrics path, "
        f"got {occurrences} occurrences: {result_str!r}"
    )


def test_metrics_path_ends_with_slug_metrics(tmp_path: Path) -> None:
    """Metrics cache dir must end with ``<repo_slug>/metrics``."""
    repo = "owner/repo"
    config = HydraFlowConfig(data_root=tmp_path, repo=repo)
    result = get_metrics_cache_dir(config)

    repo_slug = repo.replace("/", "-")
    expected = tmp_path / repo_slug / "metrics"
    assert result == expected, f"Expected {expected!r}, got {result!r}"
