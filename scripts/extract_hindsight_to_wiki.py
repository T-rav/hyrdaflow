"""One-time pre-cutover extraction: Hindsight banks → wiki.

Reads every memory from the configured Hindsight instance, filters to
the subset with corroboration (≥2 citations OR tied to a closed issue),
runs them through the librarian, and writes the survivors as WikiEntry
objects in the appropriate wiki (per-repo or tribal).

Most memories are expected to drop. This is intentional — Hindsight
accumulated years of unstructured noise; the wiki should only carry
what has evidence behind it.

Run pre-cutover:

    PYTHONPATH=src uv run python scripts/extract_hindsight_to_wiki.py \\
        --dry-run

Then without --dry-run to commit. Safe to re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from repo_wiki import RepoWikiStore
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("extract_hindsight_to_wiki")


def extract_corroborated_memories(memories: list[dict]) -> list[dict]:
    """Filter memories to those with evidence.

    Rules (any-of):
      1. ≥2 citations.
      2. Exactly 1 citation AND ``closed_issue`` truthy.
    """
    survivors: list[dict] = []
    for m in memories:
        cites = m.get("citations") or []
        closed = bool(m.get("closed_issue", False))
        if len(cites) >= 2 or len(cites) == 1 and closed:
            survivors.append(m)
    return survivors


async def write_entries_to_wiki(
    *,
    store: RepoWikiStore,
    compiler: WikiCompiler,
    repo: str,
    memories: list[dict],
) -> int:
    """Route each memory through synthesize_ingest; write what comes back.

    Returns the number of entries written.
    """
    total = 0
    for m in memories:
        entries = await compiler.synthesize_ingest(
            repo=repo,
            issue_number=m.get("issue_number", 0),
            source_type="librarian",
            raw_text=m.get("text", ""),
        )
        if entries:
            store.ingest(repo, entries)
            total += len(entries)
    return total


async def _run(args: argparse.Namespace) -> int:
    """Live-run path. Not yet integrated.

    The pure functions above (``extract_corroborated_memories`` and
    ``write_entries_to_wiki``) are tested and correct. This live driver
    is a placeholder: wiring the live Hindsight API + configured stores
    + compiler is deferred until an operator actually runs the cutover
    extraction. They will need to:

      1. Build a ``HydraFlowConfig`` via ``load_hydraflow_config()`` or
         equivalent.
      2. Construct ``HindsightClient(base_url=config.hindsight_url,
         api_key=credentials.hindsight_api_key)``.
      3. Call ``client.recall_banks(query=..., banks=[Bank.TRIBAL, ...])``
         and map each ``HindsightMemory`` to the dict shape accepted by
         ``extract_corroborated_memories`` (keys: text, citations,
         closed_issue, issue_number).
      4. Build a ``SubprocessRunner`` + ``WikiCompiler(config, runner,
         credentials)``.
      5. Build the target store: ``TribalWikiStore(...)`` for
         ``--repo global`` else ``RepoWikiStore(...)``.
      6. ``await write_entries_to_wiki(store=..., compiler=...,
         repo=effective_repo, memories=survivors)``.

    The shape of each wiring step differs slightly across HydraFlow
    versions; writing it against a specific version is safer than
    committing a stub that silently rots.
    """
    logger.info(
        "extract_hindsight_to_wiki live path is not integrated. "
        "Call extract_corroborated_memories + write_entries_to_wiki "
        "directly from a wired entry point."
    )
    _ = args  # unused
    return 1


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Filter and report counts; do not write.",
    )
    parser.add_argument(
        "--repo",
        default="global",
        help='Target repo slug. "global" → tribal store.',
    )
    args = parser.parse_args(argv)
    return await _run(args)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
