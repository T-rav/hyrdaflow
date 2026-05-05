"""Ubiquitous language as a living artifact.

See ADR-0053. Terms are first-class entities (one markdown file per term in
docs/wiki/terms/). This module provides the Pydantic models, store helpers,
lint rules, and renderers.
"""

from __future__ import annotations

import ast
import json
import re
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
