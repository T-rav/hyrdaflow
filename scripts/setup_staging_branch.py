#!/usr/bin/env python3
"""One-shot: create the staging branch + apply ADR-0042 branch protection.

Usage::

    HYDRAFLOW_REPO=owner/repo uv run python scripts/setup_staging_branch.py

Same logic the ``/api/admin/setup-staging-branch`` dashboard endpoint runs —
shipped as a script so CI, bootstraps, and reproducible repo setups don't
need the dashboard running.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


async def main() -> int:
    from config import Credentials, HydraFlowConfig  # noqa: PLC0415
    from events import EventBus  # noqa: PLC0415
    from pr_manager import PRManager  # noqa: PLC0415

    repo = os.environ.get("HYDRAFLOW_REPO", "")
    if not repo:
        print("error: HYDRAFLOW_REPO must be set (owner/repo)", file=sys.stderr)
        return 2

    cfg = HydraFlowConfig(
        repo=repo,
        repo_root=Path.cwd(),
        workspace_base=Path.cwd() / ".hydraflow-scratch" / "wt",
        state_file=Path.cwd() / ".hydraflow-scratch" / "state.json",
        data_root=Path.cwd() / ".hydraflow-scratch" / "data",
    )
    credentials = Credentials(gh_token=os.environ.get("GH_TOKEN", ""))
    pm = PRManager(config=cfg, event_bus=EventBus(), credentials=credentials)

    created = await pm.ensure_branch_exists(cfg.staging_branch, base=cfg.main_branch)
    if created:
        print(f"created {cfg.staging_branch} from {cfg.main_branch}")
    else:
        print(f"{cfg.staging_branch} already exists")

    result = await pm.apply_staging_branch_protection(cfg.staging_branch)
    print(f"protection: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
