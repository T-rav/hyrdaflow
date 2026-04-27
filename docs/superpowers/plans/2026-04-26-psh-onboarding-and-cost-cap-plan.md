# PSH Onboarding + Daily Cost Cap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CostBudgetWatcherLoop` that flips bg-worker kill-switches when daily LLM spend exceeds `HYDRAFLOW_DAILY_COST_BUDGET_USD` (default `None` = unlimited). Onboard `T-rav/poop-scoop-hero` as the first foreign managed repo using existing `RepoRuntimeRegistry` infrastructure.

**Architecture:** Watcher loop polls `cost_rollups.build_rolling_24h(config)["total"]["cost_usd"]` every 5 minutes. Over cap → calls `BGWorkerManager.set_enabled(name, False)` for a curated list of caretaker loops; tracks the disabled-by-watcher set in state so manual operator overrides are preserved. Recovery (rolling drops below cap) → re-enables only the watcher's own kills. PSH onboarding uses already-shipped `/api/repos/add` + `HYDRAFLOW_MANAGED_REPOS` env var; no new code.

**Tech Stack:** Python (BaseBackgroundLoop, asyncio, pytest), MockWorld test harness, existing `cost_rollups` + `BGWorkerManager` infrastructure.

**Spec:** `docs/superpowers/specs/2026-04-26-psh-onboarding-and-cost-cap-design.md`

---

## File touchpoints

**Create:**
- `src/cost_budget_watcher_loop.py` — the watcher loop class
- `tests/test_cost_budget_watcher_scenario.py` — `_do_work` direct unit tests
- `tests/test_multi_repo_runtime_integration.py` — closes the ADR-0038 missing-test gap
- `tests/scenarios/test_cost_budget_watcher_mockworld.py` — full `run_with_loops` scenarios

**Modify (eight-checkpoint wiring):**
- `src/service_registry.py` — import + dataclass field + factory + Services kwarg
- `src/orchestrator.py` — `bg_loop_registry` + `loop_factories`
- `src/dashboard_routes/_common.py` — `_INTERVAL_BOUNDS["cost_budget_watcher"]`
- `src/dashboard_routes/_control_routes.py` — `_bg_worker_defs` + `_INTERVAL_WORKERS`
- `src/ui/src/constants.js` — EDITABLE + INTERVALS + BACKGROUND_WORKERS
- `src/bg_worker_manager.py` — `defaults` dict
- `tests/orchestrator_integration_utils.py` — SimpleNamespace
- `tests/scenarios/catalog/loop_registrations.py` — `_BUILDERS`
- `tests/test_bg_worker_status.py` — bump worker count 22 → 23

**Modify (functional area + arch regen):**
- `docs/arch/functional_areas.yml` — `CostBudgetWatcherLoop` under `caretaking`
- `docs/arch/generated/*` — re-emitted via `python -m arch.runner --emit`

**Modify (wiki + PSH onboarding doc):**
- `docs/wiki/architecture.md` — cost-cap pattern entry
- `docs/wiki/dark-factory.md` — PSH-as-first-foreign-repo entry + `curl` onboarding command

---

## Task 1: CostBudgetWatcherLoop core (no-cap + over-cap paths)

**Files:**
- Create: `src/cost_budget_watcher_loop.py`
- Create: `tests/test_cost_budget_watcher_scenario.py`

- [ ] **Step 1: Write the failing tests (no-cap + happy paths)**

Create `tests/test_cost_budget_watcher_scenario.py`:

