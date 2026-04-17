"""Regression test for issue #6515.

Bug: _run_pre_merge_spec_check catches all exceptions (including programming
errors in extract_spec_match) and returns True, silently bypassing the spec
compliance gate.

The distinction from #6357 (which tests errors from _execute) is that #6515
targets bugs *inside* extract_spec_match itself — e.g. TypeError,
AttributeError, KeyError — which indicate a code defect, not a transient
failure.  These programming errors must propagate instead of being swallowed.

Expected behaviour after fix:
  - Programming errors (TypeError, AttributeError, ValueError, KeyError) in
    extract_spec_match propagate rather than returning True.
  - Transient errors (network, subprocess) still return True to avoid blocking.

These tests assert the *correct* behaviour, so they are RED against the
current (buggy) code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tests.conftest import TaskFactory
from tests.helpers import make_review_phase


def _product_track_task(**kwargs):
    """Create a Task that passes _is_product_track_pr (has shape comment)."""
    return TaskFactory.create(
        comments=["Selected Product Direction: build widget"],
        **kwargs,
    )


class TestExtractSpecMatchProgrammingErrorBypass:
    """Issue #6515 — programming errors in extract_spec_match must not
    silently return True (approve merge).

    When extract_spec_match has a code bug (e.g. calling .group() on None,
    accessing a missing dict key, passing wrong types), the broad
    ``except Exception`` at line 861 catches it and returns True —
    silently bypassing the spec compliance gate.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "error,label",
        [
            (TypeError("'NoneType' object is not subscriptable"), "TypeError"),
            (
                AttributeError("'NoneType' object has no attribute 'group'"),
                "AttributeError",
            ),
            (ValueError("invalid literal for int()"), "ValueError"),
            (KeyError("verdict"), "KeyError"),
        ],
        ids=["TypeError", "AttributeError", "ValueError", "KeyError"],
    )
    async def test_programming_error_in_extract_spec_match_propagates(
        self, config, error, label
    ) -> None:
        """A programming error in extract_spec_match must propagate —
        not silently approve the merge by returning True.

        The current code catches all exceptions and returns True (RED).
        After the fix, programming errors should re-raise.
        """
        phase = make_review_phase(config)
        task = _product_track_task()

        # _execute succeeds (returns transcript), but extract_spec_match
        # has a code bug and raises a programming error.
        buggy_extract = MagicMock(side_effect=error)

        with patch.dict(
            "sys.modules",
            {
                "spec_match": MagicMock(
                    build_self_review_prompt=MagicMock(return_value="prompt"),
                    extract_spec_match=buggy_extract,
                ),
                "agent_cli": MagicMock(
                    build_agent_command=MagicMock(return_value=["echo", "test"]),
                ),
            },
        ):
            phase._reviewers._execute = AsyncMock(
                return_value="SPEC_MATCH_START\n**Overall verdict:** MATCH\nSPEC_MATCH_END"
            )

            with pytest.raises(type(error)):
                await phase._run_pre_merge_spec_check(task, "diff text")

    @pytest.mark.asyncio
    async def test_extract_spec_match_attribute_error_propagates(self, config) -> None:
        """After the fix, an AttributeError in extract_spec_match must
        propagate rather than silently returning True (approving the merge).

        Previously this test was inverted — it asserted ``result is True`` to
        document the buggy fail-open behaviour. Now that the fix is in place
        (``review_phase._run_pre_merge_spec_check`` re-raises likely-bug
        exceptions) we assert the correct behaviour directly.
        """
        phase = make_review_phase(config)
        task = _product_track_task()

        buggy_extract = MagicMock(
            side_effect=AttributeError("'NoneType' object has no attribute 'group'")
        )

        with patch.dict(
            "sys.modules",
            {
                "spec_match": MagicMock(
                    build_self_review_prompt=MagicMock(return_value="prompt"),
                    extract_spec_match=buggy_extract,
                ),
                "agent_cli": MagicMock(
                    build_agent_command=MagicMock(return_value=["echo", "test"]),
                ),
            },
        ):
            phase._reviewers._execute = AsyncMock(return_value="some transcript")

            with pytest.raises(AttributeError, match="'NoneType' object"):
                await phase._run_pre_merge_spec_check(task, "diff text")

    @pytest.mark.asyncio
    async def test_programming_error_must_not_approve_merge(self, config) -> None:
        """The spec-match gate must not approve a merge when
        extract_spec_match has a programming error.

        This is the key RED test: it asserts the correct behaviour
        (error propagation), which currently fails because the broad
        except Exception swallows the error and returns True.
        """
        phase = make_review_phase(config)
        task = _product_track_task()

        # Simulate a realistic bug: extract_spec_match tries to call
        # .group() on a None regex match result.
        buggy_extract = MagicMock(
            side_effect=AttributeError("'NoneType' object has no attribute 'group'")
        )

        with patch.dict(
            "sys.modules",
            {
                "spec_match": MagicMock(
                    build_self_review_prompt=MagicMock(return_value="prompt"),
                    extract_spec_match=buggy_extract,
                ),
                "agent_cli": MagicMock(
                    build_agent_command=MagicMock(return_value=["echo", "test"]),
                ),
            },
        ):
            phase._reviewers._execute = AsyncMock(return_value="some transcript")

            # The correct behaviour: programming error propagates.
            # Current buggy behaviour: returns True (approve).
            with pytest.raises(AttributeError, match="'NoneType' object"):
                await phase._run_pre_merge_spec_check(task, "diff text")
