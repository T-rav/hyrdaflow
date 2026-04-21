"""Tests for scripts/audit_prompts.py — AuditTarget dataclass and prompt registry scaffold."""

from __future__ import annotations

from scripts.audit_prompts import (
    AuditTarget,
    score_examples,
    score_leads_with_request,
    score_specific,
    score_xml_tags,
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