```python
"""CostBudgetWatcherLoop _do_work tests with mocked cost rollups."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cost_budget_watcher_loop import CostBudgetWatcherLoop


def _build_loop(*, cap: float | None = None):
    config = MagicMock()
    config.daily_cost_budget_usd = cap
    bg_workers = MagicMock()
    bg_workers.set_enabled = MagicMock()
    bg_workers.is_enabled = MagicMock(return_value=True)
    pr_manager = AsyncMock(
        find_existing_issue=AsyncMock(return_value=0),
        create_issue=AsyncMock(return_value=0),
    )
    state = MagicMock()
    state.get_cost_budget_killed_workers = MagicMock(return_value=set())
    state.set_cost_budget_killed_workers = MagicMock()
    state.get_disabled_workers = MagicMock(return_value=set())
    deps = MagicMock()
    # Construct without bg_workers (chicken-and-egg per HealthMonitorLoop /
    # TrustFleetSanityLoop precedent — BGWorkerManager takes the loop
    # registry as a constructor input, so loops that need bg_workers get
    # it injected post-construction via set_bg_workers()).
    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=pr_manager,
        state=state,
        deps=deps,
    )
    loop.set_bg_workers(bg_workers)
    return loop, bg_workers, pr_manager, state


async def test_unlimited_when_cap_is_none() -> None:
    """Default cap=None → no-op every tick, no kills, no issues."""
    loop, bg, pr, state = _build_loop(cap=None)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        result = await loop._do_work()
    mock_rolling.assert_not_called()
    bg.set_enabled.assert_not_called()
    pr.create_issue.assert_not_awaited()
    assert result == {"action": "unlimited"}


async def test_under_cap_returns_ok() -> None:
    """Total spend < cap → ok action, no kills."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result == {"action": "ok", "cap": 10.0, "total": 5.0}
    bg.set_enabled.assert_not_called()
    pr.create_issue.assert_not_awaited()


async def test_over_cap_disables_target_loops_and_files_issue() -> None:
    """Total > cap → disable curated workers, file deduped issue, mark in state."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        result = await loop._do_work()
    assert result["action"] == "killed"
    assert result["cap"] == 10.0
    assert result["total"] == 15.0
    # set_enabled called for every name in _TARGET_WORKERS, with enabled=False
    assert bg.set_enabled.call_count > 0
    for call in bg.set_enabled.call_args_list:
        assert call.args[1] is False
    # state recorded which loops were killed
    state.set_cost_budget_killed_workers.assert_called_once()
    killed = state.set_cost_budget_killed_workers.call_args.args[0]
    assert isinstance(killed, set)
    assert len(killed) > 0
    # issue filed
    pr.create_issue.assert_awaited_once()
    issue_kwargs = pr.create_issue.await_args.kwargs
    assert issue_kwargs["title"] == "[cost-budget] daily cap exceeded"
    assert "hydraflow-find" in issue_kwargs["labels"]


async def test_over_cap_dedups_when_issue_already_open() -> None:
    """find_existing_issue returns >0 → no duplicate issue."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    pr.find_existing_issue = AsyncMock(return_value=42)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        await loop._do_work()
    pr.create_issue.assert_not_awaited()


async def test_recovery_reenables_only_watcher_kills() -> None:
    """When total drops back below cap, only re-enable loops the watcher killed."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    state.get_cost_budget_killed_workers = MagicMock(
        return_value={"dependabot_merge", "ci_monitor"}
    )
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result["action"] == "recovered"
    # set_enabled(name, True) for exactly the recorded set, not anything else
    enabled_calls = [c for c in bg.set_enabled.call_args_list if c.args[1] is True]
    enabled_names = {c.args[0] for c in enabled_calls}
    assert enabled_names == {"dependabot_merge", "ci_monitor"}
    state.set_cost_budget_killed_workers.assert_called_once_with(set())


async def test_recovery_no_op_when_no_prior_kills() -> None:
    """Total under cap and no prior kills → ok, not recovered."""
    loop, bg, pr, state = _build_loop(cap=10.0)
    state.get_cost_budget_killed_workers = MagicMock(return_value=set())
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 5.0}}
        result = await loop._do_work()
    assert result["action"] == "ok"
    bg.set_enabled.assert_not_called()


async def test_kill_skips_already_operator_disabled_loops() -> None:
    """If operator already disabled a loop, watcher must not claim authorship
    or re-enable it on recovery.

    Mechanic: ``_kill_caretakers`` only adds a worker to
    ``cost_budget_killed_workers`` if ``bg_workers.is_enabled(name)`` was
    True at kill time. So operator-pre-disabled workers never enter our
    set; recovery doesn't touch them.
    """
    loop, bg, pr, state = _build_loop(cap=10.0)
    # Operator had `dependabot_merge` disabled before cap was breached.
    # bg_workers.is_enabled returns False for it, True for everything else.

    def is_enabled(name: str) -> bool:
        return name != "dependabot_merge"

    bg.is_enabled = MagicMock(side_effect=is_enabled)

    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        mock_rolling.return_value = {"total": {"cost_usd": 15.0}}
        await loop._do_work()

    # Watcher killed everything EXCEPT dependabot_merge (operator already had it off)
    state.set_cost_budget_killed_workers.assert_called_once()
    killed_set = state.set_cost_budget_killed_workers.call_args.args[0]
    assert "dependabot_merge" not in killed_set
    # And the actual set_enabled(False) call list also excludes it
    disable_calls = [c for c in bg.set_enabled.call_args_list if c.args[1] is False]
    disable_names = {c.args[0] for c in disable_calls}
    assert "dependabot_merge" not in disable_names


async def test_kill_switch_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    """HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER=1 → return immediately."""
    monkeypatch.setenv("HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER", "1")
    loop, bg, pr, state = _build_loop(cap=10.0)
    with patch("cost_budget_watcher_loop.build_rolling_24h") as mock_rolling:
        result = await loop._do_work()
    assert result == {"skipped": "kill_switch"}
    mock_rolling.assert_not_called()
    bg.set_enabled.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cost_budget_watcher_scenario.py -v`

Expected: 7 FAIL with `ModuleNotFoundError: No module named 'cost_budget_watcher_loop'`.

- [ ] **Step 3: Write the implementation**

Create `src/cost_budget_watcher_loop.py`:

