"""Tests for acceptance_criteria.py - AcceptanceCriteriaGenerator class."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig

from acceptance_criteria import (
    _AC_END,
    _AC_START,
    _VERIFY_END,
    _VERIFY_START,
    AcceptanceCriteriaGenerator,
)
from escalation_gate import EscalationDecision
from models import VerificationCriteria
from tests.conftest import IssueFactory
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_generator(
    config: HydraFlowConfig,
    event_bus,
) -> tuple[AcceptanceCriteriaGenerator, AsyncMock]:
    """Build a generator with mocked PRManager."""
    mock_prs = AsyncMock()
    mock_prs.post_comment = AsyncMock()
    gen = AcceptanceCriteriaGenerator(config, mock_prs, event_bus)
    return gen, mock_prs


def _make_transcript(
    ac_items: list[str] | None = None,
    verify_steps: list[str] | None = None,
) -> str:
    """Build a transcript with AC and verification markers."""
    ac = ac_items or [
        "AC-1: Dark mode toggle is visible on the settings page",
        "AC-2: Clicking the toggle switches the theme",
    ]
    verify = verify_steps or [
        "1. Open the application settings page",
        "2. Locate the dark mode toggle",
        "3. Click the toggle and verify the theme switches",
    ]
    return (
        "Some preamble text.\n"
        f"{_AC_START}\n" + "\n".join(ac) + f"\n{_AC_END}\n"
        f"Some middle text.\n"
        f"{_VERIFY_START}\n" + "\n".join(verify) + f"\n{_VERIFY_END}\n"
        "Some trailing text.\n"
    )


SAMPLE_DIFF = """\
diff --git a/src/settings.py b/src/settings.py
index abc123..def456 100644
--- a/src/settings.py
+++ b/src/settings.py
@@ -1,5 +1,10 @@
+def toggle_dark_mode():
+    pass
diff --git a/tests/test_settings.py b/tests/test_settings.py
index 111222..333444 100644
--- a/tests/test_settings.py
+++ b/tests/test_settings.py
@@ -1,3 +1,8 @@
+def test_toggle_dark_mode():
+    assert True
diff --git a/tests/test_theme.py b/tests/test_theme.py
new file mode 100644
"""


# ---------------------------------------------------------------------------
# TestBuildPrompt
# ---------------------------------------------------------------------------


class TestBuildPrompt:
    """Tests for prompt construction."""

    def test_includes_issue_body(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create(body="The frobnicator needs fixing")
        prompt = gen._build_prompt(issue, "", "", [])
        assert "The frobnicator needs fixing" in prompt

    def test_includes_issue_title_and_number(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create(number=99, title="Fix the widget")
        prompt = gen._build_prompt(issue, "", "", [])
        assert "#99" in prompt
        assert "Fix the widget" in prompt

    def test_includes_plan_when_present(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "## Step 1\nDo the thing", "", [])
        assert "## Step 1" in prompt
        assert "Do the thing" in prompt
        assert "## Implementation Plan" in prompt

    def test_excludes_plan_section_when_empty(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "", [])
        assert "## Implementation Plan" not in prompt

    def test_includes_diff_summary(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "some diff content", [])
        assert "some diff content" in prompt
        assert "## PR Diff Summary" in prompt

    def test_excludes_diff_section_when_empty(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "", [])
        assert "## PR Diff Summary" not in prompt

    def test_includes_test_files(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(
            issue, "", "", ["tests/test_foo.py", "tests/test_bar.py"]
        )
        assert "tests/test_foo.py" in prompt
        assert "tests/test_bar.py" in prompt
        assert "## Test Files" in prompt

    def test_excludes_test_files_section_when_empty(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "", [])
        assert "## Test Files" not in prompt

    def test_includes_ac_marker_instructions(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "", [])
        assert _AC_START in prompt
        assert _AC_END in prompt
        assert _VERIFY_START in prompt
        assert _VERIFY_END in prompt

    def test_instructs_functional_uat_focus(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        prompt = gen._build_prompt(issue, "", "", [])
        assert "UAT" in prompt
        assert "functional" in prompt


# ---------------------------------------------------------------------------
# TestExtractCriteria
# ---------------------------------------------------------------------------


class TestExtractCriteria:
    """Tests for extracting criteria from transcripts."""

    def test_parses_ac_and_verify_markers(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        transcript = _make_transcript()
        criteria = gen._extract_criteria(transcript, 42, 101)
        assert criteria is not None
        assert "AC-1" in criteria.acceptance_criteria
        assert "AC-2" in criteria.acceptance_criteria
        assert "Open the application" in criteria.verification_instructions

    def test_returns_none_when_no_markers(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = gen._extract_criteria("No markers here.", 42, 101)
        assert criteria is None

    def test_parses_ac_only(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        transcript = f"{_AC_START}\nAC-1: Something\n{_AC_END}\nNo verify section."
        criteria = gen._extract_criteria(transcript, 42, 101)
        assert criteria is not None
        assert "AC-1: Something" in criteria.acceptance_criteria
        assert criteria.verification_instructions == ""

    def test_parses_verify_only(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        transcript = f"No AC section.\n{_VERIFY_START}\n1. Do this\n{_VERIFY_END}\n"
        criteria = gen._extract_criteria(transcript, 42, 101)
        assert criteria is not None
        assert criteria.acceptance_criteria == ""
        assert "1. Do this" in criteria.verification_instructions

    def test_sets_issue_and_pr_numbers(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        transcript = _make_transcript()
        criteria = gen._extract_criteria(transcript, 99, 200)
        assert criteria is not None
        assert criteria.issue_number == 99
        assert criteria.pr_number == 200

    def test_sets_timestamp(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        transcript = _make_transcript()
        criteria = gen._extract_criteria(transcript, 42, 101)
        assert criteria is not None
        assert criteria.timestamp  # non-empty ISO string


# ---------------------------------------------------------------------------
# TestExtractTestFiles
# ---------------------------------------------------------------------------


class TestExtractTestFiles:
    """Tests for extracting test file paths from diffs."""

    def test_extracts_test_files_from_diff(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        files = gen._extract_test_files(SAMPLE_DIFF)
        assert "tests/test_settings.py" in files
        assert "tests/test_theme.py" in files

    def test_returns_empty_list_for_no_tests(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        diff = "diff --git a/src/main.py b/src/main.py\n+++ b/src/main.py\n"
        files = gen._extract_test_files(diff)
        assert files == []

    def test_deduplicates_files(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        diff = (
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "+++ b/tests/test_foo.py\n"
            "diff --git a/tests/test_foo.py b/tests/test_foo.py\n"
            "+++ b/tests/test_foo.py\n"
        )
        files = gen._extract_test_files(diff)
        assert files.count("tests/test_foo.py") == 1


# ---------------------------------------------------------------------------
# TestSummarizeDiff
# ---------------------------------------------------------------------------


class TestSummarizeDiff:
    """Tests for diff truncation."""

    def test_short_diff_unchanged(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        diff = "short diff"
        assert gen._summarize_diff(diff) == "short diff"

    def test_long_diff_truncated(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        diff = "x" * 20_000
        result = gen._summarize_diff(diff)
        assert result.endswith("... (truncated)")
        assert len(result) < len(diff)


# ---------------------------------------------------------------------------
# TestReadPlanFile
# ---------------------------------------------------------------------------


class TestReadPlanFile:
    """Tests for reading plan files."""

    def test_reads_existing_plan(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-42.md").write_text("## The Plan\nDo stuff.")
        assert gen._read_plan_file(42) == "## The Plan\nDo stuff."

    def test_returns_empty_for_missing_plan(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        assert gen._read_plan_file(999) == ""


# ---------------------------------------------------------------------------
# TestFormatComment
# ---------------------------------------------------------------------------


class TestFormatComment:
    """Tests for formatting the GitHub comment."""

    def test_formats_ac_as_checkboxes(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: First criterion\nAC-2: Second criterion",
            verification_instructions="1. Step one\n2. Step two",
            timestamp="2026-01-01T00:00:00",
        )
        comment = gen._format_comment(criteria)
        assert "- [ ] First criterion" in comment
        assert "- [ ] Second criterion" in comment
        assert "## Acceptance Criteria & Verification Instructions" in comment

    def test_formats_verification_steps(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Something",
            verification_instructions="1. Do this\n2. Verify that",
            timestamp="2026-01-01T00:00:00",
        )
        comment = gen._format_comment(criteria)
        assert "1. Do this" in comment
        assert "2. Verify that" in comment
        assert "### Human Verification Steps" in comment

    def test_includes_generator_footer(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: X",
            verification_instructions="1. Y",
            timestamp="2026-01-01T00:00:00",
        )
        comment = gen._format_comment(criteria)
        assert "*Generated by HydraFlow AC Generator*" in comment

    def test_handles_empty_ac(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="",
            verification_instructions="1. Do thing",
            timestamp="2026-01-01T00:00:00",
        )
        comment = gen._format_comment(criteria)
        assert "### Acceptance Criteria" not in comment
        assert "1. Do thing" in comment

    def test_handles_empty_verification(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Something",
            verification_instructions="",
            timestamp="2026-01-01T00:00:00",
        )
        comment = gen._format_comment(criteria)
        assert "### Human Verification Steps" not in comment
        assert "- [ ] Something" in comment


# ---------------------------------------------------------------------------
# TestPersist
# ---------------------------------------------------------------------------


class TestPersist:
    """Tests for file persistence."""

    def test_creates_verification_directory(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Test",
            verification_instructions="1. Check",
            timestamp="2026-01-01T00:00:00",
        )
        gen._persist(criteria)
        verification_dir = config.repo_root / ".hydraflow" / "verification"
        assert verification_dir.exists()

    def test_writes_verification_file(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Feature works",
            verification_instructions="1. Open the app\n2. Verify feature",
            timestamp="2026-01-01T00:00:00",
        )
        gen._persist(criteria)
        path = config.repo_root / ".hydraflow" / "verification" / "issue-42.md"
        assert path.exists()
        content = path.read_text()
        assert "Issue #42" in content
        assert "PR #101" in content
        assert "AC-1: Feature works" in content
        assert "1. Open the app" in content

    def test_overwrites_existing_file(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria_v1 = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Old",
            verification_instructions="1. Old step",
            timestamp="2026-01-01T00:00:00",
        )
        gen._persist(criteria_v1)

        criteria_v2 = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: New",
            verification_instructions="1. New step",
            timestamp="2026-01-02T00:00:00",
        )
        gen._persist(criteria_v2)

        path = config.repo_root / ".hydraflow" / "verification" / "issue-42.md"
        content = path.read_text()
        assert "AC-1: New" in content
        assert "AC-1: Old" not in content

    def test_persist_handles_oserror(
        self, config: HydraFlowConfig, event_bus, caplog: pytest.LogCaptureFixture
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        criteria = VerificationCriteria(
            issue_number=42,
            pr_number=101,
            acceptance_criteria="AC-1: Test",
            verification_instructions="1. Check",
            timestamp="2026-01-01T00:00:00",
        )

        with patch.object(Path, "write_text", side_effect=OSError("disk full")):
            gen._persist(criteria)  # should not raise

        assert "Could not persist acceptance criteria" in caplog.text


# ---------------------------------------------------------------------------
# TestBuildCommand
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for building the claude command."""

    def test_includes_model(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        cmd = gen._build_command()
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == config.ac_model

    def test_includes_disallowed_tools(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        cmd = gen._build_command()
        assert "--disallowedTools" in cmd

    def test_excludes_budget_flag(self, config: HydraFlowConfig, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        cmd = gen._build_command()
        assert "--max-budget-usd" not in cmd

    def test_supports_codex_backend(self, config: HydraFlowConfig, event_bus) -> None:
        cfg = ConfigFactory.create(ac_tool="codex", ac_model="gpt-5-codex")
        gen, _ = _make_generator(cfg, event_bus)
        cmd = gen._build_command()
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# TestGenerate
# ---------------------------------------------------------------------------


class TestGenerate:
    """Tests for the full generate flow."""

    @pytest.mark.asyncio
    async def test_generate_posts_comment_and_persists(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, mock_prs = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        transcript = _make_transcript()

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            return_value=transcript,
        ):
            await gen.generate(
                issue_number=42, pr_number=101, issue=issue, diff=SAMPLE_DIFF
            )

        mock_prs.post_comment.assert_awaited_once()
        call_args = mock_prs.post_comment.call_args
        assert call_args[0][0] == 42  # issue number
        assert "Acceptance Criteria" in call_args[0][1]

        path = config.repo_root / ".hydraflow" / "verification" / "issue-42.md"
        assert path.exists()

    @pytest.mark.asyncio
    async def test_generate_dry_run_skips(
        self, dry_config: HydraFlowConfig, event_bus
    ) -> None:
        gen, mock_prs = _make_generator(dry_config, event_bus)
        issue = IssueFactory.create()

        await gen.generate(
            issue_number=42, pr_number=101, issue=issue, diff="some diff"
        )

        mock_prs.post_comment.assert_not_awaited()
        path = dry_config.repo_root / ".hydraflow" / "verification" / "issue-42.md"
        assert not path.exists()

    @pytest.mark.asyncio
    async def test_generate_handles_subprocess_failure(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, mock_prs = _make_generator(config, event_bus)
        issue = IssueFactory.create()

        with (
            patch(
                "acceptance_criteria.stream_claude_process",
                new_callable=AsyncMock,
                side_effect=RuntimeError("subprocess died"),
            ),
            pytest.raises(RuntimeError, match="subprocess died"),
        ):
            await gen.generate(
                issue_number=42,
                pr_number=101,
                issue=issue,
                diff=SAMPLE_DIFF,
            )

        mock_prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_no_markers_skips_posting(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, mock_prs = _make_generator(config, event_bus)
        issue = IssueFactory.create()

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            return_value="No markers in this output.",
        ):
            await gen.generate(
                issue_number=42, pr_number=101, issue=issue, diff=SAMPLE_DIFF
            )

        mock_prs.post_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_generate_reads_plan_file(
        self, config: HydraFlowConfig, event_bus
    ) -> None:
        gen, mock_prs = _make_generator(config, event_bus)
        issue = IssueFactory.create()

        # Write a plan file
        plan_dir = config.repo_root / ".hydraflow" / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        (plan_dir / "issue-42.md").write_text("## The Plan\nDo stuff.")

        captured_prompt = {}

        async def capture_prompt(**kwargs: object) -> str:
            captured_prompt["prompt"] = kwargs.get("prompt", "")
            return _make_transcript()

        with patch(
            "acceptance_criteria.stream_claude_process",
            side_effect=capture_prompt,
        ):
            await gen.generate(
                issue_number=42, pr_number=101, issue=issue, diff=SAMPLE_DIFF
            )

        assert "## The Plan" in captured_prompt["prompt"]
        assert "Do stuff." in captured_prompt["prompt"]


# ---------------------------------------------------------------------------
# _parse_precheck_transcript
# ---------------------------------------------------------------------------


class TestParsePrecheckTranscript:
    """Tests for AcceptanceCriteriaGenerator._parse_precheck_transcript."""

    def test_all_fields_present(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All looks good.\n"
        )
        risk, confidence, escalate, summary, parse_failed = (
            AcceptanceCriteriaGenerator._parse_precheck_transcript(transcript)
        )
        assert risk == "low"
        assert confidence == 0.95
        assert escalate is False
        assert summary == "All looks good."
        assert parse_failed is False

    def test_missing_risk_defaults_to_medium(self) -> None:
        transcript = (
            "PRECHECK_CONFIDENCE: 0.8\nPRECHECK_ESCALATE: no\nPRECHECK_SUMMARY: Fine.\n"
        )
        risk, _, _, _, parse_failed = (
            AcceptanceCriteriaGenerator._parse_precheck_transcript(transcript)
        )
        assert risk == "medium"
        assert parse_failed is True

    def test_missing_confidence_defaults_to_zero(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\nPRECHECK_ESCALATE: yes\nPRECHECK_SUMMARY: Risky.\n"
        )
        _, confidence, _, _, parse_failed = (
            AcceptanceCriteriaGenerator._parse_precheck_transcript(transcript)
        )
        assert confidence == 0.0
        assert parse_failed is True

    def test_escalate_yes(self) -> None:
        transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Needs debug.\n"
        )
        _, _, escalate, _, _ = AcceptanceCriteriaGenerator._parse_precheck_transcript(
            transcript
        )
        assert escalate is True

    def test_escalate_no(self) -> None:
        transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: OK.\n"
        )
        _, _, escalate, _, _ = AcceptanceCriteriaGenerator._parse_precheck_transcript(
            transcript
        )
        assert escalate is False

    def test_case_insensitive_parsing(self) -> None:
        transcript = (
            "precheck_risk: HIGH\n"
            "precheck_confidence: 0.42\n"
            "precheck_escalate: YES\n"
            "precheck_summary: Mixed case.\n"
        )
        risk, confidence, escalate, summary, parse_failed = (
            AcceptanceCriteriaGenerator._parse_precheck_transcript(transcript)
        )
        assert risk == "high"
        assert confidence == 0.42
        assert escalate is True
        assert summary == "Mixed case."
        assert parse_failed is False

    def test_empty_string_returns_defaults(self) -> None:
        risk, confidence, escalate, summary, parse_failed = (
            AcceptanceCriteriaGenerator._parse_precheck_transcript("")
        )
        assert risk == "medium"
        assert confidence == 0.0
        assert escalate is False
        assert summary == ""
        assert parse_failed is True


# ---------------------------------------------------------------------------
# _build_subskill_command / _build_debug_command
# ---------------------------------------------------------------------------


class TestBuildSubskillAndDebugCommands:
    """Tests for AC generator _build_subskill_command and _build_debug_command."""

    def test_subskill_command_uses_config_tool_and_model(
        self, config, event_bus
    ) -> None:
        gen, _ = _make_generator(config, event_bus)
        cmd = gen._build_subskill_command()
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "haiku"

    def test_subskill_command_codex_backend(self, event_bus) -> None:
        cfg = ConfigFactory.create(subskill_tool="codex", subskill_model="gpt-4")
        gen, _ = _make_generator(cfg, event_bus)
        cmd = gen._build_subskill_command()
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-4"

    def test_debug_command_uses_config_tool_and_model(self, config, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        cmd = gen._build_debug_command()
        assert "claude" in cmd
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "opus"

    def test_debug_command_codex_backend(self, event_bus) -> None:
        cfg = ConfigFactory.create(debug_tool="codex", debug_model="gpt-5")
        gen, _ = _make_generator(cfg, event_bus)
        cmd = gen._build_debug_command()
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert cmd[cmd.index("--model") + 1] == "gpt-5"


# ---------------------------------------------------------------------------
# _build_precheck_prompt
# ---------------------------------------------------------------------------


class TestBuildPrecheckPrompt:
    """Tests for AcceptanceCriteriaGenerator._build_precheck_prompt."""

    def test_includes_issue_and_diff_summary(self, config, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create(number=42, title="Fix the widget")
        prompt = gen._build_precheck_prompt(issue, 42, 101, "diff summary content")
        assert "#42" in prompt
        assert "#101" in prompt
        assert "Fix the widget" in prompt
        assert "diff summary content" in prompt

    def test_truncates_diff_summary_to_3000_chars(self, config, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        long_diff_summary = "x" * 5000
        prompt = gen._build_precheck_prompt(issue, 42, 101, long_diff_summary)
        assert "x" * 3000 in prompt
        assert "x" * 3001 not in prompt


# ---------------------------------------------------------------------------
# _run_precheck_context
# ---------------------------------------------------------------------------


class TestRunPrecheckContext:
    """Tests for AcceptanceCriteriaGenerator._run_precheck_context."""

    @pytest.mark.asyncio
    async def test_disabled_when_max_subskill_zero(self, config, event_bus) -> None:
        gen, _ = _make_generator(config, event_bus)
        issue = IssueFactory.create()
        result = await gen._run_precheck_context(issue, 42, 101, "diff summary", "")
        assert result == "Low-tier precheck disabled."

    @pytest.mark.asyncio
    async def test_success_no_escalation(self, event_bus, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            subskill_confidence_threshold=0.7,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.95\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: All clear.\n"
        )

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            return_value=valid_transcript,
        ) as mock_stream:
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert "Precheck risk: low" in result
        assert "Precheck confidence: 0.95" in result
        assert "Precheck summary: All clear." in result
        assert "Debug escalation: no" in result
        mock_stream.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_parse_failure(self, event_bus, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=3,
            debug_escalation_enabled=False,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        garbage = "No parseable fields here."
        valid_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: Finally parsed.\n"
        )

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            side_effect=[garbage, garbage, valid_transcript],
        ) as mock_stream:
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert mock_stream.call_count == 3
        assert "Precheck risk: low" in result
        assert "Precheck summary: Finally parsed." in result

    @pytest.mark.asyncio
    async def test_escalates_to_debug(self, event_bus, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky change.\n"
        )
        debug_transcript = "Debug: found critical issues."

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            side_effect=[high_risk_transcript, debug_transcript],
        ) as mock_stream:
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert mock_stream.call_count == 2
        assert "Precheck risk: high" in result
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" in result
        assert "Debug: found critical issues." in result
        assert "Escalation reasons:" in result

    @pytest.mark.asyncio
    async def test_no_debug_when_max_debug_zero(self, event_bus, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=0,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            return_value=high_risk_transcript,
        ) as mock_stream:
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert mock_stream.call_count == 1
        assert "Debug escalation: yes" in result
        assert "Debug precheck transcript:" not in result

    @pytest.mark.asyncio
    async def test_exception_returns_fallback(self, event_bus, tmp_path) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            side_effect=RuntimeError("subprocess crashed"),
        ):
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert (
            result == "Low-tier precheck failed; continuing without precheck context."
        )

    @pytest.mark.asyncio
    async def test_debug_transcript_truncated_to_1000_chars(
        self, event_bus, tmp_path
    ) -> None:
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            debug_escalation_enabled=True,
            max_debug_attempts=1,
            subskill_confidence_threshold=0.7,
            repo_root=tmp_path / "repo",
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        high_risk_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.3\n"
            "PRECHECK_ESCALATE: yes\n"
            "PRECHECK_SUMMARY: Risky.\n"
        )
        long_debug = "D" * 2000

        with patch(
            "acceptance_criteria.stream_claude_process",
            new_callable=AsyncMock,
            side_effect=[high_risk_transcript, long_debug],
        ):
            result = await gen._run_precheck_context(issue, 42, 101, "diff", "")

        assert "D" * 1000 in result
        assert "D" * 1001 not in result


