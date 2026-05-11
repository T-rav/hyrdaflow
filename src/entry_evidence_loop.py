"""Entry-Evidence Loop — populates ``Term.evidence`` from wiki-entry matches.

See ADR-0062. Mirrors :class:`EdgeProposerLoop` (ADR-0058) and
:class:`TermProposerLoop` (ADR-0054) in shape: an interval-driven background
loop that opens auto-merge bot PRs with deterministically-bounded changes
to ``docs/wiki/terms/*.md``.

Differs from its siblings in that the work is LLM-driven (one call per
unmatched wiki entry, bounded by ``entry_evidence_max_entries_per_tick``).
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from repo_wiki import RepoWikiStore
from term_proposer_llm import LLMClient
from term_proposer_loop import BotPRPort, _render_term_file_str
from ubiquitous_language import Term, TermStore, _slugify_term_name

if TYPE_CHECKING:
    from config import HydraFlowConfig


logger = logging.getLogger("hydraflow.entry_evidence_loop")

_WORKER_NAME = "entry_evidence"
ENTRY_EVIDENCE_PR_LABEL = "hydraflow-ul-evidence"
"""Label applied to bot-PRs opened by ``EntryEvidenceLoop``.

Public constant — imported by ``review_phase`` to skip routing such PRs through
the agent pipeline (the LLM-driven entry matching IS the work). See ADR-0062.
"""

_PROMPT_TEMPLATE = """You are matching a wiki knowledge entry to ubiquitous-language terms in HydraFlow.

The entry below describes architecture, patterns, gotchas, testing, etc. It MAY reference one or more named domain concepts (the UL terms below) — or it may reference none. Return only the terms the entry GENUINELY discusses or relies on, not terms that just happen to share a name fragment.

Existing UL terms:
{term_lines}

Wiki entry:
{entry_body}

Return a strict JSON object — no preamble, no markdown fences:
{{"term_ids": ["<id1>", "<id2>", ...]}}

