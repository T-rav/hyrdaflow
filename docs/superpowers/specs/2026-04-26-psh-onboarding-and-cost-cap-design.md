# PSH Onboarding + Daily Cost Cap — Design Spec

**Status:** Approved (2026-04-26)
**Goal:** Onboard `T-rav/poop-scoop-hero` (a Phaser.js game) as a first foreign managed repo so HydraFlow's existing fleet-level caretaker loops audit + maintain it. Add a global daily cost-cap kill-switch defaulting to **unlimited**, providing a runaway-cost circuit breaker for both HydraFlow-self and any future managed repos.

## 1. Context

PR #8449 surfaced the dark-factory roadmap question: *"can HydraFlow operate against a foreign repo, and how do we cap cost?"* Per the multi-repo research, the answer is mostly **already shipped**:

- `RepoRuntime` + `RepoRuntimeRegistry` (`src/repo_runtime.py`) — in-process per-repo runtime data model
- `RepoRegistryStore` (`src/repo_store.py`) persists `data_root/repos.json`
- `/api/repos/add`, `/api/repos`, `/api/runtimes/*` dashboard endpoints — wired and working
- `ManagedRepo` config dataclass (`config.py:65`)
- `HYDRAFLOW_MANAGED_REPOS` env var for declarative override (`config.py:3029`)
- `PrinciplesAuditLoop`, `WikiRotDetectorLoop`, `RepoWikiLoop` — the three fleet-level loops that already iterate `managed_repos`
- `cost_budget_alerts.py` — daily / per-issue ALERT infrastructure (no kill-switch yet)
- `daily_cost_budget_usd: float | None` config field at `config.py:923`

This spec uses what's there. The deltas are small.

## 2. What's NOT in scope (deliberate deferrals)

- **Subprocess-per-repo per ADR-0009.** The `supervisor_service.py` code lives in a worktree snapshot, not in main. The in-process `RepoRuntime` path is the working path today, has test coverage in `test_repo_runtime.py`, and is sufficient for PSH. Re-landing the supervisor is a separate ADR-0009 closeout.
- **Closing ADR-0038's `_run_with_dashboard` unification.** Cosmetic — the registry is already wired; the gap is that the primary repo's `EventBus`/`StateTracker` still constructed bare instead of via `RepoRuntime.create()`. Defer.
- **`ManagedRepoIterator` helper.** The 3 existing fan-out loops use a copy-pasted `for mr in managed_repos: try/except continue` pattern. Refactoring it into a shared helper is polish; defer until a 4th fan-out loop appears.
- **Per-repo or per-loop cost budgets.** A single global cap is the MVP. Per-dimension caps (e.g., "PSH gets $5/day, HF-self gets $20/day") wait until we have signal on which dimension matters.
- **Cleaning up `cost_budget_alerts.py` overlap.** That module does alerts (issue-creation); we add a kill-switch path. They coexist for now.
- **Subprocess-per-repo for PSH specifically.** PSH runs as an in-process `RepoRuntime` inside the main HydraFlow process. Acceptable at 2 repos; revisit if we onboard a 3rd or 4th.

## 3. Architecture

### 3.1 PSH onboarding (no new code, just configuration + invocation)

Three steps to onboard PSH:

1. **Register PSH path in the runtime registry** via `POST /api/repos/add` with body `{"path": "/Users/travisf/Documents/projects/poop-scoop-hero"}`. The endpoint:
   - Validates it's a git repo
   - Detects slug from `origin` remote (→ `T-rav/poop-scoop-hero`)
   - Calls `register_repo_cb(config)` → `RepoRuntimeRegistry.register()` + `RepoRegistryStore.upsert()`
   - Calls `ensure_labels(config)` → creates `hydraflow-ready`, `hydraflow-implement`, etc. labels on PSH