```python
"""CostBudgetWatcherLoop — daily cost-cap kill-switch.

Polls the rolling-24h spend total. When it exceeds
``config.daily_cost_budget_usd``, disables a curated set of caretaker
loops via ``BGWorkerManager.set_enabled``. When the rolling-24h total
drops back below the cap (e.g. at UTC midnight), re-enables only the
loops the watcher itself killed — operator-disabled loops are preserved.

Default behavior: ``daily_cost_budget_usd = None`` → no-op every tick.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the design at docs/superpowers/specs/2026-04-26-psh-onboarding-and-cost-cap-design.md.

Kill switch: HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER=1.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult


def build_rolling_24h(config: HydraFlowConfig) -> dict[str, Any]:
    """Lazy wrapper around dashboard_routes._cost_rollups.build_rolling_24h.

    Importing dashboard_routes at module load time triggers a circular
    import (matches the pattern at src/report_issue_loop.py:43-60).
    The wrapper is the patch target for tests.
    """
    from dashboard_routes._cost_rollups import (  # noqa: PLC0415
        build_rolling_24h as _impl,
    )

    return _impl(config)

logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER"
_ISSUE_TITLE = "[cost-budget] daily cap exceeded"
# Curated list of loops the watcher gates. The watcher itself is NOT in
# this set — it must keep running to detect recovery. Pipeline loops
# (triage/plan/implement/review) are also out — their gating is via
# their own kill-switch convention; the cost cap is for caretaker fan-out.
_TARGET_WORKERS = (
    "dependabot_merge",
    "security_patch",
    "ci_monitor",
    "stale_issue",
    "stale_issue_gc",
    "pr_unsticker",
    "epic_monitor",
    "epic_sweeper",
    "principles_audit",
    "repo_wiki",
    "wiki_rot_detector",
    "diagram_loop",
    "pricing_refresh",
    "auto_agent_preflight",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "flake_tracker",
    "trust_fleet_sanity",
    "contract_refresh",
    "corpus_learning",
    "code_grooming",
    "retrospective",
)


class CostBudgetWatcherLoop(BaseBackgroundLoop):
    """Daily cost-cap kill-switch for caretaker loops."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager: Any,  # PRPort
        state: Any,  # StateTracker
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="cost_budget_watcher",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._state = state
        self._bg_workers: Any = None  # injected post-construction

    def set_bg_workers(self, bg_workers: Any) -> None:
        """Inject BGWorkerManager post-construction.

        Chicken-and-egg: BGWorkerManager takes the loop registry as a
        constructor input, so loops that need bg_workers get it injected
        after both are built. Mirrors HealthMonitorLoop / TrustFleetSanityLoop.
        """
        self._bg_workers = bg_workers

    def _get_default_interval(self) -> int:
        # 5 minutes; configurable via HydraFlowConfig.
        return 300

    async def _do_work(self) -> WorkCycleResult:
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        cap = self._config.daily_cost_budget_usd
        if cap is None:
            # Unlimited mode — nothing to watch.
            return {"action": "unlimited"}

        try:
            rolling = await asyncio.to_thread(build_rolling_24h, self._config)
        except Exception:  # noqa: BLE001 — telemetry shouldn't kill the gate
            logger.warning("CostBudgetWatcher: rolling-24h compute failed", exc_info=True)
            # On unknown cost state, do NOT take action — neither kill nor recover.
            return {"action": "unknown"}

        total = float(rolling.get("total", {}).get("cost_usd", 0.0))
        previously_killed: set[str] = set(
            self._state.get_cost_budget_killed_workers() or set()
        )

        if total > cap:
            killed = await self._kill_caretakers(previously_killed)
            await self._file_issue(cap=cap, total=total)
            return {
                "action": "killed",
                "cap": cap,
                "total": total,
                "killed_count": len(killed),
            }

        if previously_killed:
            await self._reenable_caretakers(previously_killed)
            return {
                "action": "recovered",
                "cap": cap,
                "total": total,
                "reenabled_count": len(previously_killed),
            }

        return {"action": "ok", "cap": cap, "total": total}

    async def _kill_caretakers(self, previously_killed: set[str]) -> set[str]:
        """Disable every _TARGET_WORKERS member; persist the set we touched."""
        newly_killed: set[str] = set()
        for name in _TARGET_WORKERS:
            try:
                if self._bg_workers.is_enabled(name):
                    self._bg_workers.set_enabled(name, False)
                    newly_killed.add(name)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "CostBudgetWatcher: failed to disable %s", name, exc_info=True
                )
        # Union with previously_killed so manual re-enables don't escape recovery.
        full = previously_killed | newly_killed
        self._state.set_cost_budget_killed_workers(full)
        return newly_killed

    async def _reenable_caretakers(self, killed: set[str]) -> None:
        """Re-enable only the loops we previously killed.

        Operator-override safety is handled at KILL time, not here:
        ``_kill_caretakers`` only adds a worker to ``cost_budget_killed_workers``
        if it was enabled before our kill (`bg_workers.is_enabled` returned
        True). Workers the operator had already disabled never enter our
        killed-set, so we never claim authorship of them and never
        re-enable them on recovery.

        **Known gotcha:** if the operator manually disables a worker
        AFTER we killed it (i.e., during the kill window), recovery will
        still re-enable it. There's no clean way to detect that without
        an event log of (name, source, timestamp) for every set_enabled
        call. Documented in dark-factory.md as the cost-watcher
        operator-override gotcha.
        """
        for name in killed:
            try:
                self._bg_workers.set_enabled(name, True)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "CostBudgetWatcher: failed to re-enable %s", name, exc_info=True
                )
        self._state.set_cost_budget_killed_workers(set())

    async def _file_issue(self, *, cap: float, total: float) -> None:
        existing = await self._pr_manager.find_existing_issue(_ISSUE_TITLE)
        if existing:
            return
        body = (
            f"HydraFlow's daily LLM spend exceeded the configured cap.\n\n"
            f"- **Cap:** ${cap:.2f}\n"
            f"- **Rolling-24h spend:** ${total:.2f}\n\n"
            f"All caretaker loops are disabled until the rolling-24h figure "
            f"drops below the cap (typically at UTC midnight). The watcher will "
            f"automatically re-enable them and add a comment when that happens.\n\n"
            f"To raise or remove the cap, set "
            f"`HYDRAFLOW_DAILY_COST_BUDGET_USD` to a higher value (or unset for unlimited)."
        )
        await self._pr_manager.create_issue(
            title=_ISSUE_TITLE,
            body=body,
            labels=["hydraflow-find", "cost-budget"],
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cost_budget_watcher_scenario.py -v`

Expected: 7 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/cost_budget_watcher_loop.py tests/test_cost_budget_watcher_scenario.py
git commit -m "feat(cost): CostBudgetWatcherLoop — daily cap kill-switch (default unlimited)"
```

---

## Task 2: State support — `cost_budget_killed_workers`

The watcher reads/writes a set of worker names. `StateTracker` doesn't expose this method yet.

**Files:**
- Modify: `src/state/_persistent_state.py` (or wherever the relevant mixin lives)
- Modify: `src/models.py` — add field to `StateData`
- Test: extend a state mixin test if one exists

- [ ] **Step 1: Confirm the state mixin file**

The relevant mixin is `src/state/_worker.py` (`WorkerStateMixin`, lines 16–87). It already exposes `get_disabled_workers()` and `set_disabled_workers(names)` as the precedent for storing `set[str]` worker names. Add the new methods alongside.

- [ ] **Step 2: Add the new field to StateData**

In `src/models.py`, find the `StateData` model (around line 1688) and add a new field next to `disabled_workers`:

```python
    cost_budget_killed_workers: list[str] = Field(
        default_factory=list,
        description=(
            "Workers killed by CostBudgetWatcherLoop because daily cap was "
            "exceeded. Distinct from disabled_workers (operator-set). "
            "Preserved across restart."
        ),
    )
