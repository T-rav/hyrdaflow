"""Structural guards for CLAUDE.md and docs/wiki/.

These tests enforce the ToC-style structure CLAUDE.md is migrating toward.
They catch regressions where content drifts back into CLAUDE.md or where
ToC links break because a doc was renamed.

The wiki restructure (PR #8417) replaces ``docs/agents/`` (per-topic
how-to files) with ``docs/wiki/`` (Karpathy-pattern knowledge base with
five topic files: architecture, patterns, gotchas, testing, dependencies).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DOCS_WIKI = REPO_ROOT / "docs" / "wiki"


def _read_claude_md() -> str:
    assert CLAUDE_MD.exists(), f"{CLAUDE_MD} missing"
    return CLAUDE_MD.read_text(encoding="utf-8")


class TestKnowledgeLookupSection:
    def test_has_knowledge_lookup_section(self) -> None:
        content = _read_claude_md()
        assert "## Knowledge Lookup" in content, (
            "CLAUDE.md must have a '## Knowledge Lookup' section pointing "
            "agents at ADRs, the repo wiki, and docs/."
        )

    def test_references_adr_index(self) -> None:
        content = _read_claude_md()
        assert "docs/adr/" in content, (
            "CLAUDE.md must reference docs/adr/ so agents know where to "
            "find architecture decision records."
        )

    def test_references_wiki(self) -> None:
        content = _read_claude_md()
        assert "docs/wiki" in content, (
            "CLAUDE.md must reference the wiki so agents know about "
            "the per-repo LLM knowledge base."
        )


class TestGotchasContent:
    """Avoided-pattern rules live as wiki entries under docs/wiki/gotchas.md.
    CLAUDE.md links to the wiki rather than inlining the rules.
    """

    def test_gotchas_doc_exists(self) -> None:
        doc = DOCS_WIKI / "gotchas.md"
        assert doc.exists(), (
            f"{doc} must exist — it is the canonical location for "
            "recurring mistakes referenced by CLAUDE.md, sensor_enricher, "
            "and the code-grooming audit agent."
        )

    def test_gotchas_doc_covers_known_rules(self) -> None:
        doc = DOCS_WIKI / "gotchas.md"
        content = doc.read_text(encoding="utf-8").lower()
        # Topic markers from the legacy avoided-patterns content. As wiki
        # entries get rewritten by the librarian some terminology may
        # shift — keep this list short and rooted in concrete domain
        # terms, not exact phrasing. Match case-insensitively because the
        # librarian may write "mock" inline rather than "Mocking" as a
        # heading.
        required_markers = [
            "pydantic",
            "mock",
        ]
        missing = [m for m in required_markers if m not in content]
        assert not missing, f"docs/wiki/gotchas.md is missing topic markers: {missing}"

    def test_claude_md_links_to_wiki_gotchas(self) -> None:
        content = _read_claude_md()
        assert "docs/wiki/gotchas.md" in content, (
            "CLAUDE.md must link to docs/wiki/gotchas.md instead of "
            "inlining footgun rules."
        )

    def test_claude_md_does_not_inline_avoided_patterns(self) -> None:
        """Specific avoided-pattern rule bodies must NOT appear inline.

        CLAUDE.md keeps a high-level reminder and a wiki link; the
        rule text lives in docs/wiki/gotchas.md.
        """
        content = _read_claude_md()
        inline_markers = [
            "Never `from hindsight import Bank` at module level",
            "Never `sleep(N)` in a loop",
            "Patch functions at their *import site*",
            "Falsy checks on optional objects",
        ]
        leaked = [m for m in inline_markers if m in content]
        assert not leaked, (
            f"CLAUDE.md still inlines avoided-pattern rule text: {leaked}. "
            "These should live in docs/wiki/gotchas.md."
        )


class TestClaudeMdIsToCForm:
    """CLAUDE.md must remain a lean table of contents, not an encyclopedia."""

    LINE_BUDGET = 80

    def test_claude_md_within_line_budget(self) -> None:
        content = _read_claude_md()
        line_count = len(content.splitlines())
        assert line_count <= self.LINE_BUDGET, (
            f"CLAUDE.md is {line_count} lines — exceeds the "
            f"{self.LINE_BUDGET}-line budget. Move content into "
            "docs/wiki/ entries and link them."
        )

    def test_all_topic_files_exist(self) -> None:
        required = [
            "architecture.md",
            "patterns.md",
            "gotchas.md",
            "testing.md",
            "dependencies.md",
            "index.md",
        ]
        missing = [f for f in required if not (DOCS_WIKI / f).exists()]
        assert not missing, f"missing docs/wiki files: {missing}"

    def test_claude_md_links_to_every_topic_file(self) -> None:
        """Every topic file in docs/wiki/ (except index.md) must be
        linked from CLAUDE.md. Catches topic drift where a doc is added
        but the ToC is forgotten.
        """
        content = _read_claude_md()
        topic_files = {f.name for f in DOCS_WIKI.glob("*.md") if f.name != "index.md"}
        unlinked = [f for f in topic_files if f"docs/wiki/{f}" not in content]
        assert not unlinked, f"topic files not linked from CLAUDE.md: {unlinked}"

    def test_wiki_index_is_a_real_index(self) -> None:
        """docs/wiki/index.md is the auto-built index of every entry."""
        index = DOCS_WIKI / "index.md"
        assert index.exists()
        content = index.read_text(encoding="utf-8")
        assert "Wiki Index" in content, (
            "docs/wiki/index.md must be the wiki's auto-generated index"
        )


class TestLinkedDocsResolve:
    """Every markdown link from CLAUDE.md to a relative path must resolve
    to a real file. Prevents ToC rot as docs are renamed.
    """

    _LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")

    def test_relative_links_exist(self) -> None:
        content = _read_claude_md()
        broken: list[str] = []
        for _, target in self._LINK_RE.findall(content):
            # Skip external and in-page links.
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            # Strip fragments (#anchor) from the path.
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            resolved = (REPO_ROOT / path_part).resolve()
            if not resolved.exists():
                broken.append(target)
        assert not broken, f"CLAUDE.md has broken links: {broken}"
