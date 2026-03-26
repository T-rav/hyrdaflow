#!/usr/bin/env python3
"""Migrate existing JSON state files into embedded Dolt.

Usage:
    PYTHONPATH=src uv run python scripts/migrate-state-to-dolt.py [--state-dir PATH] [--dry-run]

Migrates:
  - state.json → Dolt `state` table
  - sessions.jsonl → Dolt `sessions` table
  - proposed_categories.json → Dolt `dedup_sets` (set_name='proposed_categories')
  - filed_patterns.json → Dolt `dedup_sets` (set_name='filed_patterns')
  - adr_sources.json → Dolt `dedup_sets` (set_name='adr_sources')

After migration, the original files are renamed with a `.migrated` suffix
(not deleted) so you can verify before removing them.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def migrate_state_json(dolt, state_file: Path, *, dry_run: bool) -> bool:
    """Migrate state.json into Dolt state table."""
    if not state_file.is_file():
        print(f"  No state file at {state_file}")
        return False

    data = state_file.read_text()
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        print("  Invalid state file (not a JSON object)")
        return False

    if dry_run:
        print(f"  [DRY] Would migrate state.json ({len(data)} bytes)")
        return True

    dolt.save_state(data)
    dolt.commit("Migrate state.json")
    state_file.rename(state_file.with_suffix(".json.migrated"))
    print(f"  Migrated state.json ({len(data)} bytes) → renamed to state.json.migrated")
    return True


def migrate_sessions(dolt, sessions_file: Path, *, dry_run: bool) -> int:
    """Migrate sessions.jsonl into Dolt sessions table."""
    if not sessions_file.is_file():
        print(f"  No sessions file at {sessions_file}")
        return 0

    # Read all sessions, dedup by session_id (last write wins)
    sessions: dict[str, dict] = {}
    for raw_line in sessions_file.read_text().splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            sid = record.get("id", "")
            if sid:
                sessions[sid] = record
        except json.JSONDecodeError:
            continue

    if dry_run:
        print(f"  [DRY] Would migrate {len(sessions)} sessions")
        return len(sessions)

    for sid, record in sessions.items():
        repo = record.get("repo", "")
        status = record.get("status", "active")
        dolt.save_session(sid, repo, json.dumps(record), status)

    if sessions:
        dolt.commit(f"Migrate {len(sessions)} sessions")
    sessions_file.rename(sessions_file.with_suffix(".jsonl.migrated"))
    print(f"  Migrated {len(sessions)} sessions → renamed to sessions.jsonl.migrated")
    return len(sessions)


def migrate_dedup_json(dolt, json_file: Path, set_name: str, *, dry_run: bool) -> int:
    """Migrate a JSON array file into a Dolt dedup_sets row."""
    if not json_file.is_file():
        print(f"  No {json_file.name}")
        return 0

    try:
        values = json.loads(json_file.read_text())
    except json.JSONDecodeError:
        print(f"  Invalid JSON in {json_file.name}")
        return 0

    if not isinstance(values, list):
        print(f"  {json_file.name} is not a JSON array")
        return 0

    str_values = {str(v) for v in values}

    if dry_run:
        print(
            f"  [DRY] Would migrate {len(str_values)} items from {json_file.name} → {set_name}"
        )
        return len(str_values)

    dolt.set_dedup_set(set_name, str_values)
    dolt.commit(f"Migrate {json_file.name} ({len(str_values)} items)")
    json_file.rename(json_file.with_suffix(".json.migrated"))
    print(
        f"  Migrated {len(str_values)} items from {json_file.name} → renamed to .migrated"
    )
    return len(str_values)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Migrate JSON state files to embedded Dolt"
    )
    parser.add_argument(
        "--state-dir",
        default=str(Path.home() / "Documents/projects/hydraflow/.hydraflow"),
        help="Path to the .hydraflow directory",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without migrating"
    )
    args = parser.parse_args()

    state_dir = Path(args.state_dir)
    if not state_dir.is_dir():
        print(f"State directory not found: {state_dir}")
        sys.exit(1)

    memory_dir = state_dir / "memory"

    dolt = None
    if args.dry_run:
        print(f"[DRY RUN] Would migrate from {state_dir}")
    else:
        from dolt_backend import DoltBackend

        dolt_dir = state_dir / "dolt"
        dolt = DoltBackend(dolt_dir)
        print(f"Dolt repo at {dolt_dir}")

    totals: dict[str, int] = {}

    # 1. state.json
    print("\n=== state.json ===")
    state_file = state_dir / "state.json"
    if args.dry_run:
        if state_file.is_file():
            print(
                f"  [DRY] Would migrate state.json ({state_file.stat().st_size} bytes)"
            )
            totals["state"] = 1
        else:
            totals["state"] = 0
    else:
        totals["state"] = (
            1 if migrate_state_json(dolt, state_file, dry_run=False) else 0
        )

    # 2. sessions.jsonl
    print("\n=== sessions.jsonl ===")
    sessions_file = state_dir / "sessions.jsonl"
    if args.dry_run:
        if sessions_file.is_file():
            count = sum(
                1 for ln in sessions_file.read_text().splitlines() if ln.strip()
            )
            print(f"  [DRY] Would migrate ~{count} session records")
            totals["sessions"] = count
        else:
            totals["sessions"] = 0
    else:
        totals["sessions"] = migrate_sessions(dolt, sessions_file, dry_run=False)

    # 3. Dedup JSON files
    dedup_files = [
        (memory_dir / "proposed_categories.json", "proposed_categories"),
        (memory_dir / "filed_patterns.json", "filed_patterns"),
        (memory_dir / "adr_sources.json", "adr_sources"),
    ]
    for json_path, set_name in dedup_files:
        print(f"\n=== {json_path.name} ===")
        if args.dry_run:
            if json_path.is_file():
                try:
                    vals = json.loads(json_path.read_text())
                    print(f"  [DRY] Would migrate {len(vals)} items → {set_name}")
                    totals[set_name] = len(vals)
                except json.JSONDecodeError:
                    totals[set_name] = 0
            else:
                totals[set_name] = 0
        else:
            totals[set_name] = migrate_dedup_json(
                dolt, json_path, set_name, dry_run=False
            )

    # Summary
    print("\n=== Summary ===")
    prefix = "[DRY] " if args.dry_run else ""
    for name, count in totals.items():
        print(f"  {prefix}{name}: {count}")

    if not args.dry_run:
        print("\nOriginal files renamed to *.migrated — verify and delete when ready.")
        print("To enable Dolt permanently, set: HYDRAFLOW_DOLT_ENABLED=true")


if __name__ == "__main__":
    main()
