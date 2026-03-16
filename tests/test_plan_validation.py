"""Tests for plan_validation.py — plan structural and content validation."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from plan_validation import _significant_words, run_phase_gates, validate_plan
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _make_config(**overrides):
    return ConfigFactory.create(**overrides)


def _valid_plan(*, word_pad: int = 200) -> str:
    """Return a plan with all required sections that passes validation."""
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


# ---------------------------------------------------------------------------
# _significant_words
# ---------------------------------------------------------------------------


class TestSignificantWords:
    def test_extracts_long_words(self):
        words = _significant_words("Fix the broken authentication handler")
        assert "broken" in words
        assert "authentication" in words
        assert "handler" in words
        assert "the" not in words
        assert "fix" not in words

    def test_filters_stop_words(self):
        words = _significant_words("This should have been done with more care")
        assert "this" not in words
        assert "should" not in words
        assert "care" in words
        assert "done" in words

    def test_empty_string(self):
        assert _significant_words("") == set()


# ---------------------------------------------------------------------------
# validate_plan
# ---------------------------------------------------------------------------


class TestValidatePlan:
    def test_valid_plan_passes(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Add data model feature")
        errors = validate_plan(task, _valid_plan(), config=config)
        assert errors == []

    def test_missing_section(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Add feature")
        plan = _valid_plan().replace("## Key Considerations", "## Other")
        errors = validate_plan(task, plan, config=config)
        assert any("Key Considerations" in e for e in errors)

    def test_files_to_modify_requires_path(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Add feature")
        plan = _valid_plan().replace(
            "- src/models.py \u2014 add new data model\n"
            "- src/config.py \u2014 add configuration field",
            "- some vague description",
        )
        errors = validate_plan(task, plan, config=config)
        assert any("file path" in e for e in errors)

    def test_clarification_markers_max_three(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Add feature")
        plan = _valid_plan() + "\n".join(
            f"[NEEDS CLARIFICATION: item {i}]" for i in range(4)
        )
        errors = validate_plan(task, plan, config=config)
        assert any("NEEDS CLARIFICATION" in e for e in errors)

    def test_three_markers_ok(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Add feature")
        plan = _valid_plan() + "\n".join(
            f"[NEEDS CLARIFICATION: item {i}]" for i in range(3)
        )
        errors = validate_plan(task, plan, config=config)
        assert not any("NEEDS CLARIFICATION" in e for e in errors)

    def test_lite_scale_fewer_required_sections(self):
        config = _make_config()
        task = TaskFactory.create(id=1, title="Fix typo")
        lite_plan = (
            "## Files to Modify\n\n"
            "- src/main.py \u2014 fix typo\n\n"
            "## Implementation Steps\n\n"
            "1. Fix the typo in src/main.py\n\n"
            "## Testing Strategy\n\n"
            "- tests/test_main.py \u2014 verify fix\n"
        )
        errors = validate_plan(task, lite_plan, scale="lite", config=config)
        assert not any("Task Graph" in e for e in errors)


# ---------------------------------------------------------------------------
# run_phase_gates
# ---------------------------------------------------------------------------


class TestRunPhaseGates:
    def test_valid_plan_passes_gates(self):
        config = _make_config()
        blocking, warnings = run_phase_gates(_valid_plan(), config)
        assert blocking == []

    def test_empty_testing_strategy_blocks(self):
        config = _make_config()
        plan = _valid_plan().replace(
            "- tests/test_models.py \u2014 unit tests for new model\n"
            "- tests/test_config.py \u2014 config field tests",
            "none",
        )
        blocking, _ = run_phase_gates(plan, config)
        assert any("empty" in e.lower() for e in blocking)

    def test_deferred_testing_blocks(self):
        config = _make_config()
        plan = _valid_plan().replace(
            "- tests/test_models.py \u2014 unit tests for new model\n"
            "- tests/test_config.py \u2014 config field tests",
            "Tests will be added later",
        )
        blocking, _ = run_phase_gates(plan, config)
        assert any("defers" in e.lower() for e in blocking)

    def test_many_new_files_warns(self):
        config = _make_config(max_new_files_warning=1)
        plan = _valid_plan().replace(
            "- src/widget.py \u2014 new widget module",
            "- src/a.py\n- src/b.py\n- src/c.py",
        )
        blocking, warnings = run_phase_gates(plan, config)
        assert any("new files" in w.lower() for w in warnings)
