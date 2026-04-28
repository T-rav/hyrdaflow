"""Sandbox entrypoint — boots HydraFlow with Fake adapters injected.

Used by docker-compose.sandbox.yml and by anyone wanting to run HydraFlow
against simulated GitHub/LLM state. Reads a seed JSON path from argv[1]
or from $HYDRAFLOW_MOCKWORLD_SEED.

Production runs the `hydraflow` console script (server:main) which never
imports this module — Fakes are unreachable from the production code path.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import cast

from dashboard import HydraFlowDashboard
from events import EventBus
from mockworld.fakes import (
    FakeGitHub,
    FakeIssueFetcher,
    FakeIssueStore,
    FakeLLM,
    FakeWorkspace,
)
from mockworld.seed import MockWorldSeed
from orchestrator import HydraFlowOrchestrator
from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort
from runtime_config import load_runtime_config
from service_registry import (
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)


def _load_seed() -> MockWorldSeed:
    """Read the seed file path from argv or env, return the seed."""
    path: str | None = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        path = os.environ.get("HYDRAFLOW_MOCKWORLD_SEED")
    if not path:
        return MockWorldSeed()
    return MockWorldSeed.from_json(Path(path).read_text())


async def main() -> None:
    config = load_runtime_config()
    seed = _load_seed()
    event_bus = EventBus()
    state = build_state_tracker(config)
    stop_event = asyncio.Event()

    # Build the Fake adapter set from the seed.
    # NOTE: Casts here intentionally bypass strict Port conformance — the
    # current FakeIssueStore / FakeIssueFetcher have a narrower surface
    # than the production Ports require (no get_triageable / mark_active /
    # fetch_issues_by_labels yet). PR B widens the Fakes to satisfy the
    # full IssueStorePort / IssueFetcherPort contract; until then the
    # cast lets sandbox_main type-check while signaling the gap. At
    # runtime the FakeLLM / FakeWorkspace / FakeGitHub adapters carry
    # the entire required surface for the loops PR A actually exercises.
    workspaces = cast(WorkspacePort, FakeWorkspace(config.workspace_base))
    fetcher = cast(IssueFetcherPort, FakeIssueFetcher.from_seed(seed))
    store = cast(IssueStorePort, FakeIssueStore.from_seed(seed, event_bus))
    prs = cast(PRPort, FakeGitHub.from_seed(seed))

    # FakeLLM provides triage_runner / planners / agents / reviewers from
    # the seed.scripts payload. Without this, the sandbox would attempt
    # real LLM calls and fail under the air-gapped network.
    fake_llm = FakeLLM()
    for phase, by_issue in seed.scripts.items():
        for issue_number, results in by_issue.items():
            getattr(fake_llm, f"script_{phase}")(issue_number, results)

    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *_a, **_kw: None,
        is_enabled=lambda *_a, **_kw: True,
        get_interval=lambda *_a, **_kw: 60,
    )

    svc = build_services(
        config,
        event_bus,
        state,
        stop_event,
        callbacks,
        prs=prs,
        workspaces=workspaces,
        store=store,
        fetcher=fetcher,
        runners=fake_llm,
    )

    orch = HydraFlowOrchestrator(
        config,
        event_bus=event_bus,
        state=state,
        services=svc,
    )

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=event_bus,
        state=state,
        orchestrator=orch,
    )
    await dashboard.start()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        if orch.running:
            await orch.stop()
        await dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
