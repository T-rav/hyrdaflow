# HydraFlow Standard — Test Pyramid

Every load-bearing feature in HydraFlow ships through three layers of tests
before it merges into `staging`. Skipping a layer is a procedural failure —
not a judgment call. This standard exists because skipping layers (which I
just did with rebase-on-conflict, PR #8482) ships features that pass unit
tests but break under real conditions.

## The three layers

```
                    ┌────────────────────────┐
                    │  Sandbox e2e (~minutes) │   tests/sandbox_scenarios/
                    │  docker-compose +      │   sNN_*.py + Playwright
                    │  Playwright            │
                    └────────┬───────────────┘
                             │
                  ┌──────────┴──────────────┐
                  │  MockWorld scenario     │   tests/scenarios/
                  │  (~seconds)             │   test_*_scenario.py
                  │  real loops + Fake*     │   uses MockWorld + FakeGitHub
                  │  adapters at boundary   │
                  └──────────┬──────────────┘
                             │
              ┌──────────────┴──────────────┐
              │  Unit (~milliseconds)        │  tests/test_*.py
              │  pure functions, mocks at   │  AsyncMock collaborators,
              │  every collaborator         │  monkeypatch run_subprocess
              └─────────────────────────────┘
```

| Layer | Where | What it proves | Mocks at |
|---|---|---|---|
| **Unit** | `tests/test_*.py` | Code paths and edge cases of one function/class | All collaborators |
| **MockWorld scenario** | `tests/scenarios/test_*_scenario.py` (mark `pytest.mark.scenario_loops`) | Real loop / runner code interacts with `MockWorld`'s `Fake*` adapters at the I/O boundary. Catches integration bugs unit tests can't see. | Subprocess / network boundary only |
| **Sandbox e2e** | `tests/sandbox_scenarios/scenarios/sNN_*.py` + `tests/sandbox_scenarios/runner/` | The real orchestrator boots inside `docker-compose.sandbox.yml`, Playwright drives the UI, the dashboard API verifies state. The dark-factory production bar. | Only at the docker-compose seam (FakeLLM, FakeGitHub via the sandbox entrypoint) |

## When each layer is required

A feature merges into `staging` when ALL three layers exist for it. Specifically:

| Feature shape | Unit | Scenario | Sandbox |
|---|---|---|---|
| New port method (e.g. `update_pr_branch`) | ✅ required | ✅ required (via the loop that calls it, using a real PRManager + FakeGitHub at the boundary) | ✅ required (drive the loop end-to-end in docker) |
| New loop or runner | ✅ required | ✅ required (Pattern B direct instantiation OR full MockWorld flow) | ✅ required (sNN scenario) |
| New phase decoration / cross-cutting concern (OTel, telemetry) | ✅ required | ✅ required (assert against `world.honeycomb` / equivalent fake) | ⚠️ recommended (skip only if the cross-cut has no observable runtime effect) |
| Pure refactor with no behavior change | ✅ required | (existing scenario coverage stays green) | (no new sandbox needed) |
| Bug fix | ✅ required (regression test in `tests/regressions/`) | ✅ required if the bug is observable through a loop / runner path | ⚠️ if the bug only manifests under sandbox conditions |
| New ADR / wiki / config | ❌ no test (docs) | ❌ | ❌ |

## How to write each layer

### Unit tests
- Live in `tests/test_<module>.py`
- One assertion per test; AAA structure (Arrange / Act / Assert) but **no AAA comments** (the test-sludge guard rejects them — see `docs/wiki/testing.md`)
- Mock every collaborator: AsyncMock for async, monkeypatch for `run_subprocess` / module-level state
- Use `tests.helpers.ConfigFactory.create()` for `HydraFlowConfig`
- Use `tests.helpers.make_pr_manager(config=, event_bus=)` for a real `PRManager` with mocked I/O

### MockWorld scenario tests
- Live in `tests/scenarios/test_<feature>_scenario.py`
- Mark with `pytestmark = pytest.mark.scenario_loops`
- **Two patterns:**
  - **Pattern A (full MockWorld):** import `MockWorld`, set up via builder methods (`add_repo`, `add_issue`, `set_phase_result`, `fail_service`), drive a phase or loop tick, assert against `world.<fake>`. Use this when the test exercises orchestration + multiple ports.
  - **Pattern B (direct instantiation):** build the loop directly with `LoopDeps` + a `MagicMock(spec=PRPort)` whose methods are scripted. Use this when the test exercises a single loop's reaction to specific port outcomes (e.g. `prs.merge_promotion_pr` returns False → loop files find-issue). Existing example: `tests/scenarios/test_caretaker_loops_part2.py::TestL22StagingPromotionLoop`.
- The choice is governed by what's being asserted. Pattern A asserts cross-cutting outcomes ("after the phase ran, the dashboard reflects X"). Pattern B asserts a loop's reaction surface ("when the port returns Y, the loop does Z").

### Sandbox e2e scenarios
- Live in `tests/sandbox_scenarios/scenarios/sNN_<feature>.py`
- Each scenario file exports `NAME`, `DESCRIPTION`, `seed() -> MockWorldSeed`, `async def assert_outcome(api, page) -> None`
- Run via `python scripts/sandbox_scenario.py run <NAME>` inside the docker stack (CI path: `Sandbox (PR→staging fast subset)` / `Sandbox (rc/* promotion PR full suite)` / `Sandbox (nightly regression)`)
- The `assert_outcome` body uses the dashboard API (`api.get("/api/state")`) and Playwright (`page.click(...)`) to verify production-shaped behavior
- **Scenarios must `import pytest` only inside function bodies** — the runner imports the module top-level in an environment without pytest as a runtime dep (see s10/s11 placeholder pattern, fixed in PR #8482)

## Anti-patterns

- **"My feature is too small to need scenario / sandbox tests."** This is the rationalisation that ships rebase-on-conflict-style bugs. If the feature has any observable runtime path through a loop or the orchestrator, both layers apply. Real-API behavior (e.g. GitHub's update-branch endpoint) is invisible to unit tests.

- **Asserting against state shapes that don't exist.** s10 / s11 (tracked in #8483) demonstrated this — scenarios authored against `state["worker_health"]["...]["tick_count"]` and `state["credits_paused"]` which have never existed in `StateData`. Always grep `src/models.py` for the field name before asserting on it.

- **Importing pytest at module level in sandbox scenarios.** The sandbox runner doesn't have pytest available; module-level `import pytest` crashes the import. Use `pytest.skip` only inside `assert_outcome` — and only after `import pytest` is also done lazily inside that function.

- **Scenario tests that just unit-test through a fake.** Pattern B is fine when the loop's reaction surface is what matters — but if the test could equivalently be written as a unit test of one method, it's not really a scenario test.

## Discoverability

This standard lives at three load-bearing surfaces:

- This document — the canonical reference
- [`docs/wiki/testing.md`](../../wiki/testing.md) — operator wiki entry pointing here
- `CLAUDE.md` Quick Rules — one-line directive that all features ship with the full pyramid

Drift detection: a future audit (extension of `principles_audit_loop`) should check that every PR landing on `staging` adds at least one test in `tests/test_*.py`, one in `tests/scenarios/test_*.py`, and one in `tests/sandbox_scenarios/scenarios/sNN_*.py` — exempting docs-only and pure-refactor PRs.

## Discovered through failure

This standard exists because PR #8482 (rebase-on-conflict) shipped with only unit tests and was caught by the user with the question "did you test it all?" — to which the honest answer was no. The MockWorld + sandbox layers were added in a follow-up. Don't repeat that pattern.
