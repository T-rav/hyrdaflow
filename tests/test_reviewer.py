"""Tests for dx/hydraflow/reviewer.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventType
from models import CodeScanningAlert, ReviewerStatus, ReviewVerdict
from reviewer import ReviewRunner
from tests.conftest import PRInfoFactory
from tests.helpers import ConfigFactory, make_streaming_proc


@pytest.fixture
def pr_info():
    return PRInfoFactory.create()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_runner(config, event_bus):
    return ReviewRunner(config=config, event_bus=event_bus)


@pytest.fixture
def task(issue):
    return issue.to_task()


# ---------------------------------------------------------------------------
# _build_command
# ---------------------------------------------------------------------------


def test_build_command_does_not_include_cwd(config, tmp_path):
    runner = _make_runner(config, None)
    cmd = runner._build_command(tmp_path)

    assert "--cwd" not in cmd


def test_build_command_accepts_none_workspace_path(config):
    """ReviewRunner._build_command accepts None since it doesn't use the path."""
    runner = _make_runner(config, None)
    cmd = runner._build_command(None)
    assert cmd[0] == "claude"


def test_build_command_includes_output_format(config, tmp_path):
    runner = _make_runner(config, None)
    cmd = runner._build_command(tmp_path)

    assert "--output-format" in cmd
    fmt_idx = cmd.index("--output-format")
    assert cmd[fmt_idx + 1] == "stream-json"


