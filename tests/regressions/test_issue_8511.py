"""Regression test for issue #8511.

FakeGitHub.close_task had no cassette under tests/trust/contracts/cassettes/github/
and no dispatch branch in _invoke_fake_github.  The fake_coverage_auditor
flagged it as un-cassetted.

Verifies:
1. The close_task.yaml cassette file exists.
2. FakeGitHub.close_task transitions issue state to "closed".
3. FakeGitHub.close_task is a no-op (not a raise) for a nonexistent issue.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub

_CASSETTE_PATH = (
    Path(__file__).parent.parent / "trust/contracts/cassettes/github/close_task.yaml"
)


class TestCloseTaskCassetteExists:
    def test_cassette_file_exists(self) -> None:
        assert _CASSETTE_PATH.exists(), (
            f"Missing cassette: {_CASSETTE_PATH}. "
            "Add close_task.yaml under tests/trust/contracts/cassettes/github/"
        )


class TestFakeGitHubCloseTask:
    @pytest.mark.asyncio
    async def test_close_task_transitions_issue_to_closed(self) -> None:
        fake = FakeGitHub()
        fake.add_issue(42, "Test issue", "body")
        await fake.close_task(42)
        assert fake._issues[42].state == "closed"

    @pytest.mark.asyncio
    async def test_close_task_is_noop_for_nonexistent_issue(self) -> None:
        fake = FakeGitHub()
        await fake.close_task(999)  # must not raise
