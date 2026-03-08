"""Tests for dx/hydraflow/reviewer.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_runner import BaseRunner
from events import EventType
from models import ReviewerStatus, ReviewVerdict
from reviewer import ReviewRunner
from tests.conftest import PRInfoFactory
from tests.helpers import ConfigFactory, make_streaming_proc


@pytest.fixture
def pr_info():
    return PRInfoFactory.create()


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


class TestReviewRunnerInheritance:
    """ReviewRunner must extend BaseRunner."""

    def test_inherits_from_base_runner(self, config, event_bus) -> None:
        runner = ReviewRunner(config, event_bus)
        assert isinstance(runner, BaseRunner)

    def test_has_terminate_method(self, config, event_bus) -> None:
        runner = ReviewRunner(config, event_bus)
        assert callable(runner.terminate)


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


def test_build_command_accepts_none_worktree_path(config):
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
        worktree_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    runner = _make_runner(cfg, None)
    cmd = runner._build_command(tmp_path)
    assert cmd[:3] == ["codex", "exec", "--json"]
    assert "--model" in cmd
    assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


# ---------------------------------------------------------------------------
# _build_review_prompt
# ---------------------------------------------------------------------------


def test_build_review_prompt_includes_pr_number(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "some diff")

    assert f"#{pr_info.number}" in prompt


def test_build_review_prompt_includes_issue_context(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "some diff")

    assert task.title in prompt
    assert task.body in prompt
    assert f"#{task.id}" in prompt


def test_build_review_prompt_includes_diff(config, event_bus, pr_info, task):
    runner = _make_runner(config, event_bus)
    diff = "diff --git a/foo.py b/foo.py\n+added line"
    prompt = runner._build_review_prompt(pr_info, task, diff)

    assert diff in prompt


def test_build_review_prompt_includes_review_instructions(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "VERDICT" in prompt
    assert "SUMMARY" in prompt
    assert "APPROVE" in prompt
    assert "REQUEST_CHANGES" in prompt


def test_build_review_prompt_includes_ui_criteria_when_diff_has_ui_files(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    diff = (
        "diff --git a/ui/src/components/Foo.jsx b/ui/src/components/Foo.jsx\n"
        "+import React from 'react';\n"
        "+export const Foo = () => <div>Hello</div>;\n"
    )
    prompt = runner._build_review_prompt(pr_info, task, diff)

    assert "DRY" in prompt
    assert "Responsive" in prompt
    assert "Style consistency" in prompt
    assert "Component reuse" in prompt
    assert "theme.js" in prompt


def test_build_review_prompt_excludes_ui_criteria_when_no_ui_files(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    diff = "diff --git a/reviewer.py b/reviewer.py\n+# backend-only change\n"
    prompt = runner._build_review_prompt(pr_info, task, diff)

    assert "DRY" not in prompt
    assert "theme.js" not in prompt


def test_build_review_prompt_skips_local_tests_when_ci_enabled(
    event_bus, pr_info, task
):
    ci_config = ConfigFactory.create(max_ci_fix_attempts=2)
    runner = _make_runner(ci_config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "Do NOT run `make lint`, `make test`, or `make quality`" in prompt
    assert "CI will verify" in prompt


def test_build_review_prompt_runs_local_tests_when_ci_disabled(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "Run `make lint` and `make test`" in prompt
    assert "Do NOT run" not in prompt


def test_build_review_prompt_fix_section_skips_tests_when_ci_enabled(
    event_bus, pr_info, task
):
    ci_config = ConfigFactory.create(max_ci_fix_attempts=1)
    runner = _make_runner(ci_config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "Do NOT run tests locally" in prompt


def test_build_review_prompt_fix_section_runs_tests_when_ci_disabled(
    config, event_bus, pr_info, task
):
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

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


def test_sanitize_summary_accepts_clean_text(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("Implementation looks good, tests pass.") == (
        "Implementation looks good, tests pass."
    )


def test_sanitize_summary_rejects_tool_arrow_output(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("→ TaskOutput: {'task_id': 'abc123'}") is None


def test_sanitize_summary_rejects_left_arrow_output(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("← Result: done") is None


def test_sanitize_summary_rejects_raw_json(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary('{"task_id": "abc", "block": true}') is None


def test_sanitize_summary_rejects_html_tags(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("<div>Some output</div>") is None


def test_sanitize_summary_rejects_code_fences(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("```python") is None


def test_sanitize_summary_rejects_git_trailers(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert (
        runner._sanitize_summary("Co-Authored-By: Claude <noreply@anthropic.com>")
        is None
    )
    assert runner._sanitize_summary("Signed-off-by: Bot <bot@example.com>") is None


def test_sanitize_summary_rejects_short_strings(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("ok") is None
    assert runner._sanitize_summary("   short   ") is None


def test_sanitize_summary_rejects_metric_lines(config, event_bus):
    runner = _make_runner(config, event_bus)
    assert runner._sanitize_summary("tokens: 12345") is None
    assert runner._sanitize_summary("cost: $0.05") is None
    assert runner._sanitize_summary("duration: 30s") is None


def test_sanitize_summary_truncates_to_200_chars(config, event_bus):
    runner = _make_runner(config, event_bus)
    long_text = "A" * 300
    result = runner._sanitize_summary(long_text)
    assert result is not None
    assert len(result) == 200


def test_sanitize_summary_strips_whitespace(config, event_bus):
    runner = _make_runner(config, event_bus)
    result = runner._sanitize_summary("   Clean summary text here   ")
    assert result == "Clean summary text here"


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
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.review(pr_info, task, tmp_path, "some diff")

    assert result.fixes_made is True
    assert result.verdict == ReviewVerdict.APPROVE


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

    with patch("runner_utils.os.killpg", side_effect=ProcessLookupError):
        runner.terminate()  # Should not raise


def test_terminate_with_no_active_processes(config, event_bus):
    runner = _make_runner(config, event_bus)
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
        patch.object(runner, "_has_changes", mock_has_changes),
        patch.object(runner, "_save_transcript"),
    ):
        result = await runner.fix_ci(
            pr_info, task, tmp_path, "Failed: ci", attempt=1, worker_id=0
        )

    assert result.verdict == ReviewVerdict.APPROVE
    assert result.fixes_made is True
    assert result.summary == "Fixed CI failures"


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
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
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
        patch.object(runner, "_has_changes", AsyncMock(return_value=True)),
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


def test_build_review_prompt_truncates_long_diff_with_warning(
    config, event_bus, pr_info, task
):
    """Large diffs should be summarized/truncated with a note."""
    runner = _make_runner(config, event_bus)
    long_diff = "x" * 20_000
    prompt = runner._build_review_prompt(pr_info, task, long_diff)

    assert "### Diff Summary" in prompt
    assert "### Diff Excerpts" in prompt
    assert "x" * 20_000 not in prompt
    assert "Diff truncated" in prompt
    assert "review may be incomplete" in prompt


def test_build_review_prompt_preserves_short_diff(config, event_bus, pr_info, task):
    """Diff under max_review_diff_chars should pass through unchanged."""
    runner = _make_runner(config, event_bus)
    short_diff = "diff --git a/foo.py\n+added line"
    prompt = runner._build_review_prompt(pr_info, task, short_diff)

    assert short_diff in prompt
    assert "Diff truncated" not in prompt


def test_build_review_prompt_diff_truncation_configurable(event_bus, pr_info, task):
    """Configured max_review_diff_chars should appear in truncation note."""
    cfg = ConfigFactory.create(max_review_diff_chars=5_000)
    runner = _make_runner(cfg, event_bus)
    diff = "x" * 10_000
    prompt = runner._build_review_prompt(pr_info, task, diff)

    assert "### Diff Summary" in prompt
    assert "x" * 10_000 not in prompt
    assert "5,000 chars" in prompt


def test_build_review_prompt_logs_warning_on_truncation(
    config, event_bus, pr_info, task
):
    """Should log a warning when diff is truncated."""
    runner = _make_runner(config, event_bus)
    long_diff = "x" * 20_000

    with patch("reviewer.logger") as mock_logger:
        runner._build_review_prompt(pr_info, task, long_diff)

    mock_logger.warning.assert_called_once()


# ---------------------------------------------------------------------------
# Reviewer test_command configuration
# ---------------------------------------------------------------------------


def test_build_review_prompt_uses_configured_test_command(event_bus, pr_info, task):
    """Reviewer prompt should use the configured test_command."""
    cfg = ConfigFactory.create(test_command="npm test", max_ci_fix_attempts=0)
    runner = _make_runner(cfg, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "`npm test`" in prompt
    assert "make test-fast" not in prompt


def test_build_review_prompt_no_make_test_fast(config, event_bus, pr_info, task):
    """Reviewer prompt should not reference make test-fast anywhere."""
    runner = _make_runner(config, event_bus)
    prompt = runner._build_review_prompt(pr_info, task, "diff")

    assert "make test-fast" not in prompt


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
# _build_precheck_prompt
# ---------------------------------------------------------------------------


class TestBuildPrecheckPrompt:
    """Tests for ReviewRunner._build_precheck_prompt."""

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
    """Tests for ReviewRunner._run_precheck_context wiring."""

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
            worktree_base=tmp_path / "wt",
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
        mock_self_execute.assert_called_once_with(
            ["cmd"],
            "prompt",
            tmp_path,
            {"pr": pr_info.number, "issue": task.id, "source": "reviewer"},
            telemetry_stats={
                "context_chars_before": len(task.body or "") + len("diff"),
                "context_chars_after": len("prompt"),
                "pruned_chars_total": len(task.body or "")
                + len("diff")
                - len("prompt"),
            },
        )


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
    logs = "E" * (runner._MAX_CI_LOG_PROMPT_CHARS + 200)

    prompt, stats = runner._build_ci_fix_prompt(
        pr, issue, "Failed checks: Build", attempt=1, ci_logs=logs
    )

    assert "truncated from" in prompt
    assert int(stats["pruned_chars_total"]) > 0


# ---------------------------------------------------------------------------
# _build_review_prompt — runtime log injection
# ---------------------------------------------------------------------------


def test_build_review_prompt_includes_runtime_logs_when_enabled(tmp_path, event_bus):
    """Review prompt includes Runtime Logs section when enabled and logs exist."""
    from tests.conftest import PRInfoFactory, TaskFactory

    config = ConfigFactory.create(
        inject_runtime_logs=True,
        repo_root=tmp_path,
    )
    log_dir = tmp_path / ".hydraflow" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "hydraflow.log").write_text("INFO: ok\nERROR: failed\n")

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    with (
        patch("base_runner.load_project_manifest", return_value=""),
        patch("base_runner.load_memory_digest", return_value=""),
    ):
        prompt = runner._build_review_prompt(pr, issue, "diff --git a/foo.py")

    assert "## Recent Application Logs" in prompt
    assert "ERROR: failed" in prompt


def test_build_review_prompt_excludes_runtime_logs_when_disabled(config, event_bus):
    """Review prompt does NOT include runtime logs when disabled."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    with (
        patch("base_runner.load_project_manifest", return_value=""),
        patch("base_runner.load_memory_digest", return_value=""),
    ):
        prompt = runner._build_review_prompt(pr, issue, "diff --git a/foo.py")

    assert "## Recent Application Logs" not in prompt


