"""Regression test for issue #6679.

``ReviewPhase._run_pre_merge_spec_check`` catches all exceptions via a
bare ``except Exception`` (line 861) and returns ``True`` (allow merge).
This fail-open behaviour is intended for transient tool errors (e.g.
a subprocess timeout), but it also swallows programming bugs —
``TypeError``, ``AttributeError``, ``KeyError`` — that indicate a logic
error in the spec-match check itself.

The result: a bug in the spec checker silently lets MISMATCH PRs
through to merge.

Test 1: ``TypeError`` from ``extract_spec_match`` must propagate (it is
a programming bug).  Currently FAILS because the broad ``except
Exception`` catches it and returns ``True``.

Test 2: ``AttributeError`` from ``build_self_review_prompt`` must
propagate.  Currently FAILS for the same reason.

Test 3: A transient ``RuntimeError`` (e.g. subprocess failure) should
still be caught and return ``True`` — fail-open is correct for
transient errors.  This test is GREEN today and guards against
over-correction.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from models import Task
from review_phase import ReviewPhase


def _make_review_phase(tmp_path: Path) -> ReviewPhase:
    """Build a ReviewPhase with just enough mocks for _run_pre_merge_spec_check."""
    from events import EventBus
    from merge_conflict_resolver import MergeConflictResolver
    from post_merge_handler import PostMergeHandler

    config = MagicMock()
    config.state_file = tmp_path / "state.json"
    config.state_file.write_text("{}")
    config.repo_root = tmp_path
    config.workspace_base = tmp_path / "workspaces"
    config.workspace_base.mkdir(parents=True, exist_ok=True)
    config.review_tool = "claude"
    config.review_model = "test"

    from state import StateTracker

    state = StateTracker(config.state_file)
    stop_event = asyncio.Event()

    mock_wt = AsyncMock()
    mock_reviewers = AsyncMock()
    mock_reviewers._execute = AsyncMock(return_value="transcript text")
    mock_prs = AsyncMock()
    mock_prs.expected_pr_title = MagicMock(return_value="Fixes #1: test")
    mock_prs.post_comment = AsyncMock()

    mock_store = MagicMock()
    mock_store.mark_active = lambda _num, _stage: None
    mock_store.mark_complete = lambda _num: None
    mock_store.is_active = lambda _num: False

    bus = EventBus()
    conflict_resolver = MergeConflictResolver(
        config=config,
        workspaces=mock_wt,
        agents=MagicMock(),
        prs=mock_prs,
        event_bus=bus,
        state=state,
        summarizer=None,
    )
    post_merge = PostMergeHandler(
        config=config,
        state=state,
        prs=mock_prs,
        event_bus=bus,
        ac_generator=None,
        retrospective=None,
        verification_judge=None,
        epic_checker=None,
        store=mock_store,
    )

    phase = ReviewPhase(
        config=config,
        state=state,
        workspaces=mock_wt,
        reviewers=mock_reviewers,
        prs=mock_prs,
        stop_event=stop_event,
        store=mock_store,
        conflict_resolver=conflict_resolver,
        post_merge=post_merge,
        event_bus=bus,
    )
    return phase


def _make_task() -> Task:
    """Return a minimal Task for the spec-match check."""
    return Task(id=42, title="Fix the widget", body="The widget is broken")


# ---------------------------------------------------------------------------
# Test 1: TypeError from extract_spec_match must propagate
# ---------------------------------------------------------------------------


class TestTypeErrorPropagates:
    """A TypeError in extract_spec_match is a programming bug and must not
    be silently swallowed and converted to 'merge allowed'."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Regression for issue #6679 — fix not yet landed", strict=False
    )
    async def test_type_error_in_spec_match_is_reraised(self, tmp_path: Path) -> None:
        """If extract_spec_match raises TypeError (e.g. it receives None
        instead of a string), _run_pre_merge_spec_check must let it
        propagate so the bug is visible.

        Currently FAILS: the bare ``except Exception`` catches it and
        returns True (merge allowed).
        """
        phase = _make_review_phase(tmp_path)
        task = _make_task()

        # Patch at definition site — the deferred imports inside the method
        # bind fresh each call, so patching the source module works.
        with (
            patch("spec_match.build_self_review_prompt", return_value="prompt"),
            patch("agent_cli.build_agent_command", return_value=["echo"]),
            patch(
                "spec_match.extract_spec_match",
                side_effect=TypeError("expected str instance, not NoneType"),
            ),
        ):
            # BUG: this should raise TypeError, but instead returns True
            # because except Exception swallows it
            with pytest.raises(TypeError, match="expected str"):
                await phase._run_pre_merge_spec_check(task, "diff content")


# ---------------------------------------------------------------------------
# Test 2: AttributeError from build_self_review_prompt must propagate
# ---------------------------------------------------------------------------


class TestAttributeErrorPropagates:
    """An AttributeError in build_self_review_prompt is a programming bug."""

    @pytest.mark.asyncio
    async def test_attribute_error_in_prompt_builder_is_reraised(
        self, tmp_path: Path
    ) -> None:
        """If build_self_review_prompt raises AttributeError (e.g. Task
        model changed and a field was removed), it must propagate.

        Currently FAILS: the bare ``except Exception`` catches it and
        returns True.
        """
        phase = _make_review_phase(tmp_path)
        task = _make_task()

        with (
            patch(
                "spec_match.build_self_review_prompt",
                side_effect=AttributeError(
                    "'Task' object has no attribute 'acceptance_criteria'"
                ),
            ),
            pytest.raises(AttributeError, match="acceptance_criteria"),
        ):
            await phase._run_pre_merge_spec_check(task, "diff content")


# ---------------------------------------------------------------------------
# Test 3: Transient RuntimeError should NOT propagate (guard rail)
# ---------------------------------------------------------------------------


class TestTransientErrorIsCaught:
    """A transient RuntimeError (subprocess failure, network blip) is not
    a programming bug and should be caught — the method should return True
    so the merge isn't blocked by tool flakiness.

    This test is GREEN today and ensures the fix doesn't over-correct.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Regression for issue #6679 — fix not yet landed", strict=False
    )
    async def test_runtime_error_returns_true(self, tmp_path: Path) -> None:
        """RuntimeError from _execute (subprocess failure) should be
        caught and return True (fail-open, don't block merge)."""
        phase = _make_review_phase(tmp_path)
        task = _make_task()

        with (
            patch("spec_match.build_self_review_prompt", return_value="prompt"),
            patch("agent_cli.build_agent_command", return_value=["echo"]),
        ):
            # Simulate subprocess failure
            phase._reviewers._execute = AsyncMock(
                side_effect=RuntimeError("subprocess timed out")
            )

            result = await phase._run_pre_merge_spec_check(task, "diff")
            assert result is True, (
                "Transient RuntimeError should fail-open (return True)"
            )
