"""MockWorld scenario for SandboxFailureFixerLoop (bead #8814, slice 5.3).

Four scenarios over the loop's auto-fix → escalation ladder:

* ``test_auto_fix_succeeds_on_first_attempt`` — PR labeled
  ``sandbox-fail-auto-fix`` is polled; the runner returns a non-crashed
  outcome on attempt 1. The loop must report ``dispatched=1, escalated=0``.

* ``test_escalates_to_hitl_after_max_attempts`` — PR has already consumed
  ``auto_agent_max_attempts`` (default 3) attempts. The loop must swap
  ``sandbox-fail-auto-fix`` → ``sandbox-hitl`` and return
  ``escalated=1, dispatched=0``.

* ``test_hitl_queue_reflects_escalated_pr`` — end-to-end HITL queue
  integration: run the loop (PR at cap), then call
  ``sandbox_hitl_handler`` against the same FakeGitHub and confirm the PR
  surfaces with the correct shape (number, branch, label, type).

* ``test_opt_out_label_skips_pr`` — PR carrying ``no-auto-fix`` is skipped
  entirely: no dispatch, no escalation, labels unchanged.

``config.sandbox_failure_fixer_enabled`` defaults to ``False``; scenarios
pass ``sandbox_failure_fixer_enabled=True`` to ``make_bg_loop_deps`` and
construct the loop directly (the catalog builder has no config-enable seam,
matching the direct-construction pattern used in unit tests).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from dashboard_routes._hitl_routes import sandbox_hitl_handler
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_AUTO_FIX_LABEL = "sandbox-fail-auto-fix"
_HITL_LABEL = "sandbox-hitl"


def _make_state(attempts: dict[int, int] | None = None) -> MagicMock:
    """Build a state mock mirroring SandboxFailureFixerStateMixin.

    ``get_sandbox_failure_fixer_attempts(pr_number)`` returns the seeded
    count (0 if absent); ``bump_sandbox_failure_fixer_attempts(pr_number)``
    increments in-memory and returns the new total.
    """
    state = MagicMock()
    counts: dict[str, int] = {str(k): v for k, v in (attempts or {}).items()}

    def _get(pr_number: int) -> int:
        return int(counts.get(str(pr_number), 0))

    def _bump(pr_number: int) -> int:
        new = _get(pr_number) + 1
        counts[str(pr_number)] = new
        return new

    state.get_sandbox_failure_fixer_attempts.side_effect = _get
    state.bump_sandbox_failure_fixer_attempts.side_effect = _bump
    state._counts = counts
    return state


class TestSandboxFailureFixerScenario:
    """Slice 5.3 / bead #8814 — auto-fix → HITL escalation path."""

    async def test_auto_fix_succeeds_on_first_attempt(self, tmp_path) -> None:
        """Sandbox red detected, auto-fix attempt #1 passes.

        The runner returns a non-crashed outcome. The loop must:
        * Bump attempt counter to 1.
        * Call runner.run once.
        * Return dispatched=1, escalated=0.
        """
        from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
        from tests.helpers import make_bg_loop_deps

        world = MockWorld(tmp_path)
        github = world.github

        github.add_pr(
            number=42,
            issue_number=10,
            branch="rc/2026-05-01-0400",
        )
        github.add_pr_label(42, _AUTO_FIX_LABEL)

        state = _make_state()
        runner = MagicMock()
        runner.run = AsyncMock(
            return_value=SimpleNamespace(crashed=False, output_text="fixed")
        )

        bg = make_bg_loop_deps(
            tmp_path,
            sandbox_failure_fixer_enabled=True,
            auto_agent_max_attempts=3,
        )
        loop = SandboxFailureFixerLoop(
            config=bg.config,
            state=state,
            prs=github,
            runner=runner,
            deps=bg.loop_deps,
        )

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "ok"
        assert result["candidates"] == 1
        assert result["dispatched"] == 1
        assert result["escalated"] == 0
        assert result["crashed"] == 0

        runner.run.assert_awaited_once()
        assert state._counts == {"42": 1}

        # The auto-fix label stays; removal on success is the responsibility
        # of a downstream watcher, not this loop.
        pr = github.pr(42)
        assert _AUTO_FIX_LABEL in pr.labels

    async def test_escalates_to_hitl_after_max_attempts(self, tmp_path) -> None:
        """Sandbox red, 3 failed attempts → escalate to sandbox-hitl.

        After ``auto_agent_max_attempts`` (3) attempts the loop must:
        * Skip the runner entirely.
        * Remove ``sandbox-fail-auto-fix`` from the PR.
        * Add ``sandbox-hitl`` to the PR.
        * Return escalated=1, dispatched=0.
        """
        from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
        from tests.helpers import make_bg_loop_deps

        world = MockWorld(tmp_path)
        github = world.github

        github.add_pr(
            number=42,
            issue_number=10,
            branch="rc/2026-05-01-0400",
        )
        github.add_pr_label(42, _AUTO_FIX_LABEL)

        # PR is already at the 3-attempt cap.
        state = _make_state(attempts={42: 3})
        runner = MagicMock()
        runner.run = AsyncMock()

        bg = make_bg_loop_deps(
            tmp_path,
            sandbox_failure_fixer_enabled=True,
            auto_agent_max_attempts=3,
        )
        loop = SandboxFailureFixerLoop(
            config=bg.config,
            state=state,
            prs=github,
            runner=runner,
            deps=bg.loop_deps,
        )

        result = await loop._do_work()

        assert result is not None
        assert result["status"] == "ok"
        assert result["escalated"] == 1
        assert result["dispatched"] == 0

        runner.run.assert_not_awaited()

        pr = github.pr(42)
        assert _AUTO_FIX_LABEL not in pr.labels, (
            "sandbox-fail-auto-fix should be removed after escalation"
        )
        assert _HITL_LABEL in pr.labels, "sandbox-hitl should be added after escalation"

    async def test_hitl_queue_reflects_escalated_pr(self, tmp_path) -> None:
        """End-to-end HITL queue integration.

        After the fixer escalates a PR to ``sandbox-hitl``, the
        ``sandbox_hitl_handler`` (backing ``/api/sandbox-hitl``) must
        surface that PR with the correct shape.
        """
        from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
        from tests.helpers import make_bg_loop_deps

        world = MockWorld(tmp_path)
        github = world.github

        github.add_pr(
            number=99,
            issue_number=20,
            branch="rc/2026-05-02-0800",
        )
        github.add_pr_label(99, _AUTO_FIX_LABEL)

        state = _make_state(attempts={99: 3})
        runner = MagicMock()
        runner.run = AsyncMock()

        bg = make_bg_loop_deps(
            tmp_path,
            sandbox_failure_fixer_enabled=True,
            auto_agent_max_attempts=3,
        )
        loop = SandboxFailureFixerLoop(
            config=bg.config,
            state=state,
            prs=github,
            runner=runner,
            deps=bg.loop_deps,
        )

        # Tick: loop escalates PR #99.
        result = await loop._do_work()
        assert result["escalated"] == 1

        # Verify the HITL queue handler surfaces the escalated PR.
        hitl_payload = await sandbox_hitl_handler(prs=github)

        assert "items" in hitl_payload
        items = hitl_payload["items"]
        assert len(items) == 1, f"expected 1 HITL item, got {items!r}"

        item = items[0]
        assert item["number"] == 99
        assert item["branch"] == "rc/2026-05-02-0800"
        assert item["label"] == _HITL_LABEL
        assert item["type"] == "pr"
        assert isinstance(item["url"], str)

    async def test_opt_out_label_skips_pr(self, tmp_path) -> None:
        """PR carrying no-auto-fix is skipped — no dispatch, no escalation."""
        from sandbox_failure_fixer_loop import SandboxFailureFixerLoop
        from tests.helpers import make_bg_loop_deps

        world = MockWorld(tmp_path)
        github = world.github

        github.add_pr(
            number=77,
            issue_number=30,
            branch="rc/2026-05-03-1200",
        )
        github.add_pr_label(77, _AUTO_FIX_LABEL)
        github.add_pr_label(77, "no-auto-fix")

        state = _make_state()
        runner = MagicMock()
        runner.run = AsyncMock()

        bg = make_bg_loop_deps(
            tmp_path,
            sandbox_failure_fixer_enabled=True,
            auto_agent_max_attempts=3,
        )
        loop = SandboxFailureFixerLoop(
            config=bg.config,
            state=state,
            prs=github,
            runner=runner,
            deps=bg.loop_deps,
        )

        result = await loop._do_work()

        assert result["skipped_opt_out"] == 1
        assert result["dispatched"] == 0
        assert result["escalated"] == 0
        runner.run.assert_not_awaited()

        pr = github.pr(77)
        assert _AUTO_FIX_LABEL in pr.labels
        assert _HITL_LABEL not in pr.labels
