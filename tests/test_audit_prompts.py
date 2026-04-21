"""Tests for scripts/audit_prompts.py — AuditTarget dataclass and prompt registry scaffold."""

from __future__ import annotations

from scripts.audit_prompts import (
    AuditTarget,
    Scorecard,
    score,
    score_cot,
    score_edge_cases,
    score_examples,
    score_leads_with_request,
    score_long_context_placement,
    score_output_contract,
    score_specific,
    score_xml_tags,
    severity_for,
)

# ---------------------------------------------------------------------------
# Task 2 fixtures
# ---------------------------------------------------------------------------

IMPERATIVE_PROMPT = "Classify this issue into one of three categories: ..."
DELAYED_PROMPT = (
    "This is a triage task. A classification is needed. Classify this issue..."
)
BURIED_PROMPT = (
    "Background context. Lots of reading. Many sentences. And finally: classify."
)

# ---------------------------------------------------------------------------
# Task 3 fixtures
# ---------------------------------------------------------------------------

SPECIFIC_PROMPT = """Produce a JSON object with fields `ready`, `reasons`, `clarity_score`.
The output must have valid JSON. Requirements: all fields must be present."""
VAGUE_PROMPT = "Think about the issue. Give me your thoughts."

# ---------------------------------------------------------------------------
# Task 1 — AuditTarget scaffold
# ---------------------------------------------------------------------------


def test_audit_target_carries_metadata():
    target = AuditTarget(
        name="triage_build_prompt",
        builder_qualname="triage.Triage._build_prompt_with_stats",
        fixture_path="tests/fixtures/prompts/triage_build_prompt.json",
        category="Triage",
        call_site="src/triage.py:194",
    )
    assert target.name == "triage_build_prompt"
    assert target.category == "Triage"
    assert target.call_site == "src/triage.py:194"


# ---------------------------------------------------------------------------
# Task 2 — Rubric #1: leads with the request
# ---------------------------------------------------------------------------


def test_score_leads_with_request_pass_when_first_sentence_has_imperative():
    assert score_leads_with_request(IMPERATIVE_PROMPT) == "Pass"


def test_score_leads_with_request_partial_when_imperative_in_sentence_two_or_three():
    assert score_leads_with_request(DELAYED_PROMPT) == "Partial"


def test_score_leads_with_request_fail_when_imperative_buried_beyond_sentence_three():
    assert score_leads_with_request(BURIED_PROMPT) == "Fail"


# ---------------------------------------------------------------------------
# Task 3 — Rubric #2: specific
# ---------------------------------------------------------------------------


def test_score_specific_pass_when_all_three_cues_present():
    assert score_specific(SPECIFIC_PROMPT) == "Pass"


def test_score_specific_fail_when_no_cues():
    assert score_specific(VAGUE_PROMPT) == "Fail"


def test_score_specific_partial_when_two_cues():
    prompt = "Produce a JSON object. All fields must be present."
    assert score_specific(prompt) == "Partial"


# ---------------------------------------------------------------------------
# Task 4 — Rubric #3: XML tags
# ---------------------------------------------------------------------------


def test_score_xml_tags_pass_with_three_distinct_tags():
    prompt = "<issue>hi</issue><diff>foo</diff><plan>bar</plan>"
    assert score_xml_tags(prompt) == "Pass"


def test_score_xml_tags_partial_with_one_or_two():
    assert score_xml_tags("<issue>hi</issue>") == "Partial"
    assert score_xml_tags("<issue>hi</issue><diff>foo</diff>") == "Partial"


def test_score_xml_tags_fail_with_none():
    assert score_xml_tags("## Heading\nBody") == "Fail"


def test_score_xml_tags_excludes_thinking_and_scratchpad():
    prompt = "<thinking>step</thinking><scratchpad>note</scratchpad>"
    assert score_xml_tags(prompt) == "Fail"


# ---------------------------------------------------------------------------
# Task 5 — Rubric #4: examples where applicable
# ---------------------------------------------------------------------------


def test_score_examples_na_when_output_is_free_form():
    prompt = "Write a short summary of the issue."
    assert score_examples(prompt) == "N/A"


def test_score_examples_pass_when_applicable_and_example_tag_present():
    prompt = 'Produce a JSON object with fields.\n<example>{"ready": true}</example>'
    assert score_examples(prompt) == "Pass"


def test_score_examples_pass_when_applicable_and_example_header_present():
    prompt = 'Produce a JSON object with fields.\n\nExample:\n{"ready": true}'
    assert score_examples(prompt) == "Pass"