term_ids MUST be a subset of the ids listed above. When in doubt, exclude.
"""


def _build_prompt(entry_text: str, terms: list[Term]) -> str:
    term_lines = "\n".join(
        f"- id={t.id} name={t.name} ({t.kind.value}, {t.bounded_context.value})"
        f" — {t.definition[:200]}"
        for t in terms
    )
    return _PROMPT_TEMPLATE.format(term_lines=term_lines, entry_body=entry_text.strip())


class EntryEvidenceLoop(BaseBackgroundLoop):
    """Links wiki entries to terms via ``Term.evidence`` (ADR-0062)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        deps: LoopDeps,
        llm: LLMClient,
        pr_port: BotPRPort,
        repo_root: Path,
    ) -> None:
        super().__init__(worker_name=_WORKER_NAME, config=config, deps=deps)
        self._llm = llm
        self._pr_port = pr_port
        self._repo_root = repo_root

    def _get_default_interval(self) -> int:
        return self._config.entry_evidence_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.entry_evidence_enabled:
            return {"status": "disabled"}

        wiki_root = self._repo_root / "docs" / "wiki"
        terms_root = wiki_root / "terms"
        store = TermStore(terms_root)
        terms = store.list()
        if not terms:
            return {
                "status": "ok",
                "checked": 0,
                "matched_entries": 0,
                "terms_touched": 0,
                "opened_pr": False,
            }

        valid_term_ids = {t.id for t in terms}
        # "Already linked" = entry id appears in any term's evidence list.
        already_linked: set[str] = set()
        for term in terms:
            already_linked.update(term.evidence or [])

        wiki_store = RepoWikiStore(wiki_root)
        topic_files: list[Path] = []
        for path in sorted(wiki_root.glob("*.md")):
            if path.name == "index.md":
                continue
            topic_files.append(path)

        # Aggregate (term_id → set of entry_ids) for new matches this tick.
        new_links: dict[str, set[str]] = {}
        max_per_tick = self._config.entry_evidence_max_entries_per_tick
        budget = max_per_tick
        entries_checked = 0

        for topic_path in topic_files:
            if budget <= 0:
                break
            entries = wiki_store._load_topic_entries(topic_path)  # noqa: SLF001
            for entry in entries:
                if budget <= 0:
                    break
                if entry.id in already_linked:
                    # Resumable: skip entries some term already references.
                    continue
                entries_checked += 1
                budget -= 1
                refs = await self._match_entry(
                    entry_id=entry.id,
                    entry_text=f"# {entry.title}\n\n{entry.content}",
                    terms=terms,
                    valid_term_ids=valid_term_ids,
                )
                for term_id in refs:
                    new_links.setdefault(term_id, set()).add(entry.id)

        if not new_links:
            return {
                "status": "ok",
                "checked": entries_checked,
                "matched_entries": 0,
                "terms_touched": 0,
                "opened_pr": False,
            }

        # Render updated term files with set-difference idempotence.
        now_iso = datetime.now(UTC).isoformat()
        files: dict[str, str] = {}
        link_summary: list[str] = []
        terms_touched = 0
        matched_entries = 0
        for term in terms:
            additions = new_links.get(term.id)
            if not additions:
                continue
            existing = set(term.evidence or [])
            delta = additions - existing
            if not delta:
                continue
            merged = sorted(existing | additions)
            data = term.model_dump()
            data["evidence"] = merged
            data["updated_at"] = now_iso
            updated = Term.model_validate(data)
            slug = _slugify_term_name(updated.name)
            rel_path = str(Path("docs/wiki/terms") / f"{slug}.md")
            files[rel_path] = _render_term_file_str(updated)
            terms_touched += 1
            matched_entries += len(delta)
            for eid in sorted(delta):
                link_summary.append(f"- `{term.name}` ← entry `{eid}`")

        if not files:
            return {
                "status": "ok",
                "checked": entries_checked,
                "matched_entries": 0,
                "terms_touched": 0,
                "opened_pr": False,
            }

        run_id = secrets.token_hex(4)
        title = (
            f"feat(ul): entry-evidence — {matched_entries} new entry links"
            f" across {terms_touched} terms"
        )
        body_lines = [
            "Auto-generated batch from `EntryEvidenceLoop` (ADR-0062).",
            "",
            "Entry → term backlinks added:",
            *link_summary,
            "",
            "Matches are LLM-validated (one call per uncached entry) against the",
            "live `TermStore`. Idempotent: re-runs skip entries already linked.",
            "",
            "Auto-merge on CI green via `DependabotMergeLoop`.",
            "",
            "Generated by `EntryEvidenceLoop`",
        ]

        pr_number = await self._pr_port.open_bot_pr(
            branch=f"ul-evidence/{run_id}",
            title=title,
            body="\n".join(body_lines),
            labels=[ENTRY_EVIDENCE_PR_LABEL],
            files=files,
        )

        return {
            "status": "ok",
            "checked": entries_checked,
            "matched_entries": matched_entries,
            "terms_touched": terms_touched,
            "opened_pr": pr_number is not None,
        }

    async def _match_entry(
        self,
        *,
        entry_id: str,
        entry_text: str,
        terms: list[Term],
        valid_term_ids: set[str],
    ) -> list[str]:
        """Return validated term IDs the LLM says the entry discusses.

        Soft-failure on LLM/parse error: log and return [] so the next tick
        retries this entry (no DedupStore needed — the set-difference write
        path is the dedup mechanism).
        """
        prompt = _build_prompt(entry_text, terms)
        try:
            raw = await self._llm.complete_structured(prompt=prompt, schema={})
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("LLM call failed for entry %s: %s", entry_id, exc)
            return []
        candidates = raw.get("term_ids") or []
        return [
            tid for tid in candidates if isinstance(tid, str) and tid in valid_term_ids
        ]
