"""One-shot migration: .hydraflow/repo_wiki/ → repo_wiki/ (tracked).

Transforms the legacy topic-level wiki layout
(``.hydraflow/repo_wiki/{owner}/{repo}/{topic}.md``, with entries serialized
as ``## Title`` sections + embedded ``json:entry`` code blocks) into the
git-backed per-entry layout
(``repo_wiki/{owner}/{repo}/{topic}/{id}-issue-{N}-{slug}.md`` with YAML
frontmatter).

See docs/git-backed-wiki-design.md §Migration for the full design.

Usage:
    python scripts/migrate_wiki_to_git.py \\
        --src .hydraflow/repo_wiki \\
        --dst repo_wiki \\
        --dedup-dst .hydraflow/repo_wiki_dedup

``--cleanup-local`` is intentionally guarded behind a paired
``--i-acknowledge-cleanup-erases-live-dedup`` flag: as long as
``RepoWikiStore`` reads ``ingest_dedup.json`` from the legacy location
(Phase 2), deleting it would cause every already-processed (issue,
source_type) pair to be re-ingested on the next phase run.  Phase 3
refactors the store to read from ``--dedup-dst``; after Phase 3 lands,
cleanup is safe.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_JSON_BLOCK_RE = re.compile(
    r"```json:entry\s*\n(.*?)\n```",
    re.DOTALL,
)
_SOURCE_LINE_RE = re.compile(r"_Source: #(\d+) \(([^)]+)\)_")

_TOPICS = ("architecture", "patterns", "gotchas", "testing", "dependencies")

# source_type (legacy on-disk value) → source_phase (new frontmatter value)
_SOURCE_TYPE_TO_PHASE = {
    "plan": "plan",
    "review": "review",
    "compiled": "synthesis",
    "synthesis": "synthesis",
}


def parse_topic_file(path: Path) -> list[dict[str, Any]]:
    """Return a list of entry dicts parsed from a legacy topic markdown file.

    Primary path: extract ``json:entry`` code blocks (the authoritative
    round-trip data written by RepoWikiStore._write_topic_page).

    Fallback: if no json blocks exist, split by ``##`` section headers and
    hand-parse title/body/source_line.  Used when a topic file was edited
    externally or pre-dates the json round-trip format.
    """
    text = path.read_text()

    json_blocks = _JSON_BLOCK_RE.findall(text)
    if json_blocks:
        entries: list[dict[str, Any]] = []
        for block in json_blocks:
            try:
                entries.append(json.loads(block))
            except json.JSONDecodeError:
                continue
        return entries

    entries = []
    for section in re.split(r"^## ", text, flags=re.MULTILINE)[1:]:
        lines = section.split("\n", 1)
        title = lines[0].strip()
        body = lines[1] if len(lines) > 1 else ""
        if not title or title.lower().startswith("_no entries"):
            continue
        entry: dict[str, Any] = {"title": title, "content": body.strip()}
        src_match = _SOURCE_LINE_RE.search(body)
        if src_match:
            entry["source_issue"] = int(src_match.group(1))
            entry["source_type"] = src_match.group(2)
            entry["content"] = _SOURCE_LINE_RE.sub("", body).strip()
        entries.append(entry)
    return entries


def _slugify(title: str, max_len: int = 50) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:max_len] or "untitled"


def _issue_tag(source_issue: object) -> str:
    if isinstance(source_issue, int):
        return str(source_issue)
    return "unknown"


def write_entry_file(
    *,
    dest_dir: Path,
    entry_id: int,
    entry: dict[str, Any],
    topic: str,
    created_at_fallback: datetime,
) -> Path:
    """Write one per-entry markdown file with YAML frontmatter."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    issue = _issue_tag(entry.get("source_issue"))
    slug = _slugify(str(entry.get("title", "untitled")))
    filename = f"{entry_id:04d}-issue-{issue}-{slug}.md"
    path = dest_dir / filename

    source_type = str(entry.get("source_type") or "")
    source_phase = _SOURCE_TYPE_TO_PHASE.get(source_type, "legacy-migrated")

    created_at = entry.get("created_at") or created_at_fallback.isoformat()
    status = "stale" if entry.get("stale") else "active"

    frontmatter = [
        "---",
        f"id: {entry_id:04d}",
        f"topic: {topic}",
        f"source_issue: {issue}",
        f"source_phase: {source_phase}",
        f"created_at: {created_at}",
        f"status: {status}",
        "---",
        "",
        f"# {entry.get('title', 'Untitled')}",
        "",
        str(entry.get("content", "")),
        "",
    ]
    path.write_text("\n".join(frontmatter))
    return path


def migrate_log(src_log: Path, dst_log_dir: Path) -> list[Path]:
    """Split the legacy combined ``log.jsonl`` into per-issue files.

    The per-entry layout partitions logs by issue number so concurrent
    issue PRs never append to the same file.  Records whose JSON
    payload does not carry a dict ``issue_number`` land in
    ``legacy.jsonl`` — in practice this is every record produced by
    the pre-migration ``RepoWikiStore._append_log`` (it never wrote
    ``issue_number``).  Phase 3 adds the field to new log records so
    post-Phase-3 writes hit per-issue files directly.
    """
    if not src_log.exists():
        return []
    dst_log_dir.mkdir(parents=True, exist_ok=True)
    by_issue: dict[str, list[str]] = {}
    for line in src_log.read_text().splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rec = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        issue = rec.get("issue_number") if isinstance(rec, dict) else None
        key = str(issue) if isinstance(issue, int) else "legacy"
        by_issue.setdefault(key, []).append(stripped)
    written: list[Path] = []
    for issue, lines in by_issue.items():
        out = dst_log_dir / f"{issue}.jsonl"
        out.write_text("\n".join(lines) + "\n")
        written.append(out)
    return written


