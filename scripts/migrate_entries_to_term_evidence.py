"""One-shot script: wire wiki-entry references into terms' `evidence` lists.

See docs/superpowers/specs/2026-05-08-entry-term-migrator-design.md.

Run from repo root:
    uv run python scripts/migrate_entries_to_term_evidence.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from execution import get_default_runner  # noqa: E402
from repo_wiki import RepoWikiStore  # noqa: E402
from term_proposer_llm import LLMClient  # noqa: E402
from term_proposer_runtime import ClaudeCLIClient  # noqa: E402
from ubiquitous_language import (  # noqa: E402
    Term,
    TermStore,
)

PROMPT_TEMPLATE = """You are matching a wiki knowledge entry to ubiquitous-language terms in HydraFlow.

The entry below describes architecture, patterns, gotchas, testing, etc. It MAY reference one or more named domain concepts (the UL terms below) — or it may reference none. Return only the terms the entry GENUINELY discusses or relies on, not terms that just happen to share a name fragment.

Existing UL terms:
{term_lines}

Wiki entry:
{entry_body}

Return a strict JSON object — no preamble, no markdown fences:
{{"term_ids": ["<id1>", "<id2>", ...]}}

term_ids MUST be a subset of the ids listed above. When in doubt, exclude.
"""


@dataclass(frozen=True)
class EntryReference:
    """A confirmed (entry_id → term_id) match from the LLM."""

    entry_id: str
    term_id: str


def _build_prompt(entry_text: str, terms: list[Term]) -> str:
    term_lines = "\n".join(
        f"- id={t.id} name={t.name} ({t.kind.value}, {t.bounded_context.value}) — {t.definition[:200]}"
        for t in terms
    )
    return PROMPT_TEMPLATE.format(term_lines=term_lines, entry_body=entry_text.strip())


def _extract_json(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise RuntimeError(f"no JSON object in LLM output: {text[:200]}")
    return json.loads(match.group(0))


async def match_entry(
    *,
    llm: LLMClient,
    entry_id: str,
    entry_text: str,
    terms: list[Term],
    valid_term_ids: set[str],
) -> list[EntryReference]:
    """Return validated (entry → term) matches. Skip on LLM/parse error."""
    prompt = _build_prompt(entry_text, terms)
    try:
        raw = await llm.complete_structured(prompt=prompt, schema={})
    except (RuntimeError, json.JSONDecodeError) as exc:
        logging.warning("LLM call failed for entry %s: %s", entry_id, exc)
        return []
    candidates = raw.get("term_ids") or []
    return [
        EntryReference(entry_id=entry_id, term_id=tid)
        for tid in candidates
        if isinstance(tid, str) and tid in valid_term_ids
    ]


def _walk_topic_files(wiki_root: Path) -> list[Path]:
    out = []
    for p in sorted(wiki_root.glob("*.md")):
        if p.name == "index.md":
            continue
        out.append(p)
    return out


async def run_migration(
    *, repo_root: Path, llm: LLMClient, dry_run: bool
) -> dict[str, int]:
    wiki_root = repo_root / "docs" / "wiki"
    terms_root = wiki_root / "terms"
    store = TermStore(terms_root)
    terms = store.list()
    valid_term_ids = {t.id for t in terms}

    # `_load_topic_entries` is a method on RepoWikiStore (not a module-level
    # function); the body operates only on the topic_path argument, so we
    # construct a throwaway store rooted at wiki_root and call it as a bound
    # method. This is the documented deviation from the plan.
    wiki_store = RepoWikiStore(wiki_root)

    topic_files = _walk_topic_files(wiki_root)
    print(f"loaded {len(terms)} terms; scanning {len(topic_files)} topic files")

    references: list[EntryReference] = []
    entries_seen = 0
    entries_unmatched = 0

    for topic_path in topic_files:
        entries = wiki_store._load_topic_entries(topic_path)  # noqa: SLF001
        for entry in entries:
            entries_seen += 1
            refs = await match_entry(
                llm=llm,
                entry_id=entry.id,
                entry_text=f"# {entry.title}\n\n{entry.content}",
                terms=terms,
                valid_term_ids=valid_term_ids,
            )
            if refs:
                references.extend(refs)
                print(f"  {entry.id} ({entry.title[:60]}) → {len(refs)} terms")
            else:
                entries_unmatched += 1

    # Aggregate per-term
    by_term: dict[str, set[str]] = {}
    for ref in references:
        by_term.setdefault(ref.term_id, set()).add(ref.entry_id)

    # Apply set-difference (idempotence)
    written = 0
    edges_added = 0
    for term in terms:
        new_evidence = by_term.get(term.id, set())
        if not new_evidence:
            continue
        existing = set(term.evidence or [])
        delta = new_evidence - existing
        if not delta:
            continue
        merged = sorted(existing | new_evidence)
        data = term.model_dump()
        data["evidence"] = merged
        updated = Term.model_validate(data)
        if not dry_run:
            store.write(updated)
        written += 1
        edges_added += len(delta)

    return {
        "terms_loaded": len(terms),
        "topic_files": len(topic_files),
        "entries_seen": entries_seen,
        "entries_unmatched": entries_unmatched,
        "references_total": len(references),
        "terms_written": written,
        "edges_added": edges_added,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--model", default="claude-sonnet-4-5")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    runner = get_default_runner()
    llm: LLMClient = ClaudeCLIClient(runner=runner, model=args.model)

    stats = await run_migration(repo_root=REPO_ROOT, llm=llm, dry_run=args.dry_run)
    print("\n=== summary ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
