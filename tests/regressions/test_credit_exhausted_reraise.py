"""Regression: broad except Exception blocks in caretaker loops must NOT swallow
CreditExhaustedError (dark-factory.md §2.2).

Slice #3 + #5.0 audit found 7 loops with broad except blocks that would eat
CreditExhaustedError, causing the loop to burn attempt budget against an
exhausted billing signal. This file guards two representative loops; the
same reraise_on_credit_or_bug pattern covers all 7.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from subprocess_util import CreditExhaustedError
from tests.helpers import make_bg_loop_deps


# ---------------------------------------------------------------------------
# CodeGroomingLoop — wraps stream_claude_process via _run_audit
# ---------------------------------------------------------------------------


class TestCodeGroomingCreditExhaustedReraise:
    """CreditExhaustedError raised by _run_audit must propagate out of _do_work."""

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_run_audit(
        self, tmp_path: Path
    ) -> None:
        """When _run_audit raises CreditExhaustedError the loop MUST re-raise it,
        not swallow it and return {"filed": 0, "error": True}."""
        from unittest.mock import patch

        from code_grooming_loop import CodeGroomingLoop

        deps = make_bg_loop_deps(tmp_path, code_grooming_enabled=True)
        loop = CodeGroomingLoop(
            config=deps.config,
            pr_manager=AsyncMock(),
            deps=deps.loop_deps,
        )

        with patch.object(
            loop,
            "_run_audit",
            new_callable=AsyncMock,
            side_effect=CreditExhaustedError("billing limit reached"),
        ):
            with pytest.raises(CreditExhaustedError, match="billing limit reached"):
                await loop._do_work()


# ---------------------------------------------------------------------------
# CorpusLearningLoop — wraps gh issue list subprocess + escape-signal query
# ---------------------------------------------------------------------------


class TestCorpusLearningCreditExhaustedReraise:
    """CreditExhaustedError raised inside corpus learning broad-except paths must
    propagate, not be swallowed."""

    def _make_loop(self, tmp_path: Path):
        from corpus_learning_loop import CorpusLearningLoop
        from dedup_store import DedupStore

        deps = make_bg_loop_deps(tmp_path)
        pr_manager = AsyncMock()
        pr_manager.list_issues_by_label = AsyncMock(return_value=[])
        dedup = DedupStore(
            "corpus_learning",
            deps.config.data_root / "memory" / "corpus_learning_dedup.json",
        )
        state = MagicMock()
        state.increment_corpus_validation_attempts = MagicMock(return_value=3)
        state.reset_corpus_validation_attempts = MagicMock()

        loop = CorpusLearningLoop(
            config=deps.config,
            prs=pr_manager,
            dedup=dedup,
            state=state,
            deps=deps.loop_deps,
        )
        return loop, pr_manager

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_escape_signal_query(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError raised by _list_escape_signals must not be swallowed
        by the broad except in _do_work."""
        from unittest.mock import patch

        loop, _ = self._make_loop(tmp_path)

        with patch.object(
            loop,
            "_list_escape_signals",
            new_callable=AsyncMock,
            side_effect=CreditExhaustedError("credits exhausted"),
        ):
            with pytest.raises(CreditExhaustedError, match="credits exhausted"):
                await loop._do_work()

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates_through_create_issue(
        self, tmp_path: Path
    ) -> None:
        """CreditExhaustedError raised by create_issue in _record_validation_failure
        must propagate out of the broad except that guards it."""
        from corpus_learning_loop import EscapeSignal, ValidationResult

        loop, pr_manager = self._make_loop(tmp_path)
        pr_manager.create_issue = AsyncMock(
            side_effect=CreditExhaustedError("credits exhausted during issue creation")
        )

        signal = EscapeSignal(
            issue_number=99,
            title="test: escape",
            body="",
            updated_at="2026-01-01T00:00:00Z",
            label="skill-escape",
        )
        result = ValidationResult(ok=False, failing_gate="harness", reason="diff empty")

        with pytest.raises(
            CreditExhaustedError, match="credits exhausted during issue creation"
        ):
            await loop._record_validation_failure(signal, result)