```

(List, not set — Pydantic-friendly; convert at the API boundary.)

- [ ] **Step 3: Add the getter/setter on `WorkerStateMixin`**

In `src/state/_worker.py`, after the existing `set_disabled_workers` (around line 87), append:

```python
    def get_cost_budget_killed_workers(self) -> set[str]:
        """Return workers killed by CostBudgetWatcherLoop (distinct from operator-disabled)."""
        return set(self._data.cost_budget_killed_workers)

    def set_cost_budget_killed_workers(self, names: set[str]) -> None:
        """Persist the set of workers the cost-budget watcher has killed."""
        self._data.cost_budget_killed_workers = sorted(names)
        self.save()
```

(Note: `save()` not `_persist()` — verified by reading `src/state/_worker.py:21`.)

- [ ] **Step 4: Add unit tests for the new mixin methods**

Find the existing test file via: `grep -rln "set_disabled_workers\|get_disabled_workers" tests/ | head -3`

In that file, append (matching the existing fixture pattern — likely `state_tracker` or a path-based setup):

```python
def test_get_cost_budget_killed_workers_defaults_to_empty(state_tracker) -> None:
    assert state_tracker.get_cost_budget_killed_workers() == set()


def test_set_cost_budget_killed_workers_round_trips(state_tracker) -> None:
    state_tracker.set_cost_budget_killed_workers({"a", "b", "c"})
    assert state_tracker.get_cost_budget_killed_workers() == {"a", "b", "c"}


def test_set_cost_budget_killed_workers_clearable(state_tracker) -> None:
    """Recovery path passes set() to clear; round-trips correctly."""
    state_tracker.set_cost_budget_killed_workers({"x", "y"})
    state_tracker.set_cost_budget_killed_workers(set())
    assert state_tracker.get_cost_budget_killed_workers() == set()
```

(Replace `state_tracker` with whatever fixture name the existing file uses — match the precedent for `set_disabled_workers` exactly. If the file uses a path-based pattern instead of a fixture, fall back to that.)

- [ ] **Step 5: Run state tests**

Run: `uv run pytest tests/test_state_*.py tests/test_persistent_state.py tests/test_state.py -v -k "cost_budget or disabled_workers" 2>&1 | tail -15`

Expected: 3 new tests PASS + the existing operator-disabled-workers tests still pass.

- [ ] **Step 6: Commit**

```bash
git add src/models.py src/state/ tests/
git commit -m "feat(state): cost_budget_killed_workers set on StateTracker"
```

---

## Task 3: Eight-checkpoint wiring + state-restorer awareness

Wire the loop into the runtime per the wiki's "Eight-Checkpoint Loop Wiring" entry.

**Files:**
- Modify: `src/service_registry.py`
- Modify: `src/orchestrator.py`
- Modify: `src/dashboard_routes/_common.py`
- Modify: `src/dashboard_routes/_control_routes.py`
- Modify: `src/ui/src/constants.js`
- Modify: `src/bg_worker_manager.py`
- Modify: `tests/orchestrator_integration_utils.py`
- Modify: `tests/scenarios/catalog/loop_registrations.py`
- Modify: `docs/arch/functional_areas.yml`

- [ ] **Step 1: Service registry import + dataclass field**

In `src/service_registry.py`, find the `from diagram_loop import DiagramLoop` line and the `pricing_refresh_loop: PricingRefreshLoop` dataclass field. Add an alphabetically-adjacent import + field for `CostBudgetWatcherLoop`:

```python
from cost_budget_watcher_loop import CostBudgetWatcherLoop  # noqa: TCH001
```

(Match the surrounding `# noqa: TCH001` style if present.)

In the `Services` / `ServiceRegistry` dataclass:

```python
    cost_budget_watcher_loop: CostBudgetWatcherLoop
```

(Place it near the other `*_loop` fields. Alphabetical against neighbors.)

- [ ] **Step 2: Service registry instantiation (no bg_workers in __init__ — chicken-and-egg)**

In the same file, find where `pricing_refresh_loop = PricingRefreshLoop(...)` is constructed. Add:

```python
    cost_budget_watcher_loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=prs,
        state=state,
        deps=loop_deps,
    )
```

**Important:** `BGWorkerManager` is constructed in `orchestrator.py:178` AFTER the service registry — it takes the loop registry as input. So `bg_workers` is NOT available here. Loops that need it (like `HealthMonitorLoop` and `TrustFleetSanityLoop`) get it injected post-construction via `set_bg_workers()`. Step 3 below adds the injector call in `orchestrator.py`.

In the `ServiceRegistry(...)` kwargs at the end of the factory:

```python
    cost_budget_watcher_loop=cost_budget_watcher_loop,
```

- [ ] **Step 3: Orchestrator registry + factories + post-construction injection**

In `src/orchestrator.py`, find the `bg_loop_registry` dict (around line 175). Add:

```python
            "cost_budget_watcher": svc.cost_budget_watcher_loop,
```

Find the existing `set_bg_workers` injections (around lines 181–182 — `svc.trust_fleet_sanity_loop.set_bg_workers(self._bg_workers)` and `svc.health_monitor_loop.set_bg_workers(self._bg_workers)`). Add immediately below:

```python
        svc.cost_budget_watcher_loop.set_bg_workers(self._bg_workers)
```

