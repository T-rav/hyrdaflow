"""Tests for the ADRCouncilReviewer."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from adr_reviewer import ADRCouncilReviewer
from models import ADRCouncilResult, CouncilVerdict, CouncilVote
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_triage_phase, supply_once


def _make_reviewer(
    tmp_path: Path,
    *,
    adr_review_enabled: bool = True,
    adr_review_approval_threshold: int = 2,
    adr_review_max_rounds: int = 3,
) -> ADRCouncilReviewer:
    """Build an ADRCouncilReviewer with test-friendly defaults."""
    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        adr_review_enabled=adr_review_enabled,
        adr_review_approval_threshold=adr_review_approval_threshold,
        adr_review_max_rounds=adr_review_max_rounds,
    )
    from events import EventBus

    bus = EventBus()
    prs = MagicMock()
    prs.create_issue = AsyncMock(return_value=42)
    runner = MagicMock()
    return ADRCouncilReviewer(config, bus, prs, runner)


def _write_adr(
    adr_dir: Path, number: int, title: str, status: str, decision: str = ""
) -> Path:
    """Write a sample ADR file."""
    adr_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{number:04d}-{title.lower().replace(' ', '-')}.md"
    path = adr_dir / filename
    content = f"""# ADR-{number:04d}: {title}

**Status:** {status}

## Context

Some context.

## Decision

{decision or "We decided to do the thing."}

## Consequences

Some consequences.
"""
    path.write_text(content, encoding="utf-8")
    return path


class TestFindProposedADRs:
    """Tests for _find_proposed_adrs."""

    def test_empty_dir(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        reviewer = _make_reviewer(tmp_path)
        assert reviewer._find_proposed_adrs(adr_dir) == []

    def test_finds_proposed_only(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "First ADR", "Proposed")
        _write_adr(adr_dir, 2, "Second ADR", "Accepted")
        _write_adr(adr_dir, 3, "Third ADR", "Proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 2
        assert result[0][0] == 1
        assert result[1][0] == 3

    def test_filters_non_adr_files(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, 1, "Valid ADR", "Proposed")
        # Write a non-ADR file
        (adr_dir / "README.md").write_text("# ADRs\n\n**Status:** Proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_case_insensitive_status(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "First", "proposed")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 1

    def test_skips_unreadable_files(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        _write_adr(adr_dir, 1, "Good ADR", "Proposed")
        # Write a binary file with ADR naming pattern
        bad_path = adr_dir / "0002-bad.md"
        bad_path.write_bytes(b"\x80\x81\x82\xff\xfe")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._find_proposed_adrs(adr_dir)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_superseded_adr_not_in_proposed(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "Old ADR", "Superseded")
        _write_adr(adr_dir, 2, "New ADR", "Proposed")
        reviewer = _make_reviewer(tmp_path)

        proposed = reviewer._find_proposed_adrs(adr_dir)
        assert len(proposed) == 1
        assert proposed[0][0] == 2

        all_adrs = reviewer._load_all_adrs(adr_dir)
        assert {entry[0] for entry in all_adrs} == {1, 2}

    def test_old_compound_status_not_treated_as_proposed(self, tmp_path: Path) -> None:
        """Regression: 'Superseded by #1883' must not match as Proposed."""
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True, exist_ok=True)
        # Simulate the pre-fix ADR-0020 format with embedded issue reference
        old_style = adr_dir / "0001-old-style.md"
        old_style.write_text(
            "# ADR-0001: Old Style\n\n**Status:** Superseded by #1883\n\n"
            "## Context\nOld.\n\n## Decision\nDone.\n\n## Consequences\nNone.\n",
            encoding="utf-8",
        )
        reviewer = _make_reviewer(tmp_path)
        proposed = reviewer._find_proposed_adrs(adr_dir)
        assert proposed == [], "Old compound status should not be matched as Proposed"

        # Also verify the index context shows 'Superseded' not the compound form
        all_adrs = reviewer._load_all_adrs(adr_dir)
        index = reviewer._build_index_context(all_adrs)
        assert "Status: Superseded" in index
        assert "by #1883" not in index


class TestLoadAllADRs:
    """Tests for _load_all_adrs."""

    def test_skips_unreadable_files(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 1, "Good ADR", "Proposed")
        bad_path = adr_dir / "0002-bad.md"
        bad_path.write_bytes(b"\x80\x81\x82\xff\xfe")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._load_all_adrs(adr_dir)
        assert len(result) == 1
        assert result[0][0] == 1

    def test_extracts_title_from_filename(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 5, "Use Docker Containers", "Accepted")
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._load_all_adrs(adr_dir)
        assert result[0][1] == "use docker containers"


class TestBuildIndexContext:
    """Tests for _build_index_context."""

    def test_empty_list(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._build_index_context([])
        assert result == "No existing ADRs found."

    def test_unknown_status(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [(1, "No Status ADR", "No status field in content")]
        result = reviewer._build_index_context(all_adrs)
        assert "Unknown" in result

    def test_formats_multiple_adrs(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "First", "**Status:** Accepted"),
            (2, "Second", "**Status:** Proposed"),
        ]
        result = reviewer._build_index_context(all_adrs)
        assert "ADR-0001" in result
        assert "ADR-0002" in result
        assert "Accepted" in result
        assert "Proposed" in result

    def test_build_index_context_shows_superseded_status(self, tmp_path: Path) -> None:
        adr_dir = tmp_path / "docs" / "adr"
        _write_adr(adr_dir, 5, "Superseded ADR", "Superseded")
        reviewer = _make_reviewer(tmp_path)
        all_adrs = reviewer._load_all_adrs(adr_dir)
        result = reviewer._build_index_context(all_adrs)
        assert "Status: Superseded" in result


class TestDuplicateDetection:
    """Tests for _detect_duplicates."""

    def test_identical_titles(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (
                1,
                "use docker for isolation",
                "# Use Docker for Isolation\n\n## Decision\nUse Docker.",
            ),
            (
                2,
                "use docker for isolation",
                "# Use Docker for Isolation\n\n## Decision\nUse Docker containers.",
            ),
        ]
        content = "# Use Docker for Isolation\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 1
        assert result[0][0] == 2
        assert result[0][2] >= 0.7

    def test_different_adrs_no_duplicates(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "use docker", "# Use Docker\n\n## Decision\nUse Docker."),
            (
                2,
                "adopt typescript",
                "# Adopt TypeScript\n\n## Decision\nSwitch to TypeScript.",
            ),
        ]
        content = "# Use Docker\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 0

    def test_self_exclusion(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "use docker", "# Use Docker\n\n## Decision\nUse Docker."),
        ]
        content = "# Use Docker\n\n## Decision\nUse Docker."
        result = reviewer._detect_duplicates(1, content, all_adrs)
        assert len(result) == 0

    def test_threshold_boundary(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        all_adrs = [
            (1, "a", "# A\n\n## Decision\nX"),
            (
                2,
                "completely different thing entirely",
                "# Completely Different Thing Entirely\n\n## Decision\nY something else entirely different",
            ),
        ]
        content = "# A\n\n## Decision\nX"
        result = reviewer._detect_duplicates(1, content, all_adrs)
        # Titles "A" and "Completely Different Thing Entirely" should be below threshold
        assert len(result) == 0


class TestBuildOrchestratorPrompt:
    """Tests for _build_orchestrator_prompt."""

    def test_contains_role_instructions(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt("ADR content", "index", "no dupes")
        assert "Architect" in prompt
        assert "Pragmatist" in prompt
        assert "Editor" in prompt

    def test_contains_adr_content(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "My ADR content here", "index", "no dupes"
        )
        assert "My ADR content here" in prompt

    def test_contains_index_context(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "content", "ADR-0001: Test", "no dupes"
        )
        assert "ADR-0001: Test" in prompt

    def test_contains_duplicate_warnings(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        prompt = reviewer._build_orchestrator_prompt(
            "content", "index", "duplicate of 0013"
        )
        assert "duplicate of 0013" in prompt

    def test_injects_max_rounds(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path, adr_review_max_rounds=5)
        prompt = reviewer._build_orchestrator_prompt("content", "index", "none")
        assert "up to 5 rounds" in prompt

    def test_injects_approval_threshold(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path, adr_review_approval_threshold=3)
        prompt = reviewer._build_orchestrator_prompt("content", "index", "none")
        assert ">= 3 APPROVE" in prompt


class TestParseCouncilResult:
    """Tests for _parse_council_result."""

    def _make_transcript(
        self,
        *,
        rounds: int = 1,
        architect: str = "APPROVE",
        pragmatist: str = "APPROVE",
        editor: str = "APPROVE",
        final: str = "ACCEPT",
        duplicate_of: str = "none",
        summary: str = "All agreed.",
        minority: str = "none",
    ) -> str:
        return f"""Some preamble text.

