"""PRManager.find_label_drift — detects cross-entity issue/PR drift.

See ADR-0056. Three drift kinds:
- ``pr_ahead_of_issue``: issue at ready/plan, PR at review with commits
- ``pr_at_pre_pr_stage``: PR labelled ready/plan but has commits
- ``pr_behind_issue``: PR at ready/plan while issue at review
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import make_pr_manager


def _gh_responder(mapping: dict[tuple[str, ...], str]):
    """Return an AsyncMock side_effect that dispatches by tuple of cmd args.

    ``mapping`` keys are partial-match tuples (e.g. ("pr", "list")) — the
    first key whose elements all appear in the call's positional args wins.
    """

    async def _side_effect(*args, **kwargs):
        for key, response in mapping.items():
            if all(part in args for part in key):
                return response
        raise AssertionError(f"unexpected gh call: {args}")

    return _side_effect


class TestFindLabelDrift:
    @pytest.mark.asyncio
    async def test_detects_issue_at_ready_pr_at_review(self, config, event_bus) -> None:
        """Issue labelled hydraflow-ready while its PR is at hydraflow-review
        with commits → kind=pr_ahead_of_issue."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 100,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "## Summary\n\nFixes #42.\n",
                    "commits": [{"oid": "a"}, {"oid": "b"}],
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-ready"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].issue == 42
        assert drift[0].pr == 100
        assert drift[0].kind == "pr_ahead_of_issue"
        assert drift[0].issue_label == "hydraflow-ready"
        assert drift[0].pr_label == "hydraflow-review"
        assert drift[0].pr_commits == 2

    @pytest.mark.asyncio
    async def test_detects_pr_at_ready_with_commits(self, config, event_bus) -> None:
        """PR labelled hydraflow-ready but has commits → kind=pr_at_pre_pr_stage."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 200,
                    "labels": [{"name": "hydraflow-ready"}],
                    "body": "Fixes #99",
                    "commits": [{"oid": "a"}, {"oid": "b"}, {"oid": "c"}],
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-review"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert len(drift) == 1
        assert drift[0].pr == 200
        assert drift[0].kind == "pr_at_pre_pr_stage"
        assert drift[0].pr_commits == 3

    @pytest.mark.asyncio
    async def test_no_drift_when_aligned(self, config, event_bus) -> None:
        """Issue and PR both at hydraflow-review → empty list."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 300,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "Fixes #7",
                    "commits": [{"oid": "x"}],
                }
            ]
        )
        issue_json = json.dumps({"labels": [{"name": "hydraflow-review"}]})

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(
                side_effect=_gh_responder(
                    {
                        ("pr", "list"): prs_json,
                        ("issue", "view"): issue_json,
                    }
                )
            ),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []

    @pytest.mark.asyncio
    async def test_skips_prs_without_fixes_link(self, config, event_bus) -> None:
        """PR body without 'Fixes #N' is skipped — no linked issue to check."""
        mgr = make_pr_manager(config, event_bus)

        prs_json = json.dumps(
            [
                {
                    "number": 400,
                    "labels": [{"name": "hydraflow-review"}],
                    "body": "no fixes link here",
                    "commits": [{"oid": "x"}],
                }
            ]
        )

        with patch(
            "pr_manager.run_subprocess_with_retry",
            new=AsyncMock(side_effect=_gh_responder({("pr", "list"): prs_json})),
        ):
            drift = await mgr.find_label_drift()

        assert drift == []
