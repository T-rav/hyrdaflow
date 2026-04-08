"""Structural guards for CLAUDE.md and docs/agents/.

These tests enforce the ToC-style structure CLAUDE.md is migrating toward
(#6425). They catch regressions where content drifts back into CLAUDE.md
or where ToC links break because a doc was renamed.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
DOCS_AGENTS = REPO_ROOT / "docs" / "agents"


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

    def test_references_repo_wiki(self) -> None:
        content = _read_claude_md()
        assert "repo_wiki" in content, (
            "CLAUDE.md must reference the repo wiki so agents know about "
            "the per-repo LLM knowledge base."
        )


class TestAvoidedPatternsExtraction:
    """CLAUDE.md should link to docs/agents/avoided-patterns.md, not
    duplicate the patterns inline (part of #6425 incremental refactor).
    """

    def test_avoided_patterns_doc_exists(self) -> None:
        doc = DOCS_AGENTS / "avoided-patterns.md"
        assert doc.exists(), (
            f"{doc} must exist — it is the canonical location for "
            "avoided patterns referenced by CLAUDE.md, sensor_enricher, "
            "and the code-grooming audit agent."
        )

    def test_avoided_patterns_doc_covers_known_rules(self) -> None:
        doc = DOCS_AGENTS / "avoided-patterns.md"
        content = doc.read_text(encoding="utf-8")
        # The five rules that existed in CLAUDE.md before extraction.
        required_markers = [
            "Pydantic",
            "optional dependencies",
            "sleep",
            "Mocking",
            "Falsy checks",
        ]
        missing = [m for m in required_markers if m not in content]
        assert not missing, f"avoided-patterns.md is missing required rules: {missing}"

    def test_claude_md_links_to_avoided_patterns_doc(self) -> None:
        content = _read_claude_md()
        assert "docs/agents/avoided-patterns.md" in content, (
            "CLAUDE.md must link to docs/agents/avoided-patterns.md "
            "instead of inlining the rules."
        )

    def test_claude_md_does_not_inline_avoided_patterns(self) -> None:
        """The five rule bullets must NOT appear inline in CLAUDE.md.

        CLAUDE.md keeps the section heading and a link, but the actual
        rule text lives in docs/agents/avoided-patterns.md.
        """
        content = _read_claude_md()
        # Each of these phrases is specific enough to the rule body that
        # finding it in CLAUDE.md means the section was not extracted.
        inline_markers = [
            "Never `from hindsight import Bank` at module level",
            "Never `sleep(N)` in a loop",
            "Patch functions at their *import site*",
            "Falsy checks on optional objects",
        ]
        leaked = [m for m in inline_markers if m in content]
        assert not leaked, (
            f"CLAUDE.md still inlines avoided-pattern rule text: {leaked}. "
            "These should live in docs/agents/avoided-patterns.md."
        )


class TestClaudeMdIsToCForm:
    """CLAUDE.md must remain a lean table of contents, not an encyclopedia.

    #6425 caps CLAUDE.md at ≤80 lines and requires the full topic set to
    exist under docs/agents/. This test guards against content drifting
    back into CLAUDE.md.
    """

    LINE_BUDGET = 80

    def test_claude_md_within_line_budget(self) -> None:
        content = _read_claude_md()
        line_count = len(content.splitlines())
        assert line_count <= self.LINE_BUDGET, (
            f"CLAUDE.md is {line_count} lines — exceeds the {self.LINE_BUDGET}-line "
            "budget. Move content into a docs/agents/*.md topic file and link it."
        )

    def test_all_topic_files_exist(self) -> None:
        required = [
            "architecture.md",
            "avoided-patterns.md",
            "background-loops.md",
            "commands.md",
            "quality-gates.md",
            "sentry.md",
            "testing.md",
            "ui-standards.md",
            "worktrees.md",
            "README.md",
        ]
        missing = [f for f in required if not (DOCS_AGENTS / f).exists()]
        assert not missing, f"missing docs/agents files: {missing}"

    def test_claude_md_links_to_every_topic_file(self) -> None:
        """Every topic file in docs/agents/ (except README.md) must be
        linked from CLAUDE.md. Catches topic drift where a doc is added
        but the ToC is forgotten."""
        content = _read_claude_md()
        topic_files = {
            f.name for f in DOCS_AGENTS.glob("*.md") if f.name != "README.md"
        }
        unlinked = [f for f in topic_files if f"docs/agents/{f}" not in content]
        assert not unlinked, f"topic files not linked from CLAUDE.md: {unlinked}"

    def test_docs_agents_readme_is_index(self) -> None:
        """The README.md in docs/agents/ is an index, not a topic."""
        readme = DOCS_AGENTS / "README.md"
        assert readme.exists()
        content = readme.read_text(encoding="utf-8")
        # The index must list every topic file.
        topic_files = sorted(
            f.name for f in DOCS_AGENTS.glob("*.md") if f.name != "README.md"
        )
        missing = [f for f in topic_files if f not in content]
        assert not missing, f"docs/agents/README.md index missing entries: {missing}"


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