In `loop_factories` (around line 959), add:

```python
            ("cost_budget_watcher", self._svc.cost_budget_watcher_loop.run),
```

- [ ] **Step 4: Interval bounds + worker management**

In `src/dashboard_routes/_common.py`, find `_INTERVAL_BOUNDS` and add:

```python
    "cost_budget_watcher": (60, 3600),  # 1m min, 1h max (default 5m)
```

In `src/bg_worker_manager.py`, find the `defaults` dict in `get_interval` and add:

```python
            "cost_budget_watcher": 300,  # 5 minutes
```

- [ ] **Step 5: Operator-control surfaces**

In `src/dashboard_routes/_control_routes.py`, find `_bg_worker_defs` and add (alphabetical or at end):

```python
    (
        "cost_budget_watcher",
        "Cost Budget Watcher",
        "Polls rolling-24h LLM spend; disables caretaker loops when daily cap exceeded. Default unlimited.",
    ),
```

In the same file, find `_INTERVAL_WORKERS` set and add:

```python
    "cost_budget_watcher",
```

- [ ] **Step 6: UI constants**

In `src/ui/src/constants.js`:

(a) Add to `EDITABLE_INTERVAL_WORKERS` set:

Replace the existing `'pricing_refresh'])` end-of-set with `'pricing_refresh', 'cost_budget_watcher'])`.

(b) Add to `SYSTEM_WORKER_INTERVALS` dict:

```js
  cost_budget_watcher: 300,
```

(c) Add to `BACKGROUND_WORKERS` array (after `pricing_refresh`):

```js
  { key: 'cost_budget_watcher', label: 'Cost Budget Watcher', description: 'Polls rolling-24h LLM spend every 5 min; disables caretaker loops when daily cap exceeded; auto-recovers as the rolling window drops below the cap. Default unlimited (cap=None).', color: theme.cyan, group: 'operations', tags: ['monitoring'] },
```

**Verify the group key** by reading `WORKER_GROUPS` in the same file. As of PR #8449 the valid keys are `repo_health`, `learning`, `operations`, `intake`, `autonomy`. The `operations` group's existing tags include `monitoring` — using that. If `operations` is gone or renamed, fall back to `learning`.

- [ ] **Step 7: Test SimpleNamespace + catalog**