# ---------------------------------------------------------------------------
# _format_code_scanning_alerts
# ---------------------------------------------------------------------------


class TestFormatCodeScanningAlerts:
    """Tests for ReviewRunner._format_code_scanning_alerts."""

    def test_empty_alerts_returns_empty_string(self):
        assert ReviewRunner._format_code_scanning_alerts([], 6000) == ""

    def test_formats_single_alert(self):
        alerts = [
            {
                "severity": "error",
                "security_severity": "high",
                "path": "src/db.js",
                "start_line": 42,
                "rule": "js/sql-injection",
                "message": "SQL injection vulnerability",
            }
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "[HIGH]" in result
        assert "src/db.js:42" in result
        assert "js/sql-injection" in result
        assert "SQL injection vulnerability" in result

    def test_uses_severity_when_no_security_severity(self):
        alerts = [
            {
                "severity": "warning",
                "security_severity": None,
                "path": "foo.py",
                "start_line": 10,
                "rule": "py/unused-import",
                "message": "",
            }
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "[WARNING]" in result

    def test_truncates_at_max_chars(self):
        alerts = [
            {
                "severity": "error",
                "path": f"src/file{i}.py",
                "start_line": i,
                "rule": f"rule-{i}",
                "message": f"Alert message {i}",
            }
            for i in range(100)
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 200)
        assert "truncated" in result
        assert "Showing" in result
        assert "100 alerts" in result

    def test_truncation_includes_gh_command(self):
        alerts = [
            {
                "severity": "error",
                "path": f"src/file{i}.py",
                "start_line": i,
                "rule": f"rule-{i}",
                "message": "x" * 50,
            }
            for i in range(100)
        ]
        result = ReviewRunner._format_code_scanning_alerts(
            alerts, 200, repo="org/repo", branch="main"
        )
        assert "gh api repos/org/repo/code-scanning/alerts" in result

    def test_no_truncation_within_limit(self):
        alerts = [
            {
                "severity": "error",
                "path": "foo.py",
                "start_line": 1,
                "rule": "test-rule",
                "message": "msg",
            }
        ]
        result = ReviewRunner._format_code_scanning_alerts(alerts, 6000)
        assert "truncated" not in result


# ---------------------------------------------------------------------------
# _build_review_prompt — code scanning alerts injection
# ---------------------------------------------------------------------------


def test_build_review_prompt_includes_code_scanning_alerts(config, event_bus):
    """Review prompt includes Code Scanning Alerts section when provided."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()
    alerts = [
        {
            "severity": "error",
            "security_severity": "high",
            "path": "src/db.js",
            "start_line": 42,
            "rule": "js/sql-injection",
            "message": "SQL injection",
        }
    ]

    with (
        patch("base_runner.load_project_manifest", return_value=""),
        patch("base_runner.load_memory_digest", return_value=""),
    ):
        prompt = runner._build_review_prompt(
            pr,
            issue,
            "diff --git a/foo.py",
            code_scanning_alerts=alerts,
        )

    assert "## Code Scanning Alerts" in prompt
    assert "src/db.js:42" in prompt
    assert "js/sql-injection" in prompt


def test_build_review_prompt_excludes_code_scanning_when_none(config, event_bus):
    """Review prompt does NOT include code scanning section when alerts is None."""
    from tests.conftest import PRInfoFactory, TaskFactory

    runner = _make_runner(config, event_bus)
    pr = PRInfoFactory.create()
    issue = TaskFactory.create()

    with (
        patch("base_runner.load_project_manifest", return_value=""),
        patch("base_runner.load_memory_digest", return_value=""),
    ):
        prompt = runner._build_review_prompt(pr, issue, "diff --git a/foo.py")

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
        {
            "severity": "error",
            "security_severity": "critical",
            "path": "src/auth.py",
            "start_line": 10,
            "rule": "py/hardcoded-credentials",
            "message": "Hardcoded password",
        }
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
