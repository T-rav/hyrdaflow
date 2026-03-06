"""Tests for triage.py — TriageRunner issue readiness evaluation."""

from __future__ import annotations

import json
import sys
import unittest.mock
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_runner import BaseRunner
from events import EventBus, EventType
from models import TriageResult
from subprocess_util import CreditExhaustedError
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_streaming_proc
from triage import TriageRunner


def _make_llm_verdict(ready: bool, reasons: list[str] | None = None) -> str:
    """Build stream-json stdout that stream_claude_process will parse into a verdict."""
    verdict = json.dumps({"ready": ready, "reasons": reasons or []})
    # stream-json: an assistant event with the JSON, then a result event
    assistant_event = json.dumps(
        {
            "type": "assistant",
            "message": {
                "id": "msg_1",
                "content": [{"type": "text", "text": verdict}],
            },
        }
    )
    result_event = json.dumps({"type": "result", "result": verdict})
    return f"{assistant_event}\n{result_event}"


@pytest.fixture
def mock_runner() -> AsyncMock:
    """A mock SubprocessRunner for injecting into TriageRunner."""
    return AsyncMock()


@pytest.fixture
def runner(event_bus: EventBus, mock_runner: AsyncMock) -> TriageRunner:
    config = ConfigFactory.create()
    return TriageRunner(config, event_bus, runner=mock_runner)


# ---------------------------------------------------------------------------
# Pre-filter tests (no LLM call)
# ---------------------------------------------------------------------------


class TestPreFilter:
    """Tests for the fast pre-filter (length checks) that skip the LLM."""

    @pytest.mark.asyncio
    async def test_not_ready_when_body_empty(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1, title="A good descriptive title", body="", tags=[], source_url=""
        )
        result = await runner.evaluate(issue)
        assert result.ready is False
        assert any("Body" in r for r in result.reasons)
        mock_runner.create_streaming_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_ready_when_body_too_short(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1,
            title="A good descriptive title",
            body="Fix it",
            tags=[],
            source_url="",
        )
        result = await runner.evaluate(issue)
        assert result.ready is False
        assert any("Body" in r for r in result.reasons)
        mock_runner.create_streaming_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_ready_when_title_too_short(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1, title="Fix", body="A" * 100, tags=[], source_url=""
        )
        result = await runner.evaluate(issue)
        assert result.ready is False
        assert any("Title" in r for r in result.reasons)
        mock_runner.create_streaming_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_not_ready_when_both_insufficient(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1, title="Bug", body="short", tags=[], source_url=""
        )
        result = await runner.evaluate(issue)
        assert result.ready is False
        assert len(result.reasons) == 2
        mock_runner.create_streaming_process.assert_not_called()


# ---------------------------------------------------------------------------
# LLM evaluation tests
# ---------------------------------------------------------------------------


