"""Ubiquitous language as a living artifact.

See ADR-0053. Terms are first-class entities (one markdown file per term in
docs/wiki/terms/). This module provides the Pydantic models, store helpers,
lint rules, and renderers.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from ulid import ULID


class TermKind(StrEnum):
    AGGREGATE = "aggregate"
    ENTITY = "entity"
    VALUE_OBJECT = "value_object"
    DOMAIN_EVENT = "domain_event"
    SERVICE = "service"
    PORT = "port"
    ADAPTER = "adapter"
    BOUNDED_CONTEXT = "bounded_context"
    INVARIANT = "invariant"
    POLICY = "policy"
    LOOP = "loop"
    RUNNER = "runner"


class BoundedContext(StrEnum):
    CARETAKER = "caretaker"
    BUILDER = "builder"
    AI_DEV_TEAM = "ai-dev-team"
    SHARED_KERNEL = "shared-kernel"


class TermRelKind(StrEnum):
    IS_A = "is_a"
    PART_OF = "part_of"
    PUBLISHES = "publishes"
    CONSUMES = "consumes"
    GUARDED_BY = "guarded_by"
    IMPLEMENTS = "implements"
    DEPENDS_ON = "depends_on"
    CONTRADICTS = "contradicts"


class TermRel(BaseModel):
    kind: TermRelKind
    target: str = Field(min_length=1, description="Target term id (ULID)")


class Term(BaseModel):
    id: str = Field(default_factory=lambda: str(ULID()))
    name: str = Field(min_length=1, description="Canonical, exact-cased name")
    kind: TermKind
    bounded_context: BoundedContext
    definition: str = Field(min_length=1, description="One-paragraph agreed meaning")
    invariants: list[str] = Field(default_factory=list)
    code_anchor: str = Field(
        min_length=1,
        description="module:symbol — e.g., 'src/repo_wiki_loop.py:RepoWikiLoop'",
    )
    related: list[TermRel] = Field(default_factory=list)
    aliases: list[str] = Field(
        default_factory=list,
        description="Deprecated/paraphrase names — drives paraphrase lint",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="ULIDs of WikiEntry notes that justify this term",
    )
    superseded_by: str | None = None
    superseded_reason: str | None = None
    confidence: Literal["proposed", "accepted", "deprecated"] = "proposed"
    proposed_by: str | None = Field(
        default=None,
        description="Name of the loop that proposed this term (e.g., 'TermProposerLoop'); None for hand-authored",
    )
    proposed_at: str | None = Field(
        default=None,
        description="ISO8601 timestamp when proposed; None for hand-authored",
    )
    proposal_signals: list[str] | None = Field(
        default=None,
        description="Detection signals that flagged this candidate (e.g., ['S1', 'S2'])",
    )
    proposal_imports_seen: int | None = Field(
        default=None,
        ge=0,
        description="Count of covered-anchor modules importing this candidate at proposal time",
    )
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


_FRONTMATTER_DELIM = "---"


def dump_term_file(path: Path, term: Term) -> None:
    """Write a Term to disk as YAML-ish frontmatter + prose body.

    Body section captures `definition` as paragraphs and `invariants` as a
    bulleted list — readable by humans, parsed deterministically.
    """
    fm: dict[str, object] = {
        "id": term.id,
        "name": term.name,
        "kind": term.kind.value,
        "bounded_context": term.bounded_context.value,
        "code_anchor": term.code_anchor,
        "aliases": term.aliases,
        "related": [r.model_dump() for r in term.related],
        "evidence": term.evidence,
        "superseded_by": term.superseded_by,
        "superseded_reason": term.superseded_reason,
        "confidence": term.confidence,
        "created_at": term.created_at,
        "updated_at": term.updated_at,
    }
    if term.proposed_by is not None:
        fm["proposed_by"] = term.proposed_by
    if term.proposed_at is not None:
        fm["proposed_at"] = term.proposed_at
    if term.proposal_signals is not None:
        fm["proposal_signals"] = term.proposal_signals
    if term.proposal_imports_seen is not None:
        fm["proposal_imports_seen"] = term.proposal_imports_seen
    lines = [_FRONTMATTER_DELIM]
    for key, value in fm.items():
        lines.append(f"{key}: {json.dumps(value)}")
    lines.append(_FRONTMATTER_DELIM)
    lines.append("")
    lines.append("## Definition")
    lines.append("")
    lines.append(term.definition)
    if term.invariants:
        lines.append("")
        lines.append("## Invariants")
        lines.append("")
        for inv in term.invariants:
            lines.append(f"- {inv}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def load_term_file(path: Path) -> Term:
    """Parse a term file. Inverse of dump_term_file."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_DELIM:
        raise ValueError(f"{path}: missing frontmatter delimiter")
    fm: dict[str, object] = {}
    i = 1
    while i < len(lines) and lines[i].strip() != _FRONTMATTER_DELIM:
        line = lines[i]
        if ":" in line:
            key, _, raw = line.partition(":")
            fm[key.strip()] = json.loads(raw.strip())
        i += 1
    if i >= len(lines):
        raise ValueError(f"{path}: unterminated frontmatter")
    body = "\n".join(lines[i + 1 :]).strip()

    definition, invariants = _parse_term_body(body)
    fm["definition"] = definition
    fm["invariants"] = invariants
    return Term.model_validate(fm)


