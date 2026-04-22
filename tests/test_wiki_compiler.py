"""Tests for WikiCompiler — LLM-driven wiki synthesis."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import RepoWikiStore, WikiEntry
from wiki_compiler import ContradictionCheck, WikiCompiler


@pytest.fixture
def store(tmp_path: Path) -> RepoWikiStore:
    return RepoWikiStore(tmp_path / "wiki")


@pytest.fixture
def compiler() -> WikiCompiler:
    config = MagicMock()
    config.wiki_compilation_tool = "claude"
    config.wiki_compilation_model = "haiku"
    config.wiki_compilation_timeout = 30
    runner = MagicMock()
    creds = MagicMock()
    creds.gh_token = "fake-token"
    return WikiCompiler(config=config, runner=runner, credentials=creds)


REPO = "acme/widget"


class TestParseEntries:
    def test_parses_json_array(self) -> None:
        raw = json.dumps(
            [
                {
                    "title": "Entry A",
                    "content": "Content A",
                    "source_type": "plan",
                    "source_issue": 1,
                },
                {
                    "title": "Entry B",
                    "content": "Content B",
                    "source_type": "review",
                    "source_issue": 2,
                },
            ]
        )
        entries = WikiCompiler._parse_entries(raw)
        assert len(entries) == 2
        assert entries[0].title == "Entry A"
        assert entries[1].source_issue == 2

    def test_parses_fenced_json(self) -> None:
        raw = (
            "```json\n"
            + json.dumps(
                [
                    {"title": "X", "content": "Y", "source_type": "compiled"},
                ]
            )
            + "\n```"
        )
        entries = WikiCompiler._parse_entries(raw)
        assert len(entries) == 1
        assert entries[0].title == "X"

    def test_handles_extra_text(self) -> None:
        raw = (
            "Here are the entries:\n"
            + json.dumps(
                [
                    {"title": "Foo", "content": "Bar", "source_type": "plan"},
                ]
            )
            + "\nDone."
        )
        entries = WikiCompiler._parse_entries(raw)
        assert len(entries) == 1

    def test_returns_empty_on_no_json(self) -> None:
        assert WikiCompiler._parse_entries("no json here") == []

    def test_returns_empty_on_invalid_json(self) -> None:
        assert WikiCompiler._parse_entries("[{invalid}]") == []

    def test_skips_non_dict_items(self) -> None:
        raw = json.dumps(
            [
                {"title": "Good", "content": "OK", "source_type": "plan"},
                "not a dict",
                42,
            ]
        )
        entries = WikiCompiler._parse_entries(raw)
        assert len(entries) == 1


class TestCompileTopic:
    @pytest.mark.asyncio
    async def test_skips_topics_with_fewer_than_2_entries(
        self, store: RepoWikiStore, compiler: WikiCompiler
    ) -> None:
        store.ingest(
            REPO, [WikiEntry(title="Solo", content="Only one.", source_type="plan")]
        )
        result = await compiler.compile_topic(store, REPO, "patterns")
        assert result <= 1  # no compilation needed

    @pytest.mark.asyncio
    async def test_compiles_entries_via_model(
        self, store: RepoWikiStore, compiler: WikiCompiler
    ) -> None:
        # Seed 3 entries in same topic
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Pattern A",
                    content="Use pattern A for errors.",
                    source_type="plan",
                    source_issue=1,
                ),
                WikiEntry(
                    title="Pattern B",
                    content="Use pattern B for errors too.",
                    source_type="plan",
                    source_issue=2,
                ),
                WikiEntry(
                    title="Pattern C",
                    content="Pattern C is better.",
                    source_type="review",
                    source_issue=3,
                ),
            ],
        )

        # Mock _call_model directly to avoid deferred import issues
        compiled_json = json.dumps(
            [
                {
                    "title": "Error handling patterns",
                    "content": "Use pattern C (preferred over A and B). See also: gotchas — edge cases.",
                    "source_type": "compiled",
                    "source_issue": None,
                },
            ]
        )
        compiler._call_model = AsyncMock(return_value=compiled_json)

        count = await compiler.compile_topic(store, REPO, "architecture")
        assert count == 1  # 3 entries compiled into 1

        # Verify the compiled entry was written
        entries = store._load_topic_entries(store._repo_dir(REPO) / "architecture.md")
        assert len(entries) == 1
        assert "pattern c" in entries[0].content.lower()

    @pytest.mark.asyncio
    async def test_keeps_originals_on_model_failure(
        self, store: RepoWikiStore, compiler: WikiCompiler
    ) -> None:
        store.ingest(
            REPO,
            [
                WikiEntry(
                    title="Module layout",
                    content="Service layer architecture.",
                    source_type="plan",
                ),
                WikiEntry(
                    title="Component design",
                    content="Layered module structure.",
                    source_type="plan",
                ),
            ],
        )

        compiler._call_model = AsyncMock(return_value=None)

        count = await compiler.compile_topic(store, REPO, "architecture")
        assert count == 2  # originals preserved


class TestSynthesizeIngest:
    @pytest.mark.asyncio
    async def test_extracts_entries_from_raw_text(self, compiler: WikiCompiler) -> None:
        synthesized = json.dumps(
            [
                {
                    "title": "Auth uses OAuth2",
                    "content": "The repo uses OAuth2 with refresh tokens.",
                    "source_type": "plan",
                    "source_issue": 42,
                },
            ]
        )
        compiler._call_model = AsyncMock(return_value=synthesized)

        entries = await compiler.synthesize_ingest(
            REPO,
            42,
            "plan",
            "## Architecture\nThe system uses OAuth2 with refresh tokens for all external API calls. "
            * 3,
        )
        assert len(entries) == 1
        assert entries[0].source_issue == 42

    @pytest.mark.asyncio
    async def test_returns_empty_on_short_input(self, compiler: WikiCompiler) -> None:
        entries = await compiler.synthesize_ingest(REPO, 1, "plan", "short")
        assert entries == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_model_failure(self, compiler: WikiCompiler) -> None:
        compiler._call_model = AsyncMock(return_value=None)

        entries = await compiler.synthesize_ingest(REPO, 1, "plan", "x" * 200)
        assert entries == []


# ---------------------------------------------------------------------------
# Contradiction output parser
# ---------------------------------------------------------------------------


def test_parse_contradiction_output_valid():
    raw = '{"contradicts":[{"id":"01HQ0000000000000000000000","reason":"replaced"}]}'
    result = WikiCompiler._parse_contradiction_output(raw)
    assert isinstance(result, ContradictionCheck)
    assert len(result.contradicts) == 1
    assert result.contradicts[0].id == "01HQ0000000000000000000000"
    assert result.contradicts[0].reason == "replaced"


def test_parse_contradiction_output_empty_list():
    raw = '{"contradicts":[]}'
    result = WikiCompiler._parse_contradiction_output(raw)
    assert result.contradicts == []


def test_parse_contradiction_output_with_markdown_fence():
    raw = '```json\n{"contradicts":[]}\n```'
    result = WikiCompiler._parse_contradiction_output(raw)
    assert result.contradicts == []


def test_parse_contradiction_output_invalid_json_returns_empty():
    raw = "not json"
    result = WikiCompiler._parse_contradiction_output(raw)
    assert result.contradicts == []


def test_parse_contradiction_output_missing_key_returns_empty():
    raw = '{"other":"shape"}'
    result = WikiCompiler._parse_contradiction_output(raw)
    assert result.contradicts == []


class TestDetectContradictions:
    @pytest.mark.asyncio
    async def test_flags_contradicting_sibling(self, compiler: WikiCompiler) -> None:
        sibling = WikiEntry(
            id="01HQ0000000000000000000000",
            title="Use X",
            content="Always use X.",
            source_type="plan",
            topic="patterns",
        )
        new = WikiEntry(
            id="01HQ1111111111111111111111",
            title="Never use X",
            content="Never use X, prefer Y.",
            source_type="plan",
            topic="patterns",
        )
        raw_output = (
            '{"contradicts":[{"id":"01HQ0000000000000000000000",'
            '"reason":"new entry reverses guidance"}]}'
        )
        compiler._call_model = AsyncMock(return_value=raw_output)

        result = await compiler.detect_contradictions(
            new_entry=new, siblings=[sibling], repo="acme/widget"
        )
        assert len(result.contradicts) == 1
        assert result.contradicts[0].id == "01HQ0000000000000000000000"

    @pytest.mark.asyncio
    async def test_empty_siblings_skips_llm(self, compiler: WikiCompiler) -> None:
        compiler._call_model = AsyncMock()
        new = WikiEntry(
            id="01HQ0000000000000000000000",
            title="x",
            content="x",
            source_type="plan",
            topic="patterns",
        )
        result = await compiler.detect_contradictions(
            new_entry=new, siblings=[], repo="acme/widget"
        )
        assert result.contradicts == []
        compiler._call_model.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_empty(self, compiler: WikiCompiler) -> None:
        compiler._call_model = AsyncMock(return_value=None)
        sibling = WikiEntry(
            id="01HQ0000000000000000000000",
            title="x",
            content="x",
            source_type="plan",
            topic="patterns",
        )
        new = WikiEntry(
            id="01HQ1111111111111111111111",
            title="y",
            content="y",
            source_type="plan",
            topic="patterns",
        )
        result = await compiler.detect_contradictions(
            new_entry=new, siblings=[sibling], repo="acme/widget"
        )
        assert result.contradicts == []


# ---------------------------------------------------------------------------
# Generalization judge (Task 5.2)
# ---------------------------------------------------------------------------


def test_parse_generalization_output_valid():
    from wiki_compiler import GeneralizationCheck, WikiCompiler

    raw = (
        '{"same_principle": true, "generalized_title": "X",'
        ' "generalized_body": "Y.", "confidence": "high"}'
    )
    result = WikiCompiler._parse_generalization_output(raw)
    assert isinstance(result, GeneralizationCheck)
    assert result.same_principle is True
    assert result.confidence == "high"


def test_parse_generalization_output_invalid_returns_empty():
    from wiki_compiler import WikiCompiler

    result = WikiCompiler._parse_generalization_output("garbage")
    assert result.same_principle is False
    assert result.confidence == "low"


@pytest.mark.asyncio
async def test_generalize_pair_returns_check(compiler: WikiCompiler) -> None:
    raw = (
        '{"same_principle": true, "generalized_title": "Pytest async",'
        ' "generalized_body": "Use mode=auto.", "confidence": "high"}'
    )
    compiler._call_model = AsyncMock(return_value=raw)
    a = WikiEntry(
        title="a",
        content="A.",
        source_type="plan",
        topic="testing",
        source_repo="acme/widget",
    )
    b = WikiEntry(
        title="b",
        content="B.",
        source_type="plan",
        topic="testing",
        source_repo="other/thing",
    )
    result = await compiler.generalize_pair(entry_a=a, entry_b=b, topic="testing")
    assert result.same_principle is True
    assert result.generalized_title == "Pytest async"


@pytest.mark.asyncio
async def test_generalize_pair_llm_failure_returns_empty(
    compiler: WikiCompiler,
) -> None:
    compiler._call_model = AsyncMock(return_value=None)
    e = WikiEntry(
        title="x",
        content="x",
        source_type="plan",
        topic="patterns",
        source_repo="a/b",
    )
    result = await compiler.generalize_pair(entry_a=e, entry_b=e, topic="patterns")
    assert result.same_principle is False