def _rebuild_index(dst_repo_dir: Path, owner: str, repo: str) -> Path:
    """Regenerate index.md deterministically from the entry files."""
    lines = [f"# Wiki: {owner}/{repo}\n"]
    for topic in _TOPICS:
        topic_dir = dst_repo_dir / topic
        if not topic_dir.is_dir():
            continue
        entry_files = sorted(topic_dir.glob("*.md"))
        if not entry_files:
            continue
        lines.append(f"\n## {topic.title()}\n")
        for entry_file in entry_files:
            lines.append(f"- [{entry_file.stem}]({topic}/{entry_file.name})")
    index_path = dst_repo_dir / "index.md"
    index_path.write_text("\n".join(lines) + "\n")
    return index_path


def migrate_repo(src_repo_dir: Path, dst_repo_dir: Path) -> list[Path]:
    """Migrate one repo's wiki from legacy layout to new layout.

    Returns the list of files written under dst_repo_dir.
    """
    written: list[Path] = []
    fallback_ts = datetime.fromtimestamp(src_repo_dir.stat().st_mtime, tz=UTC)

    written.extend(migrate_log(src_repo_dir / "log.jsonl", dst_repo_dir / "log"))

    for topic in _TOPICS:
        src_file = src_repo_dir / f"{topic}.md"
        if not src_file.exists():
            continue
        entries = parse_topic_file(src_file)
        for idx, entry in enumerate(entries, start=1):
            written.append(
                write_entry_file(
                    dest_dir=dst_repo_dir / topic,
                    entry_id=idx,
                    entry=entry,
                    topic=topic,
                    created_at_fallback=fallback_ts,
                )
            )

    owner = dst_repo_dir.parent.name
    repo = dst_repo_dir.name
    written.append(_rebuild_index(dst_repo_dir, owner, repo))
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--src",
        type=Path,
        default=Path(".hydraflow/repo_wiki"),
        help="Legacy wiki root (default: .hydraflow/repo_wiki)",
    )
    parser.add_argument(
        "--dst",
        type=Path,
        default=Path("repo_wiki"),
        help="Tracked wiki root (default: repo_wiki)",
    )
    parser.add_argument(
        "--dedup-dst",
        type=Path,
        default=Path(".hydraflow/repo_wiki_dedup"),
        help="Destination for relocated ingest_dedup.json files",
    )
    parser.add_argument(
        "--cleanup-local",
        action="store_true",
        help="After migrating, delete --src on this host. UNSAFE in Phase "
        "2: `RepoWikiStore._get_dedup()` still reads ingest_dedup.json "
        "from --src, so cleanup would erase live dedup state and re-"
        "ingest every already-processed (issue, source_type) pair on the "
        "next phase run. Do NOT pass this flag until Phase 3 refactors "
        "the store to read from --dedup-dst.",
    )
    parser.add_argument(
        "--i-acknowledge-cleanup-erases-live-dedup",
        action="store_true",
        help="Required together with --cleanup-local. Explicit opt-in to "
        "erasing live dedup state. See --cleanup-local help.",
    )
    args = parser.parse_args()

    if args.cleanup_local and not args.i_acknowledge_cleanup_erases_live_dedup:
        print(
            "Refusing to --cleanup-local without "
            "--i-acknowledge-cleanup-erases-live-dedup. In Phase 2 the "
            "running RepoWikiStore still reads ingest_dedup.json from "
            f"{args.src}; removing it causes re-ingest of every past "
            "(issue, source_type). Re-read the --cleanup-local help text.",
            file=sys.stderr,
        )
        return 2

    if not args.src.is_dir():
        print(f"Source {args.src} does not exist; nothing to migrate.", file=sys.stderr)
        return 0

    total_files = 0
    for owner_dir in sorted(args.src.iterdir()):
        if not owner_dir.is_dir():
            continue
        for repo_dir in sorted(owner_dir.iterdir()):
            if not repo_dir.is_dir():
                continue
            dst = args.dst / owner_dir.name / repo_dir.name
            written = migrate_repo(repo_dir, dst)
            total_files += len(written)
            print(
                f"Migrated {owner_dir.name}/{repo_dir.name}: "
                f"{len(written)} files → {dst}"
            )

            src_dedup = repo_dir / "ingest_dedup.json"
            if src_dedup.exists():
                dst_dedup = (
                    args.dedup_dst
                    / owner_dir.name
                    / repo_dir.name
                    / "ingest_dedup.json"
                )
                dst_dedup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_dedup, dst_dedup)

    print(f"Migrated {total_files} files total to {args.dst}")

    if args.cleanup_local:
        shutil.rmtree(args.src, ignore_errors=True)
        print(f"Removed {args.src}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
