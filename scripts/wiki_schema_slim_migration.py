# One-shot migration to the slim wiki schema (PR #8462+).
#
# Loads every wiki entry under docs/wiki/*.md via RepoWikiStore, then
# rewrites each topic file using the new write path. The new path drops
# the duplicated `content` field (and `valid_from`, which always equals
# `created_at`) from inline json:entry blocks. The reader reconstructs
# `content` from the prose section above each block.
#
# Idempotent: re-running on already-migrated files is a no-op.
# Verifies a round-trip read after each rewrite to guarantee no entry is
# lost in translation.

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from repo_wiki import RepoWikiStore  # noqa: E402

logger = logging.getLogger("wiki_schema_slim")
logging.basicConfig(level=logging.INFO, format="%(message)s")

REPO_SLUG = "T-rav/hydraflow"
WIKI_ROOT = Path("docs/wiki")


def migrate() -> int:
    if not WIKI_ROOT.exists():
        logger.error("docs/wiki/ not found — run from repo root")
        return 1

    store = RepoWikiStore(WIKI_ROOT.parent)
    repo_dir = store._repo_dir(REPO_SLUG)
    if not repo_dir.exists():
        repo_dir = WIKI_ROOT
        store._repo_dir = lambda _slug: WIKI_ROOT  # type: ignore[method-assign]

    total_in = 0
    total_out = 0
    files_rewritten = 0

    md_files = sorted(repo_dir.glob("*.md"))
    for md_file in md_files:
        if md_file.stem == "index":
            continue
        before = md_file.read_text()
        entries = store._load_topic_entries(md_file)
        if not entries:
            continue

        store._write_topic_page(md_file, md_file.stem, entries)
        after = md_file.read_text()

        roundtrip = store._load_topic_entries(md_file)
        if len(roundtrip) != len(entries):
            logger.error(
                "MIGRATION FAILED for %s: %d in → %d out (round-trip lost entries)",
                md_file.name,
                len(entries),
                len(roundtrip),
            )
            return 1
        # Content-equality check: count parity is necessary but not
        # sufficient. _strip_prose_chrome calls .strip(), so trailing
        # whitespace silently disappears; without this check the migration
        # would report success while mutating content.
        for original, reloaded in zip(entries, roundtrip, strict=True):
            if original.content.strip() != reloaded.content.strip():
                logger.error(
                    "MIGRATION FAILED for %s: content mismatch on entry %r",
                    md_file.name,
                    original.title,
                )
                return 1

        if before != after:
            files_rewritten += 1
            saved = len(before) - len(after)
            logger.info(
                "%s: %d entries, %d bytes saved (%.0f%%)",
                md_file.name,
                len(entries),
                saved,
                100 * saved / len(before) if before else 0,
            )
        total_in += len(entries)
        total_out += len(roundtrip)

    logger.info(
        "Migration complete: %d files rewritten, %d entries preserved (in=%d out=%d)",
        files_rewritten,
        total_out,
        total_in,
        total_out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(migrate())
