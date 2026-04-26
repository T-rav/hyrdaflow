# Sandbox-tier scenario testing — design spec

- **Status:** Draft
- **Date:** 2026-04-26
- **Branch:** `sandbox-tier-spec`
- **Related ADRs:** [ADR-0044](../../adr/0044-hydraflow-principles.md) (TDD as default), [ADR-0049](../../adr/0049-trust-loop-kill-switch-convention.md), [ADR-0050](../../adr/0050-auto-agent-hitl-preflight.md), [ADR-0051](../../adr/0051-iterative-production-readiness-review.md)
- **Related wiki:** [`docs/wiki/dark-factory.md`](../../wiki/dark-factory.md)
- **Slated ADR:** ADR-0052 — "Sandbox-tier scenario testing" (lands with PR B)

## Motivation

The dark-factory infrastructure-hardening track (#8445/#8446/#8448) closed the structural-enforcement gap at the unit and per-loop level: kill-switch convention is universal, subprocess runners share `BaseSubprocessRunner`, Port↔Fake conformance fails on signature drift, scaffolding generates correct loops by default. **What it did not close** is the end-to-end gap: there is no test that boots HydraFlow as a deployed system, drives the UI a human would actually click, and verifies that "issue arrives → label state machine progresses → PR merges → outcome surfaces in the dashboard" still works.

Today this gap is closed by the human in the loop. The user opens the dashboard, watches a small queue process, and notices when something stalls. Removing the human means moving that verification into automation. This spec designs that automation as a sandbox-tier scenario suite: about a dozen scenarios that boot the real HydraFlow stack inside Docker, swap MockWorld at the Port boundary, drive the UI via Playwright, and assert end-to-end behavior with no external dependencies.

The goal is not to replace the existing in-process scenarios — those remain the fast, every-PR safety net. The goal is a slower, higher-fidelity tier that catches the bugs the in-process tier cannot see: container-only wiring, network-policy violations, UI/backend protocol drift, subprocess streaming under real Docker, dashboard rendering of real loop activity. This is the last operational dependency on human verification, and removing it is the last 5% of the dark factory.

## Architecture

Two test tiers backed by **the same MockWorld substrate**:

```
┌───────────────────────────────────────────────────────────────────┐
│ Tier 1: in-process scenarios — tests/scenarios/                   │
│   pytest → MockWorld → wires Fakes via _wire_targets               │
│   Fast (~0.1s), runs every PR. ~30 scenarios today.                │
└───────────────────────────────────────────────────────────────────┘
                          │  same Fakes (src/mockworld/fakes/)
                          │  same factories (IssueFactory, etc.)
                          ▼
┌───────────────────────────────────────────────────────────────────┐
│ Tier 2: sandbox scenarios — tests/sandbox_scenarios/              │
│   docker-compose.sandbox.yml stack:                                │
│     • hydraflow → python -m mockworld.sandbox_main /seed/...json   │
│     • ui (nginx serving src/ui/dist + proxying /api, /ws)          │
│     • playwright runner (headless, drives UI on internal network)  │
│   Network: internal: true (DNS for external hosts returns NXDOMAIN)│
│   Slow (~30-60s/scenario), runs nightly + on infra-touching PRs.   │
└───────────────────────────────────────────────────────────────────┘
```

**Why this shape:**

- **One Fake codebase, two tiers.** Tier 1 catches logic regressions in seconds; Tier 2 catches container/wiring/UI regressions in minutes. The maintenance you do anyway (Port↔Fake conformance, scenario factories) keeps both honest.
- **MockWorld via injection, not configuration.** The sandbox tier calls the *real* `build_services()` factory but passes Fake adapters as constructor parameters. There is no config flag to "enable MockWorld" — the choice is made at the call site by *which entrypoint runs*. Production runs `python -m hydraflow` (no overrides → real adapters). Sandbox runs `python -m mockworld.sandbox_main` (overrides → Fakes). No conditional in `build_services()`, no env var to flip.
- **Container = closer-to-production fidelity.** Subprocess streaming, `/workspace` mounts, dashboard binding to `0.0.0.0`, agent CLI invocations, FastAPI startup, vite-built UI assets — all run for real. In-process mocking can never surface a "Dockerfile dropped a binary" or "uvicorn refuses to bind in container" bug.
- **Air-gap is structurally guaranteed,** not honor-system. The compose network is `internal: true`, so even a code path that tries `api.github.com` *cannot reach it* — DNS resolution fails. That is the strongest possible "no external deps" guarantee.

## Core concept: MockWorld is always on

MockWorld is not a mode you enable. It is **always available, always loaded, always usable** — a permanent set of alternative adapters that ship alongside the real ones. This drives every design decision below:

1. **No config switch. None.** There is no `HYDRAFLOW_MOCKWORLD_ENABLED` env var, no boolean field on `HydraFlowConfig`, no conditional branch in `build_services()` that selects "fake or real." The system has too many configurable core parts already; MockWorld will not become another. The choice is made at the **entrypoint level**: production runs `python -m hydraflow`; sandbox runs `python -m mockworld.sandbox_main`. The two entrypoints call the same factory with different adapter arguments.
2. **Fakes ship in `src/`, not `tests/`.** They follow production-code conventions: type-checked by pyright, linted by ruff, scanned by bandit, covered by the same quality gates as adapters. They are not "test fixtures" — they are alternative adapters that happen to be primarily used by tests today.
3. **`build_services()` accepts adapter overrides.** Today the factory constructs `PRManager`, `WorkspaceManager`, `IssueStore`, `IssueFetcher` itself. Tomorrow it accepts each as an optional keyword argument; when omitted, it constructs the real one. Sandbox passes Fakes; production passes nothing. Same factory, different inputs.
4. **Visibility via duck-typing, not config.** The dashboard renders a `MOCKWORLD MODE` banner when it sees a marker attribute on the injected `PRPort` instance (e.g., `getattr(prs, "_is_fake", False)`). The banner doesn't ask "is the flag set?" — it asks "is the adapter we're holding a Fake?" If yes, render the banner. If no, don't.
5. **No accidental MockWorld in production is structurally possible.** There is no flag to flip. The only way to run with Fakes is to launch the sandbox entrypoint. Production launchers can't accidentally select MockWorld because they don't pass overrides. This is stronger than any guard could be.
6. **MockWorld is a peer of "production-with-real-GitHub," not a subordinate.** Demos, training labs, hands-off sandboxes — all valid uses, all reached via the sandbox entrypoint. No code refuses them.

The "cutting off my arm" framing is not hyperbole: removing MockWorld would remove the substrate every test tier depends on. It is core infrastructure that ships with every build, in `src/`, treated identically to production code.

## Components

### Component 1 — Sandbox entrypoint + adapter-injecting `build_services()`

**No config switch.** Instead, two changes:

1. `build_services()` gains optional adapter overrides for each Port. Defaults preserve today's behavior (factory constructs real adapters).
2. A new `python -m mockworld.sandbox_main` entrypoint constructs Fakes and passes them via the overrides.

**Change 1 — `src/service_registry.py::build_services()` accepts overrides:**

```python
@dataclass(frozen=True)
class RunnerSet:
    """Bundle of the four LLM-backed runners. Allows the sandbox entrypoint
    to override all four with FakeLLM-backed variants in a single kwarg.
    """
    triage: TriageRunnerPort
    planners: PlannerRunner
    agents: AgentRunner
    reviewers: ReviewRunner


def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: WorkerRegistryCallbacks,
    active_issues_cb: Callable[[], None] | None = None,
    credentials: Credentials | None = None,
    *,
    # NEW: optional adapter overrides. None → construct the real one.
    prs: PRPort | None = None,
    workspaces: WorkspacePort | None = None,
    store: IssueStorePort | None = None,
    fetcher: IssueFetcherPort | None = None,
    runners: RunnerSet | None = None,
) -> ServiceRegistry:
    if workspaces is None:
        workspaces = WorkspaceManager(config, credentials=credentials)
    if fetcher is None:
        fetcher = IssueFetcher(config, credentials=credentials)
    if store is None:
        store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)
    if prs is None:
        prs = PRManager(config, event_bus, credentials=credentials)
    if runners is None:
        runners = _build_real_runners(config, event_bus, ...)
    # ... rest of construction unchanged ...
```

Production callers (`server.py`, `orchestrator.py`) pass nothing — get real adapters as before. Zero behavior change for the production path.

**Change 2 — `src/mockworld/sandbox_main.py` (new):**

```python
"""Sandbox entrypoint — boots HydraFlow with Fake adapters injected.

Used by docker-compose.sandbox.yml and by anyone wanting to run HydraFlow
against simulated GitHub/LLM state. Reads a seed JSON file path from argv[1]
or from $HYDRAFLOW_MOCKWORLD_SEED.
"""
from __future__ import annotations

import asyncio
import os
import sys

from mockworld.fakes import (
    FakeGitHub, FakeIssueFetcher, FakeIssueStore, FakeWorkspaceManager,
    build_fake_runner_set,
)
from mockworld.seed import MockWorldSeed
from config import load_runtime_config
from events import EventBus
from orchestrator import HydraFlowOrchestrator
from server import run_dashboard
from service_registry import build_services
from state import build_state_tracker


def _load_seed() -> MockWorldSeed:
    path = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("HYDRAFLOW_MOCKWORLD_SEED")
    if not path:
        return MockWorldSeed()  # empty — orchestrator has nothing to do
    with open(path) as f:
        return MockWorldSeed.from_json(f.read())


async def main() -> None:
    config = load_runtime_config()
    seed = _load_seed()
    event_bus = EventBus()
    state = build_state_tracker(config)
    stop_event = asyncio.Event()

    workspaces = FakeWorkspaceManager(config)
    fetcher = FakeIssueFetcher.from_seed(seed)
    store = FakeIssueStore.from_seed(seed, event_bus)
    prs = FakeGitHub.from_seed(seed)
    runners = build_fake_runner_set(seed)

    svc = build_services(
        config, event_bus, state, stop_event,
        callbacks=...,
        prs=prs, workspaces=workspaces, store=store, fetcher=fetcher,
        runners=runners,
    )
    orch = HydraFlowOrchestrator(config, event_bus=event_bus, state=state, _svc=svc)
    await run_dashboard(config, orch, stop_event)


if __name__ == "__main__":
    asyncio.run(main())
```

**Change 3 — Dashboard banner via duck-typing:**

The dashboard `/api/state` endpoint reports `"mockworld_active": True` if it sees the marker attribute on the injected `PRPort` instance:

```python
# in src/dashboard.py or wherever /api/state is built
mockworld_active = getattr(self._svc.prs, "_is_fake_adapter", False)
```

`FakeGitHub` defines `_is_fake_adapter = True` as a class attribute. Real `PRManager` doesn't. The dashboard reads what the orchestrator was actually wired with — no config consulted.

The React shell renders the banner conditionally on `state.mockworld_active`. Persistent, undismissable.

**Why this shape and not a config switch:**
- The number of configurable knobs is already a known maintenance burden. Adding `mockworld_enabled` would join 30+ other env-toggleable booleans, each of which the operator must learn about and reason about.
- Production code paths are byte-for-byte unchanged. The only diff vs. today is `build_services()` accepts kwargs that production never passes.
- "Could MockWorld accidentally run in production?" answer: only if someone runs `python -m mockworld.sandbox_main` in production. That is a deliberate, visible action. There is no flag to fat-finger.

### Component 2 — Fake relocation: `src/mockworld/fakes/`

Today: 12 Fake classes (~1,851 LOC) live under `tests/scenarios/fakes/`. Sandbox tier requires them to be importable from `src/service_registry.py` (which runs in the production container under MockWorld mode).

**Move plan:**

| Today | Tomorrow |
|-------|----------|
| `tests/scenarios/fakes/fake_github.py` | `src/mockworld/fakes/fake_github.py` |
| `tests/scenarios/fakes/fake_workspace.py` | `src/mockworld/fakes/fake_workspace.py` |
| `tests/scenarios/fakes/fake_llm.py` | `src/mockworld/fakes/fake_llm.py` |
| `tests/scenarios/fakes/fake_clock.py` | `src/mockworld/fakes/fake_clock.py` |
| `tests/scenarios/fakes/fake_docker.py` | `src/mockworld/fakes/fake_docker.py` |
| `tests/scenarios/fakes/fake_git.py` | `src/mockworld/fakes/fake_git.py` |
| `tests/scenarios/fakes/fake_fs.py` | `src/mockworld/fakes/fake_fs.py` |
| `tests/scenarios/fakes/fake_http.py` | `src/mockworld/fakes/fake_http.py` |
| `tests/scenarios/fakes/fake_sentry.py` | `src/mockworld/fakes/fake_sentry.py` |
| `tests/scenarios/fakes/fake_beads.py` | `src/mockworld/fakes/fake_beads.py` |
| `tests/scenarios/fakes/fake_subprocess_runner.py` | `src/mockworld/fakes/fake_subprocess_runner.py` |
| `tests/scenarios/fakes/fake_wiki_compiler.py` | `src/mockworld/fakes/fake_wiki_compiler.py` |
| `tests/scenarios/fakes/test_port_signature_conformance.py` | `tests/test_mockworld_fakes_conformance.py` |
| `tests/scenarios/fakes/test_port_conformance.py` | `tests/test_mockworld_runtime_conformance.py` |

**What stays in `tests/scenarios/`:** the orchestration layer (`mock_world.py` with `_wire_targets`, `run_pipeline`, `run_with_loops`, `start_dashboard`, etc.), the catalog (`loop_catalog.py`, `loop_registrations.py`), and the conftest fixtures. These are pytest-only orchestration; only the adapter-shaped Fakes move to `src/`.

**Import updates:** every `from tests.scenarios.fakes import X` becomes `from mockworld.fakes import X`. The `mock_world.py` orchestration uses the new import path; behavior is identical.

**Production safety:**

- Fakes have **zero side effects on import.** Verified: no module-level state mutation, no auto-registered hooks, no network calls at construction time.
- `src/service_registry.py` does not import them at all. The `mockworld.sandbox_main` entrypoint imports them and passes constructed instances via the override kwargs.
- Production code (`server.py`, `orchestrator.py`) never imports `mockworld.fakes` — the import graph confirms it. The Fakes ship in the wheel but are unreachable from any production-call path unless `mockworld.sandbox_main` is the launched entrypoint.

**Maintenance dividend.** When you add a method to PRPort, both tiers fail the conformance test on the same git commit. There is no "I updated the in-process Fake but forgot the sandbox one" failure mode — they ARE the same Fake.

### Component 3 — `docker-compose.sandbox.yml` (greenfield)

The repo has `Dockerfile.agent` and `Dockerfile.agent-base` but no `docker-compose.yml`. The sandbox stack is the first compose file in the repo.

**`docker-compose.sandbox.yml`:**

```yaml
version: "3.9"

networks:
  sandbox:
    internal: true   # the air-gap. No external egress. DNS for external hosts → NXDOMAIN.

services:
  hydraflow:
    build:
      context: .
      dockerfile: Dockerfile.agent
    # The selection of MockWorld vs. production is made by which entrypoint
    # runs — NOT by a config flag. This container always boots the sandbox
    # entrypoint; the production image runs `python -m hydraflow` instead.
    command: ["python", "-m", "mockworld.sandbox_main", "/seed/scenario.json"]
    environment:
      HYDRAFLOW_DASHBOARD_HOST: "0.0.0.0"
      HYDRAFLOW_DASHBOARD_PORT: "5555"
      HYDRAFLOW_ENV: "sandbox"
      # No real credentials are needed — the Fakes don't use them. These
      # placeholder values are present only so legacy code paths that read
      # `os.environ["GH_TOKEN"]` at startup don't crash before the Fake
      # adapters take over.
      GH_TOKEN: "unused-by-fake-github"
      ANTHROPIC_API_KEY: "unused-by-fake-llm"
    volumes:
      - ./tests/sandbox_scenarios/seeds:/seed:ro
    networks: [sandbox]
    healthcheck:
      test: ["CMD", "curl", "-fsS", "http://localhost:5555/healthz"]
      interval: 2s
      timeout: 1s
      retries: 30
      start_period: 5s

  ui:
    build:
      context: ./src/ui
      dockerfile: Dockerfile.ui   # NEW — multi-stage: npm build → nginx
    depends_on:
      hydraflow:
        condition: service_healthy
    networks: [sandbox]
    ports:
      - "127.0.0.1:5556:80"   # bound to localhost ONLY for human debugging.

  playwright:
    image: mcr.microsoft.com/playwright/python:v1.49.0-jammy
    volumes:
      - .:/work:ro
      - sandbox-results:/results
    working_dir: /work
    environment:
      SANDBOX_BASE_URL: "http://ui"
      SANDBOX_API_BASE: "http://hydraflow:5555"
    depends_on:
      ui:
        condition: service_started
    networks: [sandbox]
    command: ["pytest", "tests/sandbox_scenarios/runner/", "-v", "--junitxml=/results/junit.xml"]

volumes:
  sandbox-results:
```

**`src/ui/Dockerfile.ui`** (new, ~25 lines):

```dockerfile
# Stage 1: build vite assets
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: nginx serving dist + proxying /api and /ws to hydraflow:5555
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.sandbox.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**`src/ui/nginx.sandbox.conf`** (new):

```nginx
server {
    listen 80;
    root /usr/share/nginx/html;
    index index.html;

    location / {
        try_files $uri /index.html;
    }
    location /api/ {
        proxy_pass http://hydraflow:5555;
        proxy_set_header Host $host;
    }
    location /ws {
        proxy_pass http://hydraflow:5555;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Make targets** (additions to top-level `Makefile`):

```makefile
sandbox-up:
	docker compose -f docker-compose.sandbox.yml up -d --build hydraflow ui

sandbox-down:
	docker compose -f docker-compose.sandbox.yml down -v

sandbox-test:
	docker compose -f docker-compose.sandbox.yml run --rm playwright

sandbox-shell:
	docker compose -f docker-compose.sandbox.yml exec hydraflow /bin/bash
```

### Component 4 — Scenario seed format

A scenario is **one Python module** under `tests/sandbox_scenarios/scenarios/`. The module exposes:

- `NAME: str` — stable identifier (matches filename without `.py`).
- `DESCRIPTION: str` — one-line summary used in CLI output and CI dashboards.
- `seed() -> MockWorldSeed` — pure function, returns a serializable dataclass.
- `async assert_outcome(api: SandboxAPIClient, page: PlaywrightPage) -> None` — runs after the loop has ticked; asserts via REST and UI.

**`MockWorldSeed` dataclass** (`src/mockworld/seed.py`):

```python
@dataclass(frozen=True)
class MockWorldSeed:
    """Serializable initial state for a MockWorld run."""
    repos: list[tuple[str, str]] = field(default_factory=list)  # (slug, path)
    issues: list[FakeIssueDict] = field(default_factory=list)
    prs: list[FakePRDict] = field(default_factory=list)
    scripts: dict[str, dict[int, list[Any]]] = field(default_factory=dict)
    cycles_to_run: int = 4
    loops_enabled: list[str] | None = None  # None = all loops

    def to_json(self) -> str: ...
    @classmethod
    def from_json(cls, raw: str) -> "MockWorldSeed": ...
```

**Example scenario** (`tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py`):

```python
from mockworld.seed import MockWorldSeed
from tests.factories import (
    IssueFactory, PlanResultFactory, AgentResultFactory, ReviewResultFactory,
)

NAME = "s01_happy_single_issue"
DESCRIPTION = "Single hydraflow-ready issue → triage → plan → implement → review → merge"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            IssueFactory.create(
                number=1,
                title="Add hello world",
                labels=["hydraflow-ready"],
            ).model_dump(),
        ],
        scripts={
            "plan":      {1: [PlanResultFactory.create(success=True).model_dump()]},
            "implement": {1: [AgentResultFactory.create(success=True, branch="hf/issue-1").model_dump()]},
            "review":    {1: [ReviewResultFactory.create(verdict="approve").model_dump()]},
        },
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    # API assertion: outcome is "merged"
    timeline = await api.get("/api/timeline/issue/1")
    assert timeline["outcome"] == "merged", f"got {timeline['outcome']}"

    # UI assertion: dashboard shows the merged outcome
    await page.goto("/")
    await page.click("text=Outcomes")
    await page.wait_for_selector("[data-testid='outcome-row-1']", timeout=5000)
    text = await page.locator("[data-testid='outcome-row-1']").text_content()
    assert "Merged" in text, f"got {text}"
```

**Seed lifecycle:**

1. Host-side pre-test hook calls `module.seed()` → produces `MockWorldSeed`.
2. Hook serializes via `seed.to_json()` → writes `tests/sandbox_scenarios/seeds/<NAME>.json`.
3. The compose stack mounts that path read-only at `/seed/scenario.json` inside the `hydraflow` container.
4. The `hydraflow` container's command is `python -m mockworld.sandbox_main /seed/scenario.json` — the entrypoint reads the seed from argv (or `$HYDRAFLOW_MOCKWORLD_SEED` as fallback) and constructs Fake adapters from it before passing them to `build_services()`.
5. **No code execution inside container** — seed is pure data; safer to run untrusted-looking files.

**Reusing in-process MockWorld — the parity test:**

```python
# tests/scenarios/test_sandbox_parity.py
import pytest
from tests.sandbox_scenarios.runner import load_all_scenarios

@pytest.mark.parametrize("scenario", load_all_scenarios(), ids=lambda s: s.NAME)
async def test_sandbox_scenario_runs_in_process(mock_world, scenario) -> None:
    """Every sandbox scenario must also pass the in-process Tier 1.

    If this fails but Tier 2 also fails, the bug is in scenario logic.
    If this passes but Tier 2 fails, the bug is in container/wiring/UI.
    """
    seed = scenario.seed()
    mock_world.apply_seed(seed)
    loops = seed.loops_enabled or [
        "triage_loop", "plan_loop", "implement_loop", "review_loop", "merge_loop",
    ]
    await mock_world.run_with_loops(loops, cycles=seed.cycles_to_run)

    # Smoke-level check: scenario didn't crash and at least one issue advanced.
    # Per-scenario assertions stay in `assert_outcome` — UI assertions require
    # Playwright and are Tier 2 only.
    advanced = any(
        outcome.final_stage != "queued"
        for outcome in mock_world.last_run.issues.values()
    )
    assert advanced, f"scenario {scenario.NAME} produced no progress in-process"
```

This parity test is the alignment payoff: every sandbox scenario has a fast in-process counterpart. Triaging a Tier-2 failure starts with "did the parity test pass?" — yes means it's container/wiring; no means it's scenario logic.

### Component 5 — Scenario harness CLI

`scripts/sandbox_scenario.py` — a thin wrapper around docker-compose lifecycle (~150 LOC).

**CLI surface:**

```
$ python scripts/sandbox_scenario.py run s01_happy_single_issue
[1/5] Computing seed... ✓ (wrote tests/sandbox_scenarios/seeds/s01_happy_single_issue.json)
[2/5] Building images... ✓ (cached)
[3/5] Starting stack on internal network... ✓
[4/5] Waiting for hydraflow /healthz... ✓ (3.2s)
[5/5] Running playwright assertions... ✓ (12.4s)

PASSED s01_happy_single_issue (15.6s)

$ python scripts/sandbox_scenario.py run-all
PASSED  s01_happy_single_issue       (15.6s)
PASSED  s02_batch_three_issues       (28.1s)
FAILED  s03_review_retry_then_pass   (45.0s)
  → assertion failed at scenarios/s03_*.py:23
    expected timeline.outcome == "merged", got "review_failed_no_retry"
  → logs:        /tmp/sandbox-results/s03/hydraflow.log
  → screenshots: /tmp/sandbox-results/s03/screenshots/
[...]

11 passed, 1 failed in 4m 17s

$ python scripts/sandbox_scenario.py status
hydraflow:  running (healthy, port 5555 internal)
ui:         running (port 5556 → host loopback)
playwright: stopped

$ python scripts/sandbox_scenario.py down
Stopping stack... ✓
Removing volumes... ✓
```

**Subcommands:**

| Subcommand | Effect |
|------------|--------|
| `run NAME` | Compute seed, build (if needed), boot stack, run one scenario, capture artifacts, tear down |
| `run-all` | Same, but iterates the catalog; produces a summary table |
| `status` | Show current stack state without booting |
| `down` | Tear down the stack and remove volumes |
| `shell` | Drop into a bash shell inside the `hydraflow` container (debugging) |
| `seed NAME` | Compute and print the JSON seed without booting (debugging) |

**Failure handling inside the harness:** any exception during boot, healthcheck wait, or assertion captures `docker compose logs hydraflow > /tmp/sandbox-results/<NAME>/hydraflow.log` plus the Playwright trace, then runs `down` regardless. The harness exits nonzero on any scenario failure.

### Component 6 — The dozen scenarios (catalog)

Twelve scenarios, each chosen because **breakage produces a silent stall in the dark factory** rather than a loud error a unit test would catch.

**Pipeline (4) — "the assembly line works end-to-end"**

| # | NAME | What it proves |
|---|------|----------------|
| 1 | `s01_happy_single_issue` | Single `hydraflow-ready` issue → triage → plan → implement → review → merge. UI shows "Merged" in Outcomes tab. |
| 2 | `s02_batch_three_issues` | 3 issues processed in parallel (batch_size=3). UI Work Stream shows all three progressing concurrently. |
| 3 | `s03_review_retry_then_pass` | Review verdict = `request_changes` on attempt 1, then `approve` on attempt 2. Issue ends merged. |
| 4 | `s04_ci_red_then_fixed` | PR opens with red CI, ci-fix runner intervenes, CI green, merged. |

**HITL & escalation (2) — "humans see what they need to see"**

| # | NAME | What it proves |
|---|------|----------------|
| 5 | `s05_hitl_after_review_exhaustion` | 3 review failures → issue surfaces in HITL tab with `request-changes` button live. |
| 6 | `s06_kill_switch_via_ui` | Operator clicks System tab, toggles a loop off → loop stops ticking within 1 cycle. (Proves ADR-0049 works through the dashboard, not just via env var.) |

**Caretaker loops (3) — "the background loops actually run"**

| # | NAME | What it proves |
|---|------|----------------|
| 7 | `s07_workspace_gc_reaps_dead_worktree` | Orphan worktree present at boot → WorkspaceGCLoop reaps it → System tab counter increments. |
| 8 | `s08_pr_unsticker_revives_stuck_pr` | PR with no activity for >threshold → PRUnstickerLoop triggers auto-resync → PR moves. |
| 9 | `s09_dependabot_auto_merge` | Dependabot PR with green CI → DependabotMergeLoop auto-merges without a human touch. |

**Dark-factory invariants (2) — "the load-bearing conventions still hold"**

| # | NAME | What it proves |
|---|------|----------------|
| 10 | `s10_kill_switch_universal` | Disable EVERY loop via static config → no loop ticks for 5 cycles. (Proves ADR-0049's universal in-body gate.) |
| 11 | `s11_credit_exhaustion_suspends_ticking` | FakeLLM raises `CreditExhaustedError` → outer loop suspends, surfaces in System tab alert. (Proves `reraise_on_credit_or_bug` propagates correctly through `BaseSubprocessRunner`.) |

**Trust fleet & wiki (1) — "multi-repo + knowledge layer alive"**

| # | NAME | What it proves |
|---|------|----------------|
| 12 | `s12_trust_fleet_three_repos_independent` | 3 repos in registry, each with 1 issue → all process independently, no cross-contamination, Wiki tab shows entries from all three. |

**Selection rationale:** every Critical bug caught in fresh-eyes review of recent feature builds (#8390, #8431, #8439) maps to one of these scenarios. They are not "test the framework" — they are "test the parts of the dark factory that, if broken, produce silent stalls instead of loud errors."

**Out of scope for the dozen:** Sentry capture (verified in-process), wiki-rot detection (in-process is sufficient), report pipeline (separate test track), product-discovery flow (covered by s01's UI assertion). These can grow into the catalog over time without changing the architecture.

### Component 7 — Maintenance & alignment story

**Single source of truth.** Both tiers import from `src/mockworld/fakes/` and `tests/factories/`. There is no parallel "sandbox factory" or "sandbox Fake" — the same code drives both.

**Drift detection mechanisms:**

1. **Port↔Fake conformance test** (already shipped in PR #8446). Runs on every PR. If a Port method changes signature, both tiers fail the same test on the same commit.
2. **Parity test.** Every sandbox scenario has a Tier-1 counterpart that runs in the standard pytest collection. If a scenario passes Tier 2 but fails Tier 1 (or vice versa), drift is surfaced immediately — and the difference identifies whether it is logic, container, or UI.
3. **Scenario module is the seed.** A scenario is one file. To add a new dimension to MockWorld (e.g., FakeBeads gets a new method), you update the Fake, then update the conformance test, then update any scenario that exercises the new method. There is no "sandbox catalog" to maintain in addition to the scenario module — the catalog is the directory listing.

**Adding a new scenario.** One file under `tests/sandbox_scenarios/scenarios/`. Define `NAME`, `DESCRIPTION`, `seed()`, `assert_outcome()`. The harness picks it up automatically via directory enumeration. No registration table to update.

**Removing a scenario.** Delete the file. Same — no registry to maintain.

**Adding a new Fake.** Place under `src/mockworld/fakes/`, import from `mockworld.fakes` package init. Add a conformance test entry. Done.

**Quality gates.** `src/mockworld/` is treated identically to `src/` for ruff/pyright/bandit/coverage purposes. The Fakes are production code.

### Component 8 — Failure modes

Three classes of failure, each with a defined response.

**1. Scenario assertion failure (the test caught a bug).**
- Capture: hydraflow stdout/stderr, dashboard `/api/state` snapshot, Playwright trace + screenshots.
- Output to `/tmp/sandbox-results/<NAME>/`.
- CI uploads as artifact with 7-day retention.
- Fail loud: red CI, blocks merge of the offending PR.

**2. Sandbox infrastructure failure (the harness itself broke).**
- Container failed to boot, network unreachable, vite build failed, playwright crashed before assertions.
- Distinguished from #1 by: hydraflow `/healthz` never returned 200 within 60s, OR Playwright never navigated to base URL, OR docker-compose returned a non-test exit code.
- Marked in JUnit XML as `<error>` (not `<failure>`) so CI dashboards distinguish them.
- Auto-creates a `hydraflow-find` issue with the failure logs attached; treated as a flake until reproduced 3 times in a row, then promoted to a real bug.

**3. Tier-1 / Tier-2 divergence (parity test catches scenario regression).**
- Triage workflow: look at Tier 1 first (faster, easier diff), then narrow to Tier 2 specifics.
- If Tier 2 fails but Tier 1 passes → bug is in containerization, network, UI, or build pipeline.
- If both fail → bug is in scenario logic or Fake behavior.
- If only Tier 1 fails → likely a recent unrelated change broke the in-process tier; investigate per normal regression workflow.

### Component 9 — PR sequencing

Three sequential PRs. Same staging discipline as the dark-factory infra hardening track: the foundation lands in isolation, then the substantive infrastructure, then the catalog scales out.

**PR A — Fake relocation + adapter-injecting `build_services()` + sandbox entrypoint (foundation)**
- Move `tests/scenarios/fakes/` → `src/mockworld/fakes/` (12 files + conformance tests).
- Refactor `build_services()` to accept optional `prs`/`workspaces`/`store`/`fetcher`/`runners` keyword arguments. Defaults preserve current behavior. Production callers pass nothing. Add `RunnerSet` dataclass bundling `triage`/`planners`/`agents`/`reviewers` so the four LLM-backed runners can be overridden as one kwarg.
- Add `src/mockworld/sandbox_main.py` — the new entrypoint that constructs Fakes from a seed file and calls `build_services()` with overrides.
- Add `src/mockworld/seed.py` containing `MockWorldSeed` dataclass + `from_json` / `to_json` serialization.
- Add FakeLLM-backed runner variants (`FakePlannerRunner`, `FakeAgentRunner`, `FakeReviewRunner`, `FakeTriageRunner`) and `build_fake_runner_set(seed)` factory.
- Add dashboard duck-typed banner: `/api/state` reports `mockworld_active = getattr(prs, "_is_fake_adapter", False)`. React shell renders persistent top bar when true.
- Add `_is_fake_adapter = True` class attribute to all Fake adapters (5 of them).
- Add 1 trivial sandbox scenario (`s00_smoke`) that runs in-process via parity test only — proves the wiring works without requiring docker-compose yet.
- Update wiki: `docs/wiki/dark-factory.md` adds a §7 noting MockWorld is permanently-loaded core infrastructure, selected at entrypoint time, not a test-only fixture.
- **Risk:** low. Production code path is byte-for-byte unchanged (`build_services()` signature gains kwargs that production never passes). No new env var, no new config field, no new conditional in production code.
- **Estimated PR size:** ~700 LOC including tests.

**PR B — Docker compose stack + harness CLI (the new tier)**
- Add `docker-compose.sandbox.yml`.
- Add `src/ui/Dockerfile.ui` + `src/ui/nginx.sandbox.conf`.
- Add `scripts/sandbox_scenario.py` (run, run-all, status, down, shell, seed subcommands).
- Add Makefile targets (`sandbox-up`, `sandbox-down`, `sandbox-test`, `sandbox-shell`).
- Add `tests/sandbox_scenarios/runner/conftest.py` (Playwright + SandboxAPIClient fixtures).
- Add `tests/sandbox_scenarios/runner/test_scenarios.py` (single parametrized test that runs each scenario's `assert_outcome`).
- Implement `s01_happy_single_issue` end-to-end (proves the harness actually works against a real stack).
- Promote the existing `Browser Scenarios` GitHub Actions job from SKIPPED to running `sandbox_scenario.py run s01_happy_single_issue` on every PR that touches `src/service_registry.py`, `src/mockworld/`, `Dockerfile*`, `docker-compose*`, or `tests/sandbox_scenarios/`.
- Add ADR-0052 ("Sandbox-tier scenario testing") capturing the architecture and tier responsibilities.
- **Risk:** medium. New compose stack, network policy, CI infrastructure. Mitigation: gated to relevant PRs only (path-trigger), nightly run for regressions on unrelated changes.
- **Estimated PR size:** ~800 LOC.

**PR C — Catalog completion (the dozen)**
- Add `s02` through `s12`, one per task. Each task includes the scenario module, the parity test (auto-discovered via `pytest.mark.parametrize`), and the seed JSON regeneration.
- Promote the CI job to `sandbox_scenario.py run-all` with nightly schedule + path-trigger as in PR B.
- Add `tests/sandbox_scenarios/README.md` documenting "how to add a scenario."
- Update `docs/wiki/dark-factory.md` §3 (the convergence-loop section) with sandbox-tier expectations: "substantial features require all 12 sandbox scenarios green before merge."
- **Risk:** low. Each scenario is independent; failures isolated to that scenario. The catalog can land partial (some scenarios merged, some still under review) without breaking the others.
- **Estimated PR size:** ~1400 LOC, mostly per-scenario seed and assertion code.

**Why three PRs not one.** PR A is low-risk because production code paths are byte-for-byte unchanged — `build_services()` gains kwargs that production never passes, and the new entrypoint module is dead code unless someone runs `python -m mockworld.sandbox_main`. PR B is the irreversible "we have a sandbox tier now" decision and ships independently so it gets full review attention. PR C is incremental and tolerates partial landings — each scenario lands on its own merits without affecting the others.

## Out of scope

- **Tier-1 unification.** Refactoring `MockWorld._wire_targets` to construct the orchestrator the same way Tier 2 does (i.e., via `build_services(..., prs=fake, workspaces=fake, ...)` instead of post-construction monkeypatching) is a future cleanup, not part of this spec. Tier 1 keeps its current wiring throughout this work.
- **Production MockWorld deployments** (demo environments, customer training labs). The architecture supports them; productizing them is a separate track.
- **Cassette recording for the sandbox tier.** Sandbox scenarios script LLM responses statically via FakeLLM. Recording real LLM outputs and replaying them is out of scope; the existing in-process cassette pattern (used in trust-fleet contract tests) is unchanged.
- **Visual regression testing.** Playwright assertions check semantic content (text, data attributes), not pixel-level snapshots. Visual diffing is a possible future track.
- **Multi-browser support.** Playwright runs Chromium only in this design. Firefox/WebKit are out of scope.
- **Performance benchmarking under MockWorld.** The sandbox tier is a correctness gate, not a benchmark suite. Performance assertions (e.g., "loop tick under 100ms") belong in a separate benchmark track if needed.

## Failure modes that this design accepts

- **Docker daemon required on CI.** GitHub Actions runners support this; self-hosted runners must have Docker installed. This is acceptable infrastructure cost.
- **First-run image build is slow** (~3 min). Subsequent runs use the build cache. Acceptable for nightly + path-triggered CI.
- **Playwright headless can flake on slow CI.** Mitigation: explicit `wait_for_selector` with generous timeouts (5s default), retry once on infrastructure-class failures (per Component 8).
- **Sandbox network policy assumes Linux container network behavior.** Docker Desktop on macOS/Windows uses a VM that should produce equivalent isolation, but is not the primary target. CI runs on Linux runners; local-dev fidelity on macOS is best-effort.

## Open questions for implementation phase

- **Should `s06_kill_switch_via_ui` test toggling via the System tab toggle UI, or via posting to the toggle API endpoint that the UI uses?** Both prove the same wiring; the UI version is more end-to-end. Recommendation: UI version.
- **Should the seed format support binary blobs** (e.g., simulated git diffs)? Currently JSON-only. Defer until a scenario actually needs it; YAGNI.
- **CI artifact retention.** 7 days proposed; revisit if storage becomes a concern. GitHub Actions artifacts default to 90 days, so 7 is conservative.
- **Failure-issue auto-creation rate-limiting.** Three-strikes-then-bug is proposed; tune empirically once infra failures become observable.

## Source-file citations

- `src/service_registry.py::build_services()` — primary refactor target. Gains optional adapter-override kwargs in PR A.
- `tests/scenarios/fakes/` — current home of Fakes, moved to `src/mockworld/fakes/` in PR A.
- `tests/scenarios/fakes/test_port_signature_conformance.py` — load-bearing conformance test, moved to `tests/test_mockworld_fakes_conformance.py` alongside the Fakes.
- `tests/scenarios/mock_world.py:643–755` — existing in-process dashboard boot, demonstrates the dashboard can be driven from tests today.
- `src/server.py:318` (`main`), `src/server.py:124` (`_run_with_dashboard`), `src/server.py:260` (`_run_headless`) — the production entrypoint; reference for what `mockworld.sandbox_main` mirrors structurally.
- `Dockerfile.agent`, `Dockerfile.agent-base` — reused as the container base for the `hydraflow` service in compose.
- `pyproject.toml` — already declares `pytest-playwright>=0.5.0`; no new dep needed for browser automation.
- `.github/workflows/` (existing `Browser Scenarios` job, currently SKIPPED) — promotion target for the sandbox CI integration.

## Explicitly rejected: a `mockworld_enabled` config switch

An earlier draft of this spec proposed adding `mockworld_enabled: bool` to `HydraFlowConfig`, threaded through `_ENV_BOOL_OVERRIDES`, with `build_services()` branching on it. **This design was rejected** because:

1. The system already has 30+ env-toggleable booleans and the maintenance burden of each is non-trivial: documentation, tests for both branches, defaults, dashboard surfacing, cross-references in operator runbooks. Adding another for a structural choice that should be made at process-boundary (not config) level worsens that burden.
2. A flag creates the possibility — however small — of accidental enablement in production. The entrypoint-selection design makes that structurally impossible.
3. A flag implies "MockWorld is a mode you turn on." MockWorld is not a mode; it is a permanent set of alternative adapters, always loaded, selected by which `python -m` line ran.
4. The flag-based design produces a `if config.mockworld_enabled:` branch in production code paths. The injection-based design produces no production-code branching at all — the Fakes are simply parameters that production never passes.

If a future use case demands runtime switching (e.g., "flip to MockWorld for the next 10 minutes for a demo without restarting"), revisit this decision then. Until that exists, "different entrypoint" is the right granularity.
