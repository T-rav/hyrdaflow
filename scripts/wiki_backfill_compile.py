"""One-shot WikiCompiler backfill — recompile every topic with the new
doc-voice prompt without waiting for RepoWikiLoop to tick.

The wiki content shipped before the prompt update in PR #8465/#8471 is
still wall-of-prose retrospective voice. RepoWikiLoop runs at most once
an hour and only re-compiles when the entry count crosses a threshold,
so the legacy entries would linger indefinitely. This script forces a
recompile per topic immediately.

Usage:
    python scripts/wiki_backfill_compile.py --topic dependencies      # one
    python scripts/wiki_backfill_compile.py --all                     # all 12
    python scripts/wiki_backfill_compile.py --topic gotchas --dry-run # preview

Each topic recompile is one LLM call to the configured model
(``wiki_compilation_model``, default ``haiku``).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from config import Credentials, HydraFlowConfig  # noqa: E402
from execution import HostRunner  # noqa: E402
from repo_wiki import RepoWikiStore  # noqa: E402
from wiki_compiler import WikiCompiler  # noqa: E402

logger = logging.getLogger("wiki_backfill")
logging.basicConfig(level=logging.INFO, format="%(message)s")

REPO_SLUG = "T-rav/hydraflow"
WIKI_ROOT = Path("docs/wiki")


def _topic_files() -> list[Path]:
    if not WIKI_ROOT.exists():
        return []
    return sorted(p for p in WIKI_ROOT.glob("*.md") if p.stem != "index")


async def _compile_one(
    compiler: WikiCompiler,
    store: RepoWikiStore,
    topic_path: Path,
    *,
    dry_run: bool,
) -> tuple[int, int]:
    topic = topic_path.stem
    before_entries = store._load_topic_entries(topic_path)
    before_count = len(before_entries)
    if before_count < 2:
        logger.info("%s: %d entries — skip (compiler requires ≥2)", topic, before_count)
        return before_count, before_count

    if dry_run:
        logger.info("%s: %d entries — DRY RUN (would call LLM)", topic, before_count)
        return before_count, before_count

    backup = topic_path.with_suffix(".md.bak")
    shutil.copyfile(topic_path, backup)

    try:
        after_count = await compiler.compile_topic(store, REPO_SLUG, topic)
        delta = after_count - before_count
        logger.info(
            "%s: %d → %d entries (Δ%+d) — backup at %s",
            topic,
            before_count,
            after_count,
            delta,
            backup.name,
        )
        return before_count, after_count
    except Exception:  # noqa: BLE001
        logger.exception("%s: compile failed — restoring backup", topic)
        shutil.move(backup, topic_path)
        return before_count, before_count


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", help="single topic stem (e.g. dependencies)")
    parser.add_argument("--all", action="store_true", help="recompile every topic")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would change without LLM calls",
    )
    args = parser.parse_args()

    if not (args.topic or args.all):
        parser.error("must pass --topic <name> or --all")

    if not WIKI_ROOT.exists():
        logger.error("docs/wiki/ not found — run from repo root")
        return 1

    config = HydraFlowConfig(repo=REPO_SLUG)
    credentials = Credentials()
    runner = HostRunner()
    store_root = WIKI_ROOT.parent
    store = RepoWikiStore(store_root)
    store._repo_dir = lambda _slug: WIKI_ROOT  # type: ignore[method-assign]
    compiler = WikiCompiler(config, runner, credentials=credentials)

    topics: list[Path]
    if args.all:
        topics = _topic_files()
    else:
        candidate = WIKI_ROOT / f"{args.topic}.md"
        if not candidate.exists():
            logger.error("topic %r not found at %s", args.topic, candidate)
            return 1
        topics = [candidate]

    total_in = total_out = 0
    for topic_path in topics:
        before, after = await _compile_one(
            compiler, store, topic_path, dry_run=args.dry_run
        )
        total_in += before
        total_out += after

    logger.info(
        "%s — %d topics processed, %d → %d entries (Δ%+d)",
        "DRY RUN COMPLETE" if args.dry_run else "BACKFILL COMPLETE",
        len(topics),
        total_in,
        total_out,
        total_out - total_in,
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