2. **Add PSH to `HYDRAFLOW_MANAGED_REPOS` env var:**
   ```bash
   HYDRAFLOW_MANAGED_REPOS='[{"slug": "T-rav/poop-scoop-hero", "main_branch": "main", "labels_namespace": "hydraflow"}]'
   ```
   This populates `config.managed_repos`. `PrinciplesAuditLoop` reads this list and runs onboarding (P1–P5 audit) on next tick (default cadence: weekly).

3. **(Optional) Start a `RepoRuntime` for PSH** via `POST /api/runtimes/{slug}/start`. PSH's runtime runs the full orchestrator-style five-loop set (triage/plan/implement/review/HITL) in-process. **Disabled by default** — operator opts in only after the principles audit gives PSH a `ready` onboarding status.

The CLI sugar (item 1 below) is a thin wrapper around step 1.

### 3.2 Cost budget kill-switch

A new `CostBudgetWatcherLoop` (caretaker, 5-minute tick):

```
async def _do_work(self) -> WorkCycleResult:
    if os.environ.get("HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER") == "1":
        return {"skipped": "kill_switch"}
    cap = self._config.daily_cost_budget_usd
    if cap is None:
        return {"cap": None, "action": "unlimited"}

    rolling = await asyncio.to_thread(build_rolling_24h, self._config)
    total = float(rolling.get("total", {}).get("cost_usd", 0.0))

    if total > cap:
        await self._disable_all_caretaker_loops()
        return {"cap": cap, "total": total, "action": "killed"}

    if self._previously_killed():
        await self._reenable_all_caretaker_loops()
        return {"cap": cap, "total": total, "action": "reenabled"}

    return {"cap": cap, "total": total, "action": "ok"}
```

