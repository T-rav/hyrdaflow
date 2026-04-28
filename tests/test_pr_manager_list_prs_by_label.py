"""PRManager.list_prs_by_label — delegates to ``gh pr list --label``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.helpers import make_pr_manager


@pytest.mark.asyncio
async def test_list_prs_by_label_calls_gh_with_label_filter(config, event_bus) -> None:
    """Method shells out to ``gh pr list --label <label> --state open``."""
    mgr = make_pr_manager(config, event_bus)

    fake_output = json.dumps(
        [
            {
                "number": 100,
                "headRefName": "rc/2026-04-26",
                "url": "https://github.com/test/repo/pull/100",
                "isDraft": False,
            }
        ]
    )
    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value=fake_output),
    ) as mock:
        prs = await mgr.list_prs_by_label("sandbox-fail-auto-fix")

    assert len(prs) == 1
    assert prs[0].number == 100
    assert prs[0].branch == "rc/2026-04-26"

    # _run_gh delegates positionally to run_subprocess_with_retry(*cmd, ...).
    cmd_args = mock.call_args.args
    assert "pr" in cmd_args
    assert "list" in cmd_args

    # Verify --repo is passed (without it, gh defaults to CWD-inferred repo).
    assert "--repo" in cmd_args
    repo_idx = cmd_args.index("--repo")
    assert cmd_args[repo_idx + 1] == "test-org/test-repo"

    # Verify --label passes the right value at the right position.
    label_idx = cmd_args.index("--label")
    assert cmd_args[label_idx + 1] == "sandbox-fail-auto-fix"

    # Verify --state open is correctly paired (not e.g. --state closed --foo open).
    state_idx = cmd_args.index("--state")
    assert cmd_args[state_idx + 1] == "open"


@pytest.mark.asyncio
async def test_list_prs_by_label_returns_empty_when_no_prs(config, event_bus) -> None:
    """Empty gh output yields an empty list."""
    mgr = make_pr_manager(config, event_bus)

    with patch(
        "pr_manager.run_subprocess_with_retry",
        new=AsyncMock(return_value="[]"),
    ):
        prs = await mgr.list_prs_by_label("sandbox-fail-auto-fix")

    assert prs == []
