"""Tests for visual_validation.py — deterministic scope rules and skip policy."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

if TYPE_CHECKING:
    from config import HydraFlowConfig

from models import VisualValidationDecision, VisualValidationPolicy
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory
from visual_validation import (
    _extract_changed_files,
    _extract_override_reason,
    _find_override_label,
    _match_patterns,
    compute_visual_validation,
    format_visual_validation_comment,
)

# --- Helper diff strings ---

_UI_DIFF = """\
diff --git a/src/ui/App.tsx b/src/ui/App.tsx
--- a/src/ui/App.tsx
+++ b/src/ui/App.tsx
@@ -1,3 +1,4 @@
+import React from 'react';
 export default function App() {}
"""

_CSS_DIFF = """\
diff --git a/styles/main.css b/styles/main.css
--- a/styles/main.css
+++ b/styles/main.css
@@ -1 +1,2 @@
+body { color: red; }
"""

_BACKEND_DIFF = """\
diff --git a/src/server.py b/src/server.py
--- a/src/server.py
+++ b/src/server.py
@@ -1 +1,2 @@
+print("hello")
"""

_MIXED_DIFF = """\
diff --git a/src/server.py b/src/server.py
--- a/src/server.py
+++ b/src/server.py
@@ -1 +1,2 @@
+print("hello")
diff --git a/ui/components/Button.jsx b/ui/components/Button.jsx
--- a/ui/components/Button.jsx
+++ b/ui/components/Button.jsx
@@ -1 +1,2 @@
+export default function Button() {}
"""


class TestExtractChangedFiles:
    """Tests for _extract_changed_files."""

    def test_extracts_single_file(self) -> None:
        files = _extract_changed_files(_UI_DIFF)
        assert files == ["src/ui/App.tsx"]

    def test_extracts_multiple_files(self) -> None:
        files = _extract_changed_files(_MIXED_DIFF)
        assert files == ["src/server.py", "ui/components/Button.jsx"]

    def test_empty_diff(self) -> None:
        assert _extract_changed_files("") == []


class TestMatchPatterns:
    """Tests for _match_patterns."""

    def test_glob_star_match(self) -> None:
        patterns = ["src/ui/**", "*.css"]
        assert _match_patterns("src/ui/App.tsx", patterns) == ["src/ui/**"]

    def test_extension_match(self) -> None:
        patterns = ["*.css", "*.tsx"]
        assert _match_patterns("styles/main.css", patterns) == ["*.css"]

    def test_no_match(self) -> None:
        patterns = ["src/ui/**", "*.css"]
        assert _match_patterns("src/server.py", patterns) == []

    def test_multiple_matches(self) -> None:
        patterns = ["src/ui/**", "*.tsx"]
        assert _match_patterns("src/ui/App.tsx", patterns) == ["src/ui/**", "*.tsx"]


class TestFindOverrideLabel:
    """Tests for _find_override_label."""

    def test_finds_required_label(self) -> None:
        labels = ["bug", "hydraflow-visual-required", "priority"]
        result = _find_override_label(
            labels, "hydraflow-visual-required", "hydraflow-visual-skip"
        )
        assert result == "hydraflow-visual-required"

    def test_finds_skip_label(self) -> None:
        labels = ["hydraflow-visual-skip"]
        result = _find_override_label(
            labels, "hydraflow-visual-required", "hydraflow-visual-skip"
        )
        assert result == "hydraflow-visual-skip"

    def test_no_override(self) -> None:
        labels = ["bug", "feature"]
        result = _find_override_label(
            labels, "hydraflow-visual-required", "hydraflow-visual-skip"
        )
        assert result is None

    def test_required_takes_precedence_over_skip(self) -> None:
        labels = ["hydraflow-visual-required", "hydraflow-visual-skip"]
        result = _find_override_label(
            labels, "hydraflow-visual-required", "hydraflow-visual-skip"
        )
        assert result == "hydraflow-visual-required"

    def test_required_takes_precedence_over_skip_reverse_order(self) -> None:
        """REQUIRED must win even when SKIP appears first in the label list."""
        labels = ["hydraflow-visual-skip", "hydraflow-visual-required"]
        result = _find_override_label(
            labels, "hydraflow-visual-required", "hydraflow-visual-skip"
        )
        assert result == "hydraflow-visual-required"


class TestExtractOverrideReason:
    """Tests for _extract_override_reason."""

    def test_extracts_reason_from_comment(self) -> None:
        comments = ["hydraflow-visual-skip: No UI changes, only backend refactor"]
        reason = _extract_override_reason(comments, "hydraflow-visual-skip")
        assert reason == "No UI changes, only backend refactor"

    def test_uses_last_matching_comment(self) -> None:
        comments = [
            "hydraflow-visual-skip: Old reason",
            "Some other comment",
            "hydraflow-visual-skip: Updated reason",
        ]
        reason = _extract_override_reason(comments, "hydraflow-visual-skip")
        assert reason == "Updated reason"

    def test_no_matching_comment(self) -> None:
        comments = ["Just a regular comment"]
        reason = _extract_override_reason(comments, "hydraflow-visual-skip")
        assert reason == ""

    def test_empty_comments(self) -> None:
        reason = _extract_override_reason([], "hydraflow-visual-skip")
        assert reason == ""

    def test_case_insensitive_label_match(self) -> None:
        comments = ["HYDRAFLOW-VISUAL-SKIP: Reason here"]
        reason = _extract_override_reason(comments, "hydraflow-visual-skip")
        assert reason == "Reason here"


class TestComputeVisualValidation:
    """Tests for compute_visual_validation — the core decision function."""

    def test_disabled_returns_skipped(self) -> None:
        """When visual_validation_enabled=False, always skip."""
        config = ConfigFactory.create(visual_validation_enabled=False)
        decision = compute_visual_validation(config, _UI_DIFF, [])
        assert decision.policy == VisualValidationPolicy.SKIPPED
        assert "disabled" in decision.reason.lower()

    def test_required_label_overrides_no_matching_files(self) -> None:
        """Force-required label should trigger REQUIRED even without matching files."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(
            config,
            _BACKEND_DIFF,
            ["hydraflow-visual-required"],
            ["hydraflow-visual-required: Manual QA needed for this change"],
        )
        assert decision.policy == VisualValidationPolicy.REQUIRED
        assert decision.override_label == "hydraflow-visual-required"
        assert "Manual QA needed" in decision.reason

    def test_skip_label_overrides_matching_files(self) -> None:
        """Force-skip label should skip even when files match trigger patterns."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(
            config,
            _UI_DIFF,
            ["hydraflow-visual-skip"],
            ["hydraflow-visual-skip: CSS-only change, no visual impact"],
        )
        assert decision.policy == VisualValidationPolicy.SKIPPED
        assert decision.override_label == "hydraflow-visual-skip"
        assert "CSS-only change" in decision.reason

    def test_skip_label_without_reason_logs_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Skip override without audit reason should emit a warning."""
        import logging

        config = ConfigFactory.create()
        with caplog.at_level(logging.WARNING, logger="hydraflow.visual_validation"):
            decision = compute_visual_validation(
                config,
                _UI_DIFF,
                ["hydraflow-visual-skip"],
            )
        assert decision.policy == VisualValidationPolicy.SKIPPED
        assert "no reason given" in decision.reason.lower()
        assert any("without audit reason" in r.message for r in caplog.records)

    def test_ui_diff_triggers_required(self) -> None:
        """Files matching src/ui/** should trigger REQUIRED."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(config, _UI_DIFF, [])
        assert decision.policy == VisualValidationPolicy.REQUIRED
        assert len(decision.triggered_patterns) > 0

    def test_css_diff_triggers_required(self) -> None:
        """CSS files should trigger REQUIRED via *.css pattern."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(config, _CSS_DIFF, [])
        assert decision.policy == VisualValidationPolicy.REQUIRED
        assert "*.css" in decision.triggered_patterns

    def test_backend_only_diff_skipped(self) -> None:
        """Backend-only changes should be SKIPPED."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(config, _BACKEND_DIFF, [])
        assert decision.policy == VisualValidationPolicy.SKIPPED
        assert "no changed files" in decision.reason.lower()

    def test_mixed_diff_triggers_required(self) -> None:
        """If any file matches trigger patterns, decision is REQUIRED."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(config, _MIXED_DIFF, [])
        assert decision.policy == VisualValidationPolicy.REQUIRED

    def test_custom_trigger_patterns(self) -> None:
        """Custom trigger patterns should be respected."""
        config = ConfigFactory.create(
            visual_validation_trigger_patterns=["*.py"],
        )
        decision = compute_visual_validation(config, _BACKEND_DIFF, [])
        assert decision.policy == VisualValidationPolicy.REQUIRED
        assert "*.py" in decision.triggered_patterns

    def test_empty_diff(self) -> None:
        """Empty diff should be SKIPPED."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(config, "", [])
        assert decision.policy == VisualValidationPolicy.SKIPPED

    def test_required_label_without_audit_reason(self) -> None:
        """Required override without comment uses default reason."""
        config = ConfigFactory.create()
        decision = compute_visual_validation(
            config,
            _BACKEND_DIFF,
            ["hydraflow-visual-required"],
        )
        assert decision.policy == VisualValidationPolicy.REQUIRED
        assert "Override label applied" in decision.reason


class TestFormatVisualValidationComment:
    """Tests for format_visual_validation_comment."""

    def test_required_format(self) -> None:
        decision = VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason="Files match trigger patterns",
            triggered_patterns=["src/ui/**", "*.tsx"],
        )
        comment = format_visual_validation_comment(decision)
        assert "**REQUIRED**" in comment
        assert "Visual Validation" in comment
        assert "`src/ui/**`" in comment

    def test_skipped_format(self) -> None:
        decision = VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason="No matching files",
        )
        comment = format_visual_validation_comment(decision)
        assert "**SKIPPED**" in comment
        assert "No matching files" in comment

    def test_override_label_shown(self) -> None:
        decision = VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason="CSS-only change",
            override_label="hydraflow-visual-skip",
        )
        comment = format_visual_validation_comment(decision)
        assert "`hydraflow-visual-skip`" in comment


class TestPostMergeVisualDecisionEnforcement:
    """Tests that _should_create_verification_issue respects visual decisions."""

    def _make_handler(self, config: HydraFlowConfig):
        from unittest.mock import AsyncMock

        from events import EventBus
        from post_merge_handler import PostMergeHandler
        from state import StateTracker

        state = StateTracker(config.state_file)
        return PostMergeHandler(
            config=config,
            state=state,
            prs=AsyncMock(),
            event_bus=EventBus(),
            ac_generator=None,
            retrospective=None,
            verification_judge=None,
            epic_checker=None,
        )

    def _make_judge_result(self, issue_number: int = 1, instructions: str = "Check it"):
        from models import JudgeResult, VerificationCriterion

        return JudgeResult(
            issue_number=issue_number,
            pr_number=101,
            criteria=[
                VerificationCriterion(
                    description="AC-1",
                    passed=True,
                    details="OK",
                ),
            ],
            verification_instructions=instructions,
            summary="1/1 passed",
        )

    def test_visual_required_forces_verification_issue(self) -> None:
        """REQUIRED visual decision should force verification issue creation."""
        config = ConfigFactory.create()
        handler = self._make_handler(config)
        issue = TaskFactory.create(title="Backend refactor", body="Cleanup code")
        judge_result = self._make_judge_result(instructions="Run the test suite")

        visual_decision = VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason="Override label applied",
            override_label="hydraflow-visual-required",
        )

        result = handler._should_create_verification_issue(
            issue, judge_result, _BACKEND_DIFF, visual_decision
        )
        assert result is True

    def test_visual_skipped_suppresses_diff_based_detection(self) -> None:
        """SKIPPED visual decision should suppress diff-based user-surface check."""
        config = ConfigFactory.create()
        handler = self._make_handler(config)
        # Issue has no manual cues, but diff touches UI files
        issue = TaskFactory.create(
            title="Backend refactor",
            body="Internal cleanup only",
        )
        judge_result = self._make_judge_result(instructions="Run tests")

        visual_decision = VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason="No visual impact",
            override_label="hydraflow-visual-skip",
        )

        # Without visual decision, this UI diff would trigger verification
        result_without = handler._should_create_verification_issue(
            issue,
            judge_result,
            "+++ b/src/ui/App.tsx\n@@\n+<button>Save</button>",
        )

        # With SKIPPED visual decision, the diff check should be suppressed
        result_with = handler._should_create_verification_issue(
            issue,
            judge_result,
            "+++ b/src/ui/App.tsx\n@@\n+<button>Save</button>",
            visual_decision,
        )

        # Without visual decision, diff triggers verification (legacy behavior)
        assert result_without is True
        # With SKIPPED, diff check is suppressed
        assert result_with is False

    def test_no_visual_decision_preserves_legacy_behavior(self) -> None:
        """When no visual decision is provided, legacy behavior should apply."""
        config = ConfigFactory.create()
        handler = self._make_handler(config)
        issue = TaskFactory.create(title="UI update", body="Add button to page")
        judge_result = self._make_judge_result(
            instructions="Open the app in browser and click Save button"
        )

        # Legacy: manual cues in instructions trigger verification
        result = handler._should_create_verification_issue(
            issue, judge_result, _BACKEND_DIFF
        )
        assert result is True

    def test_visual_required_still_needs_instructions(self) -> None:
        """REQUIRED visual decision with empty instructions should still skip."""
        config = ConfigFactory.create()
        handler = self._make_handler(config)
        issue = TaskFactory.create()
        judge_result = self._make_judge_result(instructions="")

        visual_decision = VisualValidationDecision(
            policy=VisualValidationPolicy.REQUIRED,
            reason="Override label applied",
        )

        result = handler._should_create_verification_issue(
            issue, judge_result, _UI_DIFF, visual_decision
        )
        assert result is False

    def test_visual_skipped_still_honours_manual_keyword_cues(self) -> None:
        """SKIPPED suppresses diff-based check but still honours manual keyword cues.

        By design: if the issue title/body or judge instructions contain
        UI-surface keywords (e.g. 'visual', 'ui', 'button'), verification is
        created even when the SKIPPED override is set. This documents the
        intentional boundary documented in _should_create_verification_issue.
        """
        config = ConfigFactory.create()
        handler = self._make_handler(config)
        # Issue body explicitly references a UI surface keyword
        issue = TaskFactory.create(
            title="Fix visual glitch on settings page",
            body="The button color is wrong",
        )
        judge_result = self._make_judge_result(
            instructions="Verify that the button colour renders correctly"
        )

        visual_decision = VisualValidationDecision(
            policy=VisualValidationPolicy.SKIPPED,
            reason="CSS-only change, no logical impact",
            override_label="hydraflow-visual-skip",
        )

        # Manual keyword cues ('visual', 'button', 'page') override the SKIP decision
        result = handler._should_create_verification_issue(
            issue, judge_result, _BACKEND_DIFF, visual_decision
        )
        assert result is True, (
            "SKIPPED suppresses the diff-based check but must still honour "
            "keyword-based manual cues from issue text / judge instructions"
        )


class TestReviewPhaseVisualValidation:
    """Tests for visual validation integration in ReviewPhase."""

    def test_compute_visual_validation_returns_decision(self) -> None:
        """_compute_visual_validation should return a decision when enabled."""
        import asyncio
        from unittest.mock import AsyncMock

        from events import EventBus
        from issue_store import IssueStore
        from review_phase import ReviewPhase
        from reviewer import ReviewRunner
        from state import StateTracker
        from workspace import WorkspaceManager

        config = ConfigFactory.create()
        state = StateTracker(config.state_file)
        phase = ReviewPhase(
            config=config,
            state=state,
            worktrees=AsyncMock(spec=WorkspaceManager),
            reviewers=AsyncMock(spec=ReviewRunner),
            prs=AsyncMock(),
            stop_event=asyncio.Event(),
            store=AsyncMock(spec=IssueStore),
            event_bus=EventBus(),
        )

        task = TaskFactory.create(tags=[], comments=[])
        decision = phase._compute_visual_validation(_UI_DIFF, task)
        assert decision is not None
        assert decision.policy == VisualValidationPolicy.REQUIRED

    def test_compute_visual_validation_returns_none_when_disabled(self) -> None:
        """_compute_visual_validation should return None when disabled."""
        import asyncio
        from unittest.mock import AsyncMock

        from events import EventBus
        from issue_store import IssueStore
        from review_phase import ReviewPhase
        from reviewer import ReviewRunner
        from state import StateTracker
        from workspace import WorkspaceManager

        config = ConfigFactory.create(visual_validation_enabled=False)
        state = StateTracker(config.state_file)
        phase = ReviewPhase(
            config=config,
            state=state,
            worktrees=AsyncMock(spec=WorkspaceManager),
            reviewers=AsyncMock(spec=ReviewRunner),
            prs=AsyncMock(),
            stop_event=asyncio.Event(),
            store=AsyncMock(spec=IssueStore),
            event_bus=EventBus(),
        )

        task = TaskFactory.create()
        decision = phase._compute_visual_validation(_UI_DIFF, task)
        assert decision is None