class TestLLMEvaluation:
    """Tests for the LLM-powered evaluation path."""

    @pytest.mark.asyncio
    async def test_ready_when_llm_approves(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        result = await runner.evaluate(issue)
        assert result.ready is True
        assert result.reasons == []

    @pytest.mark.asyncio
    async def test_not_ready_when_llm_rejects(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=2,
            title="Fix the thing that is broken",
            body="Please fix the thing that is broken somewhere in the code somehow maybe. "
            * 3,
            tags=[],
            source_url="",
        )
        reasons = [
            "Issue lacks specificity — no concrete error or expected behavior described",
            "No reproduction steps or affected area mentioned",
        ]
        stdout = _make_llm_verdict(ready=False, reasons=reasons)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        result = await runner.evaluate(issue)
        assert result.ready is False
        assert result.reasons == reasons

    @pytest.mark.asyncio
    async def test_llm_returns_malformed_json(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=3,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        # Return garbage text that can't be parsed as JSON
        garbage = "This is not JSON at all, just some random text without any structure"
        assistant_event = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [{"type": "text", "text": garbage}],
                },
            }
        )
        result_event = json.dumps({"type": "result", "result": garbage})
        stdout = f"{assistant_event}\n{result_event}"
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        result = await runner.evaluate(issue)
        assert result.ready is False
        assert any("parse" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_llm_process_failure_propagates(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """RuntimeError from subprocess should propagate (not silently become ready=False).

        This ensures infrastructure failures don't incorrectly escalate issues
        to HITL — the caller can catch and retry instead.
        """
        issue = TaskFactory.create(
            id=4,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        mock_runner.create_streaming_process = AsyncMock(
            side_effect=RuntimeError("Process crashed")
        )

        with pytest.raises(RuntimeError, match="Process crashed"):
            await runner.evaluate(issue)

    @pytest.mark.asyncio
    async def test_llm_empty_transcript_raises(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """Empty LLM transcript should raise RuntimeError, not return ready=False."""
        issue = TaskFactory.create(
            id=4,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        mock_runner.create_streaming_process = make_streaming_proc(stdout="")

        with pytest.raises(RuntimeError, match="empty response"):
            await runner.evaluate(issue)

    @pytest.mark.asyncio
    async def test_non_runtime_error_still_returns_not_ready(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """Non-RuntimeError exceptions should still produce ready=False result."""
        issue = TaskFactory.create(
            id=4,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        mock_runner.create_streaming_process = AsyncMock(
            side_effect=OSError("Connection reset")
        )

        result = await runner.evaluate(issue)
        assert result.ready is False
        assert any("error" in r.lower() for r in result.reasons)

    @pytest.mark.asyncio
    async def test_auth_failure_raises_runtime_error(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """Docker containers without API key produce auth_failed stream events."""
        issue = TaskFactory.create(
            id=4,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        # Simulate the stream-json output when Claude CLI is not authenticated
        auth_failed = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [{"type": "text", "text": "Not logged in"}],
                },
                "error": "authentication_failed",
            }
        )
        result_event = json.dumps(
            {
                "type": "result",
                "result": "Not logged in",
                "is_error": True,
            }
        )
        stdout = f"{auth_failed}\n{result_event}"
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        with pytest.raises(RuntimeError, match="authentication failed"):
            await runner.evaluate(issue)

    @pytest.mark.asyncio
    async def test_credit_exhausted_propagates(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=5,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        mock_runner.create_streaming_process = AsyncMock(
            side_effect=CreditExhaustedError("Credits exhausted")
        )

        with pytest.raises(CreditExhaustedError):
            await runner.evaluate(issue)

    @pytest.mark.asyncio
    async def test_returns_triage_result_type(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1,
            title="A descriptive title",
            body="A" * 100,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        result = await runner.evaluate(issue)
        assert isinstance(result, TriageResult)
        assert result.issue_number == 1

    @pytest.mark.asyncio
    async def test_llm_json_in_code_fence(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """LLM wraps JSON in markdown code fences — parser should handle it."""
        issue = TaskFactory.create(
            id=6,
            title="Add user authentication flow",
            body="We need OAuth2 login with Google and GitHub providers. " * 3,
            tags=[],
            source_url="",
        )
        fenced = '```json\n{"ready": true, "reasons": []}\n```'
        assistant_event = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "content": [{"type": "text", "text": fenced}],
                },
            }
        )
        result_event = json.dumps({"type": "result", "result": fenced})
        stdout = f"{assistant_event}\n{result_event}"
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        result = await runner.evaluate(issue)
        assert result.ready is True


# ---------------------------------------------------------------------------
# Verdict parsing
# ---------------------------------------------------------------------------


class TestParseVerdict:
    """Tests for TriageRunner._parse_verdict static method."""

    def test_direct_json(self) -> None:
        transcript = '{"ready": true, "reasons": []}'
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is True

    def test_json_in_code_fence(self) -> None:
        transcript = (
            'Some text\n```json\n{"ready": false, "reasons": ["Vague"]}\n```\nMore text'
        )
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is False
        assert result.reasons == ["Vague"]

    def test_json_embedded_in_text(self) -> None:
        transcript = (
            'Here is my verdict: {"ready": true, "reasons": []} based on analysis'
        )
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is True

    def test_unparseable_returns_none(self) -> None:
        transcript = "This is just plain text with no JSON"
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is None

    def test_invalid_json_returns_none(self) -> None:
        transcript = '{"ready": true, "reasons": [}'  # malformed
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is None

    def test_reasons_as_string_coerced_to_list(self) -> None:
        """LLM returns reasons as a plain string instead of an array — coerced to list."""
        transcript = '{"ready": false, "reasons": "Missing specificity"}'
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is False
        assert result.reasons == [
            "Missing specificity"
        ]  # string preserved as single-item list

    def test_ready_as_string_false_coerced_correctly(self) -> None:
        """LLM returns ready as string 'false' — must NOT be coerced to True."""
        # bool("false") == True in Python; _coerce_ready must handle this.
        transcript = '{"ready": "false", "reasons": ["Missing detail"]}'
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is False  # string "false" → bool False, not True

    def test_ready_as_string_true_coerced_correctly(self) -> None:
        """LLM returns ready as string 'true' — should be coerced to True."""
        transcript = '{"ready": "true", "reasons": []}'
        result = TriageRunner._parse_verdict(transcript, 1)
        assert result is not None
        assert result.ready is True


# ---------------------------------------------------------------------------
# Command and prompt building
# ---------------------------------------------------------------------------


class TestBuildCommand:
    """Tests for TriageRunner._build_command."""

    def test_command_uses_triage_model(self, event_bus: EventBus) -> None:
        config = ConfigFactory.create(triage_model="sonnet")
        runner = TriageRunner(config, event_bus)
        cmd = runner._build_command()
        assert "--model" in cmd
        model_idx = cmd.index("--model")
        assert cmd[model_idx + 1] == "sonnet"

    def test_command_includes_max_turns(self, event_bus: EventBus) -> None:
        config = ConfigFactory.create()
        runner = TriageRunner(config, event_bus)
        cmd = runner._build_command()
        assert "--max-turns" in cmd
        turns_idx = cmd.index("--max-turns")
        assert cmd[turns_idx + 1] == "1"

    def test_command_includes_bypass_permissions(self, event_bus: EventBus) -> None:
        config = ConfigFactory.create()
        runner = TriageRunner(config, event_bus)
        cmd = runner._build_command()
        assert "--permission-mode" in cmd
        perm_idx = cmd.index("--permission-mode")
        assert cmd[perm_idx + 1] == "bypassPermissions"

    def test_command_supports_codex_backend(self, event_bus: EventBus) -> None:
        config = ConfigFactory.create(
            triage_tool="codex",
            triage_model="gpt-5-codex",
        )
        runner = TriageRunner(config, event_bus)
        cmd = runner._build_command()
        assert cmd[:3] == ["codex", "exec", "--json"]
        assert "--model" in cmd
        assert cmd[cmd.index("--model") + 1] == "gpt-5-codex"


class TestBuildPrompt:
    """Tests for TriageRunner._build_prompt."""

    def test_prompt_contains_issue_title_and_body(self) -> None:
        issue = TaskFactory.create(
            id=42,
            title="Add dark mode toggle",
            body="The app should support dark mode in settings.",
        )
        prompt = TriageRunner._build_prompt(issue)
        assert "Add dark mode toggle" in prompt
        assert "dark mode in settings" in prompt
        assert "#42" in prompt

    def test_prompt_contains_evaluation_criteria(self) -> None:
        issue = TaskFactory.create(id=1)
        prompt = TriageRunner._build_prompt(issue)
        assert "Clarity" in prompt
        assert "Specificity" in prompt
        assert "Actionability" in prompt
        assert "Scope" in prompt

    def test_build_prompt_with_stats_tracks_body_pruning(self) -> None:
        issue = TaskFactory.create(id=9, body="a" * 200)
        _prompt, stats = TriageRunner._build_prompt_with_stats(issue, max_body=50)
        assert stats["context_chars_before"] == 200
        assert stats["context_chars_after"] > 50
        assert stats["pruned_chars_total"] > 0


# ---------------------------------------------------------------------------
# Event publishing
# ---------------------------------------------------------------------------


class TestTriageEvents:
    """Tests for TRIAGE_UPDATE event emission."""

    @pytest.mark.asyncio
    async def test_evaluate_publishes_evaluating_and_done_events(
        self, runner: TriageRunner, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=1,
            title="A descriptive title",
            body="A" * 100,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        received: list = []
        queue = event_bus.subscribe()

        await runner.evaluate(issue)

        # Drain events
        while not queue.empty():
            received.append(await queue.get())

        triage_events = [e for e in received if e.type == EventType.TRIAGE_UPDATE]
        assert len(triage_events) == 2
        assert triage_events[0].data["status"] == "evaluating"
        assert triage_events[0].data["role"] == "triage"
        assert triage_events[1].data["status"] == "done"

    @pytest.mark.asyncio
    async def test_evaluate_events_carry_issue_number(
        self, runner: TriageRunner, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=99,
            title="A descriptive title here",
            body="A" * 100,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        received: list = []
        queue = event_bus.subscribe()

        await runner.evaluate(issue)

        while not queue.empty():
            received.append(await queue.get())

        triage_events = [e for e in received if e.type == EventType.TRIAGE_UPDATE]
        assert all(e.data["issue"] == 99 for e in triage_events)

    @pytest.mark.asyncio
    async def test_evaluate_emits_transcript_lines(
        self, runner: TriageRunner, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        issue = TaskFactory.create(
            id=42,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        received: list = []
        queue = event_bus.subscribe()

        await runner.evaluate(issue)

        while not queue.empty():
            received.append(await queue.get())

        transcript_events = [e for e in received if e.type == EventType.TRANSCRIPT_LINE]
        assert len(transcript_events) >= 2
        assert transcript_events[0].data["source"] == "triage"
        assert transcript_events[0].data["issue"] == 42
        assert "Evaluating" in transcript_events[0].data["line"]

    @pytest.mark.asyncio
    async def test_not_ready_transcript_shows_reasons(
        self, runner: TriageRunner, event_bus: EventBus
    ) -> None:
        """Pre-filter failures show reasons in transcript."""
        issue = TaskFactory.create(
            id=7, title="Bug", body="short", tags=[], source_url=""
        )
        received: list = []
        queue = event_bus.subscribe()

        await runner.evaluate(issue)

        while not queue.empty():
            received.append(await queue.get())

        transcript_events = [e for e in received if e.type == EventType.TRANSCRIPT_LINE]
        lines = [e.data["line"] for e in transcript_events]
        assert any("needs more information" in line for line in lines)

    @pytest.mark.asyncio
    async def test_llm_evaluation_emits_pre_filter_pass_transcript(
        self, runner: TriageRunner, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        """When pre-filter passes, a transcript line about LLM evaluation is emitted."""
        issue = TaskFactory.create(
            id=10,
            title="Add new feature for users",
            body="Detailed description of what needs to happen. " * 3,
            tags=[],
            source_url="",
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        received: list = []
        queue = event_bus.subscribe()

        await runner.evaluate(issue)

        while not queue.empty():
            received.append(await queue.get())

        transcript_events = [e for e in received if e.type == EventType.TRANSCRIPT_LINE]
        lines = [e.data["line"] for e in transcript_events]
        assert any("LLM quality evaluation" in line for line in lines)


# ---------------------------------------------------------------------------
# Dry-run mode
# ---------------------------------------------------------------------------


class TestTriageDryRun:
    """Tests for dry-run mode in TriageRunner."""

    @pytest.mark.asyncio
    async def test_dry_run_returns_ready_true(
        self, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        config = ConfigFactory.create(dry_run=True)
        runner = TriageRunner(config, event_bus, runner=mock_runner)
        issue = TaskFactory.create(id=1, title="Bug", body="", tags=[], source_url="")

        result = await runner.evaluate(issue)
        assert result.ready is True
        assert result.reasons == []
        # LLM should not be called in dry-run
        mock_runner.create_streaming_process.assert_not_called()


# ---------------------------------------------------------------------------
# Terminate
# ---------------------------------------------------------------------------


class TestTriageTerminate:
    """Tests for TriageRunner.terminate."""

    def test_terminate_calls_terminate_processes(
        self, event_bus: EventBus, mock_runner: AsyncMock
    ) -> None:
        config = ConfigFactory.create()
        runner = TriageRunner(config, event_bus, runner=mock_runner)
        mock_proc = MagicMock()
        mock_proc.pid = 12345
        runner._active_procs.add(mock_proc)

        # terminate() should not raise
        runner.terminate()
        # After terminate, the proc should have been killed
        # (terminate_processes uses os.killpg which we don't mock here,
        # so we just verify it doesn't crash with our mock)


# ---------------------------------------------------------------------------
# BaseRunner inheritance
# ---------------------------------------------------------------------------


class TestTriageRunnerInheritance:
    """Tests confirming TriageRunner extends BaseRunner."""

    def test_triage_runner_extends_base_runner(self) -> None:
        assert issubclass(TriageRunner, BaseRunner)

    def test_log_class_attribute_is_triage_logger(self) -> None:
        assert TriageRunner._log.name == "hydraflow.triage"

    def test_inherits_execute_method(self) -> None:
        """TriageRunner should inherit _execute from BaseRunner."""
        assert hasattr(TriageRunner, "_execute")
        # _execute should come from BaseRunner, not be overridden
        assert TriageRunner._execute is BaseRunner._execute

    def test_inherits_save_transcript_method(self) -> None:
        """TriageRunner should inherit _save_transcript from BaseRunner."""
        assert hasattr(TriageRunner, "_save_transcript")
        assert TriageRunner._save_transcript is BaseRunner._save_transcript


class TestTriageSaveTranscript:
    """Tests that TriageRunner saves LLM transcripts to disk via _save_transcript."""

    @pytest.mark.asyncio
    async def test_save_transcript_called_after_llm_evaluation(
        self, runner: TriageRunner, mock_runner: AsyncMock
    ) -> None:
        """_save_transcript should be called with the LLM transcript after evaluation."""
        issue = TaskFactory.create(
            id=77,
            title="Implement feature X for module Y",
            body="Detailed description of what needs to happen. " * 3,
        )
        stdout = _make_llm_verdict(ready=True)
        mock_runner.create_streaming_process = make_streaming_proc(stdout=stdout)

        with unittest.mock.patch.object(runner, "_save_transcript") as mock_save:
            await runner.evaluate(issue)
            mock_save.assert_called_once()
            call_args = mock_save.call_args[0]
            assert call_args[0] == "triage-issue"
            assert call_args[1] == 77
