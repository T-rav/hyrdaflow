"""Ubiquitous language as a living artifact.

See ADR-0053. Terms are first-class entities (one markdown file per term in
docs/wiki/terms/). This module provides the Pydantic models, store helpers,
lint rules, and renderers.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
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
