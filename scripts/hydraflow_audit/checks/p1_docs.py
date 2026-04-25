"""P1 — Documentation Contract (ADR-0044).

One function per check row in P1's table. The runner backfills
severity/source/what/remediation from the spec, so these functions only
decide PASS / WARN / FAIL / NA and attach a message when useful.

The documentation spine is now ``docs/wiki/`` (the per-repo Karpathy
knowledge base) plus ``docs/adr/`` (decisions). The legacy
``docs/agents/`` how-to files were absorbed into wiki entries; CLAUDE.md
points operators at the wiki topic files.
"""

from __future__ import annotations

import re

from ..models import CheckContext, Finding, Status
from ..registry import register
from ._helpers import exists, file_contains, finding

# ---------------------------------------------------------------------------
# Simple file-exists checks — the documentation spine.
# ---------------------------------------------------------------------------


@register("P1.1")
def _claude_md_exists(ctx: CheckContext) -> Finding:
    return exists(ctx.root, "CLAUDE.md", "P1.1")


@register("P1.2")
def _wiki_index(ctx: CheckContext) -> Finding:
    """The wiki index — operator's entry point to the knowledge base."""
    return exists(ctx.root, "docs/wiki/index.md", "P1.2")


@register("P1.3")
def _architecture_md(ctx: CheckContext) -> Finding:
    """Architecture knowledge — file layout, layers, ports, async patterns."""
    return exists(ctx.root, "docs/wiki/architecture.md", "P1.3")


@register("P1.4")
def _gotchas_md(ctx: CheckContext) -> Finding:
    """Gotchas — worktree rules, recurring mistakes, footguns."""
    return exists(ctx.root, "docs/wiki/gotchas.md", "P1.4")


@register("P1.5")
def _testing_md(ctx: CheckContext) -> Finding:
    """Testing knowledge — conventions, scenarios, fixtures."""
    return exists(ctx.root, "docs/wiki/testing.md", "P1.5")


@register("P1.6")
def _patterns_md(ctx: CheckContext) -> Finding:
    """Patterns — kill-switch convention, dedup, escalation, quality gates."""
    return exists(ctx.root, "docs/wiki/patterns.md", "P1.6")


@register("P1.7")
def _dependencies_md(ctx: CheckContext) -> Finding:
    """Dependencies — optional services, graceful degradation."""
    return exists(ctx.root, "docs/wiki/dependencies.md", "P1.7")


@register("P1.8")
def _background_loops_documented(ctx: CheckContext) -> Finding:
    """Only required for orchestration-shaped repos. Looks for any background-loop
    knowledge entry in the wiki — exact entry titles vary.
    """
    if not ctx.is_orchestration_repo:
        return finding(
            "P1.8",
            Status.NA,
            "not an orchestration repo — background-loop wiki entry not required",
        )
    arch = ctx.root / "docs/wiki/architecture.md"
    if not arch.exists():
        return finding("P1.8", Status.FAIL, "missing: docs/wiki/architecture.md")
    text = arch.read_text(encoding="utf-8", errors="replace")
    if re.search(r"BaseBackgroundLoop|trust loop|background loop", text, re.IGNORECASE):
        return finding("P1.8", Status.PASS)
    return finding(
        "P1.8",
        Status.FAIL,
        "docs/wiki/architecture.md has no background-loop knowledge entry",
    )


@register("P1.9")
def _sentry_documented(ctx: CheckContext) -> Finding:
    """Sentry rules live as a wiki entry under patterns.md."""
    patterns = ctx.root / "docs/wiki/patterns.md"
    if not patterns.exists():
        return finding("P1.9", Status.FAIL, "missing: docs/wiki/patterns.md")
    text = patterns.read_text(encoding="utf-8", errors="replace")
    if "sentry" in text.lower():
        return finding("P1.9", Status.PASS)
    return finding(
        "P1.9", Status.FAIL, "docs/wiki/patterns.md has no Sentry knowledge entry"
    )


@register("P1.10")
def _commands_documented(ctx: CheckContext) -> Finding:
    """Make-target reference lives as a wiki entry under patterns.md."""
    patterns = ctx.root / "docs/wiki/patterns.md"
    if not patterns.exists():
        return finding("P1.10", Status.FAIL, "missing: docs/wiki/patterns.md")
    text = patterns.read_text(encoding="utf-8", errors="replace")
    if re.search(r"make\s+\w", text):
        return finding("P1.10", Status.PASS)
    return finding(
        "P1.10",
        Status.FAIL,
        "docs/wiki/patterns.md has no make-target knowledge entry",
    )


