"""Tests for plan_scoring.py — actionability scoring for plans."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plan_scoring import score_actionability


def _valid_plan(*, word_pad: int = 200) -> str:
    """Plan with Task Graph, Implementation Steps, File Delta, Testing Strategy."""
    padding = " ".join(["word"] * max(0, word_pad - 80))
    return (
        "## Files to Modify\n\n"
        "- src/models.py \u2014 add new data model\n"
        "- src/config.py \u2014 add configuration field\n\n"
        "## New Files\n\n"
        "- src/widget.py \u2014 new widget module\n\n"
        "## File Delta\n\n"
        "```\n"
        "MODIFIED: src/models.py\n"
        "MODIFIED: src/config.py\n"
        "ADDED: src/widget.py\n"
        "```\n\n"
        "## Task Graph\n\n"
        "### P1 \u2014 Data Model\n"
        "**Files:** src/models.py (modify)\n"
        "**Tests:**\n"
        "- Creating a new model instance persists and returns an id\n"
        "- Invalid fields raise ValidationError\n"
        "**Depends on:** (none)\n\n"
        "### P2 \u2014 Configuration\n"
        "**Files:** src/config.py (modify)\n"
        "**Tests:**\n"
        "- Config field accepts valid values\n"
        "- Config field rejects invalid values\n"
        "**Depends on:** P1\n\n"
        "## Implementation Steps\n\n"
        "1. Add the data model to src/models.py with proper validation\n"
        "2. Add configuration field to src/config.py for the new model\n"
        "3. Write comprehensive tests in tests/test_models.py\n\n"
        "## Testing Strategy\n\n"
        "- tests/test_models.py \u2014 unit tests for new model\n"
        "- tests/test_config.py \u2014 config field tests\n\n"
        "## Acceptance Criteria\n\n"
        "- New model persists correctly\n"
        "- Configuration field works\n\n"
        "## Key Considerations\n\n"
        "- Backward compatibility with existing models\n"
        f"- {padding}\n"
    )


class TestScoreActionability:
    def test_high_score_for_complete_plan(self):
        score, rank = score_actionability(_valid_plan(), scale="full")
        assert score >= 85
        assert rank == "high"

    def test_low_score_for_shallow_plan(self):
        shallow_plan = (
            "## Files to Modify\n\nSome files\n\n"
            "## New Files\n\nNone\n\n"
            "## File Delta\n\nNo delta\n\n"
            "## Task Graph\n\nNo graph\n\n"
            "## Implementation Steps\n\n1. Do it\n\n"
            "## Testing Strategy\n\nSome tests\n\n"
            "## Acceptance Criteria\n\nIt works\n\n"
            "## Key Considerations\n\nNone\n"
        )
        score, rank = score_actionability(shallow_plan, scale="full")
        assert score < 65
        assert rank == "low"

    def test_medium_score(self):
        # Steps have a concrete target but one is shallow (< 3 words),
        # dropping the no-shallow bonus (-10) to reach medium range.
        plan = (
            "## Files to Modify\n\n"
            "- src/models.py \u2014 add model\n\n"
            "## New Files\n\nNone\n\n"
            "## File Delta\n\nNo delta\n\n"
            "## Task Graph\n\nNo phases defined\n\n"
            "## Implementation Steps\n\n"
            "1. Update the data model in src/models.py with validation logic\n"
            "2. Fix it\n\n"
            "## Testing Strategy\n\n"
            "- tests/test_models.py for unit tests\n\n"
            "## Acceptance Criteria\n\nModel works\n\n"
            "## Key Considerations\n\nNone\n"
        )
        score, rank = score_actionability(plan, scale="full")
        assert 65 <= score < 85
        assert rank == "medium"

    def test_lite_scale_scores_implementation_steps(self):
        lite_plan = (
            "## Files to Modify\n\n"
            "- src/main.py \u2014 fix typo\n\n"
            "## Implementation Steps\n\n"
            "1. Fix the typo in src/main.py in the function definition\n\n"
            "## Testing Strategy\n\n"
            "- tests/test_main.py \u2014 verify fix\n"
        )
        score, rank = score_actionability(lite_plan, scale="lite")
        assert score > 0

    def test_file_delta_contributes_points(self):
        plan_without_delta = (
            "## Implementation Steps\n\n"
            "1. Do something in src/models.py with the data model updates\n"
            "2. Add tests in tests/test_models.py for full coverage\n\n"
            "## Testing Strategy\n\n"
            "- tests/test_models.py for testing\n"
        )
        plan_with_delta = (
            plan_without_delta + "\n## File Delta\n\n"
            "```\nMODIFIED: src/models.py\n```\n"
        )
        score_without, _ = score_actionability(plan_without_delta, scale="full")
        score_with, _ = score_actionability(plan_with_delta, scale="full")
        assert score_with > score_without