# ---------------------------------------------------------------------------
# TestPrecheckHighRiskFiles
# ---------------------------------------------------------------------------


HIGH_RISK_DIFF = """\
diff --git a/src/auth/login.py b/src/auth/login.py
index abc123..def456 100644
--- a/src/auth/login.py
+++ b/src/auth/login.py
@@ -1,3 +1,8 @@
+def new_login():
+    pass
"""

SAFE_DIFF = """\
diff --git a/src/utils.py b/src/utils.py
index abc123..def456 100644
--- a/src/utils.py
+++ b/src/utils.py
@@ -1,3 +1,8 @@
+def helper():
+    pass
"""


class TestPrecheckHighRiskFiles:
    """Verify _run_precheck_context passes high_risk_files_touched correctly."""

    @pytest.mark.asyncio
    async def test_high_risk_diff_passes_true(self, event_bus) -> None:
        cfg = ConfigFactory.create(max_subskill_attempts=1)
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        precheck_transcript = (
            "PRECHECK_RISK: high\n"
            "PRECHECK_CONFIDENCE: 0.5\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: risky auth change\n"
        )

        with (
            patch(
                "acceptance_criteria.stream_claude_process",
                new_callable=AsyncMock,
                return_value=precheck_transcript,
            ),
            patch(
                "acceptance_criteria.should_escalate_debug",
                return_value=EscalationDecision(escalate=False, reasons=[]),
            ) as mock_escalate,
        ):
            await gen._run_precheck_context(issue, 42, 101, "summary", HIGH_RISK_DIFF)

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is True

    @pytest.mark.asyncio
    async def test_safe_diff_passes_false(self, event_bus) -> None:
        cfg = ConfigFactory.create(max_subskill_attempts=1)
        gen, _ = _make_generator(cfg, event_bus)
        issue = IssueFactory.create()

        precheck_transcript = (
            "PRECHECK_RISK: low\n"
            "PRECHECK_CONFIDENCE: 0.9\n"
            "PRECHECK_ESCALATE: no\n"
            "PRECHECK_SUMMARY: safe change\n"
        )

        with (
            patch(
                "acceptance_criteria.stream_claude_process",
                new_callable=AsyncMock,
                return_value=precheck_transcript,
            ),
            patch(
                "acceptance_criteria.should_escalate_debug",
                return_value=EscalationDecision(escalate=False, reasons=[]),
            ) as mock_escalate,
        ):
            await gen._run_precheck_context(issue, 42, 101, "summary", SAFE_DIFF)

        mock_escalate.assert_called_once()
        assert mock_escalate.call_args[1]["high_risk_files_touched"] is False