@register("P1.11")
def _adr_readme(ctx: CheckContext) -> Finding:
    readme = ctx.root / "docs/adr/README.md"
    if not readme.exists():
        return finding("P1.11", Status.FAIL, "missing: docs/adr/README.md")
    # An index table uses pipe-delimited markdown rows; check for at least one.
    text = readme.read_text(encoding="utf-8", errors="replace")
    if re.search(r"^\|\s*\[?\d{4}\]?", text, re.MULTILINE):
        return finding("P1.11", Status.PASS)
    return finding("P1.11", Status.FAIL, "docs/adr/README.md has no index table rows")


# ---------------------------------------------------------------------------
# Content-aware checks.
# ---------------------------------------------------------------------------


_QUICK_RULES_RE = re.compile(r"^##\s+Quick rules", re.MULTILINE)


@register("P1.12")
def _quick_rules_section(ctx: CheckContext) -> Finding:
    return file_contains(
        ctx.root,
        "CLAUDE.md",
        _QUICK_RULES_RE,
        "P1.12",
        absent_message="CLAUDE.md missing `## Quick rules` heading",
    )


_KNOWLEDGE_LOOKUP_RE = re.compile(
    r"^##\s+(Knowledge Lookup|Knowledge lookup|Topic index|Wiki topic index)",
    re.MULTILINE,
)


@register("P1.13")
def _knowledge_lookup_table(ctx: CheckContext) -> Finding:
    return file_contains(
        ctx.root,
        "CLAUDE.md",
        _KNOWLEDGE_LOOKUP_RE,
        "P1.13",
        absent_message="CLAUDE.md missing Knowledge Lookup / Topic index section",
    )


_LOAD_BEARING_ADRS = (
    ("0001", "five-concurrent-async-loops"),
    ("0002", "labels-as-state-machine"),
    ("0003", "git-worktrees-for-isolation"),
    ("0021", "persistence-architecture-and-data-layout"),
    ("0022", "integration-test-architecture-cross-phase"),
    ("0029", "caretaker-loop-pattern"),
    ("0032", "per-repo-wiki-knowledge-base"),
)


@register("P1.14")
def _load_bearing_adrs_present(ctx: CheckContext) -> Finding:
    if not ctx.is_orchestration_repo:
        return finding(
            "P1.14",
            Status.NA,
            "not an orchestration repo — load-bearing ADR set is N/A",
        )
    adr_dir = ctx.root / "docs" / "adr"
    if not adr_dir.is_dir():
        return finding("P1.14", Status.FAIL, "docs/adr/ missing")
    existing = {p.name for p in adr_dir.glob("*.md")}
    missing: list[str] = []
    for number, slug in _LOAD_BEARING_ADRS:
        if not any(name.startswith(f"{number}-") for name in existing):
            missing.append(f"ADR-{number} ({slug})")
    if missing:
        return finding(
            "P1.14", Status.FAIL, f"missing load-bearing ADRs: {', '.join(missing)}"
        )
    return finding("P1.14", Status.PASS)


@register("P1.15")
def _gotchas_has_content(ctx: CheckContext) -> Finding:
    """The gotchas topic page must have substantive content (≥5 sections)."""
    path = ctx.root / "docs/wiki/gotchas.md"
    if not path.exists():
        return finding("P1.15", Status.FAIL, "missing: docs/wiki/gotchas.md")
    text = path.read_text(encoding="utf-8", errors="replace")
    sections = re.findall(r"^##+\s+\S", text, re.MULTILINE)
    if len(sections) >= 5:
        return finding("P1.15", Status.PASS)
    return finding(
        "P1.15",
        Status.FAIL,
        f"docs/wiki/gotchas.md has {len(sections)} sections (need ≥5)",
    )


_LINE_NUMBER_CITATION = re.compile(r"`[^`]+\.py:\d+[^`]*`")


@register("P1.16")
def _no_line_numbers_in_adr_citations(ctx: CheckContext) -> Finding:
    adr_dir = ctx.root / "docs" / "adr"
    if not adr_dir.is_dir():
        return finding("P1.16", Status.NA, "no docs/adr/ — nothing to check")
    hits: list[str] = []
    for adr in sorted(adr_dir.glob("*.md")):
        text = adr.read_text(encoding="utf-8", errors="replace")
        for match in _LINE_NUMBER_CITATION.finditer(text):
            hits.append(f"{adr.name}: {match.group(0)}")
            if len(hits) >= 5:  # cap noise
                break
        if len(hits) >= 5:
            break
    if not hits:
        return finding("P1.16", Status.PASS)
    return finding(
        "P1.16",
        Status.WARN,
        "ADR citations include line numbers (drift risk); first offenders: "
        + "; ".join(hits),
    )