def _parse_term_body(body: str) -> tuple[str, list[str]]:
    """Split body into definition + invariants. Sections delimited by `## `."""
    definition_lines: list[str] = []
    invariants: list[str] = []
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            current = line[3:].strip().lower()
            continue
        if current == "definition":
            definition_lines.append(line)
        elif current == "invariants" and line.startswith("- "):
            invariants.append(line[2:].strip())
    return "\n".join(definition_lines).strip(), invariants


def _slugify_term_name(name: str) -> str:
    """Convert a term name (e.g., 'RepoWikiLoop') to a slug (e.g., 'repo-wiki-loop')."""
    # Insert hyphens before uppercase letters that follow lowercase
    step1 = re.sub(r"(?<=[a-z])(?=[A-Z])", "-", name)
    # Also insert before uppercase followed by lowercase and not at word start
    step2 = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "-", step1)
    # Convert to lowercase
    step3 = step2.lower()
    # Remove any sequences of non-alphanumeric chars and replace with single hyphen
    step4 = re.sub(r"[^a-z0-9]+", "-", step3)
    # Strip leading/trailing hyphens
    return step4.strip("-")


class TermStore:
    """File-based store for Term records (one file per term)."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def write(self, term: Term) -> Path:
        self._root.mkdir(parents=True, exist_ok=True)
        path = self._root / f"{_slugify_term_name(term.name)}.md"
        dump_term_file(path, term)
        return path

    def list(self) -> list[Term]:
        if not self._root.is_dir():
            return []
        return sorted(
            (load_term_file(p) for p in self._root.glob("*.md")),
            key=lambda t: t.name.lower(),
        )

    def load_by_name(self, name: str) -> Term | None:
        path = self._root / f"{_slugify_term_name(name)}.md"
        if not path.exists():
            return None
        return load_term_file(path)


def build_symbol_index(src_root: Path) -> dict[str, list[str]]:
    """Walk *.py under src_root, return {ClassName: [path:ClassName, ...]}.

    Uses AST so syntax errors localize to one file. Skips files that fail
    to parse (logged via a warn-only mechanism added in lint).
    """
    index: dict[str, list[str]] = {}
    for path in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                rel = path.relative_to(src_root.parent)
                index.setdefault(node.name, []).append(f"{rel}:{node.name}")
    return index


def build_import_graph(src_root: Path) -> dict[str, set[str]]:
    """Walk *.py under src_root, return {path:relative-from-src-parent: {ImportedName, ...}}.

    Captures `from X import Name` (alias resolved to original name) and `import X.Y as Z`
    (records the leaf name `Y`). Used by candidate-detection (S2) and edge-inference (E2).
    Skips files that fail to parse — same policy as build_symbol_index.
    """
    graph: dict[str, set[str]] = {}
    for path in sorted(src_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(src_root.parent))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    names.add(alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    leaf = alias.asname or alias.name.rsplit(".", 1)[-1]
                    names.add(leaf)
        graph[rel] = names
    return graph


def resolve_anchor(anchor: str, index: dict[str, list[str]]) -> bool:
    """True iff anchor (path:ClassName) appears in the index."""
    if ":" not in anchor:
        return False
    _, _, name = anchor.rpartition(":")
    return anchor in index.get(name, [])


def lint_anchor_resolution(terms: list[Term], src_root: Path) -> list[str]:
    """Return human-readable failure strings for terms whose anchors
    do not resolve. Empty list = clean.
    """
    index = build_symbol_index(src_root)
    failures: list[str] = []
    for term in terms:
        if not resolve_anchor(term.code_anchor, index):
            failures.append(f"{term.name} -> {term.code_anchor}")
    return failures


def lint_paraphrases(terms: list[Term], wiki_root: Path) -> list[str]:
    """Scan wiki/*.md (excluding wiki/terms/) for alias usage.

    Returns one human-readable string per violation. Case-insensitive
    word-boundary match. The terms/ subdirectory is excluded — those
    files DEFINE aliases.
    """
    if not wiki_root.is_dir():
        return []
    alias_map: dict[str, str] = {}
    for term in terms:
        for alias in term.aliases:
            alias_map[alias.lower()] = term.name

    violations: list[str] = []
    for path in sorted(wiki_root.rglob("*.md")):
        if "terms" in path.relative_to(wiki_root).parts:
            continue
        text = path.read_text(encoding="utf-8").lower()
        for alias, canonical in alias_map.items():
            pattern = re.compile(rf"\b{re.escape(alias)}\b")
            if pattern.search(text):
                violations.append(
                    f"{path.relative_to(wiki_root)}: '{alias}' should be '{canonical}'"
                )
    return violations


_LOAD_BEARING_SUFFIXES = ("Loop", "Runner", "Port", "Adapter")


def lint_reverse_coverage(terms: list[Term], src_root: Path) -> list[str]:
    """Return load-bearing symbols in src_root with no corresponding Term.

    Load-bearing = class name ends in Loop/Runner/Port/Adapter. Warn-only;
    the caller decides whether to fail.
    """
    index = build_symbol_index(src_root)
    covered = {t.code_anchor for t in terms}
    uncovered: list[str] = []
    for name, locations in index.items():
        if not name.endswith(_LOAD_BEARING_SUFFIXES):
            continue
        for loc in locations:
            if loc not in covered:
                uncovered.append(loc)
    return sorted(uncovered)


def render_glossary(terms: list[Term]) -> str:
    """Render an alphabetical glossary as Markdown."""
    sorted_terms = sorted(terms, key=lambda t: t.name.lower())
    lines = [
        "<!-- DO NOT EDIT — generated by src/ubiquitous_language.py:render_glossary -->",
        "",
        "# Ubiquitous Language",
        "",
        f"_{len(sorted_terms)} terms across "
        f"{len({t.bounded_context for t in sorted_terms})} bounded contexts._",
        "",
        "See [ADR-0053](../../adr/0053-ubiquitous-language-as-living-artifact.md) "
        "for the governing pattern.",
        "",
    ]
    for t in sorted_terms:
        lines.append(f"## {t.name}")
        lines.append("")
        lines.append(
            f"**Kind:** `{t.kind.value}` · **Context:** `{t.bounded_context.value}` · "
            f"**Anchor:** `{t.code_anchor}` · **Confidence:** `{t.confidence}`"
        )
        if t.aliases:
            lines.append(f"**Aliases:** {', '.join(f'`{a}`' for a in t.aliases)}")
        lines.append("")
        lines.append(t.definition)
        if t.invariants:
            lines.append("")
            lines.append("**Invariants:**")
            for inv in t.invariants:
                lines.append(f"- {inv}")
        lines.append("")
    return "\n".join(lines)


def render_context_map(terms: list[Term]) -> str:
    """Render a Mermaid graph: one subgraph per bounded context, typed edges."""
    by_context: dict[BoundedContext, list[Term]] = {}
    for t in terms:
        by_context.setdefault(t.bounded_context, []).append(t)

    id_to_name = {t.id: t.name for t in terms}

    lines = [
        "<!-- DO NOT EDIT — generated by src/ubiquitous_language.py:render_context_map -->",
        "",
        "# Ubiquitous Language — Context Map",
        "",
        "```mermaid",
        "graph LR",
    ]
    for ctx, ctx_terms in sorted(by_context.items(), key=lambda kv: kv[0].value):
        lines.append(f"  subgraph {ctx.value}")
        for t in sorted(ctx_terms, key=lambda x: x.name.lower()):
            lines.append(f'    {t.name}["{t.name}<br/><i>{t.kind.value}</i>"]')
        lines.append("  end")
    for t in terms:
        for rel in t.related:
            target_name = id_to_name.get(rel.target)
            if target_name is None:
                continue
            lines.append(f"  {t.name} -->|{rel.kind.value}| {target_name}")
    lines.append("```")
    lines.append("")
    return "\n".join(lines)


@dataclass(frozen=True)
class Candidate:
    """A class flagged as a possible new term, ready for LLM drafting."""

    name: str
    code_anchor: str  # "src/path.py:ClassName"
    signals: tuple[str, ...]  # subset of ("S1", "S2")
    imports_seen: int  # in-degree from covered-anchor modules
    importing_term_anchors: tuple[str, ...] = field(default_factory=tuple)
    """Anchors of covered terms whose modules import this candidate.
    Used by the proposer's LLM call to ground depends_on edges (E2)."""


def detect_candidates(
    index: dict[str, list[str]],
    import_graph: dict[str, set[str]],
    terms: list[Term],
) -> list[Candidate]:
    """Return ranked list of Candidates from the live codebase.

    Combines S1 (load-bearing suffix) and S2 (imported by a covered-term anchor's module),
    excludes already-covered anchors, ranks by S5 (in-degree from covered modules then by
    name for stability).
    """
    covered_anchors = {t.code_anchor for t in terms}
    covered_modules: set[str] = set()
    for anchor in covered_anchors:
        if ":" in anchor:
            module, _, _ = anchor.partition(":")
            covered_modules.add(module)

    in_degree: dict[str, int] = {}
    importers_of: dict[str, list[str]] = {}
    for module, names in import_graph.items():
        if module not in covered_modules:
            continue
        for name in names:
            in_degree[name] = in_degree.get(name, 0) + 1
            importers_of.setdefault(name, []).append(module)

    candidates_by_name: dict[str, Candidate] = {}
    for name, locations in index.items():
        for location in locations:
            if location in covered_anchors:
                continue
            signals: list[str] = []
            if name.endswith(_LOAD_BEARING_SUFFIXES):
                signals.append("S1")
            if name in in_degree:
                signals.append("S2")
            if not signals:
                continue
            importing_anchors: list[str] = []
            for importer in importers_of.get(name, []):
                for term in terms:
                    if term.code_anchor.startswith(f"{importer}:"):
                        importing_anchors.append(term.code_anchor)
            if name not in candidates_by_name:
                candidates_by_name[name] = Candidate(
                    name=name,
                    code_anchor=location,
                    signals=tuple(signals),
                    imports_seen=in_degree.get(name, 0),
                    importing_term_anchors=tuple(sorted(set(importing_anchors))),
                )

    return sorted(
        candidates_by_name.values(),
        key=lambda c: (-c.imports_seen, c.name),
    )
