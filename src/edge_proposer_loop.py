"""Edge-Proposer Loop — densifies the term context map with depends_on + implements edges.

See ADR-0058 and docs/superpowers/specs/2026-05-08-edge-proposer-loop-design.md.
"""

from __future__ import annotations

import ast
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from term_proposer_loop import BotPRPort, _render_term_file_str
from ubiquitous_language import (
    Term,
    TermRel,
    TermRelKind,
    TermStore,
    _slugify_term_name,
    build_import_graph,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig


logger = logging.getLogger("hydraflow.edge_proposer_loop")

_WORKER_NAME = "edge_proposer"
EDGE_PROPOSER_PR_LABEL = "hydraflow-ul-edges"
"""Label applied to bot-PRs opened by ``EdgeProposerLoop``.

Public constant — imported by ``review_phase`` to skip routing such PRs through
the agent pipeline (the structural edge inference IS the work). See ADR-0058.
"""


class EdgeProposerLoop(BaseBackgroundLoop):
    """Proposes depends_on + implements edges between existing terms."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        pr_port: BotPRPort,
        repo_root: Path,
    ) -> None:
        super().__init__(worker_name=_WORKER_NAME, config=config, deps=deps)
        self._pr_port = pr_port
        self._repo_root = repo_root

    def _get_default_interval(self) -> int:
        return self._config.edge_proposer_interval

    async def _do_work(self) -> dict[str, Any] | None:
        # Canonical operator UI kill-switch (ADR-0049).
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}
        # Static config gate — defense-in-depth (slice #5.0).
        if not self._config.edge_proposer_enabled:
            return {"status": "disabled"}

        terms_root = self._repo_root / "docs" / "wiki" / "terms"
        src_root = self._repo_root / "src"

        store = TermStore(terms_root)
        terms = store.list()
        graph = build_import_graph(src_root)

        # Class-name → term (for resolving import target names back to terms)
        terms_by_class_name: dict[str, Term] = {}
        for t in terms:
            class_name = (
                t.code_anchor.split(":", 1)[1]
                if ":" in t.code_anchor
                else t.code_anchor
            )
            terms_by_class_name[class_name] = t

        # Existing edges per term: set of (kind, target_id) tuples
        existing_edges: dict[str, set[tuple[str, str]]] = {
            t.id: {(r.kind.value, r.target) for r in t.related} for t in terms
        }

        proposals: dict[str, list[TermRel]] = {}  # term_id -> new edges

        for src_term in terms:
            # Resolve module path from anchor (e.g., "src/alpha.py:Alpha" -> "src/alpha.py")
            module_path = src_term.code_anchor.split(":", 1)[0]
            # depends_on: every imported name that resolves to another term
            for imported_name in graph.get(module_path, set()):
                tgt_term = terms_by_class_name.get(imported_name)
                if tgt_term is None or tgt_term.id == src_term.id:
                    continue
                edge = ("depends_on", tgt_term.id)
                if edge in existing_edges[src_term.id]:
                    continue
                existing_edges[src_term.id].add(edge)
                proposals.setdefault(src_term.id, []).append(
                    TermRel(kind=TermRelKind.DEPENDS_ON, target=tgt_term.id)
                )
            # implements: AST-walk the source's class definition for direct bases
            try:
                source_text = (self._repo_root / module_path).read_text(
                    encoding="utf-8"
                )
                tree = ast.parse(source_text)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            class_name = (
                src_term.code_anchor.split(":", 1)[1]
                if ":" in src_term.code_anchor
                else src_term.code_anchor
            )
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef) or node.name != class_name:
                    continue
                for base in node.bases:
                    base_name = _ast_name_simple(base)
                    if base_name is None:
                        continue
                    tgt_term = terms_by_class_name.get(base_name)
                    if tgt_term is None or tgt_term.id == src_term.id:
                        continue
                    edge = ("implements", tgt_term.id)
                    if edge in existing_edges[src_term.id]:
                        continue
                    existing_edges[src_term.id].add(edge)
                    proposals.setdefault(src_term.id, []).append(
                        TermRel(kind=TermRelKind.IMPLEMENTS, target=tgt_term.id)
                    )
                break  # only the canonical class def matters

        if not proposals:
            return {
                "status": "ok",
                "checked": len(terms),
                "edges": 0,
                "terms_touched": 0,
                "opened_pr": False,
            }

        # Build updated term files
        now_iso = datetime.now(UTC).isoformat()
        files: dict[str, str] = {}
        edge_summary: list[str] = []
        for term in terms:
            new_edges = proposals.get(term.id)
            if not new_edges:
                continue
            data = term.model_dump()
            data["related"] = [r.model_dump() for r in (term.related + new_edges)]
            data["updated_at"] = now_iso
            updated_term = Term.model_validate(data)
            slug = _slugify_term_name(updated_term.name)
            rel_path = str(Path("docs/wiki/terms") / f"{slug}.md")
            files[rel_path] = _render_term_file_str(updated_term)
            for rel in new_edges:
                target_term = next((t for t in terms if t.id == rel.target), None)
                target_name = target_term.name if target_term else rel.target
                edge_summary.append(
                    f"- `{term.name}` --[{rel.kind.value}]--> `{target_name}`"
                )

        run_id = secrets.token_hex(4)
        title = (
            f"feat(ul): edge-proposer — {sum(len(v) for v in proposals.values())} "
            f"new edges across {len(proposals)} terms"
        )
        body_lines = [
            "Auto-generated batch from `EdgeProposerLoop` (ADR-0058).",
            "",
            "Edges in this PR:",
            *edge_summary,
            "",
            "Edges are deterministically detected from the live import graph",
            "(`depends_on`) and class-inheritance AST (`implements`). No LLM call.",
            "",
            "Auto-merge on CI green via `DependabotMergeLoop`.",
            "",
            "Generated by `EdgeProposerLoop`",
        ]

        pr_number = await self._pr_port.open_bot_pr(
            branch=f"ul-edges/{run_id}",
            title=title,
            body="\n".join(body_lines),
            labels=[EDGE_PROPOSER_PR_LABEL],
            files=files,
        )

        return {
            "status": "ok",
            "checked": len(terms),
            "edges": sum(len(v) for v in proposals.values()),
            "terms_touched": len(proposals),
            "opened_pr": pr_number is not None,
        }


def _ast_name_simple(node: ast.expr) -> str | None:
    """Extract a simple class-name from an AST base expression.

    Handles ``ClassName`` and ``module.ClassName``; returns None for complex
    expressions (subscripts, calls, etc.).
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