def test_score_examples_fail_when_applicable_but_no_example():
    prompt = "Produce a JSON object with fields `ready` and `reasons`."
    assert score_examples(prompt) == "Fail"


# ---------------------------------------------------------------------------
# Task 6 — Rubric #5: output contract
# ---------------------------------------------------------------------------


def test_score_output_contract_pass_on_respond_with():
    assert score_output_contract("Respond with a single JSON object.") == "Pass"


def test_score_output_contract_pass_on_do_not():
    assert score_output_contract("Do not include any prose.") == "Pass"


def test_score_output_contract_pass_on_return_only():
    assert score_output_contract("Return only the JSON, nothing else.") == "Pass"


def test_score_output_contract_fail_when_no_cues():
    assert score_output_contract("Think carefully. Give your best answer.") == "Fail"


# ---------------------------------------------------------------------------
# Task 7 — Rubric #6: placement of long context
# ---------------------------------------------------------------------------


def test_score_long_context_placement_na_below_threshold():
    prompt = "Classify.\n<issue>small body</issue>\nReturn JSON."
    assert score_long_context_placement(prompt) == "N/A"


def test_score_long_context_placement_pass_when_content_before_final_imperative():
    body = "x" * 11000
    prompt = f"<issue>{body}</issue>\n\nClassify the issue above and return JSON."
    assert score_long_context_placement(prompt) == "Pass"


def test_score_long_context_placement_fail_when_content_after_final_imperative():
    body = "x" * 11000
    prompt = f"Classify the issue and return JSON.\n\n<issue>{body}</issue>"
    assert score_long_context_placement(prompt) == "Fail"


# ---------------------------------------------------------------------------
# Task 8 — Rubric #7: CoT scaffolded where decisions are made
# ---------------------------------------------------------------------------


def test_score_cot_na_when_no_decision_verb():
    assert score_cot("Summarize the issue in one sentence.") == "N/A"


def test_score_cot_pass_when_decision_and_thinking_present():
    prompt = "Classify the issue. <thinking>reason step by step</thinking>"
    assert score_cot(prompt) == "Pass"


def test_score_cot_pass_when_think_step_by_step_phrase_present():
    prompt = "Decide whether to approve. Think step by step before answering."
    assert score_cot(prompt) == "Pass"


def test_score_cot_fail_when_decision_without_scaffold():
    assert score_cot("Classify the issue into one of three categories.") == "Fail"


# ---------------------------------------------------------------------------
# Task 9 — Rubric #8: edge cases named
# ---------------------------------------------------------------------------


def test_score_edge_cases_pass_when_if_empty_present():
    assert score_edge_cases("Classify. If empty, return 'unknown'.") == "Pass"


def test_score_edge_cases_pass_when_otherwise_present():
    assert score_edge_cases("Prefer X; otherwise, Y.") == "Pass"


def test_score_edge_cases_pass_when_fallback_present():
    assert score_edge_cases("Use A as fallback when B is unavailable.") == "Pass"


def test_score_edge_cases_fail_when_no_cues():
    assert score_edge_cases("Classify the issue and return JSON.") == "Fail"


# ---------------------------------------------------------------------------
# Task 10 — Severity classifier
# ---------------------------------------------------------------------------


