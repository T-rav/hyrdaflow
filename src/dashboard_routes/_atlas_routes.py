"""/api/atlas/* endpoints — the Atlas knowledge-graph dashboard surface (ADR-0059).

Reads from the existing TermStore at config.repo_root/docs/wiki/terms/ and from
docs/adr/*.md. Sibling to _wiki_routes.py; does not replace it. The Maintenance
sub-tab continues to call /api/wiki/* for run-status; term + ADR data lives here.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from ubiquitous_language import TermStore

if TYPE_CHECKING:
    from fastapi import APIRouter

    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard.atlas")

_ADR_FILENAME_RE = re.compile(r"^(\d{4,5})-(.+)\.md$")
_ADR_TITLE_RE = re.compile(r"^#\s+ADR-\d{4,5}:\s+(.+?)\s*$", re.MULTILINE)


def _terms_root(ctx: RouteContext) -> Path:
    return (ctx.config.repo_root / "docs" / "wiki" / "terms").resolve()


def _adr_root(ctx: RouteContext) -> Path:
    return (ctx.config.repo_root / "docs" / "adr").resolve()


def _term_summary(term) -> dict[str, Any]:
    return {
        "id": term.id,
        "name": term.name,
        "kind": term.kind.value,
        "bounded_context": term.bounded_context.value,
        "code_anchor": term.code_anchor,
        "confidence": term.confidence,
    }


def _term_detail(term, by_id: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": term.id,
        "name": term.name,
        "kind": term.kind.value,
        "bounded_context": term.bounded_context.value,
        "code_anchor": term.code_anchor,
        "confidence": term.confidence,
        "definition": term.definition,
        "invariants": list(term.invariants),
        "aliases": list(term.aliases),
        "edges": [
            {
                "kind": rel.kind.value,
                "target_id": rel.target,
                "target_name": (
                    by_id[rel.target].name if rel.target in by_id else None
                ),
            }
            for rel in term.related
        ],
        "evidence": list(term.evidence),
        "superseded_by": term.superseded_by,
        "superseded_reason": term.superseded_reason,
        # Provenance fields from TermProposerLoop (ADR-0054). All None for
        # hand-authored terms; populated when the loop drafted the term.
        "proposed_by": term.proposed_by,
        "proposed_at": term.proposed_at,
        "proposal_signals": (
            list(term.proposal_signals) if term.proposal_signals is not None else None
        ),
        "proposal_imports_seen": term.proposal_imports_seen,
    }


def _adr_related_terms(body: str) -> list[str]:
    """Extract raw lines from the ADR's '## Related' section.

    Returns the line text (without the leading bullet) for each '- ' bullet.
    Lookup against term names/aliases happens at graph-assembly time.
    """
    out: list[str] = []
    related_match = re.search(r"^##\s+Related\s*$", body, re.MULTILINE)
    if not related_match:
        return out
    rest = body[related_match.end() :].lstrip("\n")
    for line in rest.splitlines():
        if line.startswith("## "):
            break
        stripped = line.strip()
        if stripped.startswith("- "):
            out.append(stripped[2:].strip())
    return out


def _parse_adr_field(body: str, heading: str) -> str:
    """Extract the first non-empty line following '## {heading}'."""
    pattern = re.compile(rf"^##\s+{re.escape(heading)}\s*$", re.MULTILINE)
    m = pattern.search(body)
    if not m:
        return ""
    rest = body[m.end() :].lstrip("\n")
    for line in rest.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            break
        if stripped:
            return stripped
    return ""


def _adr_summary_from_path(path: Path) -> dict[str, Any] | None:
    if path.name == "README.md":
        return None
    m = _ADR_FILENAME_RE.match(path.name)
    if m is None:
        return None
    number = int(m.group(1))
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    title_match = _ADR_TITLE_RE.search(text)
    title = title_match.group(1) if title_match else m.group(2).replace("-", " ")
    return {
        "number": number,
        "title": title,
        "status": _parse_adr_field(text, "Status"),
        "date": _parse_adr_field(text, "Date"),
    }


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Attach /api/atlas/* handlers to ``router``."""

    @router.get("/api/atlas/terms")
    def list_atlas_terms() -> list[dict[str, Any]]:
        store = TermStore(_terms_root(ctx))
        return [_term_summary(t) for t in store.list()]

    @router.get("/api/atlas/terms/{term_id}")
    def get_atlas_term(term_id: str) -> dict[str, Any]:
        store = TermStore(_terms_root(ctx))
        terms = store.list()
        by_id = {t.id: t for t in terms}
        if term_id not in by_id:
            raise HTTPException(status_code=404, detail="term not found")
        return _term_detail(by_id[term_id], by_id)

    @router.get("/api/atlas/graph")
    def get_atlas_graph(include_adrs: bool = True) -> dict[str, Any]:
        store = TermStore(_terms_root(ctx))
        terms = store.list()
        contexts_seen: dict[str, dict[str, str]] = {}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for term in terms:
            ctx_id = term.bounded_context.value
            contexts_seen.setdefault(ctx_id, {"id": ctx_id, "label": ctx_id})
            nodes.append(
                {
                    "id": term.id,
                    "type": "term",
                    "name": term.name,
                    "kind": term.kind.value,
                    "confidence": term.confidence,
                    "parent": ctx_id,
                    "code_anchor": term.code_anchor,
                }
            )
            for rel in term.related:
                edges.append(
                    {
                        "source": term.id,
                        "target": rel.target,
                        "kind": rel.kind.value,
                    }
                )

        if include_adrs:
            adr_root = _adr_root(ctx)
            if adr_root.is_dir():
                # Pre-build a lookup of {lowercased name|alias: term.id}.
                term_lookup: dict[str, str] = {}
                for term in terms:
                    term_lookup[term.name.lower()] = term.id
                    for alias in term.aliases:
                        term_lookup.setdefault(alias.lower(), term.id)

                adr_context_added = False
                for path in sorted(adr_root.glob("*.md")):
                    summary = _adr_summary_from_path(path)
                    if summary is None:
                        continue
                    if not adr_context_added:
                        contexts_seen.setdefault(
                            "adrs", {"id": "adrs", "label": "adrs"}
                        )
                        adr_context_added = True
                    adr_id = f"adr-{summary['number']}"
                    nodes.append(
                        {
                            "id": adr_id,
                            "type": "adr",
                            "name": f"ADR-{summary['number']:04d}",
                            "title": summary["title"],
                            "status": summary["status"],
                            "parent": "adrs",
                        }
                    )
                    try:
                        text = path.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    related_lines = _adr_related_terms(text)
                    seen_targets: set[str] = set()
                    for line in related_lines:
                        line_lower = line.lower()
                        for needle, term_id in term_lookup.items():
                            # Word-boundary match — substring matching gave
                            # spurious edges (e.g., the term "Task" matched
                            # incidental prose like "this ADR task").
                            if term_id in seen_targets:
                                continue
                            pattern = rf"\b{re.escape(needle)}\b"
                            if re.search(pattern, line_lower):
                                edges.append(
                                    {
                                        "source": adr_id,
                                        "target": term_id,
                                        "kind": "relates_to",
                                    }
                                )
                                seen_targets.add(term_id)

        return {
            "nodes": nodes,
            "edges": edges,
            "contexts": list(contexts_seen.values()),
        }

    @router.get("/api/atlas/adrs")
    def list_atlas_adrs() -> list[dict[str, Any]]:
        root = _adr_root(ctx)
        if not root.is_dir():
            return []
        out: list[dict[str, Any]] = []
        for path in sorted(root.glob("*.md")):
            summary = _adr_summary_from_path(path)
            if summary is not None:
                out.append(summary)
        return out

    @router.get("/api/atlas/adrs/{number}")
    def get_atlas_adr(number: int) -> dict[str, Any]:
        root = _adr_root(ctx)
        if not root.is_dir():
            raise HTTPException(status_code=404, detail="adr dir not found")
        prefix = f"{number:04d}-"
        for path in sorted(root.glob(f"{prefix}*.md")):
            text = path.read_text(encoding="utf-8")
            title_match = _ADR_TITLE_RE.search(text)
            title = (
                title_match.group(1)
                if title_match
                else path.stem.split("-", 1)[-1].replace("-", " ")
            )
            related_lines = _adr_related_terms(text)
            return {
                "number": number,
                "title": title,
                "status": _parse_adr_field(text, "Status"),
                "date": _parse_adr_field(text, "Date"),
                "body": text,
                "related": related_lines,
            }
        raise HTTPException(status_code=404, detail="adr not found")

    @router.get("/api/atlas/term-loops/status")
    def get_term_loops_status() -> dict[str, Any]:
        """Last-tick snapshot for the term-graph maintenance loops (P2-T6).

        Reads from StateTracker.get_worker_heartbeats() — same source the
        SystemPanel background-worker tiles consume. Returns one entry per
        relevant loop. When the orchestrator has never run, every entry is
        present with last_run=None so the UI can render "never run" without
        special-casing absence.
        """
        loops = ("term_proposer", "term_pruner", "edge_proposer")
        try:
            heartbeats = ctx.state.get_worker_heartbeats()
        except Exception:  # noqa: BLE001 — diagnostics endpoint, never fail
            heartbeats = {}
        out: dict[str, Any] = {}
        for name in loops:
            hb = heartbeats.get(name) or {}
            details = hb.get("details") or {}
            out[name] = {
                "status": hb.get("status") or "unknown",
                "last_run": hb.get("last_run"),
                "last_pr_url": (details.get("open_pr_url") or details.get("pr_url")),
                "last_action_count": details.get("count"),
            }
        return out
