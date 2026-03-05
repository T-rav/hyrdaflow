"""Tests for TriageResult parsing (issue_type normalisation)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from triage import TriageRunner

# ---------------------------------------------------------------------------
# TriageResult parsing tests
# ---------------------------------------------------------------------------


class TestTriageResultParsing:
    """Test _result_from_dict parses issue_type correctly."""

    def test_parses_issue_type_feature(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "feature"}, 1
        )
        assert result.issue_type == "feature"

    def test_parses_issue_type_bug(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": "bug"}, 1)
        assert result.issue_type == "bug"

    def test_parses_issue_type_epic(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "epic"}, 1
        )
        assert result.issue_type == "epic"

    def test_defaults_to_feature_when_missing(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True}, 1)
        assert result.issue_type == "feature"

    def test_normalises_unknown_to_feature(self) -> None:
        result = TriageRunner._result_from_dict(
            {"ready": True, "issue_type": "task"}, 1
        )
        assert result.issue_type == "feature"

    def test_normalises_none_to_feature(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": None}, 1)
        assert result.issue_type == "feature"

    def test_normalises_case_insensitive(self) -> None:
        result = TriageRunner._result_from_dict({"ready": True, "issue_type": "BUG"}, 1)
        assert result.issue_type == "bug"