def test_severity_high_when_two_fails():
    scores = {
        1: "Pass",
        2: "Fail",
        3: "Fail",
        4: "Pass",
        5: "Pass",
        6: "Pass",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "High"


def test_severity_high_when_criterion_1_fails():
    scores = {
        1: "Fail",
        2: "Pass",
        3: "Pass",
        4: "Pass",
        5: "Pass",
        6: "Pass",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "High"


def test_severity_high_when_criterion_6_fails():
    scores = {
        1: "Pass",
        2: "Pass",
        3: "Pass",
        4: "Pass",
        5: "Pass",
        6: "Fail",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "High"


def test_severity_medium_on_one_fail():
    scores = {
        1: "Pass",
        2: "Pass",
        3: "Fail",
        4: "Pass",
        5: "Pass",
        6: "Pass",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "Medium"


def test_severity_medium_on_three_partials():
    scores = {
        1: "Partial",
        2: "Partial",
        3: "Partial",
        4: "Pass",
        5: "Pass",
        6: "Pass",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "Medium"


def test_severity_low_when_clean():
    scores = {
        1: "Pass",
        2: "Pass",
        3: "Pass",
        4: "Pass",
        5: "Pass",
        6: "Pass",
        7: "N/A",
        8: "Pass",
    }
    assert severity_for(Scorecard(scores=scores)) == "Low"


# ---------------------------------------------------------------------------
# Task 11 — Combined score() orchestrator
# ---------------------------------------------------------------------------


def test_score_returns_scorecard_with_all_eight_rules_applied():
    rendered = "Classify the issue. <issue>body</issue><plan>p</plan><diff>d</diff> Return only JSON."
    card = score(rendered)
    assert set(card.scores.keys()) == {1, 2, 3, 4, 5, 6, 7, 8}


def test_score_integrates_rules_and_severity():
    rendered = (
        "Classify the issue. The output must be a JSON object with fields `ready` and `reasons`.\n"
        "<issue>body</issue><plan>p</plan><diff>d</diff>\n"
        '<example>{"ready": true}</example>\n'
        "<thinking>reason first</thinking>\n"
        "Return only JSON. If empty, return unknown."
    )
    card = score(rendered)
    assert severity_for(card) in ("Low", "Medium")


# ---------------------------------------------------------------------------
# Task 12 — Fakes module
# ---------------------------------------------------------------------------


def test_fakes_registry_has_empty_repo_wiki_store():
    from tests.fixtures.prompts.fakes import get_fake

    fake = get_fake("repo_wiki_store", "empty")
    assert fake.get_entries() == []


def test_fakes_registry_has_minimal_manifest():
    from tests.fixtures.prompts.fakes import get_fake

    manifest = get_fake("manifest", "minimal")
    assert isinstance(manifest, list)
    assert len(manifest) >= 1
    assert len(manifest) <= 10


def test_fakes_raises_on_unknown_key():
    import pytest as _pytest

    from tests.fixtures.prompts.fakes import get_fake

    with _pytest.raises(KeyError):
        get_fake("nonexistent_dep", "shape")


# ---------------------------------------------------------------------------
# Task 13 — Fixture loader + render helper
# ---------------------------------------------------------------------------


def test_load_fixture_reads_json(tmp_path):
    from scripts.audit_prompts import load_fixture

    fixture = tmp_path / "sample.json"
    fixture.write_text('{"builder": "foo.bar", "args": {"x": 1}, "faked_deps": {}}')
    loaded = load_fixture(str(fixture))
    assert loaded.builder == "foo.bar"
    assert loaded.args == {"x": 1}


def test_render_invokes_builder_and_returns_string():
    from scripts.audit_prompts import render

    def _builder(x: int, y: int) -> str:
        return f"sum={x + y}"

    result = render(_builder, args={"x": 2, "y": 3}, faked_deps={})
    assert result == "sum=5"


# ---------------------------------------------------------------------------
# Task 14 — PROMPT_REGISTRY coverage
# ---------------------------------------------------------------------------


def test_prompt_registry_covers_every_loop():
    from scripts.audit_prompts import PROMPT_REGISTRY

    categories = {t.category for t in PROMPT_REGISTRY}
    assert {"Triage", "Plan", "Implement", "Review", "HITL", "Adjacent"} <= categories


def test_prompt_registry_has_expected_minimum_entries():
    from scripts.audit_prompts import PROMPT_REGISTRY

    assert len(PROMPT_REGISTRY) >= 20


def test_prompt_registry_entries_are_unique_by_name():
    from scripts.audit_prompts import PROMPT_REGISTRY

    names = [t.name for t in PROMPT_REGISTRY]
    assert len(names) == len(set(names)), "duplicate registry names detected"


# ---------------------------------------------------------------------------
# Task 15 — Triage fixtures
# ---------------------------------------------------------------------------


def test_triage_fixtures_render_cleanly():
    from scripts.audit_prompts import PROMPT_REGISTRY, render_target

    triage_targets = [t for t in PROMPT_REGISTRY if t.category == "Triage"]
    assert len(triage_targets) >= 2

    for target in triage_targets:
        rendered = render_target(target)
        assert rendered, f"rendered output is empty for {target.name}"


# ---------------------------------------------------------------------------
# Task 16 — Plan fixtures
# ---------------------------------------------------------------------------


def test_plan_fixtures_render_cleanly():
    from scripts.audit_prompts import PROMPT_REGISTRY, render_target

    plan_targets = [t for t in PROMPT_REGISTRY if t.category == "Plan"]
    assert len(plan_targets) >= 3
    for target in plan_targets:
        rendered = render_target(target)
        assert rendered, f"rendered output is empty for {target.name}"
