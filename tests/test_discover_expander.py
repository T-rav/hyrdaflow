"""Unit tests for ``discover_expander`` (ADR-0063 W3a).

The expander is pure: it builds a prompt, dispatches a subagent through
an injected ``executor`` callable, and parses the structured marker
block. Tests assert on the prompt content (failure reason + findings
threaded in), the parser's bullet extraction (with malformed markers
falling open to ``[]``), and the dispatch surface (executor invoked
with the ``discover:expander`` source tag).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from discover_expander import (
    build_expander_prompt,
    expand_research_brief,
    format_queries_for_prompt,
    parse_expansion_queries,
)
from models import Task


def _task(issue_id: int = 7) -> Task:
    return Task(
        id=issue_id,
        title="Maybe a dark mode?",
        body="It depends on per-device vs per-account.",
        tags=[],
        comments=[],
        source_url="",
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


class TestBuildExpanderPrompt:
    def test_includes_issue_metadata(self) -> None:
        prompt = build_expander_prompt(
            issue_number=42,
            issue_title="vague thing",
            issue_body="Maybe X?",
            original_brief="Brief that paraphrased the body.",
            coherence_failure_reason="paraphrase-only — no new info",
        )
        assert "Issue #42: vague thing" in prompt
        assert "Maybe X?" in prompt
        assert "Brief that paraphrased the body." in prompt
        assert "paraphrase-only — no new info" in prompt

    def test_findings_section_renders_when_present(self) -> None:
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            original_brief="brief",
            coherence_failure_reason="missing-section:open-questions",
            failure_findings=[
                "missing-section:open-questions — no questions listed",
                "missing-section:open-questions — body has 'maybe'",
            ],
        )
        assert "Specific Findings From The Coherence Evaluator" in prompt
        assert "no questions listed" in prompt
        assert "body has 'maybe'" in prompt

    def test_findings_section_absent_when_none(self) -> None:
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            original_brief="brief",
            coherence_failure_reason="vague-criterion",
            failure_findings=None,
        )
        assert "Specific Findings From The Coherence Evaluator" not in prompt

    def test_findings_truncated_to_ten(self) -> None:
        # 12 findings → only the first 10 rendered (defensive cap to keep
        # the expander prompt under any LLM context budget).
        many = [f"finding-{i}" for i in range(12)]
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            original_brief="brief",
            coherence_failure_reason="shallow-section:intent",
            failure_findings=many,
        )
        for i in range(10):
            assert f"finding-{i}" in prompt
        assert "finding-10" not in prompt
        assert "finding-11" not in prompt

    def test_empty_body_renders_placeholder(self) -> None:
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="",
            original_brief="brief",
            coherence_failure_reason="vague-criterion",
        )
        assert "(No description provided)" in prompt

    def test_empty_brief_renders_placeholder(self) -> None:
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            original_brief="",
            coherence_failure_reason="vague-criterion",
        )
        assert "(empty brief)" in prompt

    def test_output_marker_contract_documented(self) -> None:
        # The prompt MUST instruct the agent to emit the canonical
        # markers the parser keys off; otherwise the dispatch silently
        # returns no queries every time.
        prompt = build_expander_prompt(
            issue_number=1,
            issue_title="t",
            issue_body="b",
            original_brief="brief",
            coherence_failure_reason="vague-criterion",
        )
        assert "EXPANSION_QUERIES_START" in prompt
        assert "EXPANSION_QUERIES_END" in prompt


class TestParseExpansionQueries:
    def test_extracts_bullets(self) -> None:
        transcript = (
            "Some reasoning text.\n"
            "EXPANSION_QUERIES_START\n"
            "- First specific query about competitor X.\n"
            "- Second query about persona Y's friction points.\n"
            "- Third query about ADR-0042 trade-offs.\n"
            "EXPANSION_QUERIES_END\n"
            "trailing noise"
        )
        out = parse_expansion_queries(transcript)
        assert out == [
            "First specific query about competitor X.",
            "Second query about persona Y's friction points.",
            "Third query about ADR-0042 trade-offs.",
        ]

    def test_accepts_asterisk_bullets(self) -> None:
        transcript = (
            "EXPANSION_QUERIES_START\n"
            "* asterisk style query\n"
            "* another asterisk one\n"
            "EXPANSION_QUERIES_END"
        )
        out = parse_expansion_queries(transcript)
        assert out == ["asterisk style query", "another asterisk one"]

    def test_ignores_non_bullet_lines_inside_block(self) -> None:
        transcript = (
            "EXPANSION_QUERIES_START\n"
            "Some preamble text inside the block.\n"
            "- real query one\n"
            "More prose.\n"
            "- real query two\n"
            "EXPANSION_QUERIES_END"
        )
        out = parse_expansion_queries(transcript)
        assert out == ["real query one", "real query two"]

    def test_missing_markers_returns_empty(self) -> None:
        assert parse_expansion_queries("nothing structured here") == []

    def test_only_start_marker_returns_empty(self) -> None:
        assert parse_expansion_queries("EXPANSION_QUERIES_START\n- q1\nno end") == []

    def test_empty_block_returns_empty(self) -> None:
        transcript = "EXPANSION_QUERIES_START\n\nEXPANSION_QUERIES_END"
        assert parse_expansion_queries(transcript) == []

    def test_whitespace_only_bullet_filtered(self) -> None:
        transcript = "EXPANSION_QUERIES_START\n- \n- real one\nEXPANSION_QUERIES_END"
        assert parse_expansion_queries(transcript) == ["real one"]


class TestFormatQueriesForPrompt:
    def test_renders_bulleted_section(self) -> None:
        out = format_queries_for_prompt(["alpha", "beta"])
        assert "Expanded Research Queries" in out
        assert "- alpha" in out
        assert "- beta" in out
        assert "ADR-0063 W3a" in out

    def test_empty_list_returns_empty_string(self) -> None:
        # Empty input → no injection. The runner appends unconditionally;
        # the empty-string contract keeps that call site simple.
        assert format_queries_for_prompt([]) == ""


class TestExpandResearchBrief:
    async def test_invokes_executor_with_expander_source_tag(self) -> None:
        captured_event: dict[str, object] = {}

        async def _exec(_cmd, _prompt, _cwd, event_data, **_kw):
            captured_event.update(event_data)
            return (
                "EXPANSION_QUERIES_START\n"
                "- query 1\n"
                "- query 2\n"
                "- query 3\n"
                "EXPANSION_QUERIES_END"
            )

        queries = await expand_research_brief(
            task=_task(7),
            original_brief="paraphrased brief",
            coherence_failure_reason="paraphrase-only — no new info",
            failure_findings=["paraphrase-only — no competitor named"],
            executor=_exec,
            cmd=["claude"],
            cwd=Path("/tmp"),
        )
        assert queries == ["query 1", "query 2", "query 3"]
        assert captured_event["issue"] == 7
        assert captured_event["source"] == "discover:expander"

    async def test_executor_exception_returns_empty_list(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _exec(*_a, **_k):
            raise RuntimeError("transient agent failure")

        with caplog.at_level("WARNING", logger="hydraflow.discover_expander"):
            queries = await expand_research_brief(
                task=_task(9),
                original_brief="brief",
                coherence_failure_reason="vague-criterion",
                failure_findings=[],
                executor=_exec,
                cmd=["claude"],
                cwd=Path("/tmp"),
            )
        assert queries == []
        assert any(
            "discover-expander dispatch failed for #9" in r.message
            for r in caplog.records
        )

    async def test_empty_transcript_returns_empty_list(self) -> None:
        exec_mock = AsyncMock(return_value="agent produced no markers")
        queries = await expand_research_brief(
            task=_task(11),
            original_brief="brief",
            coherence_failure_reason="hid-ambiguity",
            failure_findings=None,
            executor=exec_mock,
            cmd=["claude"],
            cwd=Path("/tmp"),
        )
        assert queries == []
        exec_mock.assert_awaited_once()

    async def test_prompt_threads_failure_reason_to_executor(self) -> None:
        captured_prompt = {"text": ""}

        async def _exec(_cmd, prompt, _cwd, _event, **_kw):
            captured_prompt["text"] = prompt
            return "EXPANSION_QUERIES_START\n- q\nEXPANSION_QUERIES_END"

        await expand_research_brief(
            task=_task(13),
            original_brief="brief body here",
            coherence_failure_reason="missing-section:acceptance-criteria",
            failure_findings=["acceptance-criteria absent from brief"],
            executor=_exec,
            cmd=["claude"],
            cwd=Path("/tmp"),
        )
        assert "missing-section:acceptance-criteria" in captured_prompt["text"]
        assert "acceptance-criteria absent from brief" in captured_prompt["text"]
        assert "brief body here" in captured_prompt["text"]