Mechanics:
- Reads existing `cost_rollups.build_rolling_24h(config)` (already shipped in PR #8447) for total spend
- When over cap → calls `BGWorkerManager.set_enabled(name, False)` for every loop in `_TARGET_WORKERS` that is currently enabled (a curated list — pricing_refresh, dependabot_merge, security_patch, ci_monitor, principles_audit, etc. The watcher itself is NOT in the list — it must keep running to detect recovery). Operator-pre-disabled workers are skipped at kill time (`is_enabled(name)` is False) so the watcher never claims authorship of them.
- When the 24h rolling sliding window drops back below cap (typically as old high-cost inferences age out, often around UTC midnight if the spike was concentrated late in a day) → calls `set_enabled(name, True)` for the worker set the watcher previously killed.
- "Watcher's killed set" tracked via state — `state.cost_budget_killed_workers: list[str]` (sorted set of worker names). Empty when no prior kill; populated on kill; cleared to empty on recovery.
- Files a `hydraflow-find` issue with `[cost-budget] daily cap exceeded` title-prefix dedup on first kill of a given calendar day. Issue auto-closes when watcher detects recovery (uses existing `pr_manager.close_issue` if exists, else just leaves a comment).

Default: `daily_cost_budget_usd = None` (already config default). With None, watcher is a no-op every tick — observability only via the `{"action": "unlimited"}` event payload.

### 3.3 CLI command — DEFERRED

The original plan included a `hf repos add <path>` CLI wrapper. Dropped from scope on plan-write: there's no `hf_cli` package in current main and building one is significant scope creep. Operators onboard PSH by calling the dashboard's `POST /api/repos/add` endpoint via the UI or `curl`:

```bash
curl -X POST http://localhost:8080/api/repos/add \
  -H 'Content-Type: application/json' \
  -d '{"path":"/Users/travisf/Documents/projects/poop-scoop-hero"}'
```

Wiki addition documents the curl command. Add a CLI in a follow-up PR if it becomes annoying.

## 4. Failure modes + handling

| Mode | Action |
|---|---|
| `daily_cost_budget_usd = None` (default) | Watcher tick is a no-op; emits `{"action": "unlimited"}` for telemetry; never kills anything |
| Rolling-24h cost compute raises | Log + retry next tick; do NOT kill loops on an unknown cost state |
| Cap breached, kill executes mid-tick | Other loops finish their current tick, then are gated on next tick by `enabled_cb` |
| Recovery (rolling drops back below cap) | Re-enable workers in `state.cost_budget_killed_workers`; reset that set to empty; comment on the dedup'd issue |
| Operator manually disables loops while watcher is in killed-state | Respect operator state — when watcher tries to re-enable, it only re-enables loops it killed (track in state which loops were killed by the watcher) |
| Dashboard unreachable when CLI runs | CLI prints clear error, suggests `--dashboard-port` flag |
| `register_repo_cb` fails (e.g., duplicate slug) | Endpoint returns 409 with detail; CLI surfaces it; PSH state unchanged |

## 5. Multi-repo isolation guarantees

The existing `RepoRuntime` + `RepoRegistryStore` provide:
- `RepoRuntime.state` is a separate `StateTracker` per repo
- `RepoRuntime.event_bus` is a separate `EventBus` per repo (with `.set_repo()` already injecting the slug into events)
- Worktree paths via `WorktreeManager` are slug-scoped (`~/.hydraflow/worktrees/<slug-with-dashes>/issue-N/`)
- `data_root/<slug>/state.json` per-repo
- GitHub `gh` CLI calls take an explicit `--repo <slug>` parameter when the per-runtime `PRPort` is constructed (each `RepoRuntime` builds its own `PRManager(config)` with `config.repo` set to the runtime's slug)

**Caveat:** the three fleet-level loops (`PrinciplesAuditLoop`, `WikiRotDetectorLoop`, `RepoWikiLoop`) currently iterate `managed_repos` from the **primary** runtime and call `gh` with explicit `--repo` flags. They share the primary runtime's PRPort instance. This is fine — they're explicitly cross-repo by design — but it means `state.cost_budget_killed_workers` is recorded against the primary runtime, not per-runtime. Acceptable for v1.

This is sufficient isolation to onboard PSH without any new isolation code.

## 6. Testing strategy

### Unit tests

- `tests/test_cost_budget_watcher_scenario.py` — `_do_work` directly with mocked `build_rolling_24h`:
  - `test_unlimited_when_cap_is_none`
  - `test_under_cap_returns_ok`
  - `test_over_cap_disables_all_target_loops`
  - `test_recovery_reenables_loops_killed_by_watcher`
  - `test_recovery_does_not_reenable_operator_disabled_loops`
  - `test_dedup_issue_when_cap_breached_twice_same_day`
  - `test_kill_switch_short_circuits`

### Integration tests

- `tests/test_state.py` (or whichever existing state test file covers `WorkerStateMixin`) — append 3 unit tests for `get_cost_budget_killed_workers` / `set_cost_budget_killed_workers` (defaults empty, round-trips, clearable).

### Multi-repo registry coverage — already exists

Note: ADR-0038 originally flagged "multi-repo registry has no integration test." Pass #2 review surfaced that `tests/test_repo_runtime.py::TestRepoRuntimeRegistry::test_two_runtimes_isolated` (lines 269–298) already provides this coverage. No new integration tests needed; the gap was closed before this PR.

### MockWorld scenario — DEFERRED

Originally specced. Pass #2 review found `MockWorld` doesn't expose a config attribute the test can mutate to set `daily_cost_budget_usd`. Plumbing this through `_seed_ports` is bigger architectural work than the scenarios warrant. Task 1's 8 unit tests cover the same logic. Catalog wiring is tested by Task 7 regression test.


## 7. Files to create / modify

**Create:**
- `src/cost_budget_watcher_loop.py` — `CostBudgetWatcherLoop(BaseBackgroundLoop)` (with lazy `build_rolling_24h` wrapper to avoid circular import per `report_issue_loop.py:43-60` precedent)
- `tests/test_cost_budget_watcher_scenario.py` — 8 unit tests

(No fixture file needed — tests mock `build_rolling_24h` directly. Multi-repo registry coverage already exists at `tests/test_repo_runtime.py:269`. MockWorld scenarios deferred per §6.)

**Modify (eight-checkpoint wiring for the new loop):**
- `src/service_registry.py` — import + dataclass field + factory
- `src/orchestrator.py` — `bg_loop_registry` + `loop_factories`
- `src/dashboard_routes/_common.py` — `_INTERVAL_BOUNDS["cost_budget_watcher"]`
- `src/dashboard_routes/_control_routes.py` — `_bg_worker_defs` + `_INTERVAL_WORKERS`
- `src/ui/src/constants.js` — `EDITABLE_INTERVAL_WORKERS`, `SYSTEM_WORKER_INTERVALS`, `BACKGROUND_WORKERS`
- `src/bg_worker_manager.py` — `defaults` dict entry
- `tests/orchestrator_integration_utils.py` — `services.cost_budget_watcher_loop = FakeBackgroundLoop()`
- `tests/scenarios/catalog/loop_registrations.py` — `_build_cost_budget_watcher_loop` + `_BUILDERS` entry
- `tests/test_bg_worker_status.py` — bump worker count from 22 → 23

**Modify (functional area + arch regen):**
- `docs/arch/functional_areas.yml` — `CostBudgetWatcherLoop` under `caretaking`
- `docs/arch/generated/*` — re-emitted via `python -m arch.runner --emit`

**Modify (wiki + methodology):**
- `docs/wiki/architecture.md` — entry for the cost-cap pattern
- `docs/wiki/dark-factory.md` — note PSH as the first foreign managed repo + the in-process `RepoRuntime` workaround for ADR-0009 not yet landing

## 8. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Re-enable loop mistakenly re-enables operator-disabled loops | Medium | Track per-loop state — only re-enable loops the watcher itself killed |
| Cap=None watcher tick consumes resources | Negligible | The no-op path is `if cap is None: return` — single dict construction |
| `build_rolling_24h` slow at 100k+ inferences | Low (pre-existing) | Watcher uses `asyncio.to_thread`, doesn't block event loop |
| Onboarding PSH triggers `PrinciplesAuditLoop` to file 50 issues | Low | Audit is per-design; PSH starts with `pending` onboarding status; user reviews before flipping to `ready` |
| `gh` CLI lacks scope for PSH | Low | If user has cloned PSH via gh auth, scope is already there. Verify before merge. |
| In-process `RepoRuntime` shares Python memory with HF-self → memory leak in PSH affects HF | Medium | Acceptable for 2 repos; revisit at 3+ |

## 9. Definition of done

- `make quality` passes
- PSH appears in `/api/runtimes` and `/api/repos` after running `hf repos add ../poop-scoop-hero`
- `HYDRAFLOW_MANAGED_REPOS` includes PSH; `PrinciplesAuditLoop` audits it on next tick
- Setting `HYDRAFLOW_DAILY_COST_BUDGET_USD=10` and racking up >$10 in 24h disables all caretaker loops; reverts when rolling-24h drops below 10
- New tests cover: budget watcher unit + MockWorld + multi-repo integration
- Wiki entry for the cost-cap pattern + PSH onboarding entry in dark-factory.md

## 10. References

- ADR-0009 — Multi-repo process-per-repo model (Accepted, but supervisor not yet on main)
- ADR-0038 — Multi-repo architecture wiring pattern (Proposed)
- ADR-0029 — Caretaker loop pattern
- ADR-0049 — Kill-switch convention
- PR #8447 — `cost_rollups.build_rolling_24h` shipped here
- PR #8449 — PricingRefreshLoop (precedent for "loop opens PR on drift")
- `docs/wiki/architecture.md` § "Eight-Checkpoint Loop Wiring"
- `docs/methodology/self-documenting-architecture.md` § anti-pattern #10
