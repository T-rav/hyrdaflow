#!/usr/bin/env python3
"""Migrate existing file-based memory data into Hindsight.

Usage:
    PYTHONPATH=src uv run python scripts/migrate-memory-to-hindsight.py [--memory-dir PATH] [--url URL] [--dry-run]

Migrates:
  - Learning items (items/*.md) → Bank.TRIBAL
  - Retrospectives (retrospectives.jsonl) → Bank.RETROSPECTIVES
  - Review insights (reviews.jsonl) → Bank.REVIEW_INSIGHTS
  - Harness failures (harness_failures.jsonl) → Bank.HARNESS_INSIGHTS
  - Troubleshooting patterns (troubleshooting_patterns.jsonl) → Bank.TROUBLESHOOTING
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from hindsight import Bank, HindsightClient


async def migrate_learnings(
    client: HindsightClient, items_dir: Path, *, dry_run: bool
) -> int:
    """Migrate individual learning .md files."""
    if not items_dir.is_dir():
        print(f"  No items directory at {items_dir}")
        return 0

    files = sorted(items_dir.glob("*.md"))
    count = 0
    for f in files:
        issue_num = f.stem
        content = f.read_text().strip()
        if not content:
            continue
        context = f"Learning from issue #{issue_num}"
        if dry_run:
            print(f"  [DRY] Would retain learning #{issue_num} ({len(content)} chars)")
        else:
            await client.retain(
                Bank.TRIBAL,
                content,
                context=context,
                metadata={"issue_number": issue_num, "source": "migration"},
            )
            print(f"  Retained learning #{issue_num} ({len(content)} chars)")
        count += 1
    return count


async def migrate_jsonl(
    client: HindsightClient,
    path: Path,
    bank: Bank,
    *,
    content_fn,
    context_fn,
    metadata_fn=None,
    dry_run: bool,
) -> int:
    """Migrate a JSONL file into a Hindsight bank."""
    if not path.is_file():
        print(f"  No file at {path}")
        return 0

    count = 0
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        content = content_fn(record)
        if not content:
            continue
        context = context_fn(record)
        metadata = metadata_fn(record) if metadata_fn else {"source": "migration"}

        if dry_run:
            print(f"  [DRY] Would retain to {bank}: {content[:60]}...")
        else:
            await client.retain(bank, content, context=context, metadata=metadata)
        count += 1

        # Rate limit: Hindsight does LLM extraction per retain
        if not dry_run and count % 10 == 0:
            await asyncio.sleep(1)

    return count


def retro_content(r: dict) -> str:
    parts = [f"Issue #{r.get('issue_number')} PR #{r.get('pr_number')}"]
    parts.append(f"plan_accuracy={r.get('plan_accuracy_pct', 0):.0f}%")
    if r.get("quality_fix_rounds"):
        parts.append(f"quality_fixes={r['quality_fix_rounds']}")
    if r.get("review_verdict"):
        parts.append(f"review={r['review_verdict']}")
    if r.get("reviewer_fixes_made"):
        parts.append("reviewer_fixes=yes")
    if r.get("ci_fix_rounds"):
        parts.append(f"ci_fixes={r['ci_fix_rounds']}")
    if r.get("unplanned_files"):
        parts.append(f"unplanned_files={len(r['unplanned_files'])}")
    if r.get("missed_files"):
        parts.append(f"missed_files={len(r['missed_files'])}")
    return ", ".join(parts)


def retro_context(r: dict) -> str:
    return f"retrospective for issue #{r.get('issue_number')} at {r.get('timestamp', '')[:10]}"


def review_content(r: dict) -> str:
    return r.get("summary", "")


def review_context(r: dict) -> str:
    return f"PR #{r.get('pr_number')} issue #{r.get('issue_number')} verdict={r.get('verdict', '')}"


def review_metadata(r: dict) -> dict:
    return {
        "pr_number": str(r.get("pr_number", "")),
        "issue_number": str(r.get("issue_number", "")),
        "verdict": str(r.get("verdict", "")),
        "source": "migration",
    }


def harness_content(r: dict) -> str:
    return r.get("details", "")


def harness_context(r: dict) -> str:
    return f"issue #{r.get('issue_number')} category={r.get('category', '')} stage={r.get('stage', '')}"


def harness_metadata(r: dict) -> dict:
    return {
        "issue_number": str(r.get("issue_number", "")),
        "category": str(r.get("category", "")),
        "stage": str(r.get("stage", "")),
        "source": "migration",
    }


def troubleshoot_content(r: dict) -> str:
    name = r.get("pattern_name", "")
    desc = r.get("description", "")
    fix = r.get("fix_strategy", "")
    return f"{name}: {desc}\nFix: {fix}"


def troubleshoot_context(r: dict) -> str:
    return f"language={r.get('language', '')} frequency={r.get('frequency', 1)}"


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Migrate file-based memory to Hindsight"
    )
    parser.add_argument(
        "--memory-dir",
        default=str(Path.home() / "Documents/projects/hydraflow/.hydraflow/memory"),
        help="Path to the .hydraflow/memory directory",
    )
    parser.add_argument(
        "--url", default="http://localhost:8888", help="Hindsight API URL"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be migrated without doing it",
    )
    args = parser.parse_args()

    memory_dir = Path(args.memory_dir)
    if not memory_dir.is_dir():
        print(f"Memory directory not found: {memory_dir}")
        sys.exit(1)

    client = HindsightClient(args.url, timeout=60)

    if not args.dry_run:
        healthy = await client.health_check()
        if not healthy:
            print(f"Hindsight not reachable at {args.url}")
            sys.exit(1)
        print(f"Connected to Hindsight at {args.url}")
    else:
        print(f"[DRY RUN] Would migrate from {memory_dir} to {args.url}")

    totals: dict[str, int] = {}

    # 1. Learnings
    print("\n=== Learnings ===")
    totals["learnings"] = await migrate_learnings(
        client, memory_dir / "items", dry_run=args.dry_run
    )

    # 2. Retrospectives
    print("\n=== Retrospectives ===")
    totals["retrospectives"] = await migrate_jsonl(
        client,
        memory_dir / "retrospectives.jsonl",
        Bank.RETROSPECTIVES,
        content_fn=retro_content,
        context_fn=retro_context,
        dry_run=args.dry_run,
    )

    # 3. Review insights
    print("\n=== Review Insights ===")
    totals["reviews"] = await migrate_jsonl(
        client,
        memory_dir / "reviews.jsonl",
        Bank.REVIEW_INSIGHTS,
        content_fn=review_content,
        context_fn=review_context,
        metadata_fn=review_metadata,
        dry_run=args.dry_run,
    )

    # 4. Harness failures
    print("\n=== Harness Failures ===")
    totals["harness"] = await migrate_jsonl(
        client,
        memory_dir / "harness_failures.jsonl",
        Bank.HARNESS_INSIGHTS,
        content_fn=harness_content,
        context_fn=harness_context,
        metadata_fn=harness_metadata,
        dry_run=args.dry_run,
    )

    # 5. Troubleshooting patterns
    print("\n=== Troubleshooting Patterns ===")
    totals["troubleshooting"] = await migrate_jsonl(
        client,
        memory_dir / "troubleshooting_patterns.jsonl",
        Bank.TROUBLESHOOTING,
        content_fn=troubleshoot_content,
        context_fn=troubleshoot_context,
        dry_run=args.dry_run,
    )

    await client.close()

    print("\n=== Summary ===")
    for name, count in totals.items():
        prefix = "[DRY] " if args.dry_run else ""
        print(f"  {prefix}{name}: {count} items")
    total = sum(totals.values())
    print(f"  {'[DRY] ' if args.dry_run else ''}Total: {total} items migrated")


if __name__ == "__main__":
    asyncio.run(main())
