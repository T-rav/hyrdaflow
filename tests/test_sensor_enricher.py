"""Tests for sensor_enricher — enrichment of tool output with agent hints.

Covers the matching engine (:func:`matching_rules`) and the public
:func:`enrich` facade. Uses hand-crafted rules so tests do not depend on
the seed registry drift.

Part of the harness-engineering foundations (#6426).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sensor_enricher import (
    ANY_TOOL,
    MATCH_ALL_TOOLS,
    ErrorPattern,
    FileChanged,
    Rule,
    enrich,
    matching_rules,
)


def _mk_rule(
    rule_id: str,
    tool: str,
    trigger: FileChanged | ErrorPattern,
    hint: str = "hint body",
) -> Rule:
    return Rule(id=rule_id, tool=tool, trigger=trigger, hint=hint)


# ---------------------------------------------------------------------------
# FileChanged trigger
# ---------------------------------------------------------------------------


class TestFileChangedTrigger:
    def test_exact_file_match(self) -> None:
        trigger = FileChanged("src/models.py")
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/models.py")],
        )

    def test_glob_match(self) -> None:
        trigger = FileChanged("src/*_loop.py")
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/code_grooming_loop.py")],
        )

    def test_no_match_when_unrelated_file(self) -> None:
        trigger = FileChanged("src/models.py")
        assert not trigger.matches(
            raw_output="",
            changed_files=[Path("src/agent.py")],
        )

    def test_no_match_with_empty_file_list(self) -> None:
        trigger = FileChanged("src/*.py")
        assert not trigger.matches(raw_output="", changed_files=[])

    def test_posix_path_conversion(self) -> None:
        """Windows-style paths should still match POSIX globs."""
        trigger = FileChanged("src/models.py")
        # PurePath.as_posix() normalizes separators regardless of OS.
        assert trigger.matches(
            raw_output="",
            changed_files=[Path("src/models.py")],
        )


# ---------------------------------------------------------------------------
# ErrorPattern trigger
# ---------------------------------------------------------------------------


class TestErrorPatternTrigger:
    def test_regex_match_single_line(self) -> None:
        trigger = ErrorPattern(r"ModuleNotFoundError.*hindsight")
        assert trigger.matches(
            raw_output="ModuleNotFoundError: No module named 'hindsight'",
            changed_files=[],
        )

    def test_regex_match_multiline(self) -> None:
        trigger = ErrorPattern(r"^ERROR:")
        output = "warning: something\nERROR: boom\n"
        assert trigger.matches(raw_output=output, changed_files=[])

    def test_no_match(self) -> None:
        trigger = ErrorPattern(r"KeyError")
        assert not trigger.matches(
            raw_output="TypeError: bad thing",
            changed_files=[],
        )


# ---------------------------------------------------------------------------
# matching_rules
# ---------------------------------------------------------------------------


class TestMatchingRules:
    def test_tool_filter_respected(self) -> None:
        rule = _mk_rule("pytest-only", "pytest", ErrorPattern("boom"))
        result = matching_rules(
            [rule],
            tool="ruff",
            raw_output="boom",
            changed_files=[],
        )
        assert not result
        assert result.fired == []

    def test_any_tool_matches_any_tool(self) -> None:
        rule = _mk_rule("universal", ANY_TOOL, ErrorPattern("boom"))
        for tool in ("pytest", "ruff", "pyright", "bandit"):
            result = matching_rules(
                [rule],
                tool=tool,
                raw_output="boom",
                changed_files=[],
            )
            assert result.fired == [rule]

    def test_multiple_rules_all_fire(self) -> None:
        rule_a = _mk_rule("a", ANY_TOOL, ErrorPattern("boom"))
        rule_b = _mk_rule("b", ANY_TOOL, FileChanged("src/models.py"))
        result = matching_rules(
            [rule_a, rule_b],
            tool="pytest",
            raw_output="boom",
            changed_files=[Path("src/models.py")],
        )
        assert result.fired == [rule_a, rule_b]

    def test_no_match_returns_empty_falsy_result(self) -> None:
        rule = _mk_rule("a", "pytest", ErrorPattern("KeyError"))
        result = matching_rules(
            [rule],
            tool="pytest",
            raw_output="TypeError: bad",
            changed_files=[],
        )
        assert not result
        assert result.fired == []

    def test_empty_rule_list_returns_empty_result(self) -> None:
        result = matching_rules(
            [],
            tool="pytest",
            raw_output="anything",
            changed_files=[],
        )
        assert not result


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------


class TestEnrich:
    def test_no_match_returns_raw_output_unchanged(self) -> None:
        rule = _mk_rule("a", "pytest", ErrorPattern("KeyError"))
        raw = "TypeError: bad thing"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[],
            rules=[rule],
        )
        assert result == raw

    def test_match_appends_hints_block(self) -> None:
        rule = _mk_rule(
            "a",
            "pytest",
            ErrorPattern("boom"),
            hint="Check the foo.",
        )
        raw = "test_x FAILED\nboom happened"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[],
            rules=[rule],
        )
        assert raw in result
        assert "## Agent Hints" in result
        assert "- Check the foo." in result

    def test_raw_output_preserved_verbatim(self) -> None:
        """Hints are additive — raw output must not be modified."""
        rule = _mk_rule(
            "a",
            ANY_TOOL,
            FileChanged("src/models.py"),
            hint="A hint.",
        )
        raw = "line1\n  indented line\nline3"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[Path("src/models.py")],
            rules=[rule],
        )
        assert result.startswith(raw + "\n\n")

    def test_multiple_hints_listed_as_bullets(self) -> None:
        rule_a = _mk_rule("a", ANY_TOOL, ErrorPattern("boom"), hint="Hint A.")
        rule_b = _mk_rule("b", ANY_TOOL, ErrorPattern("boom"), hint="Hint B.")
        result = enrich(
            tool="pytest",
            raw_output="boom",
            changed_files=[],
            rules=[rule_a, rule_b],
        )
        assert "- Hint A." in result
        assert "- Hint B." in result

    def test_empty_rules_returns_raw_output(self) -> None:
        raw = "anything"
        assert (
            enrich(
                tool="pytest",
                raw_output=raw,
                changed_files=[],
                rules=[],
            )
            == raw
        )


# ---------------------------------------------------------------------------
# Seed rule registry smoke test
# ---------------------------------------------------------------------------


class TestSeedRules:
    """Sanity checks on the seed registry — catches drift from the doc."""

    def test_seed_registry_loads(self) -> None:
        from sensor_rules import SEED_RULES

        assert len(SEED_RULES) >= 5, "seed registry must cover all known patterns"

    def test_seed_rule_ids_unique(self) -> None:
        from sensor_rules import SEED_RULES

        ids = [r.id for r in SEED_RULES]
        assert len(ids) == len(set(ids)), f"duplicate rule ids: {ids}"

    def test_seed_rules_reference_docs_agents(self) -> None:
        from sensor_rules import SEED_RULES

        # Every hint must point at a doc under docs/wiki/ so rule text
        # stays consistent with the human-facing rule descriptions and we
        # never accumulate stale CLAUDE.md references after a refactor.
        for rule in SEED_RULES:
            assert "docs/wiki/" in rule.hint, (
                f"rule {rule.id} has no docs/wiki/ reference; hint={rule.hint!r}"
            )

    def test_pydantic_rule_fires_for_models_edit(self) -> None:
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output="",
            changed_files=[Path("src/models.py")],
        )
        rule_ids = {r.id for r in result.fired}
        assert "pydantic-field-tests" in rule_ids

    def test_optional_dep_rule_fires_for_hindsight_import_error(self) -> None:
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output="ModuleNotFoundError: No module named 'hindsight'",
            changed_files=[],
        )
        rule_ids = {r.id for r in result.fired}
        assert "optional-dep-toplevel-import" in rule_ids

    def test_falsy_optional_rule_does_not_fire_on_generic_assertion(
        self,
    ) -> None:
        """The falsy-optional rule should match the source anti-pattern,
        not arbitrary `is None` assertion lines from unrelated tests."""
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output=(
                "AssertionError: assert result is None\n  + where result = compute()"
            ),
            changed_files=[],
        )
        rule_ids = {r.id for r in result.fired}
        assert "falsy-optional-check" not in rule_ids

    def test_falsy_optional_rule_fires_on_actual_anti_pattern(self) -> None:
        from sensor_rules import SEED_RULES

        result = matching_rules(
            SEED_RULES,
            tool="pytest",
            raw_output="src/foo.py:42:        if not self._hindsight:",
            changed_files=[],
        )
        rule_ids = {r.id for r in result.fired}
        assert "falsy-optional-check" in rule_ids


# ---------------------------------------------------------------------------
# MATCH_ALL_TOOLS sentinel
# ---------------------------------------------------------------------------


class TestMatchAllToolsSentinel:
    """The MATCH_ALL_TOOLS caller-side sentinel matches every rule
    regardless of the rule's `tool` filter. Used by integration points
    that don't know which tool produced the failure (HarnessInsightStore).
    """

    def test_match_all_fires_tool_specific_rule(self) -> None:
        rule = Rule(
            id="pytest-only",
            tool="pytest",
            trigger=ErrorPattern(r"boom"),
            hint="hint",
        )
        result = matching_rules(
            [rule],
            tool=MATCH_ALL_TOOLS,
            raw_output="boom",
            changed_files=[],
        )
        assert result.fired == [rule]

    def test_match_all_fires_any_tool_rule(self) -> None:
        rule = Rule(
            id="universal",
            tool=ANY_TOOL,
            trigger=ErrorPattern(r"boom"),
            hint="hint",
        )
        result = matching_rules(
            [rule],
            tool=MATCH_ALL_TOOLS,
            raw_output="boom",
            changed_files=[],
        )
        assert result.fired == [rule]

    def test_match_all_with_no_matching_rules_returns_empty(self) -> None:
        rule = Rule(
            id="pytest-only",
            tool="pytest",
            trigger=ErrorPattern(r"KeyError"),
            hint="hint",
        )
        result = matching_rules(
            [rule],
            tool=MATCH_ALL_TOOLS,
            raw_output="TypeError: bad",
            changed_files=[],
        )
        assert result.fired == []

    def test_match_all_does_not_match_rules_with_other_tool_names(
        self,
    ) -> None:
        """A rule scoped to 'ruff' should match under MATCH_ALL_TOOLS but
        NOT under tool='pytest' — sanity check that the sentinel and
        per-tool dispatch are independent."""
        rule = Rule(
            id="ruff-only",
            tool="ruff",
            trigger=ErrorPattern(r"E501"),
            hint="hint",
        )
        # Under MATCH_ALL_TOOLS, fires.
        all_result = matching_rules(
            [rule],
            tool=MATCH_ALL_TOOLS,
            raw_output="E501 line too long",
            changed_files=[],
        )
        assert all_result.fired == [rule]
        # Under tool='pytest', does NOT fire.
        pytest_result = matching_rules(
            [rule],
            tool="pytest",
            raw_output="E501 line too long",
            changed_files=[],
        )
        assert pytest_result.fired == []


# ---------------------------------------------------------------------------
# enrich() idempotency
# ---------------------------------------------------------------------------


class TestEnrichIdempotency:
    """enrich() must not stack `## Agent Hints` headings on already-
    enriched output. Callers may inadvertently double-enrich (e.g., a
    failure record passed through two integration points)."""

    def test_already_enriched_output_returns_unchanged(self) -> None:
        rule = Rule(
            id="r",
            tool=ANY_TOOL,
            trigger=ErrorPattern(r"boom"),
            hint="A hint.",
        )
        first = enrich(
            tool="pytest",
            raw_output="boom",
            changed_files=[],
            rules=[rule],
        )
        # First call appends a hints block.
        assert "## Agent Hints" in first
        # Second call returns the input unchanged — no second block.
        second = enrich(
            tool="pytest",
            raw_output=first,
            changed_files=[],
            rules=[rule],
        )
        assert second == first
        assert second.count("## Agent Hints") == 1

    def test_pre_existing_hints_heading_blocks_enrichment(self) -> None:
        rule = Rule(
            id="r",
            tool=ANY_TOOL,
            trigger=ErrorPattern(r"boom"),
            hint="A hint.",
        )
        raw = "## Agent Hints\n\n- something else\n\nboom happened"
        result = enrich(
            tool="pytest",
            raw_output=raw,
            changed_files=[],
            rules=[rule],
        )
        assert result == raw
