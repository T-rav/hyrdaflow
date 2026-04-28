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
│   Network: internal: true (no egress route — TCP to external hosts │
│            times out / is refused; DNS resolution is undefined)    │
│   Slow (~30-60s/scenario), runs nightly + on infra-touching PRs.   │
└───────────────────────────────────────────────────────────────────┘
```

**Why this shape:**

- **One Fake codebase, two tiers.** Tier 1 catches logic regressions in seconds; Tier 2 catches container/wiring/UI regressions in minutes. The maintenance you do anyway (Port↔Fake conformance, scenario factories) keeps both honest.
- **MockWorld via injection, not configuration.** The sandbox tier calls the *real* `build_services()` factory but passes Fake adapters as constructor parameters. There is no config flag to "enable MockWorld" — the choice is made at the call site by *which entrypoint runs*. Production runs the `hydraflow` console script (entry point `server:main` per `pyproject.toml`; equivalent to `python src/server.py`) → no overrides → real adapters. Sandbox runs `python -m mockworld.sandbox_main` → overrides → Fakes. No conditional in `build_services()`, no env var to flip.
- **Container = closer-to-production fidelity.** Subprocess streaming, `/workspace` mounts, dashboard binding to `0.0.0.0`, agent CLI invocations, FastAPI startup, vite-built UI assets — all run for real. In-process mocking can never surface a "Dockerfile dropped a binary" or "uvicorn refuses to bind in container" bug.
- **Air-gap is structurally guaranteed,** not honor-system. The compose network is `internal: true`, so containers have no default gateway and any code path that tries `api.github.com` *cannot route to it* — TCP connections time out or are refused. (DNS behavior under `internal: true` is host-runtime-dependent — Docker may still resolve external names but cannot route to them. Tests assert routing failure, not name-resolution failure.)

## Core concept: MockWorld is always on

MockWorld is not a mode you enable. It is **always available, always loaded, always usable** — a permanent set of alternative adapters that ship alongside the real ones. This drives every design decision below:

1. **No config switch. None.** There is no `HYDRAFLOW_MOCKWORLD_ENABLED` env var, no boolean field on `HydraFlowConfig`, no conditional branch in `build_services()` that selects "fake or real." The system has too many configurable core parts already; MockWorld will not become another. The choice is made at the **entrypoint level**: production runs the `hydraflow` console script (`server:main`); sandbox runs `python -m mockworld.sandbox_main`. The two entrypoints call the same factory with different adapter arguments.
2. **Fakes ship in `src/`, not `tests/`.** They follow production-code conventions: type-checked by pyright, linted by ruff, scanned by bandit, covered by the same quality gates as adapters. They are not "test fixtures" — they are alternative adapters that happen to be primarily used by tests today.
3. **`build_services()` accepts adapter overrides.** Today the factory constructs `PRManager`, `WorkspaceManager`, `IssueStore`, `IssueFetcher` itself. Tomorrow it accepts each as an optional keyword argument; when omitted, it constructs the real one. Sandbox passes Fakes; production passes nothing. Same factory, different inputs.
4. **Visibility via duck-typing, not config.** The dashboard renders a `MOCKWORLD MODE` banner when it sees a marker attribute on the injected `PRPort` instance (e.g., `getattr(prs, "_is_fake", False)`). The banner doesn't ask "is the flag set?" — it asks "is the adapter we're holding a Fake?" If yes, render the banner. If no, don't.
5. **No accidental MockWorld in production is structurally possible.** There is no flag to flip. The only way to run with Fakes is to launch the sandbox entrypoint. Production launchers can't accidentally select MockWorld because they don't pass overrides. This is stronger than any guard could be.
6. **MockWorld is a peer of "production-with-real-GitHub," not a subordinate.** Demos, training labs, hands-off sandboxes — all valid uses, all reached via the sandbox entrypoint. No code refuses them.

The "cutting off my arm" framing is not hyperbole: removing MockWorld would remove the substrate every test tier depends on. It is core infrastructure that ships with every build, in `src/`, treated identically to production code.

## Components

### Component 1 — Sandbox entrypoint + adapter-injecting `build_services()`

**No config switch.** Instead, four changes — three to existing surfaces, one new module:

1. `build_services()` gains optional adapter overrides for each Port. Defaults preserve today's behavior (factory constructs real adapters).
2. `HydraFlowOrchestrator.__init__` gains an optional `services: ServiceRegistry | None = None` parameter; when provided, the orchestrator skips its own `build_services()` call and uses what was passed in.
3. The Port-shaped fields on `ServiceRegistry`, `RouteContext`, and the dashboard router signatures are widened from concrete adapter types (`PRManager`, `WorkspaceManager`, `IssueStore`) to their Port protocols (`PRPort`, `WorkspacePort`, `IssueStorePort`). This is required so Fakes that satisfy the Port can be passed without pyright errors.
4. A new `python -m mockworld.sandbox_main` entrypoint constructs Fakes and passes them via the overrides into both `build_services()` and the orchestrator.

**Change 1 — Port-typing widening (preparatory).**

Today `ServiceRegistry.prs` is annotated as the concrete `PRManager` (per `src/service_registry.py:112`), and equivalent fields exist on `RouteContext` (`src/dashboard_routes/_routes.py:309–310`) and the `create_router(pr_manager: PRManager, ...)` signature (line 585). These must be widened to the Port protocol so a `FakeGitHub` (which satisfies `PRPort` but is not a `PRManager`) can be assigned.

Specific widening:

| Site | Today | After |
|------|-------|-------|
| `src/service_registry.py:112` | `prs: PRManager` | `prs: PRPort` |
| `src/service_registry.py` (workspaces field) | `workspaces: WorkspaceManager` | `workspaces: WorkspacePort` |
| `src/service_registry.py` (store field) | `store: IssueStore` | `store: IssueStorePort` |
| `src/dashboard_routes/_routes.py:309–310` | `pr_manager: PRManager` | `pr_manager: PRPort` |
| `src/dashboard_routes/_routes.py:585` | `pr_manager: PRManager` | `pr_manager: PRPort` |
| `src/dashboard_routes/_routes.py:456` (`pr_manager_for()` return) | `-> PRManager` | `-> PRPort` |

Any downstream code that calls non-Port methods on these fields (i.e., `PRManager`-specific methods that aren't on `PRPort`) is a leaky abstraction and surfaces as a pyright error after widening — fix at the call site by either (a) hoisting the method onto `PRPort`, or (b) using a narrower type at the local call site. Both are appropriate fixes; pick per case.

**Change 2 — `src/service_registry.py::build_services()` accepts overrides:**

```python
@dataclass(frozen=True)
class RunnerSet:
    """Bundle of the four LLM-backed runners. Allows the sandbox entrypoint
    to override all four with FakeLLM-backed variants in a single kwarg.

    These are the raw runners — NOT the phase coordinators (`TriagePhase`,
    `PlanPhase`, `ImplementPhase`, `ReviewPhase`). The phases are constructed
    by `build_services()` from the runners passed in here. So:
        RunnerSet.triage     -> ServiceRegistry.triage (TriageRunner)
        RunnerSet.planners   -> ServiceRegistry.planners
        RunnerSet.agents     -> ServiceRegistry.agents
        RunnerSet.reviewers  -> ServiceRegistry.reviewers
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

**Change 3 — `src/orchestrator.py::HydraFlowOrchestrator.__init__` accepts a pre-built ServiceRegistry:**

Today `HydraFlowOrchestrator.__init__` (lines 85–141) constructs `build_services()` itself unconditionally. The sandbox entrypoint needs to pre-build the services with Fakes injected, then pass them to the orchestrator. Add an optional kwarg:

```python
def __init__(
    self,
    config: HydraFlowConfig,
    event_bus: EventBus | None = None,
    state: StateTracker | None = None,
    pipeline_enabled: bool = True,
    *,
    services: ServiceRegistry | None = None,   # NEW
) -> None:
    self._config = config
    self._bus = event_bus or EventBus()
    self._state = state or build_state_tracker(config)
    # ... existing setup ...
    if services is None:
        services = build_services(
            config, self._bus, self._state, self._stop_event,
            WorkerRegistryCallbacks(...),
            active_issues_cb=self._sync_active_issue_numbers,
        )
    self._svc: ServiceRegistry = services
```

Production callers pass nothing → orchestrator builds its own services as today (byte-for-byte unchanged). Sandbox passes a pre-built registry.

**Change 4 — `src/mockworld/sandbox_main.py` (new):**

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
    orch = HydraFlowOrchestrator(
        config, event_bus=event_bus, state=state, services=svc,
    )
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
- Production runtime behavior is unchanged. `build_services()` and `HydraFlowOrchestrator.__init__` both gain optional kwargs that production never passes; defaults preserve today's behavior. The only production-visible diff is type annotations (Port instead of concrete adapter), which removes a leaky abstraction rather than adding one.
- "Could MockWorld accidentally run in production?" answer: only if someone runs `python -m mockworld.sandbox_main` in production. That is a deliberate, visible action. There is no flag to fat-finger.

### Component 2 — Fake relocation: `src/mockworld/fakes/`

Today: 12 Fake classes (~1,851 LOC) live under `tests/scenarios/fakes/`. Sandbox tier requires them to be importable from `src/service_registry.py` (which runs in the production container under MockWorld mode).

**Move plan** (Move = relocate-only; New = create as part of PR A):

| Today | Tomorrow | Status |
|-------|----------|--------|
| `tests/scenarios/fakes/fake_github.py` | `src/mockworld/fakes/fake_github.py` | Move + add `from_seed()` classmethod |
| `tests/scenarios/fakes/fake_workspace.py` | `src/mockworld/fakes/fake_workspace.py` | Move (rename class to `FakeWorkspaceManager` for symmetry with `WorkspaceManager`) |
| `tests/scenarios/fakes/fake_llm.py` | `src/mockworld/fakes/fake_llm.py` | Move + add `build_fake_runner_set(seed)` factory |
| `tests/scenarios/fakes/fake_clock.py` | `src/mockworld/fakes/fake_clock.py` | Move |
| `tests/scenarios/fakes/fake_docker.py` | `src/mockworld/fakes/fake_docker.py` | Move |
| `tests/scenarios/fakes/fake_git.py` | `src/mockworld/fakes/fake_git.py` | Move |
| `tests/scenarios/fakes/fake_fs.py` | `src/mockworld/fakes/fake_fs.py` | Move |
| `tests/scenarios/fakes/fake_http.py` | `src/mockworld/fakes/fake_http.py` | Move |
| `tests/scenarios/fakes/fake_sentry.py` | `src/mockworld/fakes/fake_sentry.py` | Move |
| `tests/scenarios/fakes/fake_beads.py` | `src/mockworld/fakes/fake_beads.py` | Move |
| `tests/scenarios/fakes/fake_subprocess_runner.py` | `src/mockworld/fakes/fake_subprocess_runner.py` | Move |
| `tests/scenarios/fakes/fake_wiki_compiler.py` | `src/mockworld/fakes/fake_wiki_compiler.py` | Move |
| (none today) | `src/mockworld/fakes/fake_issue_fetcher.py` | **NEW** — `FakeIssueFetcher(IssueFetcherPort)` with `from_seed()` classmethod. Issue-fetcher behavior is currently emulated by `_wire_targets`'s monkeypatching in `mock_world.py`; PR A extracts it into a standalone class. |
| (none today) | `src/mockworld/fakes/fake_issue_store.py` | **NEW** — `FakeIssueStore(IssueStorePort)` with `from_seed()` classmethod. Same extraction story as `FakeIssueFetcher`. |
| `tests/scenarios/fakes/test_port_signature_conformance.py` | `tests/test_mockworld_fakes_conformance.py` | Move |
| `tests/scenarios/fakes/test_port_conformance.py` | `tests/test_mockworld_runtime_conformance.py` | Move |
| (none today) | `src/mockworld/seed.py` | **NEW** — `MockWorldSeed` dataclass + `from_json` / `to_json` serialization (see Component 4). |
| (none today) | `src/mockworld/sandbox_main.py` | **NEW** — entrypoint module (see Component 1). |

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
    internal: true   # the air-gap. No default gateway → no external egress.
                   # DNS resolution behavior is runtime-dependent; rely on routing
                   # failure (timeouts/refused) for assertions, not on NXDOMAIN.

services:
  hydraflow:
    build:
      context: .
      dockerfile: Dockerfile.agent
    # The selection of MockWorld vs. production is made by which entrypoint
    # runs — NOT by a config flag. This container always boots the sandbox
    # entrypoint; the production image runs the `hydraflow` console script
    # (entry point `server:main` per pyproject.toml) instead.
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

This requires a new method on the existing `MockWorld` class (added in PR A): `apply_seed(seed: MockWorldSeed) -> None` that populates the wired Fakes (`FakeGitHub`, `FakeIssueFetcher`, `FakeIssueStore`, `FakeLLM`) from a seed object. This is a thin convenience wrapper over the existing `add_issue` / `add_pr` / `set_phase_result` fluent API — not a refactor of `_wire_targets`, which stays as-is.

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
    mock_world.apply_seed(seed)   # NEW method, added in PR A
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

**Cycle semantics:** `cycles_to_run` is the number of times `_do_work()` fires on each enabled loop. `MockWorld.run_with_loops` already mocks the inter-cycle sleep, so wall-clock time is bounded by `cycles_to_run × max(loop body duration)` rather than by `cycles_to_run × tick_interval_seconds`. Sandbox tier inherits the same semantics: the container's loops tick at their configured intervals, and `cycles_to_run` becomes a wait budget rather than a fixed-cycle execution.

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

**PR A — Fake relocation + DI plumbing + sandbox entrypoint (foundation)**
- **Move existing Fakes:** `tests/scenarios/fakes/` → `src/mockworld/fakes/` (12 files + 2 conformance tests). See Component 2 move-table for per-file disposition.
- **Create new Fakes:** `FakeIssueFetcher` and `FakeIssueStore` (extracted from `mock_world.py`'s `_wire_targets` monkeypatching into standalone classes); add `from_seed()` classmethods to `FakeGitHub`, `FakeIssueFetcher`, `FakeIssueStore`; add `build_fake_runner_set(seed)` factory in `fake_llm.py`.
- **Widen Port typing on production surfaces:** `ServiceRegistry.{prs, workspaces, store}` from concrete adapter types to Port protocols (`PRPort`, `WorkspacePort`, `IssueStorePort`). Same widening on `RouteContext.pr_manager`, `create_router(pr_manager=)`, and `pr_manager_for() -> PRPort`. Fix any leaky-abstraction call sites that surface as pyright errors.
- **Add `PRPort.list_prs_by_label(label: str) -> list[PRInfo]`** — a new method on the Port required by Component 10's `SandboxFailureFixerLoop` and by the new `/api/sandbox-hitl` endpoint. Implement on the real `PRManager` (delegates to `gh pr list --label <label>`) and on `FakeGitHub` (filters in-memory PRs by label). The Port-↔-Fake conformance test enforces both implementations stay aligned. This is added in PR A (not PR C) because moving Fakes to `src/mockworld/fakes/` triggers the conformance test on the same commit; deferring would leave the relocation broken.
- **Refactor `build_services()`** to accept optional `prs`/`workspaces`/`store`/`fetcher`/`runners` keyword arguments. Defaults preserve current behavior. Add `RunnerSet` dataclass bundling `triage`/`planners`/`agents`/`reviewers`.
- **Refactor `HydraFlowOrchestrator.__init__`** to accept optional `services: ServiceRegistry | None = None`; when provided, skip the internal `build_services()` call. Production callers pass nothing.
- **Add `src/mockworld/seed.py`** containing `MockWorldSeed` dataclass + `from_json` / `to_json` serialization.
- **Add `src/mockworld/sandbox_main.py`** — the new entrypoint that loads a seed, constructs Fakes, calls `build_services()` and `HydraFlowOrchestrator` with overrides, and starts the dashboard.
- **Add `MockWorld.apply_seed(seed: MockWorldSeed)`** convenience method on the existing in-process MockWorld harness — required by the parity test. Thin wrapper over the existing `add_issue` / `add_pr` / `set_phase_result` API.
- **Add dashboard duck-typed banner:** `/api/state` reports `mockworld_active = getattr(prs, "_is_fake_adapter", False)`. React shell renders persistent top bar when true. Add `_is_fake_adapter = True` class attribute to `FakeGitHub`, `FakeIssueFetcher`, `FakeIssueStore`, `FakeWorkspaceManager`, and the four FakeLLM-backed runners. (The dashboard reads from `prs` only — the other markers are belt-and-suspenders for future debugging.)
- **Add 1 trivial sandbox scenario (`s00_smoke`)** that runs in-process via parity test only — proves the wiring works without requiring docker-compose yet.
- **Update wiki:** `docs/wiki/dark-factory.md` adds a §7 noting MockWorld is permanently-loaded core infrastructure, selected at entrypoint time, not a test-only fixture.
- **Risk:** medium. Production runtime behavior is unchanged (new kwargs default to behavior-preserving values). The Port-typing widening removes a leaky abstraction but may surface real call sites that depended on concrete-type methods — those are fix-at-call-site changes that may cascade in unexpected directions. Mitigation: type-check first (`make typecheck`), absorb cascade fixes into PR A.
- **Estimated PR size:** ~900 LOC including tests (revised upward from initial ~700 to account for the type-widening cascade and orchestrator refactor).

**PR B — Docker compose stack + harness CLI (the new tier)**
- Add `docker-compose.sandbox.yml`.
- Add `src/ui/Dockerfile.ui` + `src/ui/nginx.sandbox.conf`.
- Add `scripts/sandbox_scenario.py` (run, run-all, status, down, shell, seed subcommands).
- Add Makefile targets (`sandbox-up`, `sandbox-down`, `sandbox-test`, `sandbox-shell`).
- Add `tests/sandbox_scenarios/runner/conftest.py` (Playwright + SandboxAPIClient fixtures).
- Add `tests/sandbox_scenarios/runner/test_scenarios.py` (single parametrized test that runs each scenario's `assert_outcome`).
- Implement `s01_happy_single_issue` end-to-end (proves the harness actually works against a real stack).
- **Add a new `sandbox` job to `.github/workflows/ci.yml`** (greenfield — no existing "Browser Scenarios" job to promote; the `scenario_browser` pytest mark exists but no CI job uses it). The new job runs `sandbox_scenario.py run s01_happy_single_issue` with path-triggers on `src/service_registry.py`, `src/orchestrator.py`, `src/mockworld/`, `Dockerfile*`, `docker-compose*`, or `tests/sandbox_scenarios/`. Provisions Docker daemon (already available on `ubuntu-latest`), uploads `/tmp/sandbox-results/` artifacts on failure with 7-day retention.
- Add ADR-0052 ("Sandbox-tier scenario testing") capturing the architecture and tier responsibilities.
- **Risk:** medium. New compose stack, network policy, CI infrastructure. Mitigation: gated to relevant PRs only (path-trigger).
- **Estimated PR size:** ~900 LOC (revised upward to account for full CI job greenfield instead of "promote existing").

**PR C — Catalog completion + full CI integration + self-fix loop (the dozen + automation)**
- Add `s02` through `s12`, one per task. Each task includes the scenario module, the parity test (auto-discovered via `pytest.mark.parametrize`), and the seed JSON regeneration.
- Expand the `sandbox` CI job per Component 10: PR-into-staging fast-subset trigger, promotion-PR (`rc/*`) full-suite trigger, nightly schedule. Add CI workflow logic that auto-labels failed promotion PRs with `sandbox-fail-auto-fix`.
- **Add `SandboxFailureFixerLoop`** — a new caretaker loop scaffolded via `scripts/scaffold_loop.py` (per the dark-factory infra hardening track) that polls open PRs labeled `sandbox-fail-auto-fix`, dispatches `AutoAgentRunner` with the new `prompts/auto_agent/sandbox_fix.md` prompt envelope, applies the proposed fix to the rc/* branch, and tracks per-PR attempt counts in `StateData.sandbox_autofix_attempts`. Cap at 3 attempts; on cap-hit, swap labels (`sandbox-fail-auto-fix` → `sandbox-hitl`).
- **Add `/api/sandbox-hitl` endpoint** in `src/dashboard_routes/_hitl_routes.py` that returns the open PRs labeled `sandbox-hitl` (via `PRPort.list_prs_by_label("sandbox-hitl")` — added in PR A). Add a small Frontend extension to the System tab's HITL panel to read both `/api/hitl` (existing — issues) and `/api/sandbox-hitl` (new — PRs) and render them in a merged list with a type indicator. Keeping the endpoints separate (rather than contaminating `/api/hitl`'s issue-shaped payload) preserves the existing endpoint's contract.
- Add `tests/sandbox_scenarios/README.md` documenting "how to add a scenario."
- Update `docs/wiki/dark-factory.md` §3 (the convergence-loop section) with sandbox-tier expectations: "substantial features require all 12 sandbox scenarios green before promotion-PR merge to main."
- **Risk:** medium. The catalog (s02–s12) is each independently low-risk and tolerates partial landings. The new caretaker loop is medium-risk because it commits to PR branches and triggers CI — the standard caretaker-loop conventions (kill-switch via `enabled_cb`, attempt cap, never-raises subprocess wrapper from `BaseSubprocessRunner`) provide the safety envelope. Mitigation: ship `SandboxFailureFixerLoop` as kill-switched-OFF by default, enable explicitly via static config + dashboard once one or two real fix-cycles have been observed.
- **Estimated PR size:** ~1900 LOC. Breakdown: ~1400 LOC scenarios + parity tests, ~400 LOC `SandboxFailureFixerLoop` (per typical scaffold-loop output), ~100 LOC CI workflow expansion.

**Why three PRs not one.** PR A is medium-risk because the Port-typing widening may surface unexpected leaky-abstraction call sites that need fixing — but the runtime behavior remains unchanged. PR B is the irreversible "we have a sandbox tier now" decision and ships independently so it gets full review attention. PR C is incremental and tolerates partial landings — each scenario lands on its own merits without affecting the others, and the CI/self-fix wiring lands once the catalog is meaningful enough to gate against.

### Component 10 — CI integration + auto-agent self-fix loop

The sandbox suite earns its "release with confidence" claim by running at three points in the development lifecycle, with a self-fix loop on the highest-confidence gate:

**Trigger 1 — PR → staging (fast feedback, every PR)**
- Runs a curated 3-scenario subset: `s01_happy_single_issue`, `s10_kill_switch_universal`, `s11_credit_exhaustion_suspends_ticking`. These are the fastest scenarios that collectively cover the highest-blast-radius regressions.
- Wall-clock budget: ~90 seconds.
- Path triggers: any change to `src/service_registry.py`, `src/orchestrator.py`, `src/mockworld/`, `Dockerfile*`, `docker-compose*`, `tests/sandbox_scenarios/`, or `src/ui/`.
- On failure: PR cannot merge to `staging` until green. **No auto-fix at this stage** — the PR author is alive in the loop and the failure is informative.
- Rationale: catch obvious breakage at human-attention time without burdening every PR with a 10-minute job.

**Trigger 2 — promotion PR (the promotion gate, full suite + self-fix)**
- Runs the full 12-scenario suite.
- Wall-clock budget: ~10 minutes (12 scenarios × ~30-60s each, parallelized where compose allows).
- Triggered automatically on every promotion PR opened by `StagingPromotionLoop` — i.e., PRs whose base is `main` and whose head matches `rc/*` (the release-candidate branch pattern from ADR-0042's staging workflow). Spec for the trigger condition: `on.pull_request.branches: [main]` plus a workflow-level guard `if: startsWith(github.head_ref, 'rc/')`.
- **On failure: dispatch the auto-agent self-fix loop** (described below).
- On success: ready to promote. The promotion PR can merge.
- Rationale: highest-confidence gate. Production code only crosses this line if every sandbox scenario passed within the last 10 minutes against the exact commit that will be deployed.

**Trigger 3 — Nightly on main (regression detection)**
- Full 12-scenario suite, scheduled run at 03:00 UTC.
- Records per-scenario duration metrics into the dashboard observability layer for slow-creep detection.
- On failure: opens a `hydraflow-find` issue with the failure logs attached. Treated as flake until the same scenario fails 3 nights in a row, then promoted to a real bug ticket.
- Rationale: catches regressions that slip through the gate (e.g., container-runtime drift, dependency updates that require rebuild) and surfaces creeping performance issues.

**Auto-agent self-fix loop (Trigger 2 failures only):**

```
                                    ┌─────────────────────────┐
promotion PR (rc/*) ──→ sandbox CI ─┤ All 12 scenarios green? │
                                    └─────────────────────────┘
                                       │              │
                                      yes             no
                                       │              ▼
                                       │  ┌──────────────────────────┐
                                       │  │ CI auto-labels PR with   │
                                       │  │ `sandbox-fail-auto-fix`, │
                                       │  │ posts log artifact URL   │
                                       │  │ to PR body               │
                                       │  └──────────────────────────┘
                                       │              │
                                       │              ▼
                                       │  ┌──────────────────────────┐
                                       │  │ NEW: SandboxFailureFixer │
                                       │  │ Loop polls PRs by label, │
                                       │  │ enqueues each match      │
                                       │  └──────────────────────────┘
                                       │              │
                                       │              ▼
                                       │  ┌──────────────────────────┐
                                       │  │ Reuses AutoAgentRunner   │
                                       │  │ (the subprocess wrapper  │
                                       │  │ from #8439) with sandbox │
                                       │  │ failure prompt envelope  │
                                       │  └──────────────────────────┘
                                       │              │
                                       │              ▼
                                       │     proposes fix commit
                                       │     on rc/* branch
                                       │              │
                                       │              ▼
                                       │     sandbox CI re-runs
                                       │              │
                                       │   ┌──────────┴──────────┐
                                       │   ▼                     ▼
                                       │  green               still red
                                       │   │                     │
                                       │   │             ┌───────┴───────┐
                                       │   │             ▼               ▼
                                       │   │      attempt < 3?    attempt = 3
                                       │   │             │               │
                                       │   │             ▼               ▼
                                       │   │       loop again      HITL escalation:
                                       │   │                       remove auto-fix label,
                                       │   │                       add `sandbox-hitl`
                                       │   │                       label, surface in
                                       │   │                       System tab HITL queue
                                       ▼   ▼                       with full context
                              promotion PR merges to main
```

**`SandboxFailureFixerLoop` — what's new vs reused:**

The self-fix mechanism is a NEW caretaker loop (per ADR-0029's caretaker pattern), NOT a label-routing tweak on the existing `AutoAgentPreflightLoop`. The existing loop polls `hitl-escalation` *issues* by label — it does not handle PRs, does not commit to PR branches, does not re-trigger CI on PRs. Those are distinct operations. Be honest about the scope:

| Concern | Reused | New (PR C deliverable) |
|---------|--------|------------------------|
| Subprocess invocation of the auto-agent (Claude Code with restricted tools) | `AutoAgentRunner` (PR #8439, post-#8446 refactor onto `BaseSubprocessRunner`) — used as-is | — |
| Prompt envelope structure (system + tool restrictions + escape hatches) | `prompts/auto_agent/_envelope.md` — used as-is | New domain-specific prompt: `prompts/auto_agent/sandbox_fix.md` framing the failed scenario(s) + sandbox logs + live diff |
| Polling for work | — | `SandboxFailureFixerLoop._do_work` polls open PRs labeled `sandbox-fail-auto-fix` via `PRPort.list_prs_by_label("sandbox-fail-auto-fix")`. **`list_prs_by_label` is itself a new method on `PRPort` added in PR A** (see PR A scope) — `PRPort` today exposes `list_issues_by_label` and `find_open_pr_for_branch` but no by-label PR enumeration. Implemented on the real `PRManager` and on `FakeGitHub`. |
| Per-PR attempt cap + state tracking | — | New `StateData.sandbox_autofix_attempts: dict[int, int]` field keyed by PR number; cap at 3 |
| Branch operations (worktree on rc/* branch, commit + push fix, trigger CI) | `WorkspacePort` operations + `PRPort.push_branch` — used as-is | New: `_apply_fix_commit_to_pr_branch(pr_number, diff)` helper that creates a worktree against the rc/* branch, applies the agent's diff, commits, pushes |
| HITL escalation surface | The dashboard's existing System tab HITL queue (rendered from `/api/hitl` for issues — see `src/dashboard_routes/_hitl_routes.py:101`) | New: dedicated `/api/sandbox-hitl` endpoint that returns `sandbox-hitl`-labeled PRs (via `PRPort.list_prs_by_label`). Frontend reads both endpoints and merges in the System tab. Keeping the endpoints separate avoids contaminating `/api/hitl`'s issue-shaped payload with PR-shaped data. |
| Kill-switch convention | `LoopDeps.enabled_cb` callback (a `Callable[[str], bool]` injected at loop construction time by `BGWorkerManager`) + the standard 10-site wiring per the dark-factory infra hardening track | New: `sandbox_failure_fixer` registered at all 10 wiring sites (models.py, state/__init__.py, config.py × 3, service_registry.py × 4, orchestrator.py × 2, ui/src/constants.js × 3, _common.py for `_INTERVAL_BOUNDS`, loop_registrations.py, functional_areas.yml, tests/helpers.py) — generated by `scripts/scaffold_loop.py` from the dark-factory hardening track. |

The scaffold (`scripts/scaffold_loop.py`) emits the 10-site wiring skeleton and a placeholder `_do_work` returning `{"status": "ok"}`. **The `_do_work` body, `_apply_fix_commit_to_pr_branch` helper, the `StateData.sandbox_autofix_attempts` mixin, and the `AutoAgentRunner` invocation are written from scratch on top of the scaffold output** — the scaffold provides the convention-correct skeleton, not the loop's behavior. This is roughly 400 LOC: ~150 LOC scaffold-generated + ~250 LOC manual implementation.

**Self-fix loop bounds:**
- Maximum auto-fix attempts: 3 per promotion PR (tracked in `StateData.sandbox_autofix_attempts`). After 3 unsuccessful attempts: the `sandbox-fail-auto-fix` label is removed, the `sandbox-hitl` label is added, and the PR surfaces in the System tab HITL queue with full failure context (sandbox logs, all attempted fix commits, current state of each scenario).
- Per-attempt wall-clock cap: 30 minutes (auto-agent budget).
- Self-fix opt-out: add the `no-auto-fix` label to the PR. The `SandboxFailureFixerLoop` skips PRs with this label even if `sandbox-fail-auto-fix` is also present. Label-based opt-out reuses existing label-handling infrastructure — no new mechanism. (Earlier draft proposed a `[no-auto-fix]` commit-message trailer; rejected because the loop is label-driven, not commit-message-driven, and adding trailer parsing would be new infrastructure for no clear benefit.)

**Why this works as the dark-factory closure:**
- Trigger 1 catches the obvious; the PR author fixes it themselves.
- Trigger 2 catches the subtle; `SandboxFailureFixerLoop` dispatches the auto-agent to fix it without human attention.
- Trigger 3 catches the slow drift; the wiki's `hydraflow-find` issue surfaces it.
- Production observability is the catch-all for what no test could anticipate.
- **The only point at which a human is required is when the auto-agent has tried 3 times and still failed** — and at that point, the human is looking at a fully-contextualized failure (sandbox logs + 3 fix attempts + parity test diagnosis) rather than a bare CI red.

**Failure modes for the self-fix loop:**
- *Loop oscillation* (auto-fix changes break a different scenario each attempt): bounded by the 3-attempt cap. After cap-hit, the PR carries all attempted commits — the human can pick the best partial fix or revert.
- *Auto-fix succeeds locally but fails in re-run* (flake): the 3-strikes-then-bug pattern from Trigger 3 applies — three flakes on the same scenario become a real bug.
- *Auto-agent dispatches infinite parallel fixes*: prevented by the existing `AutoAgentPreflightLoop` per-issue concurrency cap (one auto-agent in flight per issue/PR).
- *Self-fix changes break unrelated PR-into-staging tests*: by definition, Trigger 1 already passed. If a Trigger-2 fix breaks Trigger 1, the auto-agent's commit fails Trigger 1 on the next push and is reverted before merge.

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

- `src/service_registry.py:103–189` (`ServiceRegistry`), `:209+` (`build_services()`) — primary refactor target. Gains optional adapter-override kwargs and Port-typed fields in PR A.
- `src/orchestrator.py:85–141` (`HydraFlowOrchestrator.__init__`) — refactor target. Gains optional `services: ServiceRegistry | None` kwarg in PR A.
- `src/dashboard_routes/_routes.py:309–310` (`RouteContext.pr_manager`), `:456` (`pr_manager_for()`), `:585` (`create_router(pr_manager=...)`) — Port-typing widening sites in PR A.
- `tests/scenarios/fakes/` — current home of Fakes, moved to `src/mockworld/fakes/` in PR A.
- `tests/scenarios/fakes/test_port_signature_conformance.py` — load-bearing conformance test, moved to `tests/test_mockworld_fakes_conformance.py` alongside the Fakes.
- `tests/scenarios/mock_world.py:643–755` — existing in-process dashboard boot, demonstrates the dashboard can be driven from tests today.
- `src/server.py` (`main`, `_run_with_dashboard`, `_run_headless`) — the production entrypoint (`hydraflow` console script per `pyproject.toml:30–31`); reference for what `mockworld.sandbox_main` mirrors structurally.
- `Dockerfile.agent`, `Dockerfile.agent-base` — reused as the container base for the `hydraflow` service in compose.
- `pyproject.toml:168` — declares the `scenario_browser` pytest mark; the new `sandbox` CI job in PR B uses this mark to scope test collection.
- `pyproject.toml` — already declares `pytest-playwright>=0.5.0`; no new dep needed for browser automation.
- `.github/workflows/ci.yml` — primary CI workflow. PR B adds a new `sandbox` job here (no existing "Browser Scenarios" job to promote — the CI surface for sandbox is greenfield).
- `src/preflight/auto_agent_runner.py` (the `AutoAgentRunner` post-#8446 refactor onto `BaseSubprocessRunner`) — reused as the subprocess wrapper for the new `SandboxFailureFixerLoop` in PR C. The loop itself is new; the runner is reused as-is.
- `src/preflight/auto_agent_preflight_loop.py` (the existing `AutoAgentPreflightLoop` from #8431/#8439) — referenced as the structural template for the new `SandboxFailureFixerLoop` (same caretaker pattern, different polling target: PRs by label vs issues by label).
- `src/staging_promotion_loop.py` (per ADR-0042) — the `StagingPromotionLoop` produces `rc/*` promotion PRs that Trigger 2 fires on. The trigger condition matches against `head_ref` startswith `rc/`.
- `scripts/scaffold_loop.py` (from PR #8448) — used to scaffold the 10-site wiring + skeleton for `SandboxFailureFixerLoop` in PR C; the `_do_work` body and helpers are written manually on top of the scaffolded skeleton.
- `src/dashboard_routes/_hitl_routes.py:101` (existing `/api/hitl` endpoint, returns issues filtered by `hitl_label`/`hitl_active_label`) — referenced as the structural template for the new `/api/sandbox-hitl` endpoint added in PR C.

## Explicitly rejected: a `mockworld_enabled` config switch

An earlier draft of this spec proposed adding `mockworld_enabled: bool` to `HydraFlowConfig`, threaded through `_ENV_BOOL_OVERRIDES`, with `build_services()` branching on it. **This design was rejected** because:

1. The system already has 30+ env-toggleable booleans and the maintenance burden of each is non-trivial: documentation, tests for both branches, defaults, dashboard surfacing, cross-references in operator runbooks. Adding another for a structural choice that should be made at process-boundary (not config) level worsens that burden.
2. A flag creates the possibility — however small — of accidental enablement in production. The entrypoint-selection design makes that structurally impossible.
3. A flag implies "MockWorld is a mode you turn on." MockWorld is not a mode; it is a permanent set of alternative adapters, always loaded, selected by which entrypoint ran (the `hydraflow` console script vs `python -m mockworld.sandbox_main`).
4. The flag-based design produces a `if config.mockworld_enabled:` branch in production code paths. The injection-based design produces no production-code branching at all — the Fakes are simply parameters that production never passes.

If a future use case demands runtime switching (e.g., "flip to MockWorld for the next 10 minutes for a demo without restarting"), revisit this decision then. Until that exists, "different entrypoint" is the right granularity.