COUNCIL_RESULT:
rounds_needed: {rounds}
architect_verdict: {architect}
architect_reasoning: Architect thinks this is good
pragmatist_verdict: {pragmatist}
pragmatist_reasoning: Pragmatist agrees
editor_verdict: {editor}
editor_reasoning: Editor is fine with it
approve_count: 3
reject_count: 0
final_decision: {final}
summary: {summary}
duplicate_of: {duplicate_of}
minority_note: {minority}

Some trailing text."""

    def test_parse_unanimous_approve(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript()
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "ACCEPT"
        assert result.rounds_needed == 1
        assert len(result.votes) == 3
        assert all(v.verdict == CouncilVerdict.APPROVE for v in result.votes)

    def test_parse_reject(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="REJECT",
            pragmatist="REJECT",
            editor="REJECT",
            final="REJECT",
        )
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "REJECT"
        assert all(v.verdict == CouncilVerdict.REJECT for v in result.votes)

    def test_parse_request_changes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="REQUEST_CHANGES",
            pragmatist="APPROVE",
            editor="REQUEST_CHANGES",
            final="REQUEST_CHANGES",
        )
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.final_decision == "REQUEST_CHANGES"

    def test_parse_duplicate(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(
            architect="APPROVE",
            pragmatist="DUPLICATE",
            editor="APPROVE",
            final="DUPLICATE",
            duplicate_of="13",
        )
        result = reviewer._parse_council_result(transcript, 18, "Test ADR")
        assert result.duplicate_detected is True
        assert result.duplicate_of == 13
        assert result.final_decision == "DUPLICATE"

    def test_parse_multi_round(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = self._make_transcript(rounds=3)
        result = reviewer._parse_council_result(transcript, 1, "Test ADR")
        assert result.rounds_needed == 3
        assert len(result.all_round_votes) == 1  # Only final round in output block

    def test_missing_council_result_block(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = reviewer._parse_council_result("No result here", 1, "Test ADR")
        assert result.final_decision == "NO_CONSENSUS"

    def test_malformed_output_defaults_to_request_changes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: UNKNOWN_THING
pragmatist_verdict: ALSO_UNKNOWN
editor_verdict: NOPE
final_decision: SOMETHING_WEIRD
summary: unclear

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        # Unknown final decision should map to NO_CONSENSUS
        assert result.final_decision == "NO_CONSENSUS"
        # Unknown verdicts map to REQUEST_CHANGES
        assert all(v.verdict == CouncilVerdict.REQUEST_CHANGES for v in result.votes)

    def test_non_numeric_rounds_needed_defaults_to_one(self, tmp_path: Path) -> None:
        """Bug fix: non-numeric rounds_needed should not crash."""
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: three
architect_verdict: APPROVE
architect_reasoning: OK
pragmatist_verdict: APPROVE
pragmatist_reasoning: Fine
editor_verdict: APPROVE
editor_reasoning: Good
final_decision: ACCEPT
summary: All agree
duplicate_of: none
minority_note: none
"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 1
        assert result.final_decision == "ACCEPT"

    def test_blank_lines_in_council_result_block(self, tmp_path: Path) -> None:
        """Bug fix: blank lines in output should not truncate parsing."""
        reviewer = _make_reviewer(tmp_path)
        transcript = """Some preamble.

COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: APPROVE
architect_reasoning: Good structure

pragmatist_verdict: REJECT
pragmatist_reasoning: Not practical

editor_verdict: APPROVE
editor_reasoning: Clear
final_decision: ACCEPT
summary: Approved despite pragmatist dissent
duplicate_of: none
minority_note: Pragmatist dissented
"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        # Should still parse all fields despite blank lines
        assert result.final_decision == "ACCEPT"
        assert len(result.votes) == 3


class TestVerdictRouting:
    """Tests for _route_result."""

    @pytest.mark.asyncio
    async def test_approve_routes_to_accept(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="pragmatist", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}
        adr_path = tmp_path / "docs" / "adr" / "0001-test.md"
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        adr_path.write_text("**Status:** Proposed\n")

        with patch.object(
            reviewer, "_accept_adr", new_callable=AsyncMock
        ) as mock_accept:
            await reviewer._route_result(result, adr_path, adr_dir, stats)
            mock_accept.assert_awaited_once()
        assert stats["accepted"] == 1

    @pytest.mark.asyncio
    async def test_reject_routes_to_triage_first(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with (
            patch.object(
                reviewer, "_route_to_triage", new_callable=AsyncMock, return_value=True
            ) as mock_triage,
            patch.object(
                reviewer, "_escalate_to_hitl", new_callable=AsyncMock
            ) as mock_hitl,
        ):
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_triage.assert_awaited_once_with(result, reason="rejected")
            mock_hitl.assert_not_awaited()
        assert stats["rejected"] == 1

    @pytest.mark.asyncio
    async def test_request_changes_routes_to_triage_first(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REQUEST_CHANGES",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with (
            patch.object(
                reviewer,
                "_attempt_clerk_amend_and_revote",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_clerk,
            patch.object(
                reviewer, "_route_to_triage", new_callable=AsyncMock, return_value=True
            ) as mock_triage,
            patch.object(
                reviewer, "_escalate_to_hitl", new_callable=AsyncMock
            ) as mock_hitl,
        ):
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_clerk.assert_awaited_once()
            mock_triage.assert_awaited_once_with(result, reason="changes_requested")
            mock_hitl.assert_not_awaited()
        assert stats["escalated"] == 1

    @pytest.mark.asyncio
    async def test_duplicate_takes_priority(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Test",
            final_decision="ACCEPT",
            duplicate_detected=True,
            duplicate_of=13,
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(
                    role="pragmatist", verdict=CouncilVerdict.DUPLICATE, duplicate_of=13
                ),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with patch.object(
            reviewer, "_handle_duplicate", new_callable=AsyncMock
        ) as mock_dup:
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_dup.assert_awaited_once()
        assert stats["duplicates"] == 1
        assert stats["accepted"] == 0

    @pytest.mark.asyncio
    async def test_no_consensus_routes_to_triage_first(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="NO_CONSENSUS",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with (
            patch.object(
                reviewer, "_route_to_triage", new_callable=AsyncMock, return_value=True
            ) as mock_triage,
            patch.object(
                reviewer, "_escalate_to_hitl", new_callable=AsyncMock
            ) as mock_hitl,
        ):
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_triage.assert_awaited_once_with(result, reason="no_consensus")
            mock_hitl.assert_not_awaited()
        assert stats["escalated"] == 1

    @pytest.mark.asyncio
    async def test_triage_route_fallbacks_to_hitl_when_triage_fails(
        self, tmp_path: Path
    ) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REQUEST_CHANGES",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with (
            patch.object(
                reviewer,
                "_attempt_clerk_amend_and_revote",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_clerk,
            patch.object(
                reviewer, "_route_to_triage", new_callable=AsyncMock, return_value=False
            ) as mock_triage,
            patch.object(
                reviewer, "_escalate_to_hitl", new_callable=AsyncMock
            ) as mock_hitl,
        ):
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_clerk.assert_awaited_once()
            mock_triage.assert_awaited_once_with(result, reason="changes_requested")
            mock_hitl.assert_awaited_once_with(result, reason="changes_requested")
        assert stats["escalated"] == 1

    @pytest.mark.asyncio
    async def test_request_changes_auto_accepts_when_clerk_revote_passes(
        self, tmp_path: Path
    ) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REQUEST_CHANGES",
        )
        stats = {"accepted": 0, "rejected": 0, "escalated": 0, "duplicates": 0}

        with (
            patch.object(
                reviewer,
                "_attempt_clerk_amend_and_revote",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_clerk,
            patch.object(
                reviewer, "_route_to_triage", new_callable=AsyncMock
            ) as mock_triage,
            patch.object(
                reviewer, "_escalate_to_hitl", new_callable=AsyncMock
            ) as mock_hitl,
        ):
            await reviewer._route_result(result, MagicMock(), MagicMock(), stats)
            mock_clerk.assert_awaited_once()
            mock_triage.assert_not_awaited()
            mock_hitl.assert_not_awaited()
        assert stats["accepted"] == 1


class TestDeliberationRounds:
    """Tests for round count parsing and tracking."""

    def test_one_round_unanimous(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: APPROVE
architect_reasoning: Good
pragmatist_verdict: APPROVE
pragmatist_reasoning: Fine
editor_verdict: APPROVE
editor_reasoning: Clear
approve_count: 3
reject_count: 0
final_decision: ACCEPT
summary: Unanimous
duplicate_of: none
minority_note: none

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 1

    def test_two_round_convergence(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 2
architect_verdict: APPROVE
architect_reasoning: Changed mind
pragmatist_verdict: APPROVE
pragmatist_reasoning: Convinced
editor_verdict: APPROVE
editor_reasoning: Fine
approve_count: 3
reject_count: 0
final_decision: ACCEPT
summary: Converged in round 2
duplicate_of: none
minority_note: none

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 2
        assert len(result.all_round_votes) == 1

    def test_three_round_deadlock(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 3
architect_verdict: APPROVE
architect_reasoning: Still approve
pragmatist_verdict: REJECT
pragmatist_reasoning: Still reject
editor_verdict: REQUEST_CHANGES
editor_reasoning: Still unsure
approve_count: 1
reject_count: 1
final_decision: REQUEST_CHANGES
summary: Deadlocked after 3 rounds
duplicate_of: none
minority_note: Architect wanted to approve but was outvoted

"""
        result = reviewer._parse_council_result(transcript, 1, "Test")
        assert result.rounds_needed == 3
        assert result.final_decision == "REQUEST_CHANGES"


class TestAcceptADR:
    """Tests for _accept_adr."""

    @pytest.mark.asyncio
    async def test_updates_status_in_file(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Council approves",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
            ],
        )

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        content = adr_path.read_text(encoding="utf-8")
        assert "**Status:** Accepted" in content
        assert "**Status:** Proposed" not in content

    @pytest.mark.asyncio
    async def test_updates_readme_row(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        readme = adr_dir / "README.md"
        readme.write_text(
            "| Number | Title | Status |\n"
            "| 0001 | Test ADR | Proposed |\n"
            "| 0002 | Other | Accepted |\n"
        )
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Council approves",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
            ],
        )

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        readme_content = readme.read_text(encoding="utf-8")
        assert "Accepted" in readme_content.split("\n")[1]
        # Other rows unchanged
        assert "| 0002 | Other | Accepted |" in readme_content

    @pytest.mark.asyncio
    async def test_minority_note_included(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 1, "Test ADR", "Proposed")
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test ADR",
            final_decision="ACCEPT",
            summary="Majority approves",
            minority_note="Editor had concerns about formatting",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="Good"
                ),
                CouncilVote(
                    role="pragmatist", verdict=CouncilVerdict.APPROVE, reasoning="Fine"
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Formatting",
                ),
            ],
        )

        mock_run = AsyncMock()
        with patch("adr_reviewer.run_subprocess", mock_run):
            await reviewer._accept_adr(result, adr_path, adr_dir)

        # Check commit message includes minority note
        commit_calls = [
            c
            for c in mock_run.await_args_list
            if c.args[0] == "git" and c.args[1] == "commit"
        ]
        assert len(commit_calls) == 1
        commit_msg = commit_calls[0].args[3]
        assert "Minority note:" in commit_msg


class TestEscalateToHITL:
    """Tests for _escalate_to_hitl."""

    @pytest.mark.asyncio
    async def test_creates_issue_with_summary(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=5,
            adr_title="Bad ADR",
            final_decision="REJECT",
            rounds_needed=2,
            summary="Council rejects this ADR",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Too broad",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Not needed",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Well written",
                ),
            ],
        )

        await reviewer._escalate_to_hitl(result, reason="rejected")

        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        title = call_args.args[0]
        body = call_args.args[1]
        assert "ADR-0005" in title
        assert "rejection" in title.lower() or "reject" in title.lower()
        assert "Too broad" in body
        assert "Not needed" in body
        assert "Rounds needed" in body or "rounds_needed" in body.lower()

    @pytest.mark.asyncio
    async def test_reason_field_set_correctly(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1, adr_title="Test", final_decision="REQUEST_CHANGES"
        )

        await reviewer._escalate_to_hitl(result, reason="changes_requested")

        body = reviewer._prs.create_issue.await_args.args[1]
        assert "requests changes" in body.lower() or "changes" in body.lower()


class TestRouteToTriage:
    """Tests for _route_to_triage."""

    @pytest.mark.asyncio
    async def test_creates_find_labeled_issue(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=5,
            adr_title="Bad ADR",
            final_decision="REQUEST_CHANGES",
            summary="Needs revision",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Clarify scope",
                ),
            ],
        )
        reviewer._prs.create_issue = AsyncMock(return_value=123)

        routed = await reviewer._route_to_triage(result, reason="changes_requested")

        assert routed is True
        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        title = call_args.args[0]
        body = call_args.args[1]
        labels = call_args.kwargs["labels"]
        assert "[ADR Follow-up]" in title
        assert "ADR-0005" in body
        assert labels == reviewer._config.find_label

    @pytest.mark.asyncio
    async def test_returns_false_on_invalid_issue_number(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        reviewer._prs.create_issue = AsyncMock(return_value=0)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
        )

        routed = await reviewer._route_to_triage(result, reason="rejected")

        assert routed is False


class TestADRTriageIntegration:
    """Integration-style coverage for ADR council -> triage routing behavior."""

    @pytest.mark.asyncio
    async def test_request_changes_routes_to_triage_then_plan_when_ready(
        self, tmp_path: Path
    ) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=12,
            adr_title="Rework council handling",
            final_decision="REQUEST_CHANGES",
            summary="Needs implementation adjustments",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Adjust pipeline routing",
                ),
            ],
        )

        # Step 1: ADR council routes rework into triage queue.
        reviewer._prs.create_issue = AsyncMock(return_value=321)
        routed = await reviewer._route_to_triage(result, reason="changes_requested")
        assert routed is True
        reviewer._prs.create_issue.assert_awaited_once()

        created_title = reviewer._prs.create_issue.await_args.args[0]
        created_body = reviewer._prs.create_issue.await_args.args[1]
        created_labels = reviewer._prs.create_issue.await_args.kwargs["labels"]
        assert "ADR-0012" in created_title
        assert "Council Summary" in created_body
        assert created_labels == reviewer._config.find_label

        # Step 2: triage picks the created issue and sends it to planning.
        triage_phase, _state, triage_runner, prs, store, _stop = make_triage_phase(
            reviewer._config
        )
        from models import TriageResult

        triage_task = TaskFactory.create(
            id=321,
            title=created_title,
            body=created_body,
            tags=list(reviewer._config.find_label),
        )
        triage_runner.evaluate = AsyncMock(
            return_value=TriageResult(issue_number=321, ready=True)
        )
        store.get_triageable = supply_once([triage_task])

        processed = await triage_phase.triage_issues()
        assert processed == 1
        prs.transition.assert_called_once_with(321, "plan")
        prs.swap_pipeline_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_request_changes_routes_to_hitl_when_triage_not_ready(
        self, tmp_path: Path
    ) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=22,
            adr_title="Unclear proposal",
            final_decision="REQUEST_CHANGES",
        )
        reviewer._prs.create_issue = AsyncMock(return_value=654)
        routed = await reviewer._route_to_triage(result, reason="changes_requested")
        assert routed is True

        triage_phase, state, triage_runner, prs, store, _stop = make_triage_phase(
            reviewer._config
        )
        from models import TriageResult

        triage_task = TaskFactory.create(
            id=654,
            title="[ADR Follow-up] ADR-0022: Council requests changes",
            body="Needs more details before planning.",
            tags=list(reviewer._config.find_label),
        )
        triage_runner.evaluate = AsyncMock(
            return_value=TriageResult(
                issue_number=654,
                ready=False,
                reasons=["Missing concrete implementation details"],
            )
        )
        store.get_triageable = supply_once([triage_task])

        processed = await triage_phase.triage_issues()
        assert processed == 1
        prs.swap_pipeline_labels.assert_called_once_with(
            654, reviewer._config.hitl_label[0]
        )
        assert state.get_hitl_origin(654) == reviewer._config.find_label[0]


class TestClerkAmendment:
    """Tests for clerk amendment + re-vote behavior."""

    @pytest.mark.asyncio
    async def test_clerk_revote_accepts_and_commits(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 9, "Council Edits", "Proposed")
        original_result = ADRCouncilResult(
            adr_number=9,
            adr_title="Council Edits",
            final_decision="REQUEST_CHANGES",
            summary="Needs refinements",
            votes=[
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Clarify tradeoffs",
                )
            ],
        )
        rerun_result = ADRCouncilResult(
            adr_number=9,
            adr_title="Council Edits",
            final_decision="ACCEPT",
            summary="Looks good now",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Accept",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Accept",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Accept",
                ),
            ],
        )
        reviewer._run_council_session = AsyncMock(return_value=rerun_result)

        with patch.object(
            reviewer, "_accept_adr", new_callable=AsyncMock
        ) as mock_accept:
            accepted = await reviewer._attempt_clerk_amend_and_revote(
                original_result, adr_path, adr_dir
            )
            assert accepted is True
            mock_accept.assert_awaited_once_with(rerun_result, adr_path, adr_dir)

        updated = adr_path.read_text(encoding="utf-8")
        assert "## Council Amendment Notes" in updated
        assert "Clarify tradeoffs" in updated

    @pytest.mark.asyncio
    async def test_clerk_revote_non_accept_falls_back(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 10, "Council Edits", "Proposed")
        original = adr_path.read_text(encoding="utf-8")
        original_result = ADRCouncilResult(
            adr_number=10,
            adr_title="Council Edits",
            final_decision="REQUEST_CHANGES",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Need narrower scope",
                )
            ],
        )
        reviewer._run_council_session = AsyncMock(
            return_value=ADRCouncilResult(
                adr_number=10,
                adr_title="Council Edits",
                final_decision="REQUEST_CHANGES",
            )
        )

        with patch.object(
            reviewer, "_accept_adr", new_callable=AsyncMock
        ) as mock_accept:
            accepted = await reviewer._attempt_clerk_amend_and_revote(
                original_result, adr_path, adr_dir
            )
            assert accepted is False
            mock_accept.assert_not_awaited()

        assert adr_path.read_text(encoding="utf-8") == original

    @pytest.mark.asyncio
    async def test_clerk_self_review_blocks_revote(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "repo" / "docs" / "adr"
        adr_path = _write_adr(adr_dir, 11, "Council Edits", "Proposed")
        result = ADRCouncilResult(
            adr_number=11,
            adr_title="Council Edits",
            final_decision="REQUEST_CHANGES",
            votes=[
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Clarify migration safety",
                )
            ],
        )

        reviewer._run_council_session = AsyncMock()
        with patch.object(
            reviewer,
            "_clerk_self_review",
            return_value=(False, "missing feedback items"),
        ) as mock_self_review:
            accepted = await reviewer._attempt_clerk_amend_and_revote(
                result,
                adr_path,
                adr_dir,
            )

        assert accepted is False
        mock_self_review.assert_called_once()
        reviewer._run_council_session.assert_not_awaited()

    def test_clerk_self_review_detects_missing_feedback(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        original = (
            "# ADR-0012: Test\n\n"
            "**Status:** Proposed\n\n"
            "## Context\n\nA\n\n"
            "## Decision\n\nB\n\n"
            "## Consequences\n\nC\n"
        )
        amended = (
            "# ADR-0012: Test\n\n"
            "**Status:** Proposed\n\n"
            "## Context\n\nA\n\n"
            "## Decision\n\nB\n\n"
            "## Consequences\n\nC\n\n"
            "## Council Amendment Notes\n\n"
            "- Editor: generic note"
        )
        result = ADRCouncilResult(
            adr_number=12,
            adr_title="Test",
            final_decision="REQUEST_CHANGES",
            votes=[
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.REQUEST_CHANGES,
                    reasoning="Need explicit rollback strategy",
                )
            ],
        )

        ok, note = reviewer._clerk_self_review(
            original=original,
            amended=amended,
            result=result,
        )

        assert ok is False
        assert "missing feedback items" in note


class TestHandleDuplicate:
    """Tests for _handle_duplicate."""

    @pytest.mark.asyncio
    async def test_creates_duplicate_issue(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Duplicate Thing",
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=13,
            votes=[
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.DUPLICATE,
                    duplicate_of=13,
                    reasoning="Same as ADR-13",
                ),
            ],
        )

        await reviewer._handle_duplicate(result)

        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        body = call_args.args[1]
        assert "0018" in body or "18" in body
        assert "0013" in body or "13" in body

    @pytest.mark.asyncio
    async def test_duplicate_of_populated(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Dup",
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=13,
        )

        await reviewer._handle_duplicate(result)

        body = reviewer._prs.create_issue.await_args.args[1]
        assert "ADR-0013" in body

    @pytest.mark.asyncio
    async def test_duplicate_of_none_does_not_crash(self, tmp_path: Path) -> None:
        """Bug fix: duplicate_of=None should not cause TypeError on :04d format."""
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=18,
            adr_title="Mystery Dup",
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=None,
        )

        await reviewer._handle_duplicate(result)

        reviewer._prs.create_issue.assert_awaited_once()
        call_args = reviewer._prs.create_issue.await_args
        title = call_args.args[0]
        body = call_args.args[1]
        assert "0018" in body
        assert "unknown" in body.lower()
        assert "ADR-0018" in title or "0018" in title


class TestExecuteOrchestrator:
    """Tests for _execute_orchestrator."""

    @pytest.mark.asyncio
    async def test_claude_tool(self, tmp_path: Path) -> None:
        """Default tool uses claude CLI."""
        reviewer = _make_reviewer(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "COUNCIL_RESULT:\nfinal_decision: ACCEPT"
        mock_result.stderr = ""
        reviewer._runner.run_simple = AsyncMock(return_value=mock_result)

        result = await reviewer._execute_orchestrator("test prompt")

        assert result == "COUNCIL_RESULT:\nfinal_decision: ACCEPT"
        call_args = reviewer._runner.run_simple.call_args
        cmd = call_args.args[0]
        assert cmd[0] == "claude"
        assert "-p" in cmd
        # Prompt must be immediately after -p for the CLI to recognise it.
        p_idx = cmd.index("-p")
        assert not cmd[p_idx + 1].startswith("--"), "prompt must follow -p, not a flag"

    @pytest.mark.asyncio
    async def test_codex_tool(self, tmp_path: Path) -> None:
        """Codex tool uses codex exec."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            adr_review_enabled=True,
            background_tool="codex",
        )
        from events import EventBus

        reviewer = ADRCouncilReviewer(config, EventBus(), MagicMock(), MagicMock())
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""
        reviewer._runner.run_simple = AsyncMock(return_value=mock_result)

        result = await reviewer._execute_orchestrator("prompt")

        assert result == "output"
        cmd = reviewer._runner.run_simple.call_args.args[0]
        assert cmd[0] == "codex"
        assert "exec" in cmd

    @pytest.mark.asyncio
    async def test_inherit_tool_defaults_to_claude(self, tmp_path: Path) -> None:
        """inherit tool should resolve to claude."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            adr_review_enabled=True,
            background_tool="inherit",
        )
        from events import EventBus

        reviewer = ADRCouncilReviewer(config, EventBus(), MagicMock(), MagicMock())
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "output"
        mock_result.stderr = ""
        reviewer._runner.run_simple = AsyncMock(return_value=mock_result)

        await reviewer._execute_orchestrator("prompt")

        cmd = reviewer._runner.run_simple.call_args.args[0]
        assert cmd[0] == "claude"

    @pytest.mark.asyncio
    async def test_nonzero_returncode_returns_none(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "Error happened"
        reviewer._runner.run_simple = AsyncMock(return_value=mock_result)

        result = await reviewer._execute_orchestrator("prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_stdout_returns_none(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""
        reviewer._runner.run_simple = AsyncMock(return_value=mock_result)

        result = await reviewer._execute_orchestrator("prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_timeout_returns_none(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        reviewer._runner.run_simple = AsyncMock(side_effect=TimeoutError)

        result = await reviewer._execute_orchestrator("prompt")

        assert result is None

    @pytest.mark.asyncio
    async def test_oserror_returns_none(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        reviewer._runner.run_simple = AsyncMock(
            side_effect=OSError("command not found")
        )

        result = await reviewer._execute_orchestrator("prompt")

        assert result is None


class TestRunCouncilSession:
    """Tests for _run_council_session."""

    @pytest.mark.asyncio
    async def test_none_transcript_returns_no_consensus(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        with patch.object(
            reviewer, "_execute_orchestrator", new_callable=AsyncMock, return_value=None
        ):
            result = await reviewer._run_council_session(
                1, "Test", "content", "index", "no dupes"
            )
        assert result.final_decision == "NO_CONSENSUS"
        assert result.adr_number == 1

    @pytest.mark.asyncio
    async def test_valid_transcript_parses(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        transcript = """COUNCIL_RESULT:
rounds_needed: 1
architect_verdict: APPROVE
architect_reasoning: Good
pragmatist_verdict: APPROVE
pragmatist_reasoning: Fine
editor_verdict: APPROVE
editor_reasoning: Clear
final_decision: ACCEPT
summary: All agree
duplicate_of: none
minority_note: none
"""
        with patch.object(
            reviewer,
            "_execute_orchestrator",
            new_callable=AsyncMock,
            return_value=transcript,
        ):
            result = await reviewer._run_council_session(
                1, "Test", "content", "index", "no dupes"
            )
        assert result.final_decision == "ACCEPT"
        assert result.rounds_needed == 1


class TestAcceptADREdgeCases:
    """Additional edge case tests for _accept_adr."""

    @pytest.mark.asyncio
    async def test_unreadable_file_returns_early(self, tmp_path: Path) -> None:
        """Bug fix: unreadable ADR file should not crash."""
        reviewer = _make_reviewer(tmp_path)
        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        adr_path = adr_dir / "0001-test.md"
        # Write binary content that can't be decoded as UTF-8
        adr_path.write_bytes(b"\x80\x81\x82\xff\xfe")
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            summary="Approved",
            votes=[CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE)],
        )

        # Should not raise
        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock) as mock_run:
            await reviewer._accept_adr(result, adr_path, adr_dir)
            # Should not reach commit since file couldn't be read
            mock_run.assert_not_awaited()


class TestCommitAcceptance:
    """Tests for _commit_acceptance."""

    @pytest.mark.asyncio
    async def test_dry_run_skips_git_ops(self, tmp_path: Path) -> None:
        """Bug fix: dry_run should skip all git operations."""
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            adr_review_enabled=True,
            dry_run=True,
        )
        from events import EventBus

        reviewer = ADRCouncilReviewer(config, EventBus(), MagicMock(), MagicMock())
        result = ADRCouncilResult(
            adr_number=1, adr_title="Test", final_decision="ACCEPT", summary="OK"
        )

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock) as mock_run:
            await reviewer._commit_acceptance(
                tmp_path / "adr.md", tmp_path / "README.md", result
            )
            mock_run.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_git_failure_logs_and_returns(self, tmp_path: Path) -> None:
        """Worktree creation failure should be caught and logged."""
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1, adr_title="Test", final_decision="ACCEPT", summary="OK"
        )
        adr_path = tmp_path / "repo" / "docs" / "adr" / "0001-test.md"
        adr_path.parent.mkdir(parents=True)
        adr_path.write_text("**Status:** Accepted")

        with patch(
            "adr_reviewer.run_subprocess",
            new_callable=AsyncMock,
            side_effect=RuntimeError("git worktree add failed"),
        ):
            # Should not raise
            await reviewer._commit_acceptance(
                adr_path, tmp_path / "repo" / "docs" / "adr" / "README.md", result
            )

    @pytest.mark.asyncio
    async def test_pr_creation_failure_does_not_crash(self, tmp_path: Path) -> None:
        """PR creation failure after successful commit should be caught."""
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1, adr_title="Test", final_decision="ACCEPT", summary="OK"
        )
        adr_path = tmp_path / "repo" / "docs" / "adr" / "0001-test.md"
        adr_path.parent.mkdir(parents=True)
        adr_path.write_text("**Status:** Accepted")

        call_count = 0

        async def _mock_run(*args: object, **kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            # Last call is `gh pr create` — make it fail
            if call_count >= 6 and args[0] == "gh":
                raise RuntimeError("gh pr create failed")

        with patch("adr_reviewer.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.side_effect = _mock_run
            # Should not raise
            await reviewer._commit_acceptance(
                adr_path, tmp_path / "repo" / "docs" / "adr" / "README.md", result
            )


class TestTitleTruncation:
    """Tests for title truncation in escalation and duplicate methods."""

    @pytest.mark.asyncio
    async def test_escalation_title_truncated(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
        )
        # Use a custom reason that, combined with prefix, exceeds 70 chars
        await reviewer._escalate_to_hitl(
            result,
            reason="a_very_long_custom_reason_that_makes_the_title_exceed_seventy_characters",
        )

        title = reviewer._prs.create_issue.await_args.args[0]
        assert len(title) <= 70
        assert title.endswith("...")

    @pytest.mark.asyncio
    async def test_duplicate_title_within_bounds(self, tmp_path: Path) -> None:
        """Duplicate issue titles stay within 70 chars."""
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="A" * 100,
            final_decision="DUPLICATE",
            duplicate_detected=True,
            duplicate_of=2,
        )

        await reviewer._handle_duplicate(result)

        title = reviewer._prs.create_issue.await_args.args[0]
        assert len(title) <= 70


class TestBuildCouncilSummary:
    """Tests for _build_council_summary."""

    def test_multi_round_format(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            rounds_needed=2,
            final_decision="ACCEPT",
            summary="Converged after discussion",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Good structure",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Practical",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Well written",
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "ACCEPT" in summary
        assert "2" in summary  # rounds_needed
        assert "Architect" in summary
        assert "Pragmatist" in summary
        assert "Editor" in summary
        assert "Good structure" in summary

    def test_minority_notes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            minority_note="Editor had concerns",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="OK"
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "Editor had concerns" in summary

    def test_per_judge_reasoning(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
            votes=[
                CouncilVote(
                    role="architect",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Too narrow scope",
                ),
                CouncilVote(
                    role="pragmatist",
                    verdict=CouncilVerdict.REJECT,
                    reasoning="Already covered",
                ),
                CouncilVote(
                    role="editor",
                    verdict=CouncilVerdict.APPROVE,
                    reasoning="Clear prose",
                ),
            ],
        )

        summary = reviewer._build_council_summary(result)
        assert "Too narrow scope" in summary
        assert "Already covered" in summary
        assert "Clear prose" in summary


class TestBuildCouncilSummaryEdgeCases:
    """Edge case tests for _build_council_summary."""

    def test_no_minority_note(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="ACCEPT",
            minority_note="none",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.APPROVE, reasoning="OK"
                ),
            ],
        )
        summary = reviewer._build_council_summary(result)
        assert "Minority Note" not in summary

    def test_no_summary(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="REJECT",
            summary="",
            votes=[
                CouncilVote(
                    role="architect", verdict=CouncilVerdict.REJECT, reasoning="Bad"
                ),
            ],
        )
        summary = reviewer._build_council_summary(result)
        assert "### Summary" not in summary

    def test_no_votes(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        result = ADRCouncilResult(
            adr_number=1,
            adr_title="Test",
            final_decision="NO_CONSENSUS",
            votes=[],
        )
        summary = reviewer._build_council_summary(result)
        assert "NO_CONSENSUS" in summary


class TestReviewProposedADRs:
    """Integration-level tests for review_proposed_adrs."""

    @pytest.mark.asyncio
    async def test_no_adr_directory(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        stats = await reviewer.review_proposed_adrs()
        assert stats["reviewed"] == 0

    @pytest.mark.asyncio
    async def test_no_proposed_adrs(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, 1, "Accepted ADR", "Accepted")
        stats = await reviewer.review_proposed_adrs()
        assert stats["reviewed"] == 0

    @pytest.mark.asyncio
    async def test_reviews_proposed_adrs(self, tmp_path: Path) -> None:
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, 1, "Proposed ADR", "Proposed")

        accept_result = ADRCouncilResult(
            adr_number=1,
            adr_title="proposed adr",
            final_decision="ACCEPT",
            votes=[
                CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="pragmatist", verdict=CouncilVerdict.APPROVE),
                CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
            ],
        )
        with (
            patch.object(
                reviewer,
                "_run_council_session",
                new_callable=AsyncMock,
                return_value=accept_result,
            ),
            patch.object(reviewer, "_accept_adr", new_callable=AsyncMock),
        ):
            stats = await reviewer.review_proposed_adrs()

        assert stats["reviewed"] == 1
        assert stats["accepted"] == 1

    @pytest.mark.asyncio
    async def test_multiple_adrs_mixed_outcomes(self, tmp_path: Path) -> None:
        """Integration test: multiple ADRs with different council outcomes."""
        reviewer = _make_reviewer(tmp_path)
        adr_dir = Path(reviewer._config.repo_root) / "docs" / "adr"
        _write_adr(adr_dir, 1, "Good ADR", "Proposed")
        _write_adr(adr_dir, 2, "Bad ADR", "Proposed")
        _write_adr(adr_dir, 3, "Duplicate ADR", "Proposed")
        _write_adr(adr_dir, 4, "Already Accepted", "Accepted")

        results = [
            ADRCouncilResult(
                adr_number=1,
                adr_title="good adr",
                final_decision="ACCEPT",
                votes=[
                    CouncilVote(role="architect", verdict=CouncilVerdict.APPROVE),
                    CouncilVote(role="pragmatist", verdict=CouncilVerdict.APPROVE),
                    CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
                ],
            ),
            ADRCouncilResult(
                adr_number=2,
                adr_title="bad adr",
                final_decision="REJECT",
                rounds_needed=2,
                votes=[
                    CouncilVote(role="architect", verdict=CouncilVerdict.REJECT),
                    CouncilVote(role="pragmatist", verdict=CouncilVerdict.REJECT),
                    CouncilVote(role="editor", verdict=CouncilVerdict.APPROVE),
                ],
            ),
            ADRCouncilResult(
                adr_number=3,
                adr_title="duplicate adr",
                final_decision="DUPLICATE",
                duplicate_detected=True,
                duplicate_of=1,
                votes=[
                    CouncilVote(
                        role="editor", verdict=CouncilVerdict.DUPLICATE, duplicate_of=1
                    ),
                ],
            ),
        ]

        call_idx = 0

        async def _mock_council(*_args: object, **_kwargs: object) -> ADRCouncilResult:
            nonlocal call_idx
            r = results[call_idx]
            call_idx += 1
            return r

        with (
            patch.object(reviewer, "_run_council_session", side_effect=_mock_council),
            patch.object(reviewer, "_accept_adr", new_callable=AsyncMock),
            patch.object(reviewer, "_escalate_to_hitl", new_callable=AsyncMock),
            patch.object(reviewer, "_handle_duplicate", new_callable=AsyncMock),
        ):
            stats = await reviewer.review_proposed_adrs()

        assert stats["reviewed"] == 3
        assert stats["accepted"] == 1
        assert stats["rejected"] == 1
        assert stats["duplicates"] == 1
        assert stats["rounds_total"] == 4  # 1 + 2 + 1