def test_build_command_supports_codex_backend(tmp_path):
    cfg = ConfigFactory.create(
        review_tool="codex",
        review_model="gpt-5-codex",
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    runner = _make_runner(cfg, None)
    cmd = runner._build_command(tmp_path)
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# _build_review_prompt_with_stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_review_prompt_includes_pr_number(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "some diff")

    assert f"#{pr_info.number}" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_issue_context(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "some diff")

    assert task.title in prompt
    assert task.body in prompt
    assert f"#{task.id}" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_arch_drift_checks(
    config, event_bus, pr_info, task
):
    """Reviewer prompt must ask for architectural-drift signals. This is the
    only general-purpose drift-prevention HydraFlow has on review now that
    the hardcoded static layer checker is gone; regressions in the prompt
    silently re-open the gap."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "some diff")

    assert "Architectural drift" in prompt, (
        "reviewer prompt no longer contains the Architectural drift bullet"
    )
    # Spot-check the three specific smells we care about.
    assert "Layer jumps" in prompt
    assert "Misplaced I/O" in prompt
    assert "God-file creep" in prompt
    # And the escape hatch for repos without recognisable architecture.
    assert "Escape hatch" in prompt
    assert "do not invent violations" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_hydraflow_principles_checks(
    config, event_bus, pr_info, task
):
    """Reviewer prompt must ask for HydraFlow-specific principle drift
    (ADR-0044). The architectural-drift bullet handles generic layer
    concerns; this bullet adds MockWorld scenario coverage, TDD + BDD
    test naming, Port compliance, and one-responsibility-per-file. These
    are the principles plans and PRs tend to skip first."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "some diff")

    assert "HydraFlow principles" in prompt, (
        "reviewer prompt no longer contains the HydraFlow principles bullet"
    )
    # MockWorld / scenario coverage for new cross-phase behaviour.
    assert "MockWorld" in prompt
    assert "tests/scenarios/" in prompt
    # TDD + BDD-flavour test naming.
    assert (
        "BDD" in prompt
        or "behavioural" in prompt.lower()
        or "behavioral" in prompt.lower()
    )
    # Hexagonal port compliance.
    assert "PRPort" in prompt or "IssueStorePort" in prompt or "WorkspacePort" in prompt
    # One-responsibility files.
    assert (
        "one responsibility" in prompt.lower()
        or "single responsibility" in prompt.lower()
    )


@pytest.mark.asyncio
async def test_build_review_prompt_includes_diff(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    diff = "diff --git a/foo.py b/foo.py\n+added line"
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, diff)

    assert diff in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_review_instructions(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "VERDICT" in prompt
    assert "SUMMARY" in prompt
    assert "APPROVE" in prompt
    assert "REQUEST_CHANGES" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_ui_criteria_when_diff_has_ui_files(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    diff = (
        "diff --git a/ui/src/components/Foo.jsx b/ui/src/components/Foo.jsx\n"
        "+import React from 'react';\n"
        "+export const Foo = () => <div>Hello</div>;\n"
    )
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, diff)

    assert "DRY" in prompt
    assert "Responsive" in prompt
    assert "Style consistency" in prompt
    assert "Component reuse" in prompt
    assert "theme.js" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_excludes_ui_criteria_when_no_ui_files(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    diff = "diff --git a/reviewer.py b/reviewer.py\n+# backend-only change\n"
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, diff)

    assert "DRY" not in prompt
    assert "theme.js" not in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_skips_local_tests_when_ci_enabled(
    event_bus, pr_info, task
):
    ci_config = ConfigFactory.create(max_ci_fix_attempts=2)
    runner = _make_runner(ci_config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Do NOT run `make lint`, `make test`, or `make quality`" in prompt
    assert "CI will verify" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_runs_local_tests_when_ci_disabled(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Run `make lint` and `make test`" in prompt
    assert "Do NOT run" not in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_fix_section_skips_tests_when_ci_enabled(
    event_bus, pr_info, task
):
    ci_config = ConfigFactory.create(max_ci_fix_attempts=1)
    runner = _make_runner(ci_config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Do NOT run tests locally" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_fix_section_runs_tests_when_ci_disabled(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "`make test`" in prompt


# ---------------------------------------------------------------------------
# _parse_verdict
# ---------------------------------------------------------------------------


def test_parse_verdict_approve(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "All looks good.\nVERDICT: APPROVE\nSUMMARY: looks good"
    verdict = runner._parse_verdict(transcript)
    assert verdict == ReviewVerdict.APPROVE


def test_parse_verdict_request_changes(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Issues found.\nVERDICT: REQUEST_CHANGES\nSUMMARY: needs work"
    verdict = runner._parse_verdict(transcript)
    assert verdict == ReviewVerdict.REQUEST_CHANGES


def test_parse_verdict_comment(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Minor notes.\nVERDICT: COMMENT\nSUMMARY: minor issues"
    verdict = runner._parse_verdict(transcript)
    assert verdict == ReviewVerdict.COMMENT


def test_parse_verdict_no_verdict_defaults_to_comment(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "This is a review without any verdict line at all."
    verdict = runner._parse_verdict(transcript)
    assert verdict == ReviewVerdict.COMMENT


def test_parse_verdict_case_insensitive(config, event_bus):
    runner = _make_runner(config, event_bus)

    transcript_lower = "verdict: approve\nsummary: lgtm"
    assert runner._parse_verdict(transcript_lower) == ReviewVerdict.APPROVE

    transcript_mixed = "Verdict: Request_Changes\nSummary: needs fixes"
    assert runner._parse_verdict(transcript_mixed) == ReviewVerdict.REQUEST_CHANGES

    transcript_upper = "VERDICT: COMMENT\nSUMMARY: minor"
    assert runner._parse_verdict(transcript_upper) == ReviewVerdict.COMMENT


# ---------------------------------------------------------------------------
# _extract_summary
# ---------------------------------------------------------------------------


def test_extract_summary_with_summary_line(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "Review done.\nVERDICT: APPROVE\nSUMMARY: looks good to me"
    summary = runner._extract_summary(transcript)
    assert summary == "looks good to me"


def test_extract_summary_case_insensitive(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "summary: everything checks out"
    summary = runner._extract_summary(transcript)
    assert summary == "everything checks out"


def test_extract_summary_strips_whitespace(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "SUMMARY:   extra spaces around this   "
    summary = runner._extract_summary(transcript)
    assert summary == "extra spaces around this"


def test_extract_summary_fallback_to_last_line(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "First line.\nSecond line.\nThis is the last line"
    summary = runner._extract_summary(transcript)
    assert summary == "This is the last line"


def test_extract_summary_fallback_ignores_empty_lines(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "First line.\nSecond line.\n\n   \n"
    summary = runner._extract_summary(transcript)
    assert summary == "Second line."


# ---------------------------------------------------------------------------
# _sanitize_summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "→ TaskOutput: {'task_id': 'abc123'}",
        "← Result: done",
        '{"task_id": "abc", "block": true}',
        "<div>Some output</div>",
        "```python",
        "Co-Authored-By: Claude <noreply@anthropic.com>",
        "Signed-off-by: Bot <bot@example.com>",
        "ok",
        "   short   ",
        "tokens: 12345",
        "cost: $0.05",
        "duration: 30s",
    ],
)
def test_sanitize_summary_rejects_invalid(config, event_bus, text):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "Implementation looks good, tests pass.",
            "Implementation looks good, tests pass.",
        ),
        ("   Clean summary text here   ", "Clean summary text here"),
        ("A" * 300, "A" * 200),
    ],
)
def test_sanitize_summary_accepts_valid(config, event_bus, text, expected):
    runner = _make_runner(config, event_bus)
    result = runner._sanitize_summary(text)
    assert result == expected


# ---------------------------------------------------------------------------
# _extract_summary — garbage-resistant fallback
# ---------------------------------------------------------------------------


def test_extract_summary_skips_tool_output_in_fallback(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = (
        "Good review line here.\n"
        "→ TaskOutput: {'task_id': 'a9d78cf47fcf6174b', 'block': True}\n"
    )
    summary = runner._extract_summary(transcript)
    assert summary == "Good review line here."
    assert "TaskOutput" not in summary


def test_extract_summary_skips_json_in_fallback(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = 'Review completed successfully.\n{"status": "done", "result": true}\n'
    summary = runner._extract_summary(transcript)
    assert summary == "Review completed successfully."


def test_extract_summary_returns_default_when_all_garbage(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = '→ Tool call\n{"json": true}\n```code```\nok\n'
    summary = runner._extract_summary(transcript)
    assert summary == "No summary provided"


def test_extract_summary_sanitizes_summary_marker_content(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "SUMMARY: → TaskOutput: {'task_id': 'abc'}\nGood fallback line here."
    summary = runner._extract_summary(transcript)
    # SUMMARY line is garbage, should fall back to clean line
    assert summary == "Good fallback line here."


def test_extract_summary_prefers_summary_marker_when_clean(config, event_bus):
    runner = _make_runner(config, event_bus)
    transcript = "SUMMARY: All checks pass, implementation is solid."
    summary = runner._extract_summary(transcript)
    assert summary == "All checks pass, implementation is solid."


# ---------------------------------------------------------------------------
# review - success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_success_path(config, event_bus, pr_info, task, tmp_path):
    runner = _make_runner(config, event_bus)
    transcript = (
        "All checks pass.\nVERDICT: APPROVE\nSUMMARY: Implementation looks good"
    )

    mock_execute = AsyncMock(return_value=transcript)
    mock_has_changes = AsyncMock(return_value=False)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff", worker_id=0)

    assert result.pr_number == pr_info.number
    assert result.issue_number == task.id
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.summary == "Implementation looks good"
    assert result.transcript == transcript
    assert result.fixes_made is False
    assert result.files_changed == []


@pytest.mark.asyncio
async def test_review_success_path_with_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = (
        "Found issues, fixed them.\nVERDICT: APPROVE\nSUMMARY: Fixed and approved"
    )

    mock_execute = AsyncMock(return_value=transcript)
    mock_has_changes = AsyncMock(return_value=True)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.pr_number == pr_info.number
    assert result.issue_number == task.id
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.summary == "Fixed and approved"
    assert result.transcript == transcript
    assert result.fixes_made is True
    assert result.files_changed == ["src/foo.py"]


# ---------------------------------------------------------------------------
# review - failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_failure_path_on_exception(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)

    mock_execute = AsyncMock(side_effect=RuntimeError("subprocess crashed"))

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.verdict == ReviewVerdict.COMMENT
    assert "Review failed" in result.summary
    assert "subprocess crashed" in result.summary


# ---------------------------------------------------------------------------
# review - dry_run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_dry_run_returns_auto_approved(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)
    mock_create = make_streaming_proc(returncode=0, stdout="")

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    mock_create.assert_not_called()
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.summary == "Dry-run: auto-approved"
    assert result.pr_number == pr_info.number


# ---------------------------------------------------------------------------
# _save_transcript
# ---------------------------------------------------------------------------


def test_save_transcript_writes_to_correct_path(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = ReviewRunner(config=cfg, event_bus=event_bus)
    transcript = "This is the review transcript."

    runner._save_transcript("review-pr", 42, transcript)

    expected_path = tmp_path / ".hydraflow" / "logs" / "review-pr-42.txt"
    assert expected_path.exists()
    assert expected_path.read_text() == transcript


def test_save_transcript_creates_log_directory(event_bus, tmp_path):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = ReviewRunner(config=cfg, event_bus=event_bus)
    log_dir = tmp_path / ".hydraflow" / "logs"
    assert not log_dir.exists()

    runner._save_transcript("review-pr", 7, "transcript content")

    assert log_dir.exists()
    assert log_dir.is_dir()


def test_save_transcript_handles_oserror(event_bus, tmp_path, caplog):
    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = ReviewRunner(config=cfg, event_bus=event_bus)

    with patch.object(Path, "write_text", side_effect=OSError("disk full")):
        runner._save_transcript("review-pr", 42, "transcript")  # should not raise

    assert "Could not save transcript" in caplog.text


# ---------------------------------------------------------------------------
# REVIEW_UPDATE events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_events_include_reviewer_role(
    config, event_bus, pr_info, task, tmp_path
):
    """REVIEW_UPDATE events should carry role='reviewer'."""
    runner = _make_runner(config, event_bus)
    transcript = "All good.\nVERDICT: APPROVE\nSUMMARY: Looks great"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.review(pr_info, task, tmp_path, "diff", worker_id=1)

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    assert len(review_events) >= 2
    for event in review_events:
        assert event.data.get("role") == "reviewer"


@pytest.mark.asyncio
async def test_dry_run_review_events_include_reviewer_role(
    dry_config, event_bus, pr_info, task, tmp_path
):
    """In dry-run mode, REVIEW_UPDATE events should still carry role='reviewer'."""
    runner = _make_runner(dry_config, event_bus)

    await runner.review(pr_info, task, tmp_path, "diff")

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    assert len(review_events) >= 1
    for event in review_events:
        assert event.data.get("role") == "reviewer"


@pytest.mark.asyncio
async def test_review_publishes_review_update_events(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "All good.\nVERDICT: APPROVE\nSUMMARY: Looks great"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.review(pr_info, task, tmp_path, "diff", worker_id=2)

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]

    # Should have at least two: one for "reviewing" and one for "done"
    assert len(review_events) >= 2

    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.REVIEWING.value in statuses
    assert ReviewerStatus.DONE.value in statuses


@pytest.mark.asyncio
async def test_review_start_event_includes_worker_id(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: ok"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.review(pr_info, task, tmp_path, "diff", worker_id=3)

    events = event_bus.get_history()
    reviewing_event = next(
        e
        for e in events
        if e.type == EventType.REVIEW_UPDATE
        and e.data.get("status") == ReviewerStatus.REVIEWING.value
    )
    assert reviewing_event.data["worker"] == 3
    assert reviewing_event.data["pr"] == pr_info.number
    assert reviewing_event.data["issue"] == task.id


@pytest.mark.asyncio
async def test_review_done_event_includes_verdict_and_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: REQUEST_CHANGES\nSUMMARY: needs work"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.review(pr_info, task, tmp_path, "diff")

    events = event_bus.get_history()
    done_event = next(
        e
        for e in events
        if e.type == EventType.REVIEW_UPDATE
        and e.data.get("status") == ReviewerStatus.DONE.value
    )
    assert done_event.data["verdict"] == ReviewVerdict.REQUEST_CHANGES.value
    assert "duration" in done_event.data


@pytest.mark.asyncio
async def test_review_dry_run_still_publishes_review_update_event(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    await runner.review(pr_info, task, tmp_path, "diff")

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    # The "reviewing" event is published before the dry-run check
    assert any(
        e.data.get("status") == ReviewerStatus.REVIEWING.value for e in review_events
    )


# ---------------------------------------------------------------------------
# _get_head_sha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_head_sha_returns_sha(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"abc123def456\n", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await runner._get_head_sha(tmp_path)

    assert result == "abc123def456"


@pytest.mark.asyncio
async def test_get_head_sha_returns_none_on_failure(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)
    mock_proc = AsyncMock()
    mock_proc.returncode = 128
    mock_proc.communicate = AsyncMock(return_value=(b"", b"fatal: not a git repo"))
    mock_create = AsyncMock(return_value=mock_proc)

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await runner._get_head_sha(tmp_path)

    assert result is None


@pytest.mark.asyncio
async def test_get_head_sha_returns_none_on_file_not_found(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)
    mock_create = AsyncMock(side_effect=FileNotFoundError("git not found"))

    with patch("asyncio.create_subprocess_exec", mock_create):
        result = await runner._get_head_sha(tmp_path)

    assert result is None


# ---------------------------------------------------------------------------
# _has_changes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_changes_true_when_head_moved(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)

    with patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is True


@pytest.mark.asyncio
async def test_has_changes_true_when_uncommitted_changes(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)
    # Same SHA (no new commits), but dirty working tree
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b" M foo.py\n", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is True


@pytest.mark.asyncio
async def test_has_changes_false_when_clean(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)
    # Same SHA and clean status
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is False


@pytest.mark.asyncio
async def test_has_changes_true_when_both_commits_and_dirty(
    config, event_bus, tmp_path
):
    runner = _make_runner(config, event_bus)
    # HEAD moved — should return True immediately without checking status

    with patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is True


@pytest.mark.asyncio
async def test_has_changes_false_on_file_not_found(config, event_bus, tmp_path):
    runner = _make_runner(config, event_bus)

    with patch.object(
        runner, "_get_head_sha", AsyncMock(side_effect=FileNotFoundError)
    ):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is False


@pytest.mark.asyncio
async def test_has_changes_true_when_before_sha_none_and_dirty(
    config, event_bus, tmp_path
):
    runner = _make_runner(config, event_bus)
    # before_sha is None (e.g., empty repo) — falls through to status check
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"?? new_file.py\n", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await runner._has_changes(tmp_path, before_sha=None)

    assert result is True


@pytest.mark.asyncio
async def test_has_changes_false_when_before_sha_none_and_clean(
    config, event_bus, tmp_path
):
    runner = _make_runner(config, event_bus)
    # before_sha is None, clean status
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"", b""))
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch("asyncio.create_subprocess_exec", mock_create),
    ):
        result = await runner._has_changes(tmp_path, before_sha=None)

    assert result is False


# ---------------------------------------------------------------------------
# _get_commit_stat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_commit_stat_returns_stat_output(config, event_bus, tmp_path):
    """_get_commit_stat returns the git diff --stat output on success."""
    runner = _make_runner(config, event_bus)
    stat_output = " src/foo.py | 3 ++-\n 1 file changed, 2 insertions(+), 1 deletion(-)"

    mock_result = AsyncMock()
    mock_result.returncode = 0
    mock_result.stdout = stat_output

    with patch.object(
        runner._runner, "run_simple", AsyncMock(return_value=mock_result)
    ):
        result = await runner._get_commit_stat(tmp_path)

    assert result == stat_output.strip()


@pytest.mark.asyncio
async def test_get_commit_stat_returns_empty_on_failure(config, event_bus, tmp_path):
    """_get_commit_stat returns empty string when git command fails."""
    runner = _make_runner(config, event_bus)

    mock_result = AsyncMock()
    mock_result.returncode = 1
    mock_result.stdout = ""

    with patch.object(
        runner._runner, "run_simple", AsyncMock(return_value=mock_result)
    ):
        result = await runner._get_commit_stat(tmp_path)

    assert result == ""


@pytest.mark.asyncio
async def test_get_commit_stat_returns_empty_on_timeout(config, event_bus, tmp_path):
    """_get_commit_stat returns empty string on timeout."""
    runner = _make_runner(config, event_bus)

    with patch.object(
        runner._runner, "run_simple", AsyncMock(side_effect=TimeoutError)
    ):
        result = await runner._get_commit_stat(tmp_path)

    assert result == ""


@pytest.mark.asyncio
async def test_get_commit_stat_returns_empty_on_file_not_found(
    config, event_bus, tmp_path
):
    """_get_commit_stat returns empty string on FileNotFoundError."""
    runner = _make_runner(config, event_bus)

    with patch.object(
        runner._runner, "run_simple", AsyncMock(side_effect=FileNotFoundError)
    ):
        result = await runner._get_commit_stat(tmp_path)

    assert result == ""


@pytest.mark.asyncio
async def test_get_commit_stat_returns_empty_when_no_stdout(
    config, event_bus, tmp_path
):
    """_get_commit_stat returns empty string when stdout is empty."""
    runner = _make_runner(config, event_bus)

    mock_result = AsyncMock()
    mock_result.returncode = 0
    mock_result.stdout = ""

    with patch.object(
        runner._runner, "run_simple", AsyncMock(return_value=mock_result)
    ):
        result = await runner._get_commit_stat(tmp_path)

    assert result == ""


@pytest.mark.asyncio
async def test_get_commit_stat_uses_before_sha_range(config, event_bus, tmp_path):
    """_get_commit_stat passes 'before_sha..HEAD' when before_sha is provided."""
    runner = _make_runner(config, event_bus)
    stat_output = " src/foo.py | 2 +-\n 1 file changed"

    mock_result = AsyncMock()
    mock_result.returncode = 0
    mock_result.stdout = stat_output

    mock_run_simple = AsyncMock(return_value=mock_result)
    with patch.object(runner._runner, "run_simple", mock_run_simple):
        result = await runner._get_commit_stat(tmp_path, before_sha="abc123")

    assert result == stat_output.strip()
    called_args = mock_run_simple.call_args[0][0]
    assert "abc123..HEAD" in called_args


@pytest.mark.asyncio
async def test_get_commit_stat_falls_back_to_head1_without_before_sha(
    config, event_bus, tmp_path
):
    """_get_commit_stat uses HEAD~1 when before_sha is not provided."""
    runner = _make_runner(config, event_bus)

    mock_result = AsyncMock()
    mock_result.returncode = 0
    mock_result.stdout = " src/foo.py | 1 +\n 1 file changed"

    mock_run_simple = AsyncMock(return_value=mock_result)
    with patch.object(runner._runner, "run_simple", mock_run_simple):
        await runner._get_commit_stat(tmp_path)

    called_args = mock_run_simple.call_args[0][0]
    assert "HEAD~1" in called_args


# ---------------------------------------------------------------------------
# Warning path: fixes_made=True but files_changed=[]
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_logs_warning_when_fixes_made_but_no_committed_files(
    config, event_bus, pr_info, task, tmp_path
):
    """review() warns when fixes_made is True but no committed file changes are detected."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Fixed it"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_save_transcript"),
        patch("reviewer.logger") as mock_logger,
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    mock_logger.warning.assert_called_once()
    assert result.fixes_made is True
    assert result.files_changed == []
    assert result.commit_stat == ""


# ---------------------------------------------------------------------------
# commit_stat populated in review/fix_ci/fix_review_findings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_populates_commit_stat_when_fixes_made(
    config, event_bus, pr_info, task, tmp_path
):
    """review() should populate commit_stat when fixes_made is True."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: All good"
    stat = " src/foo.py | 2 +-\n 1 file changed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value=stat)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.fixes_made is True
    assert result.files_changed == ["src/foo.py"]
    assert result.commit_stat == stat


@pytest.mark.asyncio
async def test_review_commit_stat_empty_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """review() should leave commit_stat empty when no fixes were made."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Looks good"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.fixes_made is False
    assert result.commit_stat == ""


@pytest.mark.asyncio
async def test_fix_ci_populates_commit_stat_when_fixes_made(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() should populate commit_stat when fixes_made is True."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed lint.\nVERDICT: APPROVE\nSUMMARY: Fixed CI"
    stat = " src/bar.py | 5 ++---\n 1 file changed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/bar.py"])
        ),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value=stat)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(
            pr_info, task, tmp_path, "Failed: ci", attempt=1, worker_id=0
        )

    assert result.fixes_made is True
    assert result.files_changed == ["src/bar.py"]
    assert result.commit_stat == stat


@pytest.mark.asyncio
async def test_fix_ci_commit_stat_empty_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() should leave commit_stat empty when no fixes were made."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: CI passed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(
            pr_info, task, tmp_path, "Failed: ci", attempt=1, worker_id=0
        )

    assert result.fixes_made is False
    assert result.commit_stat == ""


@pytest.mark.asyncio
async def test_fix_review_findings_populates_commit_stat_when_fixes_made(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() should populate commit_stat when fixes_made is True."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed review.\nVERDICT: APPROVE\nSUMMARY: Addressed feedback"
    stat = " src/baz.py | 1 +\n 1 file changed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/baz.py"])
        ),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value=stat)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Please fix null check"
        )

    assert result.fixes_made is True
    assert result.files_changed == ["src/baz.py"]
    assert result.commit_stat == stat


@pytest.mark.asyncio
async def test_fix_review_findings_commit_stat_empty_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() should leave commit_stat empty when no fixes were made."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Already looks good"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Please fix null check"
        )

    assert result.fixes_made is False
    assert result.commit_stat == ""


# ---------------------------------------------------------------------------
# terminate
# ---------------------------------------------------------------------------


def test_terminate_kills_active_processes(config, event_bus):
    runner = _make_runner(config, event_bus)
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    runner._active_procs.add(mock_proc)

    with patch("runner_utils.os.killpg") as mock_killpg:
        runner.terminate()

    mock_killpg.assert_called_once()


def test_terminate_handles_process_lookup_error(config, event_bus):
    runner = _make_runner(config, event_bus)
    mock_proc = MagicMock()
    mock_proc.pid = 12345
    runner._active_procs.add(mock_proc)

    with patch("runner_utils.os.killpg", side_effect=ProcessLookupError) as mock_killpg:
        runner.terminate()  # Should not raise
    mock_killpg.assert_called_once()


def test_terminate_with_no_active_processes(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert len(runner._active_procs) == 0
    runner.terminate()  # Should not raise


# ---------------------------------------------------------------------------
# _execute
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_execute_returns_transcript(config, event_bus, pr_info, tmp_path):
    runner = _make_runner(config, event_bus)
    expected_output = "VERDICT: APPROVE\nSUMMARY: looks good"
    mock_create = make_streaming_proc(returncode=0, stdout=expected_output)

    with patch("asyncio.create_subprocess_exec", mock_create):
        transcript = await runner._execute(
            ["claude", "-p"],
            "review prompt",
            tmp_path,
            {"pr": pr_info.number, "source": "reviewer"},
        )

    assert transcript == expected_output


@pytest.mark.asyncio
async def test_execute_publishes_transcript_line_events(
    config, event_bus, pr_info, tmp_path
):
    runner = _make_runner(config, event_bus)
    output = "Line one\nLine two\nLine three"
    mock_create = make_streaming_proc(returncode=0, stdout=output)

    with patch("asyncio.create_subprocess_exec", mock_create):
        await runner._execute(
            ["claude", "-p"],
            "prompt",
            tmp_path,
            {"pr": pr_info.number, "source": "reviewer"},
        )

    events = event_bus.get_history()
    transcript_events = [e for e in events if e.type == EventType.TRANSCRIPT_LINE]
    assert len(transcript_events) == 3
    lines = [e.data["line"] for e in transcript_events]
    assert "Line one" in lines
    assert "Line two" in lines
    assert "Line three" in lines
    # All events should carry the correct pr number and source
    for ev in transcript_events:
        assert ev.data["pr"] == pr_info.number
        assert ev.data["source"] == "reviewer"


@pytest.mark.asyncio
async def test_execute_uses_large_stream_limit(config, event_bus, pr_info, tmp_path):
    """_execute should set limit=1MB to handle large stream-json lines."""
    runner = _make_runner(config, event_bus)
    mock_create = make_streaming_proc(returncode=0, stdout="ok")

    with patch("asyncio.create_subprocess_exec", mock_create) as mock_exec:
        await runner._execute(
            ["claude", "-p"],
            "prompt",
            tmp_path,
            {"pr": pr_info.number, "source": "reviewer"},
        )

    kwargs = mock_exec.call_args[1]
    assert kwargs["limit"] == 1024 * 1024


# ---------------------------------------------------------------------------
# _build_ci_fix_prompt
# ---------------------------------------------------------------------------


def test_build_ci_fix_prompt_includes_failure_summary(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    prompt, _stats = runner._build_ci_fix_prompt(
        pr_info, task, "Failed checks: ci, lint", 1
    )

    assert "Failed checks: ci, lint" in prompt


def test_build_ci_fix_prompt_includes_pr_and_issue_context(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt, _stats = runner._build_ci_fix_prompt(pr_info, task, "CI failed", 2)

    assert f"#{pr_info.number}" in prompt
    assert f"#{task.id}" in prompt
    assert task.title in prompt
    assert "Attempt 2" in prompt


def test_build_ci_fix_prompt_uses_configured_test_command(event_bus, pr_info, task):
    """CI fix prompt should use the configured test_command."""
    cfg = ConfigFactory.create(test_command="npm test")
    runner = _make_runner(cfg, event_bus)
    prompt, _stats = runner._build_ci_fix_prompt(pr_info, task, "CI failed", 1)

    assert "`npm test`" in prompt
    assert "make test-fast" not in prompt


# ---------------------------------------------------------------------------
# fix_ci — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_success_path(config, event_bus, pr_info, task, tmp_path):
    runner = _make_runner(config, event_bus)
    transcript = "Fixed lint.\nVERDICT: APPROVE\nSUMMARY: Fixed CI failures"

    mock_execute = AsyncMock(return_value=transcript)
    mock_has_changes = AsyncMock(return_value=True)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(
            pr_info, task, tmp_path, "Failed: ci", attempt=1, worker_id=0
        )

    assert result.pr_number == pr_info.number
    assert result.issue_number == task.id
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.fixes_made is True
    assert result.summary == "Fixed CI failures"
    assert result.transcript == transcript
    assert result.files_changed == ["src/foo.py"]


# ---------------------------------------------------------------------------
# fix_ci — failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_failure_path(config, event_bus, pr_info, task, tmp_path):
    runner = _make_runner(config, event_bus)

    mock_execute = AsyncMock(side_effect=RuntimeError("agent crashed"))

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert "CI fix failed" in result.summary


# ---------------------------------------------------------------------------
# fix_ci — dry-run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_dry_run_returns_auto_approved(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.verdict == ReviewVerdict.APPROVE
    assert "Dry-run" in result.summary


# ---------------------------------------------------------------------------
# fix_ci — CI_CHECK events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_publishes_ci_check_events(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    events = event_bus.get_history()
    ci_events = [e for e in events if e.type == EventType.CI_CHECK]
    assert len(ci_events) >= 2
    statuses = [e.data["status"] for e in ci_events]
    assert ReviewerStatus.FIXING.value in statuses
    assert ReviewerStatus.FIX_DONE.value in statuses


# ---------------------------------------------------------------------------
# duration_seconds recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_success_records_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: looks good"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    assert result.duration_seconds > 0


@pytest.mark.asyncio
async def test_review_dry_run_records_duration(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    result = await runner.review(pr_info, task, tmp_path, "diff")

    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_review_failure_records_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    assert result.duration_seconds > 0


@pytest.mark.asyncio
async def test_fix_ci_records_duration(config, event_bus, pr_info, task, tmp_path):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.duration_seconds > 0


@pytest.mark.asyncio
async def test_fix_ci_dry_run_records_duration(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_fix_ci_failure_records_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.duration_seconds > 0


# ---------------------------------------------------------------------------
# Reviewer diff truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_review_prompt_truncates_long_diff_with_warning(
    config, event_bus, pr_info, task
):
    """Large diffs should be summarized/truncated with a note."""
    runner = _make_runner(config, event_bus)
    long_diff = "x" * 20_000
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, long_diff)

    assert "### Diff Summary" in prompt
    assert "### Diff Excerpts" in prompt
    assert "x" * 20_000 not in prompt
    assert "Diff truncated" in prompt
    assert "review may be incomplete" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_preserves_short_diff(
    config, event_bus, pr_info, task
):
    """Diff under max_review_diff_chars should pass through unchanged."""
    runner = _make_runner(config, event_bus)
    short_diff = "diff --git a/foo.py\n+added line"
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, short_diff)

    assert short_diff in prompt
    assert "Diff truncated" not in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_diff_truncation_configurable(
    event_bus, pr_info, task
):
    """Configured max_review_diff_chars should appear in truncation note."""
    cfg = ConfigFactory.create(max_review_diff_chars=5_000)
    runner = _make_runner(cfg, event_bus)
    diff = "x" * 10_000
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, diff)

    assert "### Diff Summary" in prompt
    assert "x" * 10_000 not in prompt
    assert "5,000 chars" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_logs_warning_on_truncation(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    long_diff = "x" * 20_000

    with patch("reviewer.logger") as mock_logger:
        await runner._build_review_prompt_with_stats(pr_info, task, long_diff)

    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Reviewer test_command configuration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_review_prompt_uses_configured_test_command(
    event_bus, pr_info, task
):
    """Reviewer prompt should use the configured test_command."""
    cfg = ConfigFactory.create(test_command="npm test", max_ci_fix_attempts=0)
    runner = _make_runner(cfg, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "`npm test`" in prompt
    assert "make test-fast" not in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_no_make_test_fast(config, event_bus, pr_info, task):
    """Reviewer prompt should not reference make test-fast anywhere."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "make test-fast" not in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_test_coverage_audit(
    config, event_bus, pr_info, task
):
    """Reviewer prompt should include expanded test coverage audit criteria."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Test coverage audit" in prompt
    assert "issue requirements" in prompt
    assert "dead code" in prompt
    assert "Failure and error paths" in prompt
    assert "New branches/conditions" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_redundant_guard_audit(
    config, event_bus, pr_info, task
):
    """Reviewer prompt must remind reviewers to flag redundant guard chains."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    audits_index = prompt.index("Run project audits on changed code:")
    guard_index = prompt.index("redundant guard conditions in if/elif chains")
    merge_index = prompt.index("Merge-artifact check")

    assert guard_index > audits_index
    assert guard_index < merge_index


@pytest.mark.asyncio
async def test_build_review_prompt_includes_scope_creep_check(
    config, event_bus, pr_info, task
):
    """Reviewer prompt must instruct mandatory scope check to catch unrelated changes."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Scope check" in prompt
    assert "scope creep" in prompt
    assert "unrelated" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_includes_post_commit_scope_creep_verification(
    config, event_bus, pr_info, task
):
    """Reviewer prompt must require git diff --stat verification after commits (scope-creep removal still mentioned)."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")

    assert "Post-commit verification" in prompt
    assert "git diff --stat HEAD~1" in prompt
    assert "scope-creep removal" in prompt.lower()


@pytest.mark.asyncio
async def test_build_review_prompt_stat_verification_for_each_commit(
    config, event_bus, pr_info, task
):
    """Review prompt must require stat verification for each commit, not just scope-creep."""
    runner = _make_runner(config, event_bus)
    prompt, _ = await runner._build_review_prompt_with_stats(pr_info, task, "diff")
    lower = prompt.lower()

    assert "git diff --stat head~1" in lower
    assert "verify your commit" in lower
    assert "intended file appears" in lower
    assert "after each commit" in lower


# ---------------------------------------------------------------------------
# _get_head_sha — timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_head_sha_timeout_returns_none(config, event_bus, tmp_path):
    """_get_head_sha should return None when git rev-parse times out."""
    runner = _make_runner(config, event_bus)
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.kill = MagicMock()
    mock_proc.wait = AsyncMock()
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch("asyncio.create_subprocess_exec", mock_create),
        patch("asyncio.wait_for", side_effect=TimeoutError),
    ):
        result = await runner._get_head_sha(tmp_path)

    assert result is None
    mock_proc.kill.assert_called_once()
    mock_proc.wait.assert_awaited_once()


# ---------------------------------------------------------------------------
# _has_changes — timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_changes_timeout_returns_false(config, event_bus, tmp_path):
    """_has_changes should return False when git status times out."""
    runner = _make_runner(config, event_bus)
    # Same SHA so it falls through to git status check
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError)
    mock_create = AsyncMock(return_value=mock_proc)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch("asyncio.create_subprocess_exec", mock_create),
        patch("asyncio.wait_for", side_effect=TimeoutError),
    ):
        result = await runner._has_changes(tmp_path, before_sha="abc123")

    assert result is False


# ---------------------------------------------------------------------------
# _record_fix_outcome
# ---------------------------------------------------------------------------


class TestRecordFixOutcome:
    @pytest.fixture
    def runner(self, config, event_bus):
        return _make_runner(config, event_bus)

    @pytest.fixture
    def result(self):
        from models import ReviewResult

        return ReviewResult(pr_number=42, issue_number=7)

    @pytest.mark.asyncio
    async def test_populates_fields_when_changes_committed(
        self, runner, result, tmp_path
    ) -> None:
        """_record_fix_outcome populates files_changed, fixes_made, commit_stat,
        and sets success=True when the agent made committed changes."""
        with (
            patch.object(
                runner,
                "_get_changed_files",
                AsyncMock(return_value=["src/foo.py", "src/bar.py"]),
            ),
            patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
            patch.object(
                runner,
                "_get_commit_stat",
                AsyncMock(return_value=" 2 files changed, 10 insertions(+)"),
            ),
            patch.object(runner, "_save_transcript"),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                "abc123",
                "transcript text",
                transcript_prefix="review-pr",
                label="CI fix",
            )

        assert result.files_changed == ["src/foo.py", "src/bar.py"]
        assert result.fixes_made is True
        assert result.commit_stat == " 2 files changed, 10 insertions(+)"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_success_true_no_commit_stat_when_no_fixes(
        self, runner, result, tmp_path
    ) -> None:
        """_record_fix_outcome sets success=True and leaves commit_stat empty
        when no fixes were made."""
        with (
            patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
            patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
            patch.object(runner, "_save_transcript"),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                "abc123",
                "transcript text",
                transcript_prefix="review-pr",
                label="Review fix",
            )

        assert result.success is True
        assert result.commit_stat == ""
        assert result.fixes_made is False

    @pytest.mark.asyncio
    async def test_logs_warning_when_fixes_made_but_no_files(
        self, runner, result, tmp_path, caplog
    ) -> None:
        """_record_fix_outcome logs a warning when fixes_made is True but
        files_changed is empty."""
        import logging

        caplog.set_level(logging.WARNING, logger="hydraflow.reviewer")
        with (
            patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
            patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
            patch.object(runner, "_save_transcript"),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                "abc123",
                "transcript text",
                transcript_prefix="review-pr",
                label="Review fix",
            )

        assert result.success is True
        assert any(
            "fixes_made is True but no committed file changes" in r.message
            for r in caplog.records
            if r.levelname == "WARNING"
        )

    @pytest.mark.asyncio
    async def test_calls_save_transcript_with_prefix_and_pr(
        self, runner, result, tmp_path
    ) -> None:
        """_record_fix_outcome calls _save_transcript with the provided
        transcript_prefix and pr_number."""
        mock_save = MagicMock()
        with (
            patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
            patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
            patch.object(runner, "_save_transcript", mock_save),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                "abc123",
                "my transcript",
                transcript_prefix="review-fix",
                label="Review-fix",
            )

        mock_save.assert_called_once_with("review-fix", 42, "my transcript")

    @pytest.mark.asyncio
    async def test_label_appears_in_info_log(
        self, runner, result, tmp_path, caplog
    ) -> None:
        """_record_fix_outcome passes the label parameter into the info log
        message."""
        import logging

        caplog.set_level(logging.INFO, logger="hydraflow.reviewer")
        with (
            patch.object(
                runner,
                "_get_changed_files",
                AsyncMock(return_value=["src/a.py"]),
            ),
            patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
            patch.object(runner, "_get_commit_stat", AsyncMock(return_value="stat")),
            patch.object(runner, "_save_transcript"),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                "abc123",
                "transcript",
                transcript_prefix="review-pr",
                label="CI fix",
            )

        assert any(
            "CI fix" in r.message and "PR #42" in r.message
            for r in caplog.records
            if r.levelname == "INFO"
        )

    @pytest.mark.asyncio
    async def test_before_sha_none_skips_commit_stat(
        self, runner, result, tmp_path
    ) -> None:
        """_record_fix_outcome with before_sha=None still sets success=True.

        _get_changed_files returns [] immediately for None before_sha;
        _has_changes only checks uncommitted changes (no SHA comparison).
        """
        with (
            patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
            patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
            patch.object(runner, "_save_transcript"),
        ):
            await runner._record_fix_outcome(
                result,
                tmp_path,
                None,
                "transcript text",
                transcript_prefix="review-pr",
                label="Review fix",
            )

        assert result.success is True
        assert result.commit_stat == ""
        assert result.files_changed == []


# ---------------------------------------------------------------------------
# _build_precheck_prompt
# ---------------------------------------------------------------------------


class TestBuildPrecheckPrompt:
    def test_includes_pr_and_issue_info(self, config, event_bus, pr_info, task) -> None:
        runner = _make_runner(config, event_bus)
        prompt = runner._build_precheck_prompt(pr_info, task, "some diff content")
        assert f"#{pr_info.number}" in prompt
        assert f"#{task.id}" in prompt
        assert task.title in prompt
        assert "some diff content" in prompt

    def test_truncates_diff_to_3000_chars(
        self, config, event_bus, pr_info, task
    ) -> None:
        runner = _make_runner(config, event_bus)
        long_diff = "x" * 10_000
        prompt = runner._build_precheck_prompt(pr_info, task, long_diff)
        # Should contain at most 3000 x's
        assert "x" * 3000 in prompt
        assert "x" * 3001 not in prompt

    def test_short_diff_not_truncated(self, config, event_bus, pr_info, task) -> None:
        runner = _make_runner(config, event_bus)
        short_diff = "x" * 100
        prompt = runner._build_precheck_prompt(pr_info, task, short_diff)
        assert "x" * 100 in prompt


# ---------------------------------------------------------------------------
# _run_precheck_context (wiring tests — shared logic tested in test_precheck.py)
# ---------------------------------------------------------------------------


class TestRunPrecheckContext:
    @pytest.mark.asyncio
    async def test_delegates_to_shared_run_precheck_context(
        self, config, event_bus, pr_info, task, tmp_path
    ) -> None:
        """Verify ReviewRunner delegates to the shared precheck module."""
        runner = _make_runner(config, event_bus)

        with patch(
            "reviewer.run_precheck_context",
            new_callable=AsyncMock,
            return_value="Precheck risk: low",
        ) as mock_rpc:
            result = await runner._run_precheck_context(pr_info, task, "diff", tmp_path)

        mock_rpc.assert_awaited_once()
        assert result == "Precheck risk: low"
        call_kwargs = mock_rpc.call_args[1]
        assert call_kwargs["config"] is runner._config
        assert "root causes" in call_kwargs["debug_message"]

    @pytest.mark.asyncio
    async def test_execute_closure_calls_self_execute(
        self, event_bus, pr_info, task, tmp_path
    ) -> None:
        """Verify the execute closure wires through to self._execute."""
        cfg = ConfigFactory.create(
            max_subskill_attempts=1,
            repo_root=tmp_path / "repo",
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        runner = _make_runner(cfg, event_bus)

        captured_execute = {}

        async def capture_rpc(**kwargs):
            captured_execute["fn"] = kwargs["execute"]
            return "Precheck risk: low"

        with patch(
            "reviewer.run_precheck_context",
            side_effect=capture_rpc,
        ):
            await runner._run_precheck_context(pr_info, task, "diff", tmp_path)

        # Call the captured execute closure
        mock_self_execute = AsyncMock(return_value="transcript")
        with patch.object(runner, "_execute", mock_self_execute):
            result = await captured_execute["fn"](["cmd"], "prompt")

        assert result == "transcript"
        call_kwargs = mock_self_execute.call_args
        assert call_kwargs is not None
        telemetry = call_kwargs.kwargs["telemetry_stats"]
        expected_before = len(task.body or "") + len("diff")
        expected_after = len("prompt")
        assert telemetry["context_chars_before"] == expected_before
        assert telemetry["context_chars_after"] == expected_after
        assert telemetry["pruned_chars_total"] == expected_before - expected_after


# ---------------------------------------------------------------------------
# _build_ci_fix_prompt — CI log injection
# ---------------------------------------------------------------------------


def test_build_ci_fix_prompt_includes_ci_logs_when_provided(config, event_bus):
    """Prompt should include Full CI Failure Logs section when ci_logs is provided."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _stats = runner._build_ci_fix_prompt(
        pr, issue, "Failed checks: Build", attempt=1, ci_logs="Error in main.py:42"
    )

    assert "## Full CI Failure Logs" in prompt
    assert "Error in main.py:42" in prompt


def test_build_ci_fix_prompt_excludes_ci_logs_when_empty(config, event_bus):
    """Prompt should NOT include CI logs section when ci_logs is empty."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _stats = runner._build_ci_fix_prompt(
        pr, issue, "Failed checks: Build", attempt=1
    )

    assert "## Full CI Failure Logs" not in prompt


def test_build_ci_fix_prompt_truncates_large_ci_logs(config, event_bus):
    """Large CI logs are truncated and counted in pruning stats."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()
    logs = "E" * (runner._config.max_ci_log_prompt_chars + 200)

    prompt, stats = runner._build_ci_fix_prompt(
        pr, issue, "Failed checks: Build", attempt=1, ci_logs=logs
    )

    assert "truncated from" in prompt
    assert int(stats["pruned_chars_total"]) > 0


# ---------------------------------------------------------------------------
# _build_review_prompt_with_stats — runtime log injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_review_prompt_includes_runtime_logs_when_enabled(
    tmp_path, event_bus
):
    """Review prompt includes Runtime Logs section when enabled and logs exist."""
    from tests.conftest import PRInfoFactory, TaskFactory

    config = ConfigFactory.create(
        repo_root=tmp_path,
    )
    log_dir = tmp_path / ".hydraflow" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "hydraflow.log").write_text("INFO: ok\nERROR: failed\n")

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _ = await runner._build_review_prompt_with_stats(
        pr, issue, "diff --git a/foo.py"
    )

    assert "## Recent Application Logs" in prompt
    assert "ERROR: failed" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_excludes_runtime_logs_when_disabled(
    config, event_bus
):
    """Review prompt does NOT include runtime logs when disabled."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _ = await runner._build_review_prompt_with_stats(
        pr, issue, "diff --git a/foo.py"
    )

    assert "## Recent Application Logs" not in prompt


# ---------------------------------------------------------------------------
# _format_code_scanning_alerts
# ---------------------------------------------------------------------------


class TestFormatCodeScanningAlerts:
    def test_empty_alerts_returns_empty_string(self):
        assert ReviewRunner._format_code_scanning_alerts([], 6000) == ""

    def test_formats_single_alert(self):
        alerts = [
            CodeScanningAlert(
                severity="error",
                security_severity="high",
                path="src/db.js",
                start_line=42,
                rule="js/sql-injection",
                message="SQL injection vulnerability",
            )
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "[HIGH]" in result
        assert "src/db.js:42" in result
        assert "js/sql-injection" in result
        assert "SQL injection vulnerability" in result

    def test_uses_severity_when_no_security_severity(self):
        alerts = [
            CodeScanningAlert(
                severity="warning",
                security_severity=None,
                path="foo.py",
                start_line=10,
                rule="py/unused-import",
                message="",
            )
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "[WARNING]" in result

    def test_truncates_at_max_chars(self):
        alerts = [
            CodeScanningAlert(
                severity="error",
                path=f"src/file{i}.py",
                start_line=i,
                rule=f"rule-{i}",
                message=f"Alert message {i}",
            )
            for i in range(100)
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 200)
        assert "truncated" in result
        assert "Showing" in result
        assert "100 alerts" in result

    def test_truncation_includes_gh_command(self):
        alerts = [
            CodeScanningAlert(
                severity="error",
                path=f"src/file{i}.py",
                start_line=i,
                rule=f"rule-{i}",
                message="x" * 50,
            )
            for i in range(100)
        ]
        result = ReviewRunner._format_code_scanning_alerts(
            alerts, 200, repo="org/repo", branch="main"
        )
        assert "gh api repos/org/repo/code-scanning/alerts" in result

    def test_truncation_without_repo_uses_empty_interpolation(self):
        alerts = [
            CodeScanningAlert(
                severity="error",
                path=f"src/file{i}.py",
                start_line=i,
                rule=f"rule-{i}",
                message="x" * 50,
            )
            for i in range(100)
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 200)
        assert "truncated" in result
        assert "gh api repos/" in result

    def test_no_truncation_within_limit(self):
        alerts = [
            CodeScanningAlert(
                severity="error",
                path="foo.py",
                start_line=1,
                rule="test-rule",
                message="msg",
            )
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "truncated" not in result


# ---------------------------------------------------------------------------
# _build_review_prompt_with_stats — code scanning alerts injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_review_prompt_includes_code_scanning_alerts(config, event_bus):
    """Review prompt includes Code Scanning Alerts section when provided."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()
    alerts = [
        CodeScanningAlert(
            severity="error",
            security_severity="high",
            path="src/db.js",
            start_line=42,
            rule="js/sql-injection",
            message="SQL injection",
        )
    ]

    prompt, _ = await runner._build_review_prompt_with_stats(
        pr,
        issue,
        "diff --git a/foo.py",
        code_scanning_alerts=alerts,
    )

    assert "## Code Scanning Alerts" in prompt
    assert "src/db.js:42" in prompt
    assert "js/sql-injection" in prompt


@pytest.mark.asyncio
async def test_build_review_prompt_excludes_code_scanning_when_none(config, event_bus):
    """Review prompt does NOT include code scanning section when alerts is None."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _ = await runner._build_review_prompt_with_stats(
        pr, issue, "diff --git a/foo.py"
    )

    assert "## Code Scanning Alerts" not in prompt


# ---------------------------------------------------------------------------
# _build_ci_fix_prompt — code scanning alerts injection
# ---------------------------------------------------------------------------


def test_build_ci_fix_prompt_includes_code_scanning_alerts(config, event_bus):
    """CI fix prompt includes Code Scanning Alerts when provided."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()
    alerts = [
        CodeScanningAlert(
            severity="error",
            security_severity="critical",
            path="src/auth.py",
            start_line=10,
            rule="py/hardcoded-credentials",
            message="Hardcoded password",
        )
    ]

    prompt, _stats = runner._build_ci_fix_prompt(
        pr,
        issue,
        "Failed checks: CodeQL",
        attempt=1,
        code_scanning_alerts=alerts,
    )

    assert "## Code Scanning Alerts" in prompt
    assert "src/auth.py:10" in prompt
    assert "py/hardcoded-credentials" in prompt


def test_build_ci_fix_prompt_excludes_code_scanning_when_none(config, event_bus):
    """CI fix prompt does NOT include code scanning section when alerts is None."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt, _stats = runner._build_ci_fix_prompt(
        pr,
        issue,
        "Failed checks: Build",
        attempt=1,
    )

    assert "## Code Scanning Alerts" not in prompt


# ---------------------------------------------------------------------------
# fix_review_findings
# ---------------------------------------------------------------------------


def test_build_review_fix_prompt_contains_feedback(config, event_bus):
    """Review fix prompt should contain the review summary and instructions."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    prompt = runner._build_review_fix_prompt(pr, issue, "Missing null check in foo()")

    assert "Missing null check in foo()" in prompt
    assert "review-fix:" in prompt
    assert "VERDICT:" in prompt


def test_build_review_fix_prompt_includes_stat_verification(
    config, event_bus, pr_info, task
):
    """Review fix prompt must include git diff --stat HEAD~1 post-commit verification."""
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_fix_prompt(pr_info, task, "Some feedback")
    lower = prompt.lower()

    assert "git diff --stat head~1" in lower
    assert "verify your commit" in lower
    assert "intended file appears" in lower
    assert "after each commit" in lower


def test_build_ci_fix_prompt_includes_stat_verification(
    config, event_bus, pr_info, task
):
    """CI fix prompt must include git diff --stat HEAD~1 post-commit verification."""
    runner = _make_runner(config, event_bus)
    prompt, _ = runner._build_ci_fix_prompt(pr_info, task, "CI failed", 1)
    lower = prompt.lower()

    assert "git diff --stat head~1" in lower
    assert "verify your commit" in lower
    assert "intended file appears" in lower
    assert "after each commit" in lower


# ---------------------------------------------------------------------------
# is_likely_bug re-raise — review()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_reraises_likely_bug_exceptions(
    config, event_bus, pr_info, task, tmp_path
):
    """Code bugs (TypeError, KeyError, etc.) must propagate, not be swallowed."""
    runner = _make_runner(config, event_bus)

    for exc_cls in (TypeError, KeyError, AttributeError):
        mock_execute = AsyncMock(side_effect=exc_cls("code bug"))
        with (
            patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
            patch.object(runner, "_execute", mock_execute),
            pytest.raises(exc_cls, match="code bug"),
        ):
            await runner.review(pr_info, task, tmp_path, "some diff")


@pytest.mark.asyncio
async def test_review_still_catches_runtime_errors(
    config, event_bus, pr_info, task, tmp_path
):
    """RuntimeError (subprocess failures) should still be caught gracefully."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(
            runner, "_execute", AsyncMock(side_effect=RuntimeError("subprocess boom"))
        ),
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    assert result.verdict == ReviewVerdict.COMMENT
    assert "subprocess boom" in result.summary


# ---------------------------------------------------------------------------
# is_likely_bug re-raise — fix_ci()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_reraises_likely_bug_exceptions(
    config, event_bus, pr_info, task, tmp_path
):
    """Code bugs in fix_ci must propagate."""
    runner = _make_runner(config, event_bus)

    for exc_cls in (TypeError, AttributeError, ValueError):
        mock_execute = AsyncMock(side_effect=exc_cls("code bug"))
        with (
            patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
            patch.object(runner, "_execute", mock_execute),
            pytest.raises(exc_cls, match="code bug"),
        ):
            await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)


@pytest.mark.asyncio
async def test_fix_ci_still_catches_runtime_errors(
    config, event_bus, pr_info, task, tmp_path
):
    """RuntimeError in fix_ci should still be caught gracefully."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(
            runner, "_execute", AsyncMock(side_effect=RuntimeError("agent crashed"))
        ),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert "CI fix failed" in result.summary


# ---------------------------------------------------------------------------
# is_likely_bug re-raise — fix_review_findings()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_reraises_likely_bug_exceptions(
    config, event_bus, pr_info, task, tmp_path
):
    """Code bugs (TypeError, KeyError, etc.) must propagate, not be swallowed."""
    runner = _make_runner(config, event_bus)

    for exc_cls in (TypeError, KeyError, AttributeError):
        mock_execute = AsyncMock(side_effect=exc_cls("code bug"))
        with (
            patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
            patch.object(runner, "_execute", mock_execute),
            pytest.raises(exc_cls, match="code bug"),
        ):
            await runner.fix_review_findings(
                pr_info, task, tmp_path, "Missing null check"
            )


# ---------------------------------------------------------------------------
# fix_review_findings — success path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_success_path(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "No issues.\nVERDICT: APPROVE\nSUMMARY: All findings addressed"

    mock_execute = AsyncMock(return_value=transcript)
    mock_has_changes = AsyncMock(return_value=False)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.pr_number == pr_info.number
    assert result.issue_number == task.id
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.summary == "All findings addressed"
    assert result.transcript == transcript
    assert result.fixes_made is False
    assert result.files_changed == []


@pytest.mark.asyncio
async def test_fix_review_findings_success_path_with_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "Fixed issues.\nVERDICT: APPROVE\nSUMMARY: Fixed review findings"

    mock_execute = AsyncMock(return_value=transcript)
    mock_has_changes = AsyncMock(return_value=True)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/bar.py"])
        ),
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.pr_number == pr_info.number
    assert result.issue_number == task.id
    assert result.verdict == ReviewVerdict.APPROVE
    assert result.summary == "Fixed review findings"
    assert result.transcript == transcript
    assert result.fixes_made is True
    assert result.files_changed == ["src/bar.py"]


# ---------------------------------------------------------------------------
# fix_review_findings — failure path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_failure_path(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)

    mock_execute = AsyncMock(side_effect=RuntimeError("agent crashed"))

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", mock_execute),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert "Review fix failed" in result.summary

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.FIX_FINDINGS_DONE.value in statuses


# ---------------------------------------------------------------------------
# fix_review_findings — dry-run
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_dry_run_returns_auto_approved(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    mock_execute = AsyncMock()
    with patch.object(runner, "_execute", mock_execute):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    mock_execute.assert_not_called()
    assert result.verdict == ReviewVerdict.APPROVE
    assert "Dry-run" in result.summary


@pytest.mark.asyncio
async def test_fix_review_findings_dry_run_publishes_done_event(
    dry_config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() dry-run path publishes FIX_FINDINGS_DONE event."""
    runner = _make_runner(dry_config, event_bus)

    mock_execute = AsyncMock()
    with patch.object(runner, "_execute", mock_execute):
        await runner.fix_review_findings(pr_info, task, tmp_path, "Missing null check")

    mock_execute.assert_not_called()
    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.FIX_FINDINGS_DONE.value in statuses

    done_event = next(
        e
        for e in review_events
        if e.data["status"] == ReviewerStatus.FIX_FINDINGS_DONE.value
    )
    assert done_event.data["verdict"] == "approve"
    assert done_event.data["duration"] is not None


# ---------------------------------------------------------------------------
# fix_review_findings — REVIEW_UPDATE events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_publishes_review_update_events(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/fix.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.fix_review_findings(pr_info, task, tmp_path, "Missing null check")

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]

    # Should have at least two: one for start and one for done
    assert len(review_events) >= 2

    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.FIXING_REVIEW_FINDINGS.value in statuses
    assert ReviewerStatus.FIX_FINDINGS_DONE.value in statuses


# ---------------------------------------------------------------------------
# fix_review_findings — duration recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_records_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/fix.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.duration_seconds > 0


@pytest.mark.asyncio
async def test_fix_review_findings_dry_run_records_duration(
    dry_config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(dry_config, event_bus)

    result = await runner.fix_review_findings(
        pr_info, task, tmp_path, "Missing null check"
    )

    assert result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_fix_review_findings_failure_records_duration(
    config, event_bus, pr_info, task, tmp_path
):
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.duration_seconds > 0


# ---------------------------------------------------------------------------
# fix_review_findings / fix_ci — reraise likely-bug exceptions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_reraises_likely_bug_exceptions(
    config, event_bus, pr_info, task, tmp_path
):
    """Code bugs in fix_review_findings must propagate."""
    runner = _make_runner(config, event_bus)

    for exc_cls in (TypeError, KeyError, IndexError):
        mock_execute = AsyncMock(side_effect=exc_cls("code bug"))
        with (
            patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
            patch.object(runner, "_execute", mock_execute),
            pytest.raises(exc_cls, match="code bug"),
        ):
            await runner.fix_review_findings(
                pr_info, task, tmp_path, "Missing null check"
            )


@pytest.mark.asyncio
async def test_fix_review_findings_still_catches_runtime_errors(
    config, event_bus, pr_info, task, tmp_path
):
    """RuntimeError in fix_review_findings should still be caught gracefully."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.verdict == ReviewVerdict.REQUEST_CHANGES
    assert "Review fix failed" in result.summary


# ---------------------------------------------------------------------------
# _get_changed_files
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_changed_files_returns_file_list(config, event_bus, tmp_path):
    """_get_changed_files returns list of file paths when HEAD has moved."""
    runner = _make_runner(config, event_bus)

    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "src/foo.py\ntests/test_foo.py\n"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")),
        patch.object(runner._runner, "run_simple", AsyncMock(return_value=mock_result)),
    ):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == ["src/foo.py", "tests/test_foo.py"]


@pytest.mark.asyncio
async def test_get_changed_files_empty_when_head_unchanged(config, event_bus, tmp_path):
    """_get_changed_files returns empty list when HEAD hasn't moved."""
    runner = _make_runner(config, event_bus)

    with patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == []


@pytest.mark.asyncio
async def test_get_changed_files_empty_on_git_failure(config, event_bus, tmp_path):
    """_get_changed_files returns empty list on git command failure."""
    runner = _make_runner(config, event_bus)

    mock_result = MagicMock()
    mock_result.returncode = 128
    mock_result.stdout = ""

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")),
        patch.object(runner._runner, "run_simple", AsyncMock(return_value=mock_result)),
    ):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == []


@pytest.mark.asyncio
async def test_get_changed_files_empty_when_before_sha_none(
    config, event_bus, tmp_path
):
    """_get_changed_files returns empty list when before_sha is None."""
    runner = _make_runner(config, event_bus)

    result = await runner._get_changed_files(tmp_path, before_sha=None)

    assert result == []


@pytest.mark.asyncio
async def test_get_changed_files_empty_on_timeout(config, event_bus, tmp_path):
    """_get_changed_files returns empty list on timeout."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")),
        patch.object(runner._runner, "run_simple", AsyncMock(side_effect=TimeoutError)),
    ):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == []


@pytest.mark.asyncio
async def test_get_changed_files_empty_on_file_not_found(config, event_bus, tmp_path):
    """_get_changed_files returns empty list when git binary is not found."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="def456")),
        patch.object(
            runner._runner, "run_simple", AsyncMock(side_effect=FileNotFoundError)
        ),
    ):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == []


@pytest.mark.asyncio
async def test_get_changed_files_empty_when_head_sha_none(config, event_bus, tmp_path):
    """_get_changed_files returns empty list when _get_head_sha returns None."""
    runner = _make_runner(config, event_bus)

    with patch.object(runner, "_get_head_sha", AsyncMock(return_value=None)):
        result = await runner._get_changed_files(tmp_path, before_sha="abc123")

    assert result == []


# ---------------------------------------------------------------------------
# files_changed integration — review()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_populates_files_changed(
    config, event_bus, pr_info, task, tmp_path
):
    """After review() with agent commits, result.files_changed contains the changed file list."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed it.\nVERDICT: APPROVE\nSUMMARY: All good"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner,
            "_get_changed_files",
            AsyncMock(return_value=["src/bar.py", "tests/test_bar.py"]),
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.files_changed == ["src/bar.py", "tests/test_bar.py"]


@pytest.mark.asyncio
async def test_review_empty_files_changed_when_no_commits(
    config, event_bus, pr_info, task, tmp_path
):
    """After review() with no changes, result.files_changed is empty."""
    runner = _make_runner(config, event_bus)
    transcript = "Looks fine.\nVERDICT: APPROVE\nSUMMARY: No issues"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.files_changed == []


# ---------------------------------------------------------------------------
# files_changed integration — fix_ci()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_ci_populates_files_changed(
    config, event_bus, pr_info, task, tmp_path
):
    """After fix_ci() with agent commits, result.files_changed is populated."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed CI.\nVERDICT: APPROVE\nSUMMARY: CI fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner,
            "_get_changed_files",
            AsyncMock(return_value=["src/bar.py", "tests/test_bar.py"]),
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.files_changed == ["src/bar.py", "tests/test_bar.py"]


