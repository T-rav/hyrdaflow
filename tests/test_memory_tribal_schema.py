"""Tests for the TribalMemory schema and the new MEMORY_SUGGESTION parser."""

from __future__ import annotations

import pytest


def test_tribal_memory_requires_durable_fields():
    from models import TribalMemory

    mem = TribalMemory(
        principle="The main branch is protected; never push directly.",
        rationale="Branch protection added 2025-Q4 after a force-push wiped 3 days of work.",
        failure_mode="Direct pushes to main are rejected; the agent appears stuck.",
        scope="all",
    )
    assert mem.schema_version == 1
    assert mem.principle
    assert mem.rationale
    assert mem.failure_mode
    assert mem.scope


def test_tribal_memory_rejects_empty_principle():
    from pydantic import ValidationError

    from models import TribalMemory

    with pytest.raises(ValidationError):
        TribalMemory(principle="", rationale="x" * 20, failure_mode="y" * 20, scope="z")


def test_tribal_memory_rejects_short_rationale():
    from pydantic import ValidationError

    from models import TribalMemory

    with pytest.raises(ValidationError):
        TribalMemory(
            principle="A durable principle with enough length",
            rationale="too short",
            failure_mode="y" * 20,
            scope="z",
        )


def test_parse_memory_suggestion_extracts_tribal_block():
    from memory import parse_memory_suggestion

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "principle: Always rebuild assets before pushing UI changes.\n"
        "rationale: Vite cache poisoning broke prod twice in 2025.\n"
        "failure_mode: Stale bundles ship; users see white-screen on /dashboard.\n"
        "scope: src/ui/**\n"
        "MEMORY_SUGGESTION_END\n"
    )
    parsed = parse_memory_suggestion(transcript)
    assert parsed is not None
    assert parsed["principle"].startswith("Always rebuild")
    assert parsed["rationale"].startswith("Vite cache")
    assert parsed["failure_mode"].startswith("Stale bundles")
    assert parsed["scope"] == "src/ui/**"


def test_parse_memory_suggestion_rejects_old_format():
    from memory import parse_memory_suggestion

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "title: anything\n"
        "learning: anything\n"
        "MEMORY_SUGGESTION_END\n"
    )
    assert parse_memory_suggestion(transcript) is None


def test_parse_memory_suggestion_rejects_partial_block():
    """A block missing any of the four required fields must return None."""
    from memory import parse_memory_suggestion

    transcript = (
        "MEMORY_SUGGESTION_START\n"
        "principle: A thing\n"
        "rationale: Because reasons\n"
        "failure_mode: It breaks\n"
        # scope missing
        "MEMORY_SUGGESTION_END\n"
    )
    assert parse_memory_suggestion(transcript) is None
