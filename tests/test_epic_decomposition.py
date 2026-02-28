"""Tests for epic auto-decomposition parsing and triage integration."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import EpicDecompResult, NewIssueSpec, TriageResult
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


class TestParseDecomposition:
    """Tests for TriageRunner._parse_decomposition."""

    def _parse(self, transcript: str) -> EpicDecompResult:
        from triage import TriageRunner

        return TriageRunner._parse_decomposition(transcript)

    def test_direct_json(self) -> None:
        data = {
            "should_decompose": True,
            "epic_title": "Epic: Big Feature",
            "epic_body": "## Sub-issues\n\n- [ ] Child A\n- [ ] Child B",
            "children": [
                {"title": "Child A", "body": "Do A"},
                {"title": "Child B", "body": "Do B"},
            ],
            "reasoning": "Too complex for one pass",
        }
        result = self._parse(json.dumps(data))
        assert result.should_decompose is True
        assert result.epic_title == "Epic: Big Feature"
        assert len(result.children) == 2
        assert result.children[0].title == "Child A"
        assert result.children[1].body == "Do B"

    def test_code_fence_json(self) -> None:
        transcript = (
            "Here is my analysis:\n\n```json\n"
            + json.dumps(
                {
                    "should_decompose": True,
                    "epic_title": "Fenced",
                    "epic_body": "body",
                    "children": [{"title": "C1", "body": "B1"}],
                    "reasoning": "reason",
                }
            )
            + "\n```\n"
        )
        result = self._parse(transcript)
        assert result.should_decompose is True
        assert result.epic_title == "Fenced"
        assert len(result.children) == 1

    def test_no_decompose(self) -> None:
        data = {
            "should_decompose": False,
            "reasoning": "Issue is already scoped",
        }
        result = self._parse(json.dumps(data))
        assert result.should_decompose is False
        assert "already scoped" in result.reasoning

    def test_unparseable_returns_empty(self) -> None:
        result = self._parse("This is not JSON at all")
        assert result.should_decompose is False
        assert len(result.children) == 0

    def test_missing_children_key(self) -> None:
        data = {"should_decompose": True, "epic_title": "No kids"}
        result = self._parse(json.dumps(data))
        assert result.should_decompose is True
        assert len(result.children) == 0

    def test_malformed_children_skipped(self) -> None:
        data = {
            "should_decompose": True,
            "epic_title": "Mixed",
            "children": [
                {"title": "Good", "body": "ok"},
                "not a dict",
                {"no_title": True},
                {"title": "Also Good"},
            ],
        }
        result = self._parse(json.dumps(data))
        assert len(result.children) == 2
        assert result.children[0].title == "Good"
        assert result.children[1].title == "Also Good"


class TestBuildDecompositionPrompt:
    def test_contains_issue_info(self) -> None:
        from triage import TriageRunner

        task = TaskFactory.create(
            id=42, title="Big Feature", body="Complex description"
        )
        prompt = TriageRunner._build_decomposition_prompt(task)
        assert "Issue #42" in prompt
        assert "Big Feature" in prompt
        assert "Complex description" in prompt
        assert "should_decompose" in prompt


class TestMaybeDecompose:
    """Tests for TriagePhase._maybe_decompose."""

    def _make_phase(self, config, *, epic_manager=None):
        import asyncio

        from events import EventBus
        from issue_store import IssueStore
        from state import StateTracker
        from triage_phase import TriagePhase

        state = StateTracker(config.state_file)
        bus = EventBus()
        store = MagicMock(spec=IssueStore)
        prs = AsyncMock()
        triage = AsyncMock()
        stop_event = asyncio.Event()

        phase = TriagePhase(
            config,
            state,
            store,
            triage,
            prs,
            bus,
            stop_event,
            epic_manager=epic_manager,
        )
        return phase, state, prs, triage

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, config) -> None:
        phase, _, prs, _ = self._make_phase(config)
        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=9)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is False
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_no_epic_manager(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_auto_decompose=True,
        )
        phase, _, prs, _ = self._make_phase(config, epic_manager=None)
        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=9)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is False

    @pytest.mark.asyncio
    async def test_skips_low_complexity(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_auto_decompose=True,
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        phase, _, prs, _ = self._make_phase(config, epic_manager=mgr)
        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=5)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is False

    @pytest.mark.asyncio
    async def test_decomposes_high_complexity(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_auto_decompose=True,
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        mgr.register_epic = AsyncMock()

        phase, state, prs, triage = self._make_phase(config, epic_manager=mgr)

        # Mock the triage runner's run_decomposition
        triage.run_decomposition = AsyncMock(
            return_value=EpicDecompResult(
                should_decompose=True,
                epic_title="Epic: Big Work",
                epic_body="## Sub-issues",
                children=[
                    NewIssueSpec(title="Child 1", body="Do 1"),
                    NewIssueSpec(title="Child 2", body="Do 2"),
                ],
                reasoning="Too complex",
            )
        )
        phase._triage = triage

        # Mock issue creation: epic gets #200, children get #201, #202
        prs.create_issue = AsyncMock(side_effect=[200, 201, 202])

        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=9)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is True

        # Epic issue created
        assert prs.create_issue.call_count == 3
        # Original issue closed
        prs.close_issue.assert_called_once_with(10)
        # Registered with EpicManager
        mgr.register_epic.assert_called_once_with(
            200,
            "Epic: Big Work",
            [201, 202],
            auto_decomposed=True,
        )

    @pytest.mark.asyncio
    async def test_skips_when_decomposition_declined(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_auto_decompose=True,
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        phase, _, prs, triage = self._make_phase(config, epic_manager=mgr)

        triage.run_decomposition = AsyncMock(
            return_value=EpicDecompResult(
                should_decompose=False,
                reasoning="Not appropriate",
            )
        )
        phase._triage = triage

        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=9)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is False
        prs.create_issue.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_too_few_children(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            state_file=tmp_path / "state.json",
            epic_auto_decompose=True,
            epic_decompose_complexity_threshold=8,
        )
        mgr = AsyncMock()
        phase, _, prs, triage = self._make_phase(config, epic_manager=mgr)

        triage.run_decomposition = AsyncMock(
            return_value=EpicDecompResult(
                should_decompose=True,
                epic_title="Tiny",
                children=[NewIssueSpec(title="Only One", body="")],
            )
        )
        phase._triage = triage

        task = TaskFactory.create(id=10)
        result = TriageResult(issue_number=10, ready=True, complexity_score=9)

        decomposed = await phase._maybe_decompose(task, result)
        assert decomposed is False