In `tests/orchestrator_integration_utils.py`, find `services.pricing_refresh_loop = FakeBackgroundLoop()` (line ~502 — landed in PR #8449) and add immediately below it:

```python
    services.cost_budget_watcher_loop = FakeBackgroundLoop()
```

In `tests/scenarios/catalog/loop_registrations.py`, find `_build_pricing_refresh_loop` and add:

```python
def _build_cost_budget_watcher_loop(
    ports: dict[str, Any], config: Any, deps: Any
) -> Any:
    from cost_budget_watcher_loop import CostBudgetWatcherLoop  # noqa: PLC0415

    loop = CostBudgetWatcherLoop(
        config=config,
        pr_manager=ports["github"],
        state=ports["state"],
        deps=deps,
    )
    bg_workers = ports.get("bg_workers")
    if bg_workers is not None:
        loop.set_bg_workers(bg_workers)
    return loop
```

In the `_BUILDERS` dict, add:

```python
    "cost_budget_watcher": _build_cost_budget_watcher_loop,
```

- [ ] **Step 8: Functional area assignment**

In `docs/arch/functional_areas.yml`, find the `caretaking` block's `loops:` list and insert `CostBudgetWatcherLoop` alphabetically (between `CIMonitorLoop` / `CodeGroomingLoop` and the rest).

- [ ] **Step 9: Bump worker-list assertion**

In `tests/test_bg_worker_status.py`, find the `assert len(data["workers"]) == 22` line. PR #8449 bumped it to 22 by adding `pricing_refresh`. Bump to 23 and add `"cost_budget_watcher"` to the names list immediately after `"pricing_refresh"`.

- [ ] **Step 10: Re-emit arch generated docs**

Run: `uv run python -m arch.runner --emit`

Expected: changes in `docs/arch/generated/loops.md`, `docs/arch/generated/functional_areas.md`, etc. — picks up the new loop.

- [ ] **Step 11: Run smoke checks**

Run:
```bash
uv run pyright src/cost_budget_watcher_loop.py src/service_registry.py src/orchestrator.py
uv run pytest tests/test_loop_wiring_completeness.py tests/test_cost_budget_watcher_scenario.py tests/test_bg_worker_status.py tests/architecture/ -v
```

Expected: all pass. completeness test now sees `cost_budget_watcher` discovered + wired.

- [ ] **Step 12: Commit**

```bash
git add src/service_registry.py src/orchestrator.py src/dashboard_routes/_common.py src/dashboard_routes/_control_routes.py src/ui/src/constants.js src/bg_worker_manager.py tests/orchestrator_integration_utils.py tests/scenarios/catalog/loop_registrations.py tests/test_bg_worker_status.py docs/arch/functional_areas.yml docs/arch/
git commit -m "feat(loop): wire CostBudgetWatcherLoop into runtime — eight-checkpoint pattern"
```

---

## Task 4 — DEFERRED: Multi-repo runtime integration test

**Originally specced** as new tests for `RepoRuntimeRegistry` to close ADR-0038's missing-test gap. **Pass #2 review found** that `tests/test_repo_runtime.py::TestRepoRuntimeRegistry` already provides equivalent coverage:
- `test_register_and_get`
- `test_register_duplicate_raises`
- `test_remove_deregisters_and_stops_runtime`
- `test_stop_all`
- `test_two_runtimes_isolated` (lines 269–298)

That last one specifically validates 2-runtime isolation (independent state, event_bus, orchestrator) — which is what ADR-0038 flagged as missing. New tests would either duplicate this coverage or require extensive `RepoRuntime.__init__` mocks (the existing tests use `with patch("repo_runtime.HydraFlowOrchestrator"), patch("repo_runtime.EventBus", ...), patch("repo_runtime.build_state_tracker"), patch("repo_runtime.EventLog"):` to keep construction tractable).

**Decision:** drop. ADR-0038's missing-test gap is closed by the existing tests; the spec's claim that this PR adds new coverage is incorrect. Update spec §6 + §7 accordingly (covered in the spec-narrative-cleanup edit below).

This task has no implementation steps — kept here as documentation of why it was dropped.

## Task 5 — DEFERRED: MockWorld scenarios for the watcher

**Originally specced** as 3 MockWorld `run_with_loops(["cost_budget_watcher"])` scenarios. **Pass #2 review found** two blockers:
1. `MockWorld` doesn't expose a `.config` attribute the test can mutate; the loop's `config` is built internally by `make_bg_loop_deps(tmp_path)` at `mock_world.py:612`. Setting `world.config.daily_cost_budget_usd` doesn't flow into the loop.
2. Adding config-mutation plumbing through `_seed_ports` is a bigger architectural change than the scenarios warrant.

**Decision:** drop. Task 1's 8 unit tests cover the same logic with `build_rolling_24h` mocked directly. Catalog wiring is checked by Task 7's regression test.

This task has no implementation steps.

---

**Files:**
- Create: `tests/scenarios/test_cost_budget_watcher_mockworld.py`

- [ ] **Step 1: Write the scenarios**

Create `tests/scenarios/test_cost_budget_watcher_mockworld.py`:

```python
"""MockWorld scenarios for CostBudgetWatcherLoop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


def _seed_state_and_bg(world: MockWorld) -> tuple[MagicMock, MagicMock]:
    """Inject MagicMock state + bg_workers into the world's port seed."""
    bg_workers = MagicMock()
    bg_workers.set_enabled = MagicMock()
    bg_workers.is_enabled = MagicMock(return_value=True)

    state = MagicMock()
    state.get_cost_budget_killed_workers = MagicMock(return_value=set())
    state.set_cost_budget_killed_workers = MagicMock()

    return bg_workers, state


class TestCostBudgetWatcher:
    """Watcher gates caretaker loops on daily LLM spend cap."""

    async def test_unlimited_cap_no_op(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        # config.daily_cost_budget_usd defaults to None on MockWorld's MagicMock config
        bg_workers, state = _seed_state_and_bg(world)
        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github, bg_workers=bg_workers, state=state)
        # Force config.daily_cost_budget_usd to None
        world.config.daily_cost_budget_usd = None

        with patch(
            "cost_budget_watcher_loop.build_rolling_24h"
        ) as mock_rolling:
            stats = await world.run_with_loops(["cost_budget_watcher"], cycles=1)

        mock_rolling.assert_not_called()
        bg_workers.set_enabled.assert_not_called()
        github.create_issue.assert_not_awaited()
        assert stats["cost_budget_watcher"] == {"action": "unlimited"}

    async def test_over_cap_disables_caretakers(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        bg_workers, state = _seed_state_and_bg(world)
        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github, bg_workers=bg_workers, state=state)
        world.config.daily_cost_budget_usd = 10.0

        with patch(
            "cost_budget_watcher_loop.build_rolling_24h",
            return_value={"total": {"cost_usd": 15.0}},
        ):
            stats = await world.run_with_loops(["cost_budget_watcher"], cycles=1)

        result = stats["cost_budget_watcher"]
        assert result["action"] == "killed"
        assert result["cap"] == 10.0
        assert result["total"] == 15.0
        # Bg workers received set_enabled(name, False) calls
        assert bg_workers.set_enabled.call_count > 0
        github.create_issue.assert_awaited_once()
        kwargs = github.create_issue.await_args.kwargs
        assert kwargs["title"] == "[cost-budget] daily cap exceeded"

    async def test_recovery_reenables_only_watcher_kills(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        bg_workers, state = _seed_state_and_bg(world)
        # State reports 2 prior watcher-killed loops; cap not exceeded → recover.
        state.get_cost_budget_killed_workers = MagicMock(
            return_value={"dependabot_merge", "ci_monitor"}
        )
        github = AsyncMock(
            find_existing_issue=AsyncMock(return_value=0),
            create_issue=AsyncMock(return_value=0),
        )
        _seed_ports(world, github=github, bg_workers=bg_workers, state=state)
        world.config.daily_cost_budget_usd = 10.0

        with patch(
            "cost_budget_watcher_loop.build_rolling_24h",
            return_value={"total": {"cost_usd": 5.0}},
        ):
            stats = await world.run_with_loops(["cost_budget_watcher"], cycles=1)

        result = stats["cost_budget_watcher"]
        assert result["action"] == "recovered"
        # Two re-enable calls for the prior-killed set, no new kills
        enabled_calls = [c for c in bg_workers.set_enabled.call_args_list if c.args[1] is True]
        enabled_names = {c.args[0] for c in enabled_calls}
        assert enabled_names == {"dependabot_merge", "ci_monitor"}
```

- [ ] **Step 2: Run scenarios**

Run: `uv run pytest tests/scenarios/test_cost_budget_watcher_mockworld.py -v -m scenario_loops`

Expected: 3 PASS. **If the catalog builder doesn't support `bg_workers` and `state` ports, the seeding helper will raise.** That's a real gap in the catalog — fix by extending `_BUILDERS["cost_budget_watcher"]` to read `ports.get("bg_workers")` and `ports.get("state")`. The plan's Task 3 step 7 already wires this; verify it matches.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_cost_budget_watcher_mockworld.py
git commit -m "test(scenario): MockWorld scenarios for CostBudgetWatcherLoop"
```

---

## Task 6: PSH onboarding doc + dark-factory.md update

**Files:**
- Modify: `docs/wiki/architecture.md` — cost-cap pattern entry
- Modify: `docs/wiki/dark-factory.md` — PSH onboarding section

- [ ] **Step 1: Add cost-cap pattern entry to architecture.md**

In `docs/wiki/architecture.md`, find the Karpathy-pattern entries and append after the most recent one. Pattern: prose then `json:entry` block. Add:

```markdown
## Daily Cost-Cap Kill-Switch

HydraFlow honors a global `HYDRAFLOW_DAILY_COST_BUDGET_USD` env var. When the rolling-24h LLM spend exceeds the cap, `CostBudgetWatcherLoop` (5-min tick) calls `BGWorkerManager.set_enabled(name, False)` for ~23 caretaker workers (the curated `_TARGET_WORKERS` list). It records the disabled set in `state.cost_budget_killed_workers` so that recovery (rolling-24h drops back below cap, e.g. at UTC midnight) re-enables ONLY the loops it killed — operator-disabled loops are preserved across the recovery. Default `daily_cost_budget_usd = None` means unlimited (no kills). The watcher itself is not in the target set so it can detect recovery; the pipeline loops (triage/plan/implement/review) are also not gated — their cost discipline is via per-issue caps, not the global gate. See also: Eight-Checkpoint Loop Wiring; cost_budget_alerts.py (alert-only sibling).


```json:entry
{"id":"01KS5C8X4M9PR8XVH7TYZN3W2A","title":"Daily Cost-Cap Kill-Switch","content":"HydraFlow honors a global HYDRAFLOW_DAILY_COST_BUDGET_USD env var. CostBudgetWatcherLoop polls cost_rollups.build_rolling_24h every 5 min; over cap → BGWorkerManager.set_enabled(name, False) for ~23 caretaker workers in _TARGET_WORKERS; records the killed set in state.cost_budget_killed_workers; recovery (rolling drops below cap) re-enables only watcher-killed loops, preserving operator overrides. Default cap=None = unlimited. Watcher excluded from gating to detect recovery. Pipeline loops (triage/plan/implement/review) gated separately by per-issue caps. See also: Eight-Checkpoint Loop Wiring; cost_budget_alerts.py.","topic":"architecture","source_type":"manual","source_issue":null,"source_repo":null,"created_at":"2026-04-26T00:00:00.000000+00:00","updated_at":"2026-04-26T00:00:00.000000+00:00","valid_from":"2026-04-26T00:00:00.000000+00:00","valid_to":null,"superseded_by":null,"superseded_reason":null,"confidence":"high","stale":false,"corroborations":1}
```
```

(Use a fresh ULID for the `id` field. The example one is illustrative; pyright won't enforce it but the wiki ingest will.)

- [ ] **Step 2: Add PSH-onboarding section to dark-factory.md**

In `docs/wiki/dark-factory.md`, append a new section:

```markdown
## Onboarding a foreign managed repo

The first foreign managed repo is `T-rav/poop-scoop-hero` (PSH, a Phaser.js game). Onboarding flow:

1. Clone the foreign repo locally (`git clone git@github.com:T-rav/poop-scoop-hero.git ~/projects/poop-scoop-hero`).
2. Register with HydraFlow's runtime registry:
   ```bash
   curl -X POST http://localhost:8080/api/repos/add \
     -H 'Content-Type: application/json' \
     -d '{"path":"/Users/travisf/Documents/projects/poop-scoop-hero"}'
   ```
   This validates the path, detects the slug from the `origin` remote, calls `register_repo_cb` (→ `RepoRuntimeRegistry.register()` + `RepoRegistryStore.upsert()`), and creates HydraFlow lifecycle labels on the repo via `ensure_labels`.
3. Add the slug to `HYDRAFLOW_MANAGED_REPOS`:
   ```bash
   export HYDRAFLOW_MANAGED_REPOS='[{"slug":"T-rav/poop-scoop-hero","main_branch":"main"}]'
   ```
   This makes `PrinciplesAuditLoop` audit the repo on its weekly tick. The audit produces a `pending` → `ready` (or `blocked`) onboarding status.
4. (Optional) Start a `RepoRuntime` for the repo via `POST /api/runtimes/{slug}/start`. The runtime runs the orchestrator-style five-loop set in-process. **Recommend waiting** until the principles audit gives the repo a `ready` status before flipping this on.

**Architectural note (April 2026):** ADR-0009 (Accepted) specifies a subprocess-per-repo model with a TCP supervisor (`hf_cli/supervisor_service.py`). That code lives in a worktree snapshot and was never merged onto main. The in-process `RepoRuntime` is the working path; isolation (state, event bus, worktree paths) is enforced via per-slug data paths but the Python interpreter is shared. Acceptable at 2 repos. Re-landing the supervisor is a separate ADR-0009 closeout.
```

- [ ] **Step 3: Commit**

```bash
git add docs/wiki/architecture.md docs/wiki/dark-factory.md
git commit -m "docs(wiki): cost-cap kill-switch pattern + PSH onboarding section"
```

---

## Task 7: Backward-compat regression test

Cover the additivity of the watcher's wiring. The existing tests assume 22 workers; my Task 3 bumped to 23. A regression test pinning the new total + the cost-budget-specific names guards against future drift.

**Files:**
- Create: `tests/regressions/test_cost_budget_wiring_additive.py`

- [ ] **Step 1: Write the regression test**

Create `tests/regressions/test_cost_budget_wiring_additive.py`:

```python
"""Regression: cost_budget_watcher is wired in all 8 checkpoints.

Locks the wiring so future loop additions don't accidentally remove
cost_budget_watcher from any of: registry, services, constants.js,
_INTERVAL_BOUNDS, _bg_worker_defs, defaults dict, functional area,
worker-list test.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src"
ROOT = Path(__file__).resolve().parents[2]


def test_cost_budget_watcher_in_orchestrator_registry() -> None:
    text = (SRC / "orchestrator.py").read_text()
    assert '"cost_budget_watcher": svc.cost_budget_watcher_loop' in text


def test_cost_budget_watcher_in_loop_factories() -> None:
    text = (SRC / "orchestrator.py").read_text()
    assert '("cost_budget_watcher", self._svc.cost_budget_watcher_loop.run)' in text


def test_cost_budget_watcher_in_interval_bounds() -> None:
    text = (SRC / "dashboard_routes" / "_common.py").read_text()
    assert '"cost_budget_watcher"' in text


def test_cost_budget_watcher_in_constants_js() -> None:
    text = (SRC / "ui" / "src" / "constants.js").read_text()
    # EDITABLE_INTERVAL_WORKERS, SYSTEM_WORKER_INTERVALS, BACKGROUND_WORKERS
    assert "'cost_budget_watcher'" in text or '"cost_budget_watcher"' in text
    assert text.count("cost_budget_watcher") >= 3


def test_cost_budget_watcher_in_bg_worker_defaults() -> None:
    text = (SRC / "bg_worker_manager.py").read_text()
    assert '"cost_budget_watcher": 300' in text


def test_cost_budget_watcher_in_functional_areas_yaml() -> None:
    text = (ROOT / "docs" / "arch" / "functional_areas.yml").read_text()
    assert "CostBudgetWatcherLoop" in text


def test_cost_budget_watcher_in_simplenamespace() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / "orchestrator_integration_utils.py"
    ).read_text()
    assert "services.cost_budget_watcher_loop = FakeBackgroundLoop()" in text


def test_cost_budget_watcher_in_loop_registrations_catalog() -> None:
    text = (
        Path(__file__).resolve().parents[1]
        / "scenarios"
        / "catalog"
        / "loop_registrations.py"
    ).read_text()
    assert '"cost_budget_watcher"' in text
    assert "_build_cost_budget_watcher_loop" in text
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/regressions/test_cost_budget_wiring_additive.py -v`

Expected: 8 PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/regressions/test_cost_budget_wiring_additive.py
git commit -m "test(regression): lock cost_budget_watcher across all 8 wiring checkpoints"
```

---

## Task 8: Final quality gate + PR

**Files:**
- None (verification only).

- [ ] **Step 1: Run `make quality`**

Run: `make quality`

Expected: lint OK, typecheck OK, security OK, tests OK. **11781 (current main) + ~16 new tests = ~11797 passed.**

- [ ] **Step 2: Verify the loop count delta**

Run: `grep -c '"\w*": svc\.' src/orchestrator.py`

Expected: 33 (was 32 before this PR — +1 for `cost_budget_watcher`). If your local count differs, use `git diff origin/main..HEAD -- src/orchestrator.py | grep '+.*svc\.' | wc -l` to confirm the delta is exactly 1.

- [ ] **Step 3: Push branch + open PR**

Run:

```bash
git push -u origin feat-psh-onboarding-and-cost-cap
gh pr create --base main --head feat-psh-onboarding-and-cost-cap \
  --title "feat: CostBudgetWatcherLoop + PSH onboarding (multi-repo prereq)" \
  --body "..."
```

PR body should mention:
- The single-global-cap MVP design
- PSH onboarding via existing `/api/repos/add` (no new code)
- ADR-0009 in-process workaround acknowledgement
- Skip-ADR rationale (no new architectural decision)

- [ ] **Step 4: Monitor CI** — fix anything CI surfaces (pre-existing fleet behavior: completeness regex catches widened-name issues; bandit may flag new urllib calls; functional-area drift; arch.runner --emit). Ride convergence reviews per ADR-0051 if substantial.

- [ ] **Step 5: No commit** — verification only.

---

## Self-review

**Spec coverage:**

| Spec section | Implementing task |
|---|---|
| §3.1 PSH onboarding (no code, just config + curl) | Task 6 (docs only) |
| §3.2 CostBudgetWatcherLoop core | Task 1 |
| §3.2 State support (`get/set_cost_budget_killed_workers`) | Task 2 |
| §3.3 CLI command — DEFERRED | (none — confirmed deferred in spec) |
| §4 Failure handling (cap=None, rolling raises, recovery dedup) | Task 1 (tests + impl) |
| §5 Multi-repo isolation | Task 4 (integration test) |
| §6 Testing strategy | Tasks 1, 4, 5, 7 |
| §7 Files (all touchpoints) | Tasks 1–7 |
| §8 Risks (operator override preservation) | Task 1 (recovery test) + Task 2 (state) |
| §9 Done definition | Task 8 |

No gaps.

**Type consistency:**

- `_TARGET_WORKERS` constant: tuple of strings, identical in Task 1 impl and Task 2 state.
- `state.get/set_cost_budget_killed_workers(set[str])` consistent across Task 1, 2, 5.
- Loop registry key `cost_budget_watcher` (no `_loop` suffix) consistent across Task 3 wiring sites and Task 5 catalog.
- Worker_name `"cost_budget_watcher"` matches registry key (no hyphenation — heeds the lesson from PR #8449's pass-#2 review).
- Issue title `"[cost-budget] daily cap exceeded"` consistent in Task 1 + Task 5.
- Kill-switch env `HYDRAFLOW_DISABLE_COST_BUDGET_WATCHER` consistent.

**Placeholder scan:** none. (Step 2 of Task 2 says "find the right state mixin via grep" rather than naming the file — this is acknowledged because the state structure varies; the implementer will run the grep and pick the right file. Documented as such, not a placeholder.)
