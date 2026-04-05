"""Tests for the expert council voting system."""

from __future__ import annotations

from expert_council import CouncilResult, CouncilVote, ExpertCouncil


class TestCouncilVote:
    def test_direction_uppercased(self) -> None:
        vote = CouncilVote("User Advocate", "b", "Good UX", 8)
        assert vote.direction == "B"

    def test_confidence_clamped(self) -> None:
        vote = CouncilVote("Expert", "A", "reason", 15)
        assert vote.confidence == 10
        vote2 = CouncilVote("Expert", "A", "reason", -5)
        assert vote2.confidence == 1

    def test_to_dict(self) -> None:
        vote = CouncilVote("Tech Lead", "C", "Feasible", 7)
        d = vote.to_dict()
        assert d["expert"] == "Tech Lead"
        assert d["direction"] == "C"
        assert d["confidence"] == 7


class TestCouncilResult:
    def test_consensus_with_2_of_3_agreeing(self) -> None:
        votes = [
            CouncilVote("User Advocate", "B", "Best UX", 8),
            CouncilVote("Tech Lead", "B", "Feasible", 7),
            CouncilVote("Strategist", "A", "Better market fit", 6),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is True
        assert result.winning_direction == "B"

    def test_no_consensus_with_3_way_split(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 5),
            CouncilVote("Tech Lead", "B", "reason", 5),
            CouncilVote("Strategist", "C", "reason", 5),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is False
        assert result.winning_direction is None

    def test_unanimous_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 9),
            CouncilVote("Tech Lead", "A", "reason", 8),
            CouncilVote("Strategist", "A", "reason", 7),
        ]
        result = CouncilResult(votes)
        assert result.has_consensus is True
        assert result.winning_direction == "A"
        assert result.avg_confidence == 8.0

    def test_format_summary_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "B", "Best UX", 8),
            CouncilVote("Tech Lead", "B", "Feasible", 7),
            CouncilVote("Strategist", "A", "Market fit", 6),
        ]
        result = CouncilResult(votes)
        summary = result.format_summary()
        assert "Expert Council Vote" in summary
        assert "Consensus reached" in summary
        assert "Direction B" in summary

    def test_format_summary_no_consensus(self) -> None:
        votes = [
            CouncilVote("User Advocate", "A", "reason", 5),
            CouncilVote("Tech Lead", "B", "reason", 5),
            CouncilVote("Strategist", "C", "reason", 5),
        ]
        result = CouncilResult(votes)
        summary = result.format_summary()
        assert "No consensus" in summary
        assert "tiebreaker" in summary


class TestParseVote:
    def test_parses_valid_vote(self) -> None:
        transcript = """Some preamble.

COUNCIL_VOTE_START

```json
{"direction": "B", "reasoning": "Great UX potential", "confidence": 8}
```

COUNCIL_VOTE_END
"""
        vote = ExpertCouncil._parse_vote(transcript, "User Advocate")
        assert vote is not None
        assert vote.direction == "B"
        assert vote.confidence == 8

    def test_returns_none_without_markers(self) -> None:
        vote = ExpertCouncil._parse_vote("no markers here", "Expert")
        assert vote is None

    def test_returns_none_with_bad_json(self) -> None:
        transcript = "COUNCIL_VOTE_START\n```json\n{bad}\n```\nCOUNCIL_VOTE_END"
        vote = ExpertCouncil._parse_vote(transcript, "Expert")
        assert vote is None
