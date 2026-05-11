"""One-shot trigger for TermProposerLoop._do_work() against the live repo.

Constructs the loop with production adapters (ClaudeCLIClient + OpenAutoPRBotPRPort)
and invokes a single tick. Useful for:
- Demoing the system end-to-end without waiting for the 4h interval
- Debugging the loop's behavior with a real LLM + real PR
- Recording cassettes for the integration smoke test placeholder

Run from repo root:
    uv run python scripts/run_term_proposer_once.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from base_background_loop import LoopDeps  # noqa: E402
from config import HydraFlowConfig, build_credentials  # noqa: E402
from events import EventBus  # noqa: E402
from execution import get_default_runner  # noqa: E402
from term_proposer_llm import TermProposerLLM  # noqa: E402
from term_proposer_loop import BotPRPort, TermProposerLoop  # noqa: E402
from term_proposer_runtime import ClaudeCLIClient, OpenAutoPRBotPRPort  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If set, swap the BotPRPort for a logging stub (no real PR opened).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    config = HydraFlowConfig()
    credentials = build_credentials(config)
    runner = get_default_runner()

    llm = TermProposerLLM(client=ClaudeCLIClient(runner=runner))

    pr_port: BotPRPort
    if args.dry_run:

        class _LoggingPort:
            async def open_bot_pr(self, *, branch, title, body, labels, files):
                print("\n[DRY-RUN] would open PR:")
                print(f"  branch: {branch}")
                print(f"  title:  {title}")
                print(f"  labels: {labels}")
                print(f"  files:  {list(files.keys())}")
                print(f"  body excerpt:\n{body[:400]}")
                return 999_999

        pr_port = _LoggingPort()
    else:
        pr_port = OpenAutoPRBotPRPort(
            repo_root=config.repo_root,
            gh_token=credentials.gh_token,
        )

    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *_, **__: None,
        enabled_cb=lambda _: True,
    )
    loop = TermProposerLoop(
        config=config,
        deps=deps,
        llm=llm,
        pr_port=pr_port,
        repo_root=config.repo_root,
        dedup_path=config.data_root / "dedup" / "term_proposer_oneshot.json",
    )

    print(f"running TermProposerLoop._do_work() against {config.repo_root}")
    print(f"  max_per_tick={config.term_proposer_max_per_tick}")
    print(f"  dry_run={args.dry_run}\n")

    result = await loop._do_work()
    print(f"\nresult: {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
