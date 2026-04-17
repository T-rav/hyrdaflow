"""Regression test for issue #6534.

Bug: ``GitHubDataCache.poll()`` wraps each dataset fetch in a broad
``except Exception`` that logs a warning and continues.  This means
``AuthenticationError`` — a permanent token failure — is silently
swallowed, and consumers continue reading stale cached data indefinitely.

Expected behaviour after fix:
  - ``AuthenticationError`` propagates out of ``poll()`` so the caller
    (``GitHubCacheLoop._do_work``) can halt and alert.

These tests assert the *correct* behaviour (AuthenticationError propagates),
so they are RED against the buggy code that catches it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from github_cache_loop import GitHubDataCache  # noqa: E402
from subprocess_util import AuthenticationError  # noqa: E402


def _make_cache(tmp_path: Path) -> GitHubDataCache:
    """Build a GitHubDataCache with minimal mocked dependencies."""
    config = MagicMock()
    config.ready_label = ["hydraflow-ready"]
    config.review_label = ["hydraflow-review"]
    config.hitl_label = ["hydraflow-hitl"]
    config.hitl_active_label = ["hydraflow-hitl-active"]
    type(config).repo_data_root = PropertyMock(return_value=tmp_path)

    pr_manager = MagicMock()
    pr_manager.list_open_prs = AsyncMock(return_value=[])
    pr_manager.list_hitl_items = AsyncMock(return_value=[])
    pr_manager.get_label_counts = AsyncMock(return_value=None)

    fetcher = MagicMock()
    fetcher._get_collaborators = AsyncMock(return_value=set())

    return GitHubDataCache(
        config=config,
        pr_manager=pr_manager,
        fetcher=fetcher,
        cache_dir=tmp_path,
    )


class TestAuthenticationErrorNotSwallowed:
    """Issue #6534 — AuthenticationError must propagate out of poll(),
    not be silently caught by the broad ``except Exception`` blocks.
    """

    @pytest.mark.asyncio
    async def test_open_prs_auth_error_propagates(self, tmp_path: Path) -> None:
        """When list_open_prs raises AuthenticationError, poll() must
        re-raise it instead of logging a warning and continuing.
        """
        cache = _make_cache(tmp_path)
        cache._prs.list_open_prs = AsyncMock(
            side_effect=AuthenticationError("Bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await cache.poll()

    @pytest.mark.asyncio
    async def test_hitl_items_auth_error_propagates(self, tmp_path: Path) -> None:
        """When list_hitl_items raises AuthenticationError, poll() must
        re-raise it instead of logging a warning and continuing.
        """
        cache = _make_cache(tmp_path)
        cache._prs.list_hitl_items = AsyncMock(
            side_effect=AuthenticationError("Bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await cache.poll()

    @pytest.mark.asyncio
    async def test_label_counts_auth_error_propagates(self, tmp_path: Path) -> None:
        """When get_label_counts raises AuthenticationError, poll() must
        re-raise it instead of logging a warning and continuing.
        """
        cache = _make_cache(tmp_path)
        cache._prs.get_label_counts = AsyncMock(
            side_effect=AuthenticationError("Bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await cache.poll()

    @pytest.mark.asyncio
    async def test_collaborators_auth_error_propagates(self, tmp_path: Path) -> None:
        """When _get_collaborators raises AuthenticationError, poll() must
        re-raise it instead of logging a warning and continuing.
        """
        cache = _make_cache(tmp_path)
        cache._fetcher._get_collaborators = AsyncMock(
            side_effect=AuthenticationError("Bad credentials"),
        )

        with pytest.raises(AuthenticationError, match="Bad credentials"):
            await cache.poll()

    @pytest.mark.asyncio
    async def test_auth_error_returns_stale_data(self, tmp_path: Path) -> None:
        """Demonstrate the real-world impact: after an AuthenticationError,
        get_open_prs() returns stale data instead of signaling failure.

        This test seeds the cache with initial data, then triggers an
        AuthenticationError on the next poll.  The bug is that poll()
        swallows the error and the stale data remains accessible with
        no indication that auth is broken.
        """
        cache = _make_cache(tmp_path)

        # Seed with initial data
        await cache.poll()
        assert cache.get_open_prs() == []  # sanity check

        # Now auth is broken — poll should propagate, not swallow
        cache._prs.list_open_prs = AsyncMock(
            side_effect=AuthenticationError("Token expired"),
        )

        # BUG: poll() catches AuthenticationError and returns normally,
        # leaving stale data in the cache.  After the fix, this raises.
        with pytest.raises(AuthenticationError, match="Token expired"):
            await cache.poll()
