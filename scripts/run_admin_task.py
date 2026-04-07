"""Run HydraFlow admin tasks directly without a running server.

Usage:
    python scripts/run_admin_task.py <task>

Tasks:
    clean           Remove all worktrees and reset state
    compact         Run manual memory compaction (evict stale items)
    prep            Sync labels, run repo audit, seed context assets
    prune-memory    Run the tribal-memory judge over items.jsonl, archive failures
    scaffold        Generate baseline tests and CI configuration
    ensure-labels   Sync HydraFlow lifecycle labels only
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from admin_tasks import (  # noqa: E402
    run_clean,
    run_compact,
    run_ensure_labels,
    run_prep,
    run_prune_memory,
    run_scaffold,
)
from config import HydraFlowConfig  # noqa: E402

_TASKS = {
    "clean": run_clean,
    "compact": run_compact,
    "prep": run_prep,
    "prune-memory": run_prune_memory,
    "scaffold": run_scaffold,
    "ensure-labels": run_ensure_labels,
}


async def main() -> None:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    if len(sys.argv) < 2 or sys.argv[1] not in _TASKS:
        valid = ", ".join(_TASKS)
        print(f"Usage: {sys.argv[0]} <task>\nValid tasks: {valid}", file=sys.stderr)
        sys.exit(2)

    task_name = sys.argv[1]
    config = HydraFlowConfig()
    result = await _TASKS[task_name](config)
    for line in result.log:
        print(line)
    for warning in result.warnings:
        print(f"WARNING: {warning}", file=sys.stderr)
    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