@pytest.mark.asyncio
async def test_fix_ci_empty_files_changed_when_no_commits(
    config, event_bus, pr_info, task, tmp_path
):
    """After fix_ci() with no changes, result.files_changed is empty."""
    runner = _make_runner(config, event_bus)
    transcript = "No changes needed.\nVERDICT: APPROVE\nSUMMARY: CI OK"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.files_changed == []


# ---------------------------------------------------------------------------
# files_changed integration — fix_review_findings()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_populates_files_changed(
    config, event_bus, pr_info, task, tmp_path
):
    """After fix_review_findings() with agent commits, result.files_changed is populated."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed null check.\nVERDICT: APPROVE\nSUMMARY: Fixed"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/fix.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.files_changed == ["src/fix.py"]


@pytest.mark.asyncio
async def test_fix_review_findings_empty_files_changed_when_no_commits(
    config, event_bus, pr_info, task, tmp_path
):
    """After fix_review_findings() with no changes, result.files_changed is empty."""
    runner = _make_runner(config, event_bus)
    transcript = "Looks fine.\nVERDICT: APPROVE\nSUMMARY: No issues found"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.files_changed == []


# ---------------------------------------------------------------------------
# Scope-creep verification logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_logs_changed_files_when_fixes_made(
    config, event_bus, pr_info, task, tmp_path, caplog
):
    """When reviewer makes fix commits and files_changed is non-empty, log lists changed files."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Done"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner,
            "_get_changed_files",
            AsyncMock(return_value=["src/reviewer.py"]),
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
        caplog.at_level("INFO", logger="hydraflow.reviewer"),
    ):
        await runner.review(pr_info, task, tmp_path, "diff")

    assert any("changed files" in r.message for r in caplog.records)
    assert any("src/reviewer.py" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_review_warns_when_fixes_made_but_no_files_changed(
    config, event_bus, pr_info, task, tmp_path, caplog
):
    """When fixes_made is True but files_changed is empty, a WARNING is logged."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Done"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
        caplog.at_level("WARNING", logger="hydraflow.reviewer"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    assert result.commit_stat == ""
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "fixes_made is True but no committed file changes" in r.message
        for r in warning_records
    )


@pytest.mark.asyncio
async def test_fix_review_findings_warns_when_fixes_made_but_no_files_changed(
    config, event_bus, pr_info, task, tmp_path, caplog
):
    """fix_review_findings warns when fixes_made but files_changed is empty."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Done"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
        caplog.at_level("WARNING", logger="hydraflow.reviewer"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.commit_stat == ""
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "fixes_made is True but no committed file changes" in r.message
        for r in warning_records
    )


@pytest.mark.asyncio
async def test_fix_ci_warns_when_fixes_made_but_no_files_changed(
    config, event_bus, pr_info, task, tmp_path, caplog
):
    """fix_ci warns when fixes_made but files_changed is empty."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed CI.\nVERDICT: APPROVE\nSUMMARY: Done"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="should not")),
        patch.object(runner, "_save_transcript"),
        caplog.at_level("WARNING", logger="hydraflow.reviewer"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.commit_stat == ""
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "fixes_made is True but no committed file changes" in r.message
        for r in warning_records
    )


# ---------------------------------------------------------------------------
# ReviewResult.files_changed model tests
# ---------------------------------------------------------------------------


def test_review_result_files_changed_defaults_to_empty_list():
    """ReviewResult() with no files_changed argument defaults to empty list."""
    from models import ReviewResult

    result = ReviewResult(pr_number=1, issue_number=1)
    assert result.files_changed == []


def test_review_result_files_changed_round_trips():
    """ReviewResult(files_changed=[...]) round-trips through serialization."""
    from models import ReviewResult

    result = ReviewResult(pr_number=1, issue_number=1, files_changed=["src/foo.py"])
    data = result.model_dump()
    restored = ReviewResult(**data)
    assert restored.files_changed == ["src/foo.py"]


# ---------------------------------------------------------------------------
# fix_review_findings — event publishing (symmetric with review & fix_ci)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fix_review_findings_publishes_review_update_event(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings publishes start and done REVIEW_UPDATE events."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Done"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/fix.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        await runner.fix_review_findings(pr_info, task, tmp_path, "Missing null check")

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    assert len(review_events) >= 2
    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.FIXING_REVIEW_FINDINGS.value in statuses
    assert ReviewerStatus.FIX_FINDINGS_DONE.value in statuses

    # Done event should include verdict and duration
    done_event = next(
        e
        for e in review_events
        if e.data["status"] == ReviewerStatus.FIX_FINDINGS_DONE.value
    )
    assert done_event.data["verdict"] == "approve"
    assert done_event.data["duration"] is not None


@pytest.mark.asyncio
async def test_fix_review_findings_failure_publishes_done_event(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings publishes FIX_FINDINGS_DONE even when execution fails."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(
            runner, "_execute", AsyncMock(side_effect=RuntimeError("agent crashed"))
        ),
    ):
        await runner.fix_review_findings(pr_info, task, tmp_path, "Missing null check")

    events = event_bus.get_history()
    review_events = [e for e in events if e.type == EventType.REVIEW_UPDATE]
    statuses = [e.data["status"] for e in review_events]
    assert ReviewerStatus.FIX_FINDINGS_DONE.value in statuses

    done_event = next(
        e
        for e in review_events
        if e.data["status"] == ReviewerStatus.FIX_FINDINGS_DONE.value
    )
    assert done_event.data["verdict"] == "request-changes"


# ---------------------------------------------------------------------------
# ReviewResult.success field (#3187)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_success_path_sets_success_true(
    config, event_bus, pr_info, task, tmp_path
):
    """review() must set result.success = True on a successful run."""
    runner = _make_runner(config, event_bus)
    transcript = "All good.\nVERDICT: APPROVE\nSUMMARY: Looks great"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.success is True


@pytest.mark.asyncio
async def test_review_failure_path_leaves_success_false(
    config, event_bus, pr_info, task, tmp_path
):
    """review() must leave result.success = False when an exception occurs."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.success is False


@pytest.mark.asyncio
async def test_review_dry_run_sets_success_true(
    dry_config, event_bus, pr_info, task, tmp_path
):
    """review() dry-run path must set result.success = True."""
    runner = _make_runner(dry_config, event_bus)

    result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.success is True


@pytest.mark.asyncio
async def test_fix_ci_success_path_sets_success_true(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() must set result.success = True on a successful run."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed lint.\nVERDICT: APPROVE\nSUMMARY: Fixed CI failures"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/foo.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.success is True


@pytest.mark.asyncio
async def test_fix_ci_failure_path_leaves_success_false(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() must leave result.success = False when an exception occurs."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.success is False


@pytest.mark.asyncio
async def test_fix_ci_dry_run_sets_success_true(
    dry_config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() dry-run path must set result.success = True."""
    runner = _make_runner(dry_config, event_bus)

    result = await runner.fix_ci(pr_info, task, tmp_path, "Failed: ci", attempt=1)

    assert result.success is True


@pytest.mark.asyncio
async def test_fix_review_findings_success_path_sets_success_true(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() must set result.success = True on a successful run."""
    runner = _make_runner(config, event_bus)
    transcript = "Fixed.\nVERDICT: APPROVE\nSUMMARY: Fixed review issues"

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(
            runner, "_get_changed_files", AsyncMock(return_value=["src/fix.py"])
        ),
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
        patch.object(runner, "_get_commit_stat", AsyncMock(return_value="")),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.success is True


@pytest.mark.asyncio
async def test_fix_review_findings_failure_path_leaves_success_false(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() must leave result.success = False on exception."""
    runner = _make_runner(config, event_bus)

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Missing null check"
        )

    assert result.success is False


@pytest.mark.asyncio
async def test_fix_review_findings_dry_run_sets_success_true(
    dry_config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() dry-run path must set result.success = True."""
    runner = _make_runner(dry_config, event_bus)

    result = await runner.fix_review_findings(
        pr_info, task, tmp_path, "Missing null check"
    )

    assert result.success is True


# ---------------------------------------------------------------------------
# Symmetric field assertion checklist — coverage guard (#3191)
# ---------------------------------------------------------------------------
#
# Every shared ReviewResult field populated by multiple methods must have
# a 3-leg test checklist per method.  The guard introspects this module and
# fails if any required test function is missing.

# (method, field, [(leg_label, test_function_name), ...])
_SHARED_FIELD_CHECKLIST: list[tuple[str, str, list[tuple[str, str]]]] = [
    # --- files_changed ---
    (
        "review",
        "files_changed",
        [
            ("happy_path", "test_review_success_path_with_fixes"),
            ("populates", "test_review_populates_files_changed"),
            (
                "empty_when_no_changes",
                "test_review_empty_files_changed_when_no_commits",
            ),
        ],
    ),
    (
        "fix_ci",
        "files_changed",
        [
            ("happy_path", "test_fix_ci_success_path"),
            ("populates", "test_fix_ci_populates_files_changed"),
            (
                "empty_when_no_changes",
                "test_fix_ci_empty_files_changed_when_no_commits",
            ),
        ],
    ),
    (
        "fix_review_findings",
        "files_changed",
        [
            ("happy_path", "test_fix_review_findings_success_path_with_fixes"),
            ("populates", "test_fix_review_findings_populates_files_changed"),
            (
                "empty_when_no_changes",
                "test_fix_review_findings_empty_files_changed_when_no_commits",
            ),
        ],
    ),
    # --- success (#3185 / #3187) ---
    (
        "review",
        "success",
        [
            ("happy_path", "test_review_success_path_sets_success_true"),
            ("failure_path", "test_review_failure_path_leaves_success_false"),
            ("dry_run", "test_review_dry_run_sets_success_true"),
        ],
    ),
    (
        "fix_ci",
        "success",
        [
            ("happy_path", "test_fix_ci_success_path_sets_success_true"),
            ("failure_path", "test_fix_ci_failure_path_leaves_success_false"),
            ("dry_run", "test_fix_ci_dry_run_sets_success_true"),
        ],
    ),
    (
        "fix_review_findings",
        "success",
        [
            ("happy_path", "test_fix_review_findings_success_path_sets_success_true"),
            (
                "failure_path",
                "test_fix_review_findings_failure_path_leaves_success_false",
            ),
            ("dry_run", "test_fix_review_findings_dry_run_sets_success_true"),
        ],
    ),
]


def _find_missing_shared_field_legs(
    checklist: list[tuple[str, str, list[tuple[str, str]]]],
    test_names: frozenset[str],
) -> list[str]:
    """Return human-readable descriptions of missing test legs."""
    missing: list[str] = []
    for method, field, legs in checklist:
        for leg_label, test_name in legs:
            if test_name not in test_names:
                missing.append(f"{method}() × {field} [{leg_label}]: {test_name}")
    return missing


def _get_module_test_names() -> frozenset[str]:
    """Collect all test function names defined in this module."""
    return frozenset(
        name
        for name, obj in globals().items()
        if name.startswith("test_") and callable(obj)
    )


def test_shared_field_coverage_guard():
    """Every shared ReviewResult field must have all required test legs.

    If this test fails, a new method×field combination was added to the
    checklist but the corresponding test functions have not been written yet.
    """
    test_names = _get_module_test_names()
    missing = _find_missing_shared_field_legs(_SHARED_FIELD_CHECKLIST, test_names)
    assert not missing, "Missing symmetric field test legs:\n" + "\n".join(
        f"  - {m}" for m in missing
    )


def test_guard_detects_removed_leg():
    """Removing test_fix_ci_populates_files_changed causes the guard to
    fail with a message mentioning ``fix_ci() × files_changed``."""
    test_names = _get_module_test_names() - {"test_fix_ci_populates_files_changed"}
    missing = _find_missing_shared_field_legs(_SHARED_FIELD_CHECKLIST, test_names)
    assert any("fix_ci() × files_changed" in m for m in missing)
    assert any("test_fix_ci_populates_files_changed" in m for m in missing)


def test_guard_detects_uncovered_new_field():
    """Adding a checklist entry for a field with no tests causes the guard to
    fail, listing exactly which method×leg combinations are missing."""
    extended = _SHARED_FIELD_CHECKLIST + [
        (
            "review",
            "new_field",
            [
                ("happy_path", "test_review_populates_new_field"),
                ("empty", "test_review_empty_new_field"),
                ("integration", "test_review_new_field_integration"),
            ],
        ),
    ]
    test_names = _get_module_test_names()
    missing = _find_missing_shared_field_legs(extended, test_names)
    assert len(missing) >= 3
    assert all("review() × new_field" in m for m in missing)


# ---------------------------------------------------------------------------
# Nested guard: _get_commit_stat is never called when fixes_made is False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_skips_commit_stat_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """review() must not call _get_commit_stat when fixes_made is False."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Clean"
    commit_stat_mock = AsyncMock(return_value="should not be called")

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", commit_stat_mock),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "diff")

    commit_stat_mock.assert_not_called()
    assert result.commit_stat == ""


@pytest.mark.asyncio
async def test_fix_ci_skips_commit_stat_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_ci() must not call _get_commit_stat when fixes_made is False."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: CI green"
    commit_stat_mock = AsyncMock(return_value="should not be called")

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", commit_stat_mock),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(pr_info, task, tmp_path, "CI log")

    commit_stat_mock.assert_not_called()
    assert result.commit_stat == ""


@pytest.mark.asyncio
async def test_fix_review_findings_skips_commit_stat_when_no_fixes(
    config, event_bus, pr_info, task, tmp_path
):
    """fix_review_findings() must not call _get_commit_stat when fixes_made is False."""
    runner = _make_runner(config, event_bus)
    transcript = "VERDICT: APPROVE\nSUMMARY: Nothing to fix"
    commit_stat_mock = AsyncMock(return_value="should not be called")

    with (
        patch.object(runner, "_get_head_sha", AsyncMock(return_value="abc123")),
        patch.object(runner, "_execute", AsyncMock(return_value=transcript)),
        patch.object(runner, "_get_changed_files", AsyncMock(return_value=[])),
        patch.object(runner, "_has_changes", AsyncMock(return_value=False)),
        patch.object(runner, "_get_commit_stat", commit_stat_mock),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_review_findings(
            pr_info, task, tmp_path, "Findings text"
        )

    commit_stat_mock.assert_not_called()
    assert result.commit_stat == ""


# ---------------------------------------------------------------------------
# _load_plan_for_review
# ---------------------------------------------------------------------------


def test_load_plan_for_review_returns_matching_comment(event_bus, tmp_path):
    """Returns the first comment containing '## Implementation Plan'."""
    from tests.conftest import TaskFactory

    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = _make_runner(cfg, event_bus)
    plan_comment = "## Implementation Plan\n\nStep 1: do the thing."
    task = TaskFactory.create(comments=["unrelated comment", plan_comment])

    result = runner._load_plan_for_review(task)

    assert result == plan_comment


def test_load_plan_for_review_falls_back_to_plan_file(event_bus, tmp_path):
    """Falls back to reading the plan file when no matching comment exists."""
    from tests.conftest import TaskFactory

    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = _make_runner(cfg, event_bus)
    plan_content = "## Implementation Plan\n\nFile Delta: src/foo.py"
    plans_dir = cfg.plans_dir
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "issue-42.md").write_text(plan_content)
    task = TaskFactory.create(id=42, comments=[])

    result = runner._load_plan_for_review(task)

    assert result == plan_content


def test_load_plan_for_review_returns_empty_when_no_plan(event_bus, tmp_path):
    """Returns empty string when no comment matches and no plan file exists."""
    from tests.conftest import TaskFactory

    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = _make_runner(cfg, event_bus)
    task = TaskFactory.create(id=99, comments=["just a comment", "another comment"])

    result = runner._load_plan_for_review(task)

    assert result == ""


def test_load_plan_for_review_handles_none_comments(event_bus, tmp_path):
    """Handles task with None comments gracefully."""
    from tests.conftest import TaskFactory

    cfg = ConfigFactory.create(repo_root=tmp_path)
    runner = _make_runner(cfg, event_bus)
    task = TaskFactory.create(id=55, comments=None)

    result = runner._load_plan_for_review(task)

    assert result == ""
