# Staging-Red Attribution + Auto-Revert Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the loop from "RC is red" to "green RC with the culprit reverted and a retry issue filed" without pulling a human in on the happy path — `StagingBisectLoop` detects RC-red via state-tracker poll, runs a flake filter, bisects between `last_green_rc_sha` and the red RC head, attributes the culprit PR, opens an auto-revert PR, files a retry issue, and watchdogs the next RC outcome.

**Architecture:** The existing `StagingPromotionLoop` (`src/staging_promotion_loop.py`) writes two new `StateTracker` fields (`last_green_rc_sha` on `promoted`; `last_rc_red_sha` + `rc_cycle_id` bump on the CI-failed path). A new `BaseBackgroundLoop` subclass `StagingBisectLoop` (`src/staging_bisect_loop.py`) polls state every `staging_bisect_interval` seconds; when `last_rc_red_sha` differs from its last-processed SHA it runs the bisect pipeline against a dedicated worktree under `<data_root>/<repo_slug>/bisect/<rc_ref>/`. `make bisect-probe` is a new Makefile target mirroring the RC gate's scenario job (`make scenario && make scenario-loops`) so `git bisect run` and the gate can never diverge. `DedupStore` keyed on `(rc_pr_number, current_red_rc_sha)` enforces idempotency. `PRManager.create_issue` and `PRManager.create_pr`-style `gh` commands file the revert PR, the retry issue, and all escalations.

**Tech Stack:** Python 3.11, `asyncio`, `pydantic` `StateData` schema (`src/models.py:1688`), `git`, `gh` CLI, `pytest`, `pytest-asyncio`, `MagicMock`/`AsyncMock`.

**Spec:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.3 (plus §5 Makefile, §6 fail-mode rows, §7 unit tests, §8 prerequisites, §9 open-question 5 runtime cap).

**Decisions locked in this plan (spec deferred these):**

1. **Event mechanism:** state-tracker poll (not an event bus). `StagingBisectLoop` reads `last_rc_red_sha`; when it differs from `_last_processed_rc_red_sha` (in-memory, seeded at startup from the watchdog dedup store), it fires. Matches HydraFlow's existing cadence-style loops (see `StagingPromotionLoop._cadence_path`) — no new event infra.
2. **Runtime cap:** 45 minutes (`staging_bisect_runtime_cap_seconds = 2700`). Wall-clock timer around `git bisect run`. Timeout → `hitl-escalation`, `bisect-timeout`.
3. **Retry-issue title:** `Retry: {original PR title}` (spec §4.3 step 6).
4. **Revert branch name:** `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}` (spec §4.3 step 5).
5. **"current_red_rc_sha" source:** the RC PR's `head_sha` via `PRManager.get_pr_head_sha(pr_number)` (matches what the RC workflow runs CI against; see `src/pr_manager.py:1839`).
6. **Watchdog cap:** `staging_bisect_watchdog_rc_cycles = 2` (spec §4.3 step 8: "2 RC cycles or 8 hours, whichever comes first"). 8-hour wall-clock cap is enforced in parallel.
7. **No LLM model override:** the loop does no LLM dispatch.

---

## File Structure

| File | Role | Created / Modified |
|---|---|---|
| `src/state/_staging_bisect.py` | New `StagingBisectStateMixin` — six new state fields’ getters/setters | Create |
| `src/models.py` | Add six fields to `StateData` (`src/models.py:1688`) | Modify |
| `src/state/__init__.py` | Register `StagingBisectStateMixin` in the `StateTracker` MRO | Modify |
| `src/staging_promotion_loop.py` | Write `last_green_rc_sha` on promotion; write `last_rc_red_sha` + bump `rc_cycle_id` on ci_failed | Modify |
| `src/staging_bisect_loop.py` | New `BaseBackgroundLoop` — flake filter, bisect, attribution, safety guard, revert PR, retry issue, watchdog | Create |
| `src/config.py` | Add three fields (`staging_bisect_interval`, `staging_bisect_runtime_cap_seconds`, `staging_bisect_watchdog_rc_cycles`) + three `_ENV_INT_OVERRIDES` entries | Modify |
| `Makefile` | Add `bisect-probe` target mirroring RC-gate scenario commands | Modify |
| `src/service_registry.py` | Dataclass field + `build_services()` wiring | Modify |
| `src/orchestrator.py` | Add to `bg_loop_registry` dict + run-loop list | Modify |
| `src/ui/src/constants.js` | Add to `BACKGROUND_WORKERS` + `SYSTEM_WORKER_INTERVALS` + `EDITABLE_INTERVAL_WORKERS` | Modify |
| `src/dashboard_routes/_common.py` | Add to `_INTERVAL_BOUNDS` | Modify |
| `tests/test_state_staging_bisect.py` | Unit tests for the new mixin | Create |
| `tests/test_staging_promotion_loop.py` | New tests for SHA writes on each outcome | Modify |
| `tests/test_staging_bisect_loop.py` | Unit + E2E tests for the new loop | Create |

---

### Task 1: Add six new fields to `StateData`

**Files:**
- Modify: `src/models.py:1688-1767`

Six fields per spec §4.3 + §8 prerequisite. Names are load-bearing — every subsequent task reads them by exact name.

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_staging_bisect.py`:

```python
"""Tests for the StagingBisectStateMixin fields and accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_six_new_staging_bisect_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.last_green_rc_sha == ""
    assert data.last_rc_red_sha == ""
    assert data.rc_cycle_id == 0
    assert data.auto_reverts_in_cycle == 0
    assert data.auto_reverts_successful == 0
    assert data.flake_reruns_total == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
PYTHONPATH=src uv run pytest tests/test_state_staging_bisect.py::test_state_data_has_six_new_staging_bisect_fields -v
```

Expected: FAIL with `AttributeError: 'StateData' object has no attribute 'last_green_rc_sha'`.

- [ ] **Step 3: Add the six fields to `StateData`**

In `src/models.py`, after line 1766 (`trace_runs:` field) and before `last_updated:` at line 1767, insert:

```python
    # StagingBisectLoop state (spec §4.3 + §8). Written by StagingPromotionLoop
    # on each promotion outcome; polled + mutated by StagingBisectLoop.
    last_green_rc_sha: str = ""
    last_rc_red_sha: str = ""
    rc_cycle_id: int = 0
    auto_reverts_in_cycle: int = 0
    auto_reverts_successful: int = 0
    flake_reruns_total: int = 0
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_state_staging_bisect.py::test_state_data_has_six_new_staging_bisect_fields -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_state_staging_bisect.py
git commit -m "feat(state): add six fields for StagingBisectLoop (§4.3)"
```

---

### Task 2: Add `StagingBisectStateMixin` with getters/setters

**Files:**
- Create: `src/state/_staging_bisect.py`
- Modify: `src/state/__init__.py:28-46` (imports), `src/state/__init__.py:55-75` (MRO)
- Test: `tests/test_state_staging_bisect.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_state_staging_bisect.py`:

```python
def test_mixin_getters_return_defaults(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.get_last_green_rc_sha() == ""
    assert tracker.get_last_rc_red_sha() == ""
    assert tracker.get_rc_cycle_id() == 0
    assert tracker.get_auto_reverts_in_cycle() == 0
    assert tracker.get_auto_reverts_successful() == 0
    assert tracker.get_flake_reruns_total() == 0


def test_set_last_green_rc_sha_persists(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    tracker = StateTracker(state_file=path)
    tracker.set_last_green_rc_sha("abc123")
    reloaded = StateTracker(state_file=path)
    assert reloaded.get_last_green_rc_sha() == "abc123"


def test_set_last_rc_red_sha_bumps_cycle(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    tracker = StateTracker(state_file=path)
    tracker.set_last_rc_red_sha_and_bump_cycle("deadbeef")
    assert tracker.get_last_rc_red_sha() == "deadbeef"
    assert tracker.get_rc_cycle_id() == 1
    tracker.set_last_rc_red_sha_and_bump_cycle("cafef00d")
    assert tracker.get_rc_cycle_id() == 2


def test_increment_auto_reverts_in_cycle(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.increment_auto_reverts_in_cycle() == 1
    assert tracker.increment_auto_reverts_in_cycle() == 2
    tracker.reset_auto_reverts_in_cycle()
    assert tracker.get_auto_reverts_in_cycle() == 0


def test_increment_auto_reverts_successful(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.increment_auto_reverts_successful()
    tracker.increment_auto_reverts_successful()
    assert tracker.get_auto_reverts_successful() == 2


def test_increment_flake_reruns_total(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.increment_flake_reruns_total()
    assert tracker.get_flake_reruns_total() == 1
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_state_staging_bisect.py -v
```

Expected: FAIL on `get_last_green_rc_sha` attribute missing.

- [ ] **Step 3: Create the mixin**

Create `src/state/_staging_bisect.py`:

```python
"""State accessors for StagingBisectLoop (spec §4.3 + §8 prerequisite).

Six fields:

- ``last_green_rc_sha``: HEAD SHA of the most recent RC PR that promoted
  to ``main`` (written by ``StagingPromotionLoop`` on the
  ``status=promoted`` path).
- ``last_rc_red_sha``: HEAD SHA of the most recent RC PR that failed CI
  (written on the ``status=ci_failed`` path). Polled by
  ``StagingBisectLoop`` to trigger a bisect cycle.
- ``rc_cycle_id``: monotonically increasing RC-failure cycle counter,
  bumped whenever ``last_rc_red_sha`` is set. Used to scope the
  ``auto_reverts_in_cycle`` guardrail.
- ``auto_reverts_in_cycle``: count of auto-reverts filed inside the
  current ``rc_cycle_id``. Reset on a successful promotion.
- ``auto_reverts_successful``: lifetime count of auto-reverts that
  produced a subsequent green RC.
- ``flake_reruns_total``: lifetime count of RC-red events dismissed by
  the flake filter (second probe run passed).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class StagingBisectStateMixin:
    """State methods for the staging-red attribution bisect loop."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    # --- last_green_rc_sha ---

    def get_last_green_rc_sha(self) -> str:
        return self._data.last_green_rc_sha

    def set_last_green_rc_sha(self, sha: str) -> None:
        self._data.last_green_rc_sha = sha
        self.save()

    # --- last_rc_red_sha + rc_cycle_id ---

    def get_last_rc_red_sha(self) -> str:
        return self._data.last_rc_red_sha

    def get_rc_cycle_id(self) -> int:
        return self._data.rc_cycle_id

    def set_last_rc_red_sha_and_bump_cycle(self, sha: str) -> None:
        """Atomic update: set the red SHA and bump the cycle counter.

        These two fields are always written together so ``rc_cycle_id``
        is a reliable scope for ``auto_reverts_in_cycle`` — a second red
        with the same cycle-id means we are still repairing the same
        merge batch.
        """
        self._data.last_rc_red_sha = sha
        self._data.rc_cycle_id += 1
        self._data.auto_reverts_in_cycle = 0
        self.save()

    # --- auto_reverts_in_cycle ---

    def get_auto_reverts_in_cycle(self) -> int:
        return self._data.auto_reverts_in_cycle

    def increment_auto_reverts_in_cycle(self) -> int:
        """Increment and return the new count."""
        self._data.auto_reverts_in_cycle += 1
        self.save()
        return self._data.auto_reverts_in_cycle

    def reset_auto_reverts_in_cycle(self) -> None:
        self._data.auto_reverts_in_cycle = 0
        self.save()

    # --- auto_reverts_successful ---

    def get_auto_reverts_successful(self) -> int:
        return self._data.auto_reverts_successful

    def increment_auto_reverts_successful(self) -> None:
        self._data.auto_reverts_successful += 1
        self.save()

    # --- flake_reruns_total ---

    def get_flake_reruns_total(self) -> int:
        return self._data.flake_reruns_total

    def increment_flake_reruns_total(self) -> None:
        self._data.flake_reruns_total += 1
        self.save()
```

Note: `set_last_rc_red_sha_and_bump_cycle` deliberately resets `auto_reverts_in_cycle` to `0` because a new cycle is a new merge batch; spec §4.3 step 4 ("reset the counter only when a green RC promotes") is respected because `StagingPromotionLoop` writing `last_green_rc_sha` does **not** call this setter — it calls `set_last_green_rc_sha` plus `reset_auto_reverts_in_cycle` (see Task 3).

- [ ] **Step 4: Register the mixin in `StateTracker`**

In `src/state/__init__.py`, after line 44 (the `_stale_issue` import) add:

```python
from ._staging_bisect import StagingBisectStateMixin
```

And in the `StateTracker` class bases (line 55–75), add `StagingBisectStateMixin,` as a new line after `StaleIssueStateMixin,`:

```python
class StateTracker(
    IssueStateMixin,
    WorkspaceStateMixin,
    HITLStateMixin,
    ReviewStateMixin,
    RouteBackStateMixin,
    EpicStateMixin,
    LifetimeStatsMixin,
    SessionStateMixin,
    WorkerStateMixin,
    ReportStateMixin,
    ShapeStateMixin,
    DependabotMergeStateMixin,
    StaleIssueStateMixin,
    StagingBisectStateMixin,
    SecurityPatchStateMixin,
    CIMonitorStateMixin,
    CodeGroomingStateMixin,
    DiagnosticStateMixin,
    SentryStateMixin,
    TraceRunsMixin,
):
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_state_staging_bisect.py -v
```

Expected: all six tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/state/_staging_bisect.py src/state/__init__.py tests/test_state_staging_bisect.py
git commit -m "feat(state): StagingBisectStateMixin with six accessors"
```

---

### Task 3: Write state on the `promoted` path in `StagingPromotionLoop`

**Files:**
- Modify: `src/staging_promotion_loop.py:28-96`
- Modify: `tests/test_staging_promotion_loop.py`

Spec §8 prerequisite: `last_green_rc_sha` is not persisted today. Add a write on the promotion success path, also reset `auto_reverts_in_cycle` so a future red starts with a clean counter.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_promotion_loop.py` (imports: add `StateTracker` at the top):

```python
from state import StateTracker  # noqa: E402


class TestStateWritesOnPromoted:
    @pytest.mark.asyncio
    async def test_writes_last_green_rc_sha_on_promoted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=77),
            ci_result=(True, "ok"),
            merge_result=True,
        )
        prs.get_pr_head_sha = AsyncMock(return_value="abc123deadbeef")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]
        # seed a stale counter so reset is observable
        state.increment_auto_reverts_in_cycle()
        assert state.get_auto_reverts_in_cycle() == 1

        result = await loop._do_work()

        assert result["status"] == "promoted"
        assert state.get_last_green_rc_sha() == "abc123deadbeef"
        assert state.get_auto_reverts_in_cycle() == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_promotion_loop.py::TestStateWritesOnPromoted -v
```

Expected: FAIL — `StagingPromotionLoop` does not today accept a `state` kwarg.

- [ ] **Step 3: Wire `StateTracker` into `StagingPromotionLoop`**

Modify `src/staging_promotion_loop.py:28-40`. Replace the `__init__` block:

```python
class StagingPromotionLoop(BaseBackgroundLoop):
    """Periodic staging→main release-candidate promoter. See ADR-0042."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: "StateTracker | None" = None,
    ) -> None:
        super().__init__(worker_name="staging_promotion", config=config, deps=deps)
        self._prs = prs
        self._state = state
```

At the top of the file (after line 23), add:

```python
    from state import StateTracker
```

Inside the existing `TYPE_CHECKING` block so it remains import-cycle-safe.

- [ ] **Step 4: Write `last_green_rc_sha` on the promoted path**

Modify `src/staging_promotion_loop.py:69-75`. Replace the `if passed:` block:

```python
        if passed:
            merged = await self._prs.merge_promotion_pr(pr_number)
            if merged:
                logger.info("Promoted RC PR #%d to main", pr_number)
                if self._state is not None:
                    try:
                        head_sha = await self._prs.get_pr_head_sha(pr_number)
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "Could not read head SHA for promoted PR #%d", pr_number,
                            exc_info=True,
                        )
                        head_sha = ""
                    if head_sha:
                        self._state.set_last_green_rc_sha(head_sha)
                        self._state.reset_auto_reverts_in_cycle()
                return {"status": "promoted", "pr": pr_number}
            logger.warning("Promotion merge failed for PR #%d", pr_number)
            return {"status": "merge_failed", "pr": pr_number}
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_promotion_loop.py::TestStateWritesOnPromoted -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/staging_promotion_loop.py tests/test_staging_promotion_loop.py
git commit -m "feat(staging): write last_green_rc_sha on promotion (§8)"
```

---

### Task 4: Write state on the `ci_failed` path in `StagingPromotionLoop`

**Files:**
- Modify: `src/staging_promotion_loop.py:77-96`
- Modify: `tests/test_staging_promotion_loop.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_promotion_loop.py::TestStateWritesOnPromoted` (or a new class):

```python
class TestStateWritesOnCIFailed:
    @pytest.mark.asyncio
    async def test_writes_last_rc_red_sha_and_bumps_cycle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=88),
            ci_result=(False, "pytest failed: test_foo"),
        )
        prs.get_pr_head_sha = AsyncMock(return_value="cafef00d")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        assert result["status"] == "ci_failed"
        assert state.get_last_rc_red_sha() == "cafef00d"
        assert state.get_rc_cycle_id() == 1

    @pytest.mark.asyncio
    async def test_no_state_write_on_ci_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs = _make_loop(
            tmp_path,
            monkeypatch,
            open_promotion=_make_pr(number=89),
            ci_result=(False, "timed out waiting for checks"),
        )
        prs.get_pr_head_sha = AsyncMock(return_value="never_read")
        state = StateTracker(state_file=tmp_path / "s.json")
        loop._state = state  # type: ignore[attr-defined]

        result = await loop._do_work()

        assert result["status"] == "ci_pending"
        assert state.get_last_rc_red_sha() == ""
        assert state.get_rc_cycle_id() == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_promotion_loop.py::TestStateWritesOnCIFailed -v
```

Expected: FAIL — no write on ci_failed.

- [ ] **Step 3: Write `last_rc_red_sha` on the confirmed CI-failed path**

Modify `src/staging_promotion_loop.py:77-96`. Replace the block from `if "timed out"` through the final `return {...}`:

```python
        if "timed out" in summary.lower():
            return {"status": "ci_pending", "pr": pr_number}

        issue_number = await self._file_failure_issue(pr_number, summary)
        await self._prs.post_comment(
            pr_number,
            f"Promotion CI failed — closing, next cadence cycle will retry.\n\n"
            f"Filed follow-up: #{issue_number}.\n\n{summary}",
        )
        await self._prs.close_issue(pr_number)
        logger.warning(
            "Promotion PR #%d closed after CI failure; filed #%d",
            pr_number,
            issue_number,
        )
        if self._state is not None:
            try:
                red_sha = await self._prs.get_pr_head_sha(pr_number)
            except Exception:  # noqa: BLE001
                logger.debug(
                    "Could not read head SHA for red PR #%d", pr_number,
                    exc_info=True,
                )
                red_sha = ""
            if red_sha:
                self._state.set_last_rc_red_sha_and_bump_cycle(red_sha)
        return {
            "status": "ci_failed",
            "pr": pr_number,
            "find_issue": issue_number,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_promotion_loop.py -v
```

Expected: every test PASS, including both new `TestStateWritesOnCIFailed` tests.

- [ ] **Step 5: Commit**

```bash
git add src/staging_promotion_loop.py tests/test_staging_promotion_loop.py
git commit -m "feat(staging): emit last_rc_red_sha on ci_failed (§8)"
```

---

### Task 5: Wire `state` kwarg through `service_registry`

**Files:**
- Modify: `src/service_registry.py:738-742`

- [ ] **Step 1: Add the `state` kwarg to the instantiation**

Modify `src/service_registry.py:738-742`. Replace:

```python
    staging_promotion_loop = StagingPromotionLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
    )
```

with:

```python
    staging_promotion_loop = StagingPromotionLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
```

`state: StateTracker` is already in scope in `build_services` — check any nearby loop (e.g. `dependabot_merge_loop` at line 731) to confirm.

- [ ] **Step 2: Smoke-test that wiring still type-checks**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
uv run pyright src/service_registry.py src/staging_promotion_loop.py
```

Expected: 0 errors.

- [ ] **Step 3: Commit**

```bash
git add src/service_registry.py
git commit -m "wire: thread state into StagingPromotionLoop"
```

---

### Task 6: Add `make bisect-probe` target

**Files:**
- Modify: `Makefile:218` (immediately after the `scenario-loops` target)

Spec §5: `make bisect-probe` mirrors the RC gate's scenario command set so `git bisect run` and the gate cannot diverge. The RC gate runs (`.github/workflows/rc-promotion-scenario.yml:91-94`):

```yaml
- name: Scenario suite
  run: make scenario
- name: Scenario loops suite
  run: make scenario-loops
```

- [ ] **Step 1: Add the target**

Modify `Makefile`. After line 218 (end of the `scenario-loops` target), insert:

```makefile
bisect-probe: deps
	@echo "$(BLUE)Running bisect probe (mirrors rc-promotion-scenario.yml)...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && $(MAKE) scenario
	@cd $(HYDRAFLOW_DIR) && $(MAKE) scenario-loops
	@echo "$(GREEN)Bisect probe passed$(RESET)"
```

Note: intentionally NOT `scenario-browser` — the RC-gate browser job is a separate CI step that bisect cannot meaningfully re-run against ad-hoc commits without npm/playwright setup per commit. If `scenario-browser` ever becomes a mandatory RC-gate step, revisit.

- [ ] **Step 2: Smoke-test the target exists**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
make -n bisect-probe | head -20
```

Expected: `make` shows it would dispatch to `scenario` and `scenario-loops`.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "feat(make): add bisect-probe target mirroring RC gate (§5)"
```

---

### Task 7: Add three config fields

**Files:**
- Modify: `src/config.py:74-150` (`_ENV_INT_OVERRIDES` list), `src/config.py:1377` (after `staging_rc_retention_days`)

- [ ] **Step 1: Add env overrides**

In `src/config.py`, after line 112 (`staging_rc_retention_days` entry), add three lines:

```python
    ("staging_bisect_interval", "HYDRAFLOW_STAGING_BISECT_INTERVAL", 600),
    ("staging_bisect_runtime_cap_seconds", "HYDRAFLOW_STAGING_BISECT_RUNTIME_CAP_SECONDS", 2700),
    ("staging_bisect_watchdog_rc_cycles", "HYDRAFLOW_STAGING_BISECT_WATCHDOG_RC_CYCLES", 2),
```

- [ ] **Step 2: Add `Field` declarations**

In `src/config.py`, after line 1382 (end of `staging_rc_retention_days` Field) and before `git_user_name:`, insert:

```python
    staging_bisect_interval: int = Field(
        default=600,
        ge=60,
        le=86400,
        description=(
            "Seconds between StagingBisectLoop ticks — a state-tracker "
            "watchdog poll for last_rc_red_sha changes. See ADR-0042 §4.3."
        ),
    )
    staging_bisect_runtime_cap_seconds: int = Field(
        default=2700,
        ge=300,
        le=14400,
        description=(
            "Hard wall-clock cap on a single bisect run (default 45 min). "
            "On timeout the loop files hitl-escalation bisect-timeout."
        ),
    )
    staging_bisect_watchdog_rc_cycles: int = Field(
        default=2,
        ge=1,
        le=10,
        description=(
            "Max RC cycles to wait for a green outcome after an auto-revert "
            "before filing hitl-escalation rc-red-verify-timeout."
        ),
    )
```

- [ ] **Step 3: Write a tiny instantiation test**

Append to `tests/test_config_staging_promotion.py` (existing file for staging-related config):

```python
def test_staging_bisect_config_defaults(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )
    assert cfg.staging_bisect_interval == 600
    assert cfg.staging_bisect_runtime_cap_seconds == 2700
    assert cfg.staging_bisect_watchdog_rc_cycles == 2


def test_staging_bisect_env_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "300")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_RUNTIME_CAP_SECONDS", "600")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_WATCHDOG_RC_CYCLES", "4")
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )
    assert cfg.staging_bisect_interval == 300
    assert cfg.staging_bisect_runtime_cap_seconds == 600
    assert cfg.staging_bisect_watchdog_rc_cycles == 4
```

- [ ] **Step 4: Run the config tests**

```bash
PYTHONPATH=src uv run pytest tests/test_config_staging_promotion.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_config_staging_promotion.py
git commit -m "feat(config): staging_bisect_* fields + env overrides"
```

---

### Task 8: `StagingBisectLoop` skeleton with tick-time detection

**Files:**
- Create: `src/staging_bisect_loop.py`
- Test: `tests/test_staging_bisect_loop.py`

Skeleton-only: subclass of `BaseBackgroundLoop`, a no-op `_do_work` that reads `last_rc_red_sha` and exits early when nothing has changed. Flake filter + bisect + attribution land in later tasks.

- [ ] **Step 1: Write the failing test**

Create `tests/test_staging_bisect_loop.py`:

```python
"""Tests for StagingBisectLoop (spec §4.3)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from state import StateTracker


def _make_cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HydraFlowConfig:
    monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
    monkeypatch.setenv("HYDRAFLOW_STAGING_BISECT_INTERVAL", "600")
    return HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        data_root=tmp_path / "data",
    )


def _make_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[object, MagicMock, StateTracker]:
    from staging_bisect_loop import StagingBisectLoop

    cfg = _make_cfg(tmp_path, monkeypatch)
    stop_event = asyncio.Event()

    async def _sleep(_s: float) -> None:
        return None

    loop_deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop_event,
        status_cb=MagicMock(),
        enabled_cb=lambda _n: True,
        sleep_fn=_sleep,
    )
    prs = MagicMock()
    state = StateTracker(state_file=tmp_path / "s.json")
    loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)
    return loop, prs, state


class TestSkeleton:
    @pytest.mark.asyncio
    async def test_do_work_returns_noop_when_no_red_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        assert state.get_last_rc_red_sha() == ""
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "no_red"}

    @pytest.mark.asyncio
    async def test_do_work_idempotent_on_already_processed_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        loop._last_processed_rc_red_sha = "abc"  # type: ignore[attr-defined]
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "already_processed", "sha": "abc"}

    @pytest.mark.asyncio
    async def test_do_work_noop_when_staging_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "false")
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        result = await loop._do_work()  # type: ignore[attr-defined]
        assert result == {"status": "staging_disabled"}

    def test_interval_uses_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        assert loop._get_default_interval() == 600  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestSkeleton -v
```

Expected: ImportError on `staging_bisect_loop`.

- [ ] **Step 3: Create the skeleton**

Create `src/staging_bisect_loop.py`:

```python
"""Staging-red attribution bisect loop (spec §4.3).

Polls ``StateTracker.last_rc_red_sha`` every ``staging_bisect_interval``
seconds. When the red SHA changes, the loop:

1. Flake-filters the red (Task 10).
2. Bisects between ``last_green_rc_sha`` and ``current_red_rc_sha``
   (Task 12).
3. Attributes the first-bad commit to its originating PR (Task 14).
4. Enforces the second-revert-in-cycle guardrail (Task 16).
5. Files an auto-revert PR (Task 17) and a retry issue (Task 19).
6. Watchdogs the next RC cycle for outcome verification (Task 20).

Trigger mechanism: state-tracker poll (not an event bus). Matches
HydraFlow's existing cadence-style loops; no new event infra.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig

if TYPE_CHECKING:
    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_bisect")


class StagingBisectLoop(BaseBackgroundLoop):
    """Watchdog that reacts to RC-red state transitions. See ADR-0042 §4.3."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="staging_bisect", config=config, deps=deps)
        self._prs = prs
        self._state = state
        # In-memory high-water mark of RC-red SHAs that have already been
        # processed (or skipped as flakes, or escalated). Persisted via
        # DedupStore so a crash-restart does not re-process.
        self._last_processed_rc_red_sha: str = ""

    def _get_default_interval(self) -> int:
        return self._config.staging_bisect_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        red_sha = self._state.get_last_rc_red_sha()
        if not red_sha:
            return {"status": "no_red"}

        if red_sha == self._last_processed_rc_red_sha:
            return {"status": "already_processed", "sha": red_sha}

        # Real work lands in Tasks 10–22. Skeleton just marks-as-seen so
        # the skeleton tests pass.
        logger.info("StagingBisectLoop: red SHA %s — skeleton no-op", red_sha)
        self._last_processed_rc_red_sha = red_sha
        return {"status": "seen", "sha": red_sha}
```

- [ ] **Step 4: Run skeleton tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestSkeleton -v
```

Expected: four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): StagingBisectLoop skeleton + tick detection"
```

---

### Task 9: Persist `_last_processed_rc_red_sha` via `DedupStore`

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Skeleton stores the high-water mark in-memory only; a crash-restart would re-fire. Persist via `DedupStore` keyed by `rc_red_sha` (the `(rc_pr_number, current_red_rc_sha)` compound key from spec §4.3 idempotency — `rc_pr_number` alone is not enough because the same PR can be reopened).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestPersistence:
    @pytest.mark.asyncio
    async def test_processed_sha_persists_across_restart(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("abc")
        # First run marks abc as seen
        await loop._do_work()  # type: ignore[attr-defined]

        # Simulate restart: create a fresh loop with the same data_root
        loop2, _prs2, _state2 = _make_loop(tmp_path, monkeypatch)
        result = await loop2._do_work()  # type: ignore[attr-defined]
        assert result["status"] == "already_processed"
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestPersistence -v
```

Expected: FAIL — fresh loop re-processes.

- [ ] **Step 3: Wire `DedupStore`**

Modify `src/staging_bisect_loop.py`. Add import at the top:

```python
from dedup_store import DedupStore
```

Replace `__init__` and add a helper:

```python
    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="staging_bisect", config=config, deps=deps)
        self._prs = prs
        self._state = state
        self._processed_dedup = DedupStore(
            "staging_bisect_processed_rc_red",
            config.data_root / "dedup" / "staging_bisect_processed.json",
        )
        # Seed from persisted store on startup; empty on first boot.
        processed = self._processed_dedup.get()
        self._last_processed_rc_red_sha: str = (
            max(processed, key=len) if processed else ""
        )
```

Replace the existing `_do_work` ending:

```python
        if red_sha in self._processed_dedup.get():
            self._last_processed_rc_red_sha = red_sha
            return {"status": "already_processed", "sha": red_sha}

        logger.info("StagingBisectLoop: red SHA %s — skeleton no-op", red_sha)
        self._processed_dedup.add(red_sha)
        self._last_processed_rc_red_sha = red_sha
        return {"status": "seen", "sha": red_sha}
```

- [ ] **Step 4: Run persistence test**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestPersistence -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): persist processed red SHAs via DedupStore"
```

---

### Task 10: Flake filter

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 1: before bisecting, re-run `make bisect-probe` against the red RC's head once. If it passes, increment `flake_reruns_total` and exit.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestFlakeFilter:
    @pytest.mark.asyncio
    async def test_second_probe_passes_increments_flake_counter(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red123")
        loop._run_bisect_probe = AsyncMock(return_value=(True, ""))  # type: ignore[attr-defined]

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "flake_dismissed"
        assert state.get_flake_reruns_total() == 1
        loop._run_bisect_probe.assert_awaited_once_with("red123")  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_second_probe_fails_proceeds_to_bisect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red456")
        loop._run_bisect_probe = AsyncMock(return_value=(False, "failing: test_foo"))  # type: ignore[attr-defined]
        loop._run_full_bisect_pipeline = AsyncMock(return_value={"status": "reverted", "pr": 99})  # type: ignore[attr-defined]

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "reverted"
        assert state.get_flake_reruns_total() == 0
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestFlakeFilter -v
```

Expected: FAIL — no `_run_bisect_probe` method.

- [ ] **Step 3: Add the flake-filter branch and `_run_bisect_probe` stub**

Modify `src/staging_bisect_loop.py`. Replace the final lines of `_do_work` (the `logger.info(...)` + `_processed_dedup.add(...)` + return):

```python
        # Flake filter — second probe against the red head
        probe_passed, probe_output = await self._run_bisect_probe(red_sha)
        if probe_passed:
            logger.warning(
                "StagingBisectLoop: second probe passed for %s — dismissing as flake",
                red_sha,
            )
            self._state.increment_flake_reruns_total()
            self._processed_dedup.add(red_sha)
            self._last_processed_rc_red_sha = red_sha
            return {"status": "flake_dismissed", "sha": red_sha}

        # Confirmed red — run the full bisect + revert + retry pipeline
        result = await self._run_full_bisect_pipeline(red_sha, probe_output)
        self._processed_dedup.add(red_sha)
        self._last_processed_rc_red_sha = red_sha
        return result
```

Add the method stubs after `_do_work`:

```python
    async def _run_bisect_probe(self, rc_sha: str) -> tuple[bool, str]:
        """Run ``make bisect-probe`` once against *rc_sha*.

        Returns ``(passed, combined_output)``. Implemented in Task 12 once
        worktree setup is wired; stub defers to subprocess.
        """
        from subprocess import run  # noqa: PLC0415 — lazy import

        logger.info("Running bisect-probe against %s", rc_sha)
        # Task 12 replaces this with a worktree-scoped invocation.
        proc = run(
            ["make", "bisect-probe"],
            cwd=self._config.repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=self._config.staging_bisect_runtime_cap_seconds,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)

    async def _run_full_bisect_pipeline(
        self, red_sha: str, probe_output: str
    ) -> dict[str, Any]:
        """Run bisect → attribute → guardrail → revert → retry → watchdog.

        Implemented across Tasks 12–20. Stub returns a placeholder so the
        flake-filter test proves the flow routes past the filter.
        """
        logger.info("StagingBisectLoop: pipeline not yet wired for %s", red_sha)
        return {"status": "pipeline_stub", "sha": red_sha}
```

- [ ] **Step 4: Run the flake-filter tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestFlakeFilter -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): flake filter + bisect-probe dispatch"
```

---

### Task 11: Bisect harness — worktree setup + `git bisect run`

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 2: dedicated worktree under `<data_root>/<repo_slug>/bisect/<rc_ref>/`; `git bisect start <red> <green>`; `git bisect run make bisect-probe`; 45-minute wall-clock cap.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestBisectHarness:
    @pytest.mark.asyncio
    async def test_run_bisect_returns_first_bad_sha(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)

        async def fake_git(cmd: list[str], cwd: Path, timeout: int):
            if cmd[:2] == ["git", "bisect"] and cmd[2] == "run":
                return (
                    0,
                    "Bisecting: 3 revisions left to test\n"
                    "abc123def456 is the first bad commit\n"
                    "commit abc123def456\n",
                    "",
                )
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        culprit = await loop._run_bisect("green_sha", "red_sha")  # type: ignore[attr-defined]

        assert culprit == "abc123def456"
        loop._cleanup_worktree.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_bisect_timeout_raises_bisect_timeout_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectTimeoutError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        async def hanging(cmd: list[str], cwd: Path, timeout: int):
            raise TimeoutError("git bisect run exceeded budget")

        loop._run_git = AsyncMock(side_effect=hanging)  # type: ignore[attr-defined]

        with pytest.raises(BisectTimeoutError):
            await loop._run_bisect("green", "red")  # type: ignore[attr-defined]
        loop._cleanup_worktree.assert_awaited_once()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_bisect_unreachable_green_sha_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectRangeError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._setup_worktree = AsyncMock(return_value=tmp_path / "bisect-wt")  # type: ignore[attr-defined]
        loop._cleanup_worktree = AsyncMock()  # type: ignore[attr-defined]

        async def fake_git(cmd: list[str], cwd: Path, timeout: int):
            if cmd[:3] == ["git", "bisect", "start"]:
                return (1, "", "fatal: bad object green_sha")
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]

        with pytest.raises(BisectRangeError):
            await loop._run_bisect("green_sha", "red_sha")  # type: ignore[attr-defined]
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestBisectHarness -v
```

Expected: FAIL — `BisectTimeoutError`, `BisectRangeError`, `_run_bisect`, `_setup_worktree`, `_cleanup_worktree` are undefined.

- [ ] **Step 3: Implement the bisect harness**

Modify `src/staging_bisect_loop.py`. At module scope, add exception classes near the top:

```python
class BisectTimeoutError(RuntimeError):
    """Raised when a bisect exceeds ``staging_bisect_runtime_cap_seconds``."""


class BisectRangeError(RuntimeError):
    """Raised when the bisect range is invalid (e.g. unreachable green SHA)."""


class BisectHarnessError(RuntimeError):
    """Raised when git bisect itself errors for reasons unrelated to the probe."""
```

Add methods to `StagingBisectLoop` (after `_run_full_bisect_pipeline`):

```python
    async def _setup_worktree(self, rc_sha: str) -> "Path":
        """Create a dedicated worktree at ``<data_root>/<repo_slug>/bisect/<rc_ref>/``."""
        from pathlib import Path  # noqa: PLC0415

        worktree_dir = (
            self._config.data_root
            / self._config.repo_slug
            / "bisect"
            / rc_sha[:12]
        )
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        if worktree_dir.exists():
            # Stale worktree from a previous aborted run — nuke it first
            await self._run_git(
                ["git", "worktree", "remove", "--force", str(worktree_dir)],
                cwd=self._config.repo_root,
                timeout=60,
            )
        rc, out, err = await self._run_git(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree_dir),
                rc_sha,
            ],
            cwd=self._config.repo_root,
            timeout=120,
        )
        if rc != 0:
            raise BisectHarnessError(
                f"git worktree add failed for {rc_sha}: rc={rc} stderr={err}"
            )
        return worktree_dir

    async def _cleanup_worktree(self, worktree_dir: "Path") -> None:
        """Best-effort ``git worktree remove --force``."""
        try:
            await self._run_git(
                ["git", "worktree", "remove", "--force", str(worktree_dir)],
                cwd=self._config.repo_root,
                timeout=60,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "StagingBisectLoop: worktree cleanup failed for %s",
                worktree_dir,
                exc_info=True,
            )

    async def _run_git(
        self, cmd: list[str], *, cwd: "Path", timeout: int
    ) -> tuple[int, str, str]:
        """Run a git command and return ``(returncode, stdout, stderr)``.

        Overridden in tests via ``AsyncMock`` — production uses a
        subprocess runner.
        """
        import asyncio  # noqa: PLC0415

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            proc.kill()
            raise
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def _run_bisect(self, green_sha: str, red_sha: str) -> str:
        """Run bisect; return the first-bad SHA.

        Raises:
            BisectTimeoutError: wall-clock cap hit.
            BisectRangeError: bisect range invalid (e.g. unreachable green).
            BisectHarnessError: bisect internals failed for infra reasons.
        """
        import re  # noqa: PLC0415

        worktree_dir = await self._setup_worktree(red_sha)
        try:
            rc, _out, err = await self._run_git(
                ["git", "bisect", "start", red_sha, green_sha],
                cwd=worktree_dir,
                timeout=60,
            )
            if rc != 0:
                raise BisectRangeError(
                    f"git bisect start failed for {green_sha}..{red_sha}: {err}"
                )

            try:
                rc, out, err = await self._run_git(
                    [
                        "git",
                        "bisect",
                        "run",
                        "make",
                        "-C",
                        str(self._config.repo_root),
                        "bisect-probe",
                    ],
                    cwd=worktree_dir,
                    timeout=self._config.staging_bisect_runtime_cap_seconds,
                )
            except TimeoutError as exc:
                raise BisectTimeoutError(
                    f"bisect exceeded {self._config.staging_bisect_runtime_cap_seconds}s"
                ) from exc
            if rc not in (0, 1):
                raise BisectHarnessError(
                    f"git bisect run errored (rc={rc}): {err[:500]}"
                )
            match = re.search(
                r"([0-9a-f]{7,40})\s+is the first bad commit", out
            )
            if not match:
                raise BisectHarnessError(
                    f"could not parse first-bad SHA from bisect output: {out[:500]}"
                )
            return match.group(1)
        finally:
            await self._cleanup_worktree(worktree_dir)
```

- [ ] **Step 4: Run harness tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestBisectHarness -v
```

Expected: three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): worktree harness + git bisect run"
```

---

### Task 12: Attribution — resolve first-bad SHA to its PR number

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 3: `gh api repos/.../commits/<sha>/pulls` returns the containing PR; take the first (oldest) entry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestAttribution:
    @pytest.mark.asyncio
    async def test_attribute_resolves_sha_to_pr_number(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)

        async def fake_gh(cmd: list[str]) -> str:
            assert cmd[:3] == ["gh", "api", "repos/"] or cmd[0] == "gh"
            return '[{"number": 321, "title": "Feature: widgets", "merge_commit_sha": "culprit_sha"}]'

        loop._run_gh = AsyncMock(side_effect=fake_gh)  # type: ignore[attr-defined]

        pr_number, pr_title = await loop._attribute_culprit("culprit_sha")  # type: ignore[attr-defined]

        assert pr_number == 321
        assert pr_title == "Feature: widgets"

    @pytest.mark.asyncio
    async def test_attribute_returns_zero_when_no_pr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._run_gh = AsyncMock(return_value="[]")  # type: ignore[attr-defined]

        pr_number, pr_title = await loop._attribute_culprit("culprit_sha")  # type: ignore[attr-defined]

        assert pr_number == 0
        assert pr_title == ""
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestAttribution -v
```

Expected: FAIL — `_attribute_culprit`, `_run_gh` missing.

- [ ] **Step 3: Add attribution**

Modify `src/staging_bisect_loop.py`. Append to the class:

```python
    async def _run_gh(self, cmd: list[str]) -> str:
        """Run a ``gh`` command and return stdout. Overridable in tests."""
        import asyncio  # noqa: PLC0415

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"gh failed: {stderr.decode()[:500]}")
        return stdout.decode()

    async def _attribute_culprit(self, sha: str) -> tuple[int, str]:
        """Resolve *sha* to (pr_number, pr_title).

        Returns ``(0, "")`` if the commit belongs to no PR (direct push).
        """
        import json  # noqa: PLC0415

        raw = await self._run_gh(
            [
                "gh",
                "api",
                f"repos/{self._config.repo}/commits/{sha}/pulls",
                "--jq",
                "[.[] | {number, title, merge_commit_sha}]",
            ]
        )
        try:
            payload = json.loads(raw.strip() or "[]")
        except json.JSONDecodeError:
            logger.warning("Could not parse gh pulls output: %s", raw[:200])
            return 0, ""
        if not payload:
            return 0, ""
        first = payload[0]
        return int(first.get("number") or 0), str(first.get("title") or "")
```

- [ ] **Step 4: Run attribution tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestAttribution -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): attribute first-bad SHA to PR number"
```

---

### Task 13: Safety guardrail — block second revert in one cycle

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 4: if `auto_reverts_in_cycle > 0`, do **not** revert — file `hitl-escalation`, `rc-red-bisect-exhausted` and stop.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestGuardrail:
    @pytest.mark.asyncio
    async def test_second_revert_in_cycle_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        # Simulate a prior auto-revert in this cycle
        state.set_last_rc_red_sha_and_bump_cycle("prev_red")
        state.increment_auto_reverts_in_cycle()
        state.set_last_rc_red_sha_and_bump_cycle("current_red")
        state.increment_auto_reverts_in_cycle()  # we are at 2 reverts
        prs.create_issue = AsyncMock(return_value=555)

        result = await loop._check_guardrail_and_maybe_escalate(  # type: ignore[attr-defined]
            red_sha="current_red",
            culprit_sha="culprit_sha",
            culprit_pr=321,
            bisect_log="log",
        )

        assert result == {
            "status": "guardrail_escalated",
            "escalation_issue": 555,
        }
        prs.create_issue.assert_awaited_once()
        title = prs.create_issue.await_args.args[0]
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-bisect-exhausted" in labels
        assert "hitl-escalation" in labels
        assert "current_red" in title

    @pytest.mark.asyncio
    async def test_first_revert_passes_guardrail(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("current_red")
        # auto_reverts_in_cycle == 0 — guardrail allows proceeding
        prs.create_issue = AsyncMock()

        result = await loop._check_guardrail_and_maybe_escalate(  # type: ignore[attr-defined]
            red_sha="current_red",
            culprit_sha="culprit_sha",
            culprit_pr=321,
            bisect_log="log",
        )

        assert result is None
        prs.create_issue.assert_not_awaited()
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestGuardrail -v
```

Expected: FAIL — `_check_guardrail_and_maybe_escalate` missing.

- [ ] **Step 3: Implement the guardrail**

Append to `StagingBisectLoop`:

```python
    async def _check_guardrail_and_maybe_escalate(
        self,
        *,
        red_sha: str,
        culprit_sha: str,
        culprit_pr: int,
        bisect_log: str,
    ) -> dict[str, Any] | None:
        """Return None when safe to revert, escalation-result dict otherwise.

        Enforces the "second-revert-in-cycle" rule from spec §4.3 step 4.
        """
        if self._state.get_auto_reverts_in_cycle() == 0:
            return None

        title = (
            f"hitl: RC-red bisect exhausted — second red in cycle "
            f"{self._state.get_rc_cycle_id()} (rc_sha={red_sha[:12]})"
        )
        body = (
            "## RC-red bisect exhausted\n\n"
            f"A second red RC was detected inside the same cycle "
            f"(`rc_cycle_id={self._state.get_rc_cycle_id()}`).\n\n"
            f"- Current red RC head: `{red_sha}`\n"
            f"- Bisect-identified culprit: `{culprit_sha}`"
            f" (PR #{culprit_pr or 'unknown'})\n"
            f"- Auto-reverts already filed in this cycle: "
            f"{self._state.get_auto_reverts_in_cycle()}\n\n"
            "Either the prior bisect was wrong, or the damage is broader "
            "than one PR. Halting auto-revert per spec §4.3 step 4.\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```"
        )
        labels = ["hitl-escalation", "rc-red-bisect-exhausted"]
        issue = await self._prs.create_issue(title, body, labels)
        logger.error(
            "StagingBisectLoop: guardrail tripped — escalated #%d", issue
        )
        return {"status": "guardrail_escalated", "escalation_issue": issue}
```

- [ ] **Step 4: Run guardrail tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestGuardrail -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): second-revert-in-cycle guardrail"
```

---

### Task 14: Revert PR creation

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 5: branch `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}`; `git revert -m 1 <sha>` for merges (default on `staging` per ADR-0042); `git revert <sha>` for single-commit; push; open PR with title/body/labels.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestRevertPR:
    @pytest.mark.asyncio
    async def test_create_revert_pr_merge_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock()
        prs._run_gh = AsyncMock(return_value="https://github.com/o/r/pull/900")  # not used
        loop._run_git = AsyncMock(return_value=(0, "", ""))  # type: ignore[attr-defined]
        loop._is_merge_commit = AsyncMock(return_value=True)  # type: ignore[attr-defined]
        loop._create_pr_via_gh = AsyncMock(return_value=900)  # type: ignore[attr-defined]

        pr_number, branch = await loop._create_revert_pr(  # type: ignore[attr-defined]
            culprit_sha="culprit_sha",
            culprit_pr=321,
            failing_tests="test_foo, test_bar",
            rc_pr_url="https://github.com/o/r/pull/77",
            bisect_log="log",
            retry_issue_number=654,
        )

        assert pr_number == 900
        assert branch.startswith("auto-revert/pr-321-rc-")
        # Verify git revert -m 1 was invoked
        calls = [c.args[0] for c in loop._run_git.await_args_list]  # type: ignore[attr-defined]
        revert_cmds = [c for c in calls if len(c) >= 2 and c[1] == "revert"]
        assert revert_cmds
        assert "-m" in revert_cmds[0] and "1" in revert_cmds[0]

    @pytest.mark.asyncio
    async def test_create_revert_pr_single_commit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock()
        loop._run_git = AsyncMock(return_value=(0, "", ""))  # type: ignore[attr-defined]
        loop._is_merge_commit = AsyncMock(return_value=False)  # type: ignore[attr-defined]
        loop._create_pr_via_gh = AsyncMock(return_value=901)  # type: ignore[attr-defined]

        await loop._create_revert_pr(  # type: ignore[attr-defined]
            culprit_sha="c",
            culprit_pr=321,
            failing_tests="t",
            rc_pr_url="u",
            bisect_log="l",
            retry_issue_number=0,
        )

        calls = [c.args[0] for c in loop._run_git.await_args_list]  # type: ignore[attr-defined]
        revert_cmds = [c for c in calls if len(c) >= 2 and c[1] == "revert"]
        assert revert_cmds
        assert "-m" not in revert_cmds[0]

    @pytest.mark.asyncio
    async def test_revert_conflict_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import RevertConflictError

        loop, _prs, _state = _make_loop(tmp_path, monkeypatch)
        loop._is_merge_commit = AsyncMock(return_value=True)  # type: ignore[attr-defined]

        async def fake_git(cmd, **_kw):
            if len(cmd) >= 2 and cmd[1] == "revert":
                return (1, "", "CONFLICT (content): Merge conflict in foo.py")
            return (0, "", "")

        loop._run_git = AsyncMock(side_effect=fake_git)  # type: ignore[attr-defined]

        with pytest.raises(RevertConflictError):
            await loop._create_revert_pr(  # type: ignore[attr-defined]
                culprit_sha="c",
                culprit_pr=321,
                failing_tests="t",
                rc_pr_url="u",
                bisect_log="l",
                retry_issue_number=0,
            )
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestRevertPR -v
```

Expected: FAIL — `_create_revert_pr`, `RevertConflictError`, `_is_merge_commit`, `_create_pr_via_gh` missing.

- [ ] **Step 3: Implement revert PR creation**

In `src/staging_bisect_loop.py`, add the exception near the top:

```python
class RevertConflictError(RuntimeError):
    """Raised when ``git revert`` produced a merge conflict."""
```

Append methods to `StagingBisectLoop`:

```python
    async def _is_merge_commit(self, sha: str) -> bool:
        """Return True if *sha* has two or more parents."""
        rc, out, _err = await self._run_git(
            ["git", "rev-list", "--parents", "-n", "1", sha],
            cwd=self._config.repo_root,
            timeout=30,
        )
        if rc != 0:
            return False
        # Output is "<sha> <parent1> [<parent2> ...]"
        parts = out.strip().split()
        return len(parts) >= 3

    async def _create_pr_via_gh(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        labels: list[str],
    ) -> int:
        """Open a PR via ``gh pr create``; return the PR number (0 on failure)."""
        import re  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        with tempfile.NamedTemporaryFile(
            "w", suffix=".md", delete=False
        ) as body_fh:
            body_path = Path(body_fh.name)
            body_fh.write(body)
        try:
            cmd = [
                "gh",
                "pr",
                "create",
                "--repo",
                self._config.repo,
                "--head",
                branch,
                "--base",
                self._config.staging_branch,
                "--title",
                title,
                "--body-file",
                str(body_path),
            ]
            for label in labels:
                cmd.extend(["--label", label])
            out = await self._run_gh(cmd)
            match = re.search(r"/pull/(\d+)", out)
            return int(match.group(1)) if match else 0
        finally:
            body_path.unlink(missing_ok=True)

    async def _create_revert_pr(
        self,
        *,
        culprit_sha: str,
        culprit_pr: int,
        failing_tests: str,
        rc_pr_url: str,
        bisect_log: str,
        retry_issue_number: int,
    ) -> tuple[int, str]:
        """Create the auto-revert branch + PR. Return (pr_number, branch)."""
        from datetime import UTC, datetime  # noqa: PLC0415

        now = datetime.now(UTC)
        branch = f"auto-revert/pr-{culprit_pr}-rc-{now.strftime('%Y%m%d%H%M')}"

        # Create branch off staging
        await self._run_git(
            ["git", "fetch", "origin", self._config.staging_branch],
            cwd=self._config.repo_root,
            timeout=60,
        )
        await self._run_git(
            [
                "git",
                "checkout",
                "-b",
                branch,
                f"origin/{self._config.staging_branch}",
            ],
            cwd=self._config.repo_root,
            timeout=30,
        )

        # Run revert with -m 1 for merge commits
        is_merge = await self._is_merge_commit(culprit_sha)
        revert_cmd = ["git", "revert", "--no-edit"]
        if is_merge:
            revert_cmd += ["-m", "1"]
        revert_cmd.append(culprit_sha)
        rc, _out, err = await self._run_git(
            revert_cmd, cwd=self._config.repo_root, timeout=60
        )
        if rc != 0:
            # Abort any partial revert state
            await self._run_git(
                ["git", "revert", "--abort"],
                cwd=self._config.repo_root,
                timeout=30,
            )
            raise RevertConflictError(
                f"git revert failed for {culprit_sha}: {err[:500]}"
            )

        # Push branch
        await self._run_git(
            ["git", "push", "origin", branch],
            cwd=self._config.repo_root,
            timeout=120,
        )

        # Open PR
        title = f"Auto-revert: PR #{culprit_pr} — RC-red attribution on {failing_tests}"
        show_rc, show_out, _show_err = await self._run_git(
            ["git", "show", culprit_sha, "--stat"],
            cwd=self._config.repo_root,
            timeout=30,
        )
        stat_block = show_out if show_rc == 0 else "(git show failed)"
        retry_link = (
            f"- Retry issue: #{retry_issue_number}\n"
            if retry_issue_number
            else ""
        )
        body = (
            "## Auto-revert (StagingBisectLoop)\n\n"
            f"- Culprit SHA: `{culprit_sha}`\n"
            f"- Originating PR: #{culprit_pr}\n"
            f"- Failing tests: {failing_tests}\n"
            f"- Red RC PR: {rc_pr_url}\n"
            f"{retry_link}\n"
            "### `git show --stat`\n\n"
            f"```\n{stat_block[:3000]}\n```\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```\n\n"
            "_Filed per spec §4.3. Auto-merges on green per §3.2._"
        )
        pr_number = await self._create_pr_via_gh(
            title=title,
            body=body,
            branch=branch,
            labels=["hydraflow-find", "auto-revert", "rc-red-attribution"],
        )
        return pr_number, branch
```

- [ ] **Step 4: Run revert-PR tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestRevertPR -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): auto-revert branch + PR with merge-aware revert"
```

---

### Task 15: Retry issue filing

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 6: `Retry: {original PR title}`, body references reverted PR, full bisect log, failing tests, time bounds.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestRetryIssue:
    @pytest.mark.asyncio
    async def test_file_retry_issue_title_and_labels(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock(return_value=654)

        issue = await loop._file_retry_issue(  # type: ignore[attr-defined]
            culprit_pr=321,
            culprit_pr_title="Feature: widgets",
            culprit_sha="culprit_sha",
            green_sha="green_sha",
            red_sha="red_sha",
            failing_tests="test_foo",
            bisect_log="log",
            revert_pr_url="https://github.com/o/r/pull/900",
        )

        assert issue == 654
        prs.create_issue.assert_awaited_once()
        title, body, labels = prs.create_issue.await_args.args
        assert title == "Retry: Feature: widgets"
        assert "hydraflow-find" in labels
        assert "rc-red-retry" in labels
        assert "pull/900" in body
        assert "green_sha" in body
        assert "red_sha" in body
```

- [ ] **Step 2: Run to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestRetryIssue -v
```

Expected: FAIL — `_file_retry_issue` missing.

- [ ] **Step 3: Implement retry-issue filing**

Append to `StagingBisectLoop`:

```python
    async def _file_retry_issue(
        self,
        *,
        culprit_pr: int,
        culprit_pr_title: str,
        culprit_sha: str,
        green_sha: str,
        red_sha: str,
        failing_tests: str,
        bisect_log: str,
        revert_pr_url: str,
    ) -> int:
        """File a ``hydraflow-find`` retry issue and return its number."""
        title = f"Retry: {culprit_pr_title or f'PR #{culprit_pr}'}"
        body = (
            "## Retry request\n\n"
            f"Original PR #{culprit_pr} (`{culprit_sha}`) was auto-reverted "
            f"after bisect attributed it to the red RC "
            f"({green_sha[:12]}..{red_sha[:12]}).\n\n"
            f"- Reverted PR: {revert_pr_url}\n"
            f"- Failing tests: {failing_tests}\n"
            f"- Time bounds: `{green_sha}` (last green) → `{red_sha}` (red)\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```\n\n"
            "_Factory picks up `hydraflow-find` issues; the work re-enters "
            "the standard implement/review pipeline._"
        )
        return await self._prs.create_issue(
            title, body, ["hydraflow-find", "rc-red-retry"]
        )
```

- [ ] **Step 4: Run the retry-issue test**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestRetryIssue -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): file Retry: issue after auto-revert (§4.3 step 6)"
```

---

### Task 16: Outcome watchdog

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Spec §4.3 step 8: after the revert merges, poll `StateTracker.last_green_rc_sha`/`last_rc_red_sha` for `staging_bisect_watchdog_rc_cycles` RC cycles or 8 hours (whichever is shorter) and verify the outcome.

Since the watchdog can span up to 8 hours, it does NOT block the current `_do_work` cycle. Instead, we persist a pending-watchdog record and check it on every subsequent tick.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestWatchdog:
    @pytest.mark.asyncio
    async def test_watchdog_green_outcome(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, _prs, state = _make_loop(tmp_path, monkeypatch)
        state.increment_auto_reverts_in_cycle()  # simulate prior revert
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": state.get_rc_cycle_id(),
            "deadline_ts": 9_999_999_999.0,
        }
        # Promotion happened → last_green_rc_sha advanced
        state.set_last_green_rc_sha("green_B")
        state.reset_auto_reverts_in_cycle()

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result == {"status": "watchdog_green"}
        assert state.get_auto_reverts_successful() == 1
        assert loop._pending_watchdog is None  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_watchdog_still_red_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_rc_red_sha_and_bump_cycle("red_A")
        state.increment_auto_reverts_in_cycle()
        prior_cycle = state.get_rc_cycle_id()

        # New red arrives
        state.set_last_rc_red_sha_and_bump_cycle("red_B")
        prs.create_issue = AsyncMock(return_value=888)
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": prior_cycle,
            "deadline_ts": 9_999_999_999.0,
        }

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result["status"] == "watchdog_still_red"
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-post-revert-red" in labels

    @pytest.mark.asyncio
    async def test_watchdog_timeout_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, _state = _make_loop(tmp_path, monkeypatch)
        prs.create_issue = AsyncMock(return_value=889)
        loop._pending_watchdog = {  # type: ignore[attr-defined]
            "red_sha_at_revert": "red_A",
            "rc_cycle_at_revert": 1,
            "deadline_ts": 0.0,  # already past
        }

        result = await loop._check_pending_watchdog()  # type: ignore[attr-defined]

        assert result["status"] == "watchdog_timeout"
        labels = prs.create_issue.await_args.args[2]
        assert "rc-red-verify-timeout" in labels
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestWatchdog -v
```

Expected: FAIL — `_check_pending_watchdog`, `_pending_watchdog` missing.

- [ ] **Step 3: Implement the watchdog**

In `src/staging_bisect_loop.py`, add to `__init__`:

```python
        # Pending watchdog state — set after an auto-revert is filed.
        # None when no watchdog active.
        self._pending_watchdog: dict[str, Any] | None = None
```

Append methods to the class:

```python
    async def _check_pending_watchdog(self) -> dict[str, Any] | None:
        """Resolve any pending watchdog to green / still-red / timeout.

        Returns a status dict when the watchdog resolves this tick,
        ``None`` when still waiting (no resolution yet).
        """
        import time  # noqa: PLC0415

        wd = self._pending_watchdog
        if wd is None:
            return None

        # Green outcome: a new green RC arrived after the revert
        # (auto_reverts_in_cycle was reset on the promoted path — see Task 3).
        if (
            self._state.get_last_green_rc_sha()
            and self._state.get_auto_reverts_in_cycle() == 0
            and self._state.get_rc_cycle_id() >= wd["rc_cycle_at_revert"]
        ):
            self._state.increment_auto_reverts_successful()
            self._pending_watchdog = None
            logger.info("StagingBisectLoop: watchdog resolved green")
            return {"status": "watchdog_green"}

        # Still-red: a new red with a different SHA than the one we reverted
        new_red = self._state.get_last_rc_red_sha()
        if (
            new_red
            and new_red != wd["red_sha_at_revert"]
            and self._state.get_rc_cycle_id() > wd["rc_cycle_at_revert"]
        ):
            issue = await self._prs.create_issue(
                f"hitl: RC still red after auto-revert "
                f"(cycle {self._state.get_rc_cycle_id()})",
                (
                    "## Post-revert verification failed\n\n"
                    f"- Reverted in cycle {wd['rc_cycle_at_revert']} "
                    f"(red_sha={wd['red_sha_at_revert']}).\n"
                    f"- New red detected this cycle "
                    f"(red_sha={new_red}).\n\n"
                    "The revert stays in place per spec §4.3 step 8 — "
                    "a human must disambiguate."
                ),
                ["hitl-escalation", "rc-red-post-revert-red"],
            )
            self._pending_watchdog = None
            return {
                "status": "watchdog_still_red",
                "escalation_issue": issue,
            }

        # Timeout: deadline elapsed without a green or a new red
        if time.time() >= wd["deadline_ts"]:
            issue = await self._prs.create_issue(
                f"hitl: RC verification timed out after auto-revert "
                f"(cycle {wd['rc_cycle_at_revert']})",
                (
                    "## Watchdog timeout\n\n"
                    "No green RC and no new red RC within the "
                    f"{self._config.staging_bisect_watchdog_rc_cycles}-cycle "
                    "or 8-hour window after the auto-revert.\n\n"
                    "The RC pipeline may be stalled for unrelated reasons."
                ),
                ["hitl-escalation", "rc-red-verify-timeout"],
            )
            self._pending_watchdog = None
            return {"status": "watchdog_timeout", "escalation_issue": issue}

        # Still waiting
        return None
```

- [ ] **Step 4: Run the watchdog tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestWatchdog -v
```

Expected: three tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): outcome watchdog (green/still-red/timeout)"
```

---

### Task 17: Wire pipeline — `_run_full_bisect_pipeline`

**Files:**
- Modify: `src/staging_bisect_loop.py`
- Modify: `tests/test_staging_bisect_loop.py`

Replace the stub from Task 10. Orders the subroutines: bisect → attribute → guardrail → revert → retry → schedule watchdog → increment `auto_reverts_in_cycle`.

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestPipelineIntegration:
    @pytest.mark.asyncio
    async def test_confirmed_red_happy_path_revert_and_retry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("green_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")

        loop._run_bisect_probe = AsyncMock(return_value=(False, "test_foo failed"))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(return_value="culprit_sha")  # type: ignore[attr-defined]
        loop._attribute_culprit = AsyncMock(return_value=(321, "Feature: widgets"))  # type: ignore[attr-defined]
        loop._create_revert_pr = AsyncMock(return_value=(900, "auto-revert/pr-321-rc-123"))  # type: ignore[attr-defined]
        loop._file_retry_issue = AsyncMock(return_value=654)  # type: ignore[attr-defined]
        prs.find_open_pr = AsyncMock()
        prs.get_pr_head_sha = AsyncMock(return_value="red_sha")
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="https://github.com/o/r/pull/77")
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "reverted"
        assert result["revert_pr"] == 900
        assert result["retry_issue"] == 654
        assert state.get_auto_reverts_in_cycle() == 1
        assert loop._pending_watchdog is not None  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_timeout_during_bisect_escalates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from staging_bisect_loop import BisectTimeoutError

        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("green_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")
        loop._run_bisect_probe = AsyncMock(return_value=(False, ""))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(side_effect=BisectTimeoutError("timeout"))  # type: ignore[attr-defined]
        prs.create_issue = AsyncMock(return_value=777)
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="u")
        )

        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result["status"] == "bisect_timeout"
        labels = prs.create_issue.await_args.args[2]
        assert "bisect-timeout" in labels
        assert "hitl-escalation" in labels
```

- [ ] **Step 2: Run to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestPipelineIntegration -v
```

Expected: FAIL — pipeline stub still in place.

- [ ] **Step 3: Implement the full pipeline**

Replace the `_run_full_bisect_pipeline` stub in `src/staging_bisect_loop.py` with:

```python
    async def _run_full_bisect_pipeline(
        self, red_sha: str, probe_output: str
    ) -> dict[str, Any]:
        """End-to-end pipeline: bisect → attribute → guardrail → revert → retry."""
        import time  # noqa: PLC0415

        green_sha = self._state.get_last_green_rc_sha()
        if not green_sha:
            logger.warning(
                "StagingBisectLoop: no last_green_rc_sha — skipping bisect for %s",
                red_sha,
            )
            return {"status": "no_green_anchor", "sha": red_sha}

        # 1. Bisect
        try:
            culprit_sha = await self._run_bisect(green_sha, red_sha)
        except BisectTimeoutError:
            issue = await self._escalate_harness_failure(
                red_sha,
                green_sha,
                "bisect-timeout",
                "bisect exceeded runtime cap",
            )
            return {
                "status": "bisect_timeout",
                "escalation_issue": issue,
            }
        except BisectRangeError as exc:
            logger.warning(
                "StagingBisectLoop: invalid bisect range %s..%s — %s",
                green_sha,
                red_sha,
                exc,
            )
            return {"status": "invalid_bisect_range", "sha": red_sha}
        except BisectHarnessError as exc:
            issue = await self._escalate_harness_failure(
                red_sha,
                green_sha,
                "bisect-harness-failure",
                str(exc),
            )
            return {
                "status": "bisect_harness_failure",
                "escalation_issue": issue,
            }

        # 2. Attribute
        culprit_pr, culprit_pr_title = await self._attribute_culprit(culprit_sha)
        bisect_log = (
            f"green_sha={green_sha}\n"
            f"red_sha={red_sha}\n"
            f"first_bad={culprit_sha}\n"
            f"probe_output:\n{probe_output[:2000]}"
        )

        # 3. Safety guardrail
        guard = await self._check_guardrail_and_maybe_escalate(
            red_sha=red_sha,
            culprit_sha=culprit_sha,
            culprit_pr=culprit_pr,
            bisect_log=bisect_log,
        )
        if guard is not None:
            return guard

        # 4. Resolve RC PR URL for revert-PR body
        rc_pr_url = ""
        rc_pr = await self._prs.find_open_promotion_pr()
        if rc_pr is not None:
            rc_pr_url = rc_pr.url

        # 5. Retry issue first (so revert body can link to it)
        failing_tests = self._parse_failing_tests(probe_output)
        try:
            retry_issue = await self._file_retry_issue(
                culprit_pr=culprit_pr,
                culprit_pr_title=culprit_pr_title,
                culprit_sha=culprit_sha,
                green_sha=green_sha,
                red_sha=red_sha,
                failing_tests=failing_tests,
                bisect_log=bisect_log,
                revert_pr_url="(pending)",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "StagingBisectLoop: retry issue filing failed for %s", culprit_sha
            )
            retry_issue = 0

        # 6. Revert PR
        try:
            revert_pr, _branch = await self._create_revert_pr(
                culprit_sha=culprit_sha,
                culprit_pr=culprit_pr,
                failing_tests=failing_tests,
                rc_pr_url=rc_pr_url,
                bisect_log=bisect_log,
                retry_issue_number=retry_issue,
            )
        except RevertConflictError as exc:
            issue = await self._prs.create_issue(
                f"hitl: git revert conflict on {culprit_sha[:12]}",
                (
                    "## Revert conflict\n\n"
                    f"`git revert` produced merge conflicts while attempting "
                    f"to revert `{culprit_sha}` (PR #{culprit_pr}).\n\n"
                    "Per spec §4.3, auto-resolution is not attempted — "
                    "subsequent PRs likely depend on the culprit.\n\n"
                    f"```\n{exc}\n```"
                ),
                ["hitl-escalation", "revert-conflict"],
            )
            return {"status": "revert_conflict", "escalation_issue": issue}

        # 7. Bump counters + schedule watchdog
        self._state.increment_auto_reverts_in_cycle()
        watchdog_wall_seconds = 8 * 3600  # spec §4.3 step 8
        self._pending_watchdog = {
            "red_sha_at_revert": red_sha,
            "rc_cycle_at_revert": self._state.get_rc_cycle_id(),
            "deadline_ts": time.time() + watchdog_wall_seconds,
        }

        return {
            "status": "reverted",
            "revert_pr": revert_pr,
            "retry_issue": retry_issue,
            "culprit_sha": culprit_sha,
            "culprit_pr": culprit_pr,
        }

    async def _escalate_harness_failure(
        self,
        red_sha: str,
        green_sha: str,
        label: str,
        detail: str,
    ) -> int:
        """Common escalation for bisect-harness-class failures."""
        title = f"hitl: StagingBisectLoop {label} ({red_sha[:12]})"
        body = (
            "## Bisect harness failure\n\n"
            f"- Range: `{green_sha}` → `{red_sha}`\n"
            f"- Failure class: `{label}`\n\n"
            f"```\n{detail[:3000]}\n```"
        )
        return await self._prs.create_issue(
            title, body, ["hitl-escalation", label]
        )

    def _parse_failing_tests(self, probe_output: str) -> str:
        """Heuristic extraction of failing test identifiers from probe output."""
        import re  # noqa: PLC0415

        names = re.findall(r"(?:FAILED|failed)\s+(\S+::[A-Za-z0-9_:.\[\]-]+)", probe_output)
        if not names:
            return "(see bisect log)"
        # Dedupe preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for n in names:
            if n not in seen:
                seen.add(n)
                unique.append(n)
        return ", ".join(unique[:10])
```

Also thread watchdog checks into `_do_work`. Replace the section of `_do_work` that begins with `red_sha = self._state.get_last_rc_red_sha()` with:

```python
        # Resolve any pending watchdog first so a green outcome clears
        # the auto_reverts_in_cycle counter before we evaluate a new red.
        watchdog_result = await self._check_pending_watchdog()
        if watchdog_result is not None:
            return watchdog_result

        red_sha = self._state.get_last_rc_red_sha()
        if not red_sha:
            return {"status": "no_red"}

        if red_sha in self._processed_dedup.get():
            self._last_processed_rc_red_sha = red_sha
            return {"status": "already_processed", "sha": red_sha}

        probe_passed, probe_output = await self._run_bisect_probe(red_sha)
        if probe_passed:
            logger.warning(
                "StagingBisectLoop: second probe passed for %s — flake",
                red_sha,
            )
            self._state.increment_flake_reruns_total()
            self._processed_dedup.add(red_sha)
            self._last_processed_rc_red_sha = red_sha
            return {"status": "flake_dismissed", "sha": red_sha}

        result = await self._run_full_bisect_pipeline(red_sha, probe_output)
        self._processed_dedup.add(red_sha)
        self._last_processed_rc_red_sha = red_sha
        return result
```

- [ ] **Step 4: Run the integration tests**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py -v
```

Expected: all tests PASS including `TestPipelineIntegration`.

- [ ] **Step 5: Commit**

```bash
git add src/staging_bisect_loop.py tests/test_staging_bisect_loop.py
git commit -m "feat(bisect): wire full pipeline (bisect→attribute→revert→retry)"
```

---

### Task 18: Edge — invalid bisect range skips cleanly

**Files:**
- Modify: `tests/test_staging_bisect_loop.py`

Spec §6: "`StagingBisectLoop` — invalid bisect range" → skip with warning log, idempotent no-op. Already implemented in Task 17 (`except BisectRangeError`); add an explicit unit test.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_staging_bisect_loop.py`:

```python
class TestInvalidRange:
    @pytest.mark.asyncio
    async def test_invalid_range_logs_and_noops(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        from staging_bisect_loop import BisectRangeError

        loop, prs, state = _make_loop(tmp_path, monkeypatch)
        state.set_last_green_rc_sha("unreachable_sha")
        state.set_last_rc_red_sha_and_bump_cycle("red_sha")
        loop._run_bisect_probe = AsyncMock(return_value=(False, ""))  # type: ignore[attr-defined]
        loop._run_bisect = AsyncMock(side_effect=BisectRangeError("bad object"))  # type: ignore[attr-defined]
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="u")
        )

        caplog.set_level("WARNING")
        result = await loop._do_work()  # type: ignore[attr-defined]

        assert result == {"status": "invalid_bisect_range", "sha": "red_sha"}
        assert any(
            "invalid bisect range" in rec.message for rec in caplog.records
        )
```

- [ ] **Step 2: Run to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestInvalidRange -v
```

Expected: PASS (already implemented in Task 17).

- [ ] **Step 3: Commit**

```bash
git add tests/test_staging_bisect_loop.py
git commit -m "test(bisect): invalid range is idempotent no-op"
```

---

### Task 19: Five-checkpoint wiring — `ServiceRegistry` + `build_services`

**Files:**
- Modify: `src/service_registry.py:45-75` (imports), `src/service_registry.py:96-175` (dataclass fields), `src/service_registry.py:742-873` (instantiation + return)

- [ ] **Step 1: Add import**

In `src/service_registry.py`, after the `StagingPromotionLoop` import at line 75, add:

```python
from staging_bisect_loop import StagingBisectLoop
```

- [ ] **Step 2: Add the dataclass field**

In `src/service_registry.py`, after line 158 (`staging_promotion_loop: StagingPromotionLoop`), insert:

```python
    staging_bisect_loop: StagingBisectLoop
```

- [ ] **Step 3: Instantiate in `build_services`**

In `src/service_registry.py`, after the `staging_promotion_loop = ...` block (line 738-742), insert:

```python
    staging_bisect_loop = StagingBisectLoop(  # noqa: F841
        config=config,
        prs=prs,
        deps=loop_deps,
        state=state,
    )
```

- [ ] **Step 4: Pass to `ServiceRegistry(...)`**

In `src/service_registry.py`, in the return statement at the end of `build_services`, add after `staging_promotion_loop=staging_promotion_loop,`:

```python
        staging_bisect_loop=staging_bisect_loop,
```

- [ ] **Step 5: Commit**

```bash
git add src/service_registry.py
git commit -m "wire: StagingBisectLoop into ServiceRegistry"
```

---

### Task 20: Five-checkpoint wiring — orchestrator

**Files:**
- Modify: `src/orchestrator.py:138-159` (`bg_loop_registry`), `src/orchestrator.py:885-910` (run-loop list)

- [ ] **Step 1: Add to `bg_loop_registry`**

In `src/orchestrator.py:138-159`, after `"staging_promotion": svc.staging_promotion_loop,` at line 149, insert:

```python
            "staging_bisect": svc.staging_bisect_loop,
```

- [ ] **Step 2: Add to the run-loop list**

In `src/orchestrator.py:885-910`, after `("staging_promotion", self._svc.staging_promotion_loop.run),` at line 898, insert:

```python
            ("staging_bisect", self._svc.staging_bisect_loop.run),
```

- [ ] **Step 3: Commit**

```bash
git add src/orchestrator.py
git commit -m "wire: StagingBisectLoop into orchestrator run loops"
```

---

### Task 21: Five-checkpoint wiring — UI constants

**Files:**
- Modify: `src/ui/src/constants.js:252` (EDITABLE_INTERVAL_WORKERS), `src/ui/src/constants.js:259-274` (SYSTEM_WORKER_INTERVALS), `src/ui/src/constants.js:293-313` (BACKGROUND_WORKERS)

- [ ] **Step 1: Add to `EDITABLE_INTERVAL_WORKERS`**

In `src/ui/src/constants.js:252`, add `'staging_bisect'` to the Set:

```javascript
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'pr_unsticker', 'pipeline_poller', 'report_issue', 'worktree_gc', 'adr_reviewer', 'epic_sweeper', 'dependabot_merge', 'staging_promotion', 'staging_bisect', 'stale_issue', 'security_patch', 'ci_monitor', 'code_grooming', 'sentry_ingest', 'retrospective'])
```

- [ ] **Step 2: Add to `SYSTEM_WORKER_INTERVALS`**

In `src/ui/src/constants.js:259-274`, after `staging_promotion: 300,` at line 268, insert:

```javascript
  staging_bisect: 600,
```

- [ ] **Step 3: Add to `BACKGROUND_WORKERS`**

In `src/ui/src/constants.js:293-313`, after the `staging_promotion` entry at line 303, insert:

```javascript
  { key: 'staging_bisect', label: 'Staging Bisect', description: 'Bisects the culprit PR on RC-red, files auto-revert + retry issue, watchdogs the next RC. See ADR-0042 §4.3.', color: theme.red, group: 'operations', tags: ['release', 'recovery'] },
```

- [ ] **Step 4: Commit**

```bash
git add src/ui/src/constants.js
git commit -m "wire: staging_bisect in UI constants"
```

---

### Task 22: Five-checkpoint wiring — route bounds

**Files:**
- Modify: `src/dashboard_routes/_common.py:54`

- [ ] **Step 1: Add to `_INTERVAL_BOUNDS`**

In `src/dashboard_routes/_common.py:54`, after `"staging_promotion": (60, 86400),`, insert:

```python
    "staging_bisect": (60, 86400),
```

- [ ] **Step 2: Run the wiring completeness test**

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: all tests PASS — the auto-discovery picks up `StagingBisectLoop` and finds it in all four checkpoint tables.

- [ ] **Step 3: Commit**

```bash
git add src/dashboard_routes/_common.py
git commit -m "wire: staging_bisect in route interval bounds"
```

---

### Task 23: E2E — three-commit fixture repo

**Files:**
- Modify: `tests/test_staging_bisect_loop.py`

Spec §7 "End-to-end per subsystem": drive a three-commit fixture repo through the bisect with mocked `gh`, asserting the correct culprit and issue titles.

- [ ] **Step 1: Write the failing E2E test**

Append to `tests/test_staging_bisect_loop.py`:

```python
import subprocess


def _init_three_commit_repo(repo_root: Path) -> tuple[str, str, str]:
    """Create a git repo with three commits: good, culprit (bad), bad.

    Returns ``(good_sha, culprit_sha, head_sha)``.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=repo_root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"], cwd=repo_root, check=True
    )
    (repo_root / "probe.sh").write_text("#!/bin/sh\nexit 0\n")
    (repo_root / "probe.sh").chmod(0o755)
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "good"], cwd=repo_root, check=True
    )
    good = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()

    (repo_root / "probe.sh").write_text("#!/bin/sh\nexit 1\n")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "culprit — breaks probe"],
        cwd=repo_root,
        check=True,
    )
    culprit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()

    (repo_root / "unrelated.txt").write_text("unrelated\n")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "follow-up unrelated commit"],
        cwd=repo_root,
        check=True,
    )
    head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo_root, text=True
    ).strip()

    return good, culprit, head


class TestEndToEnd:
    @pytest.mark.asyncio
    async def test_e2e_three_commits_real_bisect(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Drive a real ``git bisect`` against a fixture repo.

        Uses a shell-script probe (``./probe.sh``) instead of
        ``make bisect-probe`` so the test does not pull in the full
        Makefile. The loop's ``_run_bisect`` is monkey-patched to invoke
        the script; everything else uses the real method.
        """
        repo_root = tmp_path / "fixture_repo"
        repo_root.mkdir()
        good, culprit, head = _init_three_commit_repo(repo_root)

        monkeypatch.setenv("HYDRAFLOW_STAGING_ENABLED", "true")
        cfg = HydraFlowConfig(
            repo_root=repo_root,
            workspace_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
            data_root=tmp_path / "data",
        )
        stop_event = asyncio.Event()

        async def _sleep(_s: float) -> None:
            return None

        loop_deps = LoopDeps(
            event_bus=EventBus(),
            stop_event=stop_event,
            status_cb=MagicMock(),
            enabled_cb=lambda _n: True,
            sleep_fn=_sleep,
        )
        prs = MagicMock()
        prs.create_issue = AsyncMock(return_value=654)
        prs.find_open_promotion_pr = AsyncMock(
            return_value=MagicMock(number=77, url="https://example/pull/77")
        )
        state = StateTracker(state_file=tmp_path / "s.json")
        state.set_last_green_rc_sha(good)
        state.set_last_rc_red_sha_and_bump_cycle(head)

        from staging_bisect_loop import StagingBisectLoop

        loop = StagingBisectLoop(config=cfg, prs=prs, deps=loop_deps, state=state)

        # Probe: first run fails (confirms the red); bisect will use probe.sh
        async def probe(rc_sha: str):
            out = subprocess.run(
                ["./probe.sh"], cwd=repo_root, capture_output=True, text=True
            )
            return out.returncode == 0, out.stdout + out.stderr

        loop._run_bisect_probe = probe  # type: ignore[attr-defined]

        # Override bisect to invoke probe.sh directly (no Makefile)
        original_run_bisect = loop._run_bisect  # type: ignore[attr-defined]

        async def patched_run_bisect(green: str, red: str) -> str:
            # Use a private branch so bisect does not wander the live repo
            # Rely on the real implementation but point it at probe.sh
            return await original_run_bisect(green, red)

        # Stub worktree: run bisect in-place on the fixture repo
        async def fake_setup(rc_sha: str):
            return repo_root

        async def fake_cleanup(_wt):
            return None

        loop._setup_worktree = fake_setup  # type: ignore[attr-defined]
        loop._cleanup_worktree = fake_cleanup  # type: ignore[attr-defined]

        # Redirect bisect probe command to probe.sh
        async def patched_run_git(cmd, *, cwd, timeout):
            if cmd[:2] == ["git", "bisect"] and "run" in cmd:
                cmd = ["git", "bisect", "run", str(repo_root / "probe.sh")]
            proc = subprocess.run(
                cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout
            )
            return proc.returncode, proc.stdout, proc.stderr

        loop._run_git = patched_run_git  # type: ignore[attr-defined]

        loop._attribute_culprit = AsyncMock(  # type: ignore[attr-defined]
            return_value=(321, "culprit — breaks probe")
        )
        loop._create_revert_pr = AsyncMock(return_value=(900, "auto-revert/pr-321-rc-abc"))  # type: ignore[attr-defined]

        result = await loop._do_work()  # type: ignore[attr-defined]

        # Hardening: the test must prove bisect identified the culprit by
        # asserting _attribute_culprit was called with the right SHA.
        attribution_args = loop._attribute_culprit.await_args.args  # type: ignore[attr-defined]
        assert attribution_args[0].startswith(culprit[:7])
        assert result["status"] == "reverted"
        assert result["revert_pr"] == 900
        assert result["retry_issue"] == 654

        # git cleanup — leave bisect unset so teardown doesn't complain
        subprocess.run(["git", "bisect", "reset"], cwd=repo_root, check=False)
```

- [ ] **Step 2: Run the E2E test**

```bash
PYTHONPATH=src uv run pytest tests/test_staging_bisect_loop.py::TestEndToEnd -v
```

Expected: PASS. If bisect isolation is finicky, the fixture `git bisect reset` at the end handles teardown.

- [ ] **Step 3: Commit**

```bash
git add tests/test_staging_bisect_loop.py
git commit -m "test(bisect): E2E against three-commit fixture repo"
```

---

### Task 24: Verify the loop-wiring completeness test accepts `StagingBisectLoop`

**Files:**
- Verify-only: `tests/test_loop_wiring_completeness.py`

The test auto-discovers; no new entries needed. But run it end-to-end to prove each of the five checkpoints is satisfied.

- [ ] **Step 1: Run the completeness test**

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: every test PASS. Any failure indicates a missing checkpoint — re-read Tasks 19–22.

- [ ] **Step 2: Run the full loop-related test tree**

```bash
PYTHONPATH=src uv run pytest tests/test_state_staging_bisect.py tests/test_staging_promotion_loop.py tests/test_staging_bisect_loop.py tests/test_config_staging_promotion.py tests/test_loop_wiring_completeness.py -v
```

Expected: every test PASS.

- [ ] **Step 3: Run `make quality`**

```bash
make quality
```

Expected: all gates PASS.

- [ ] **Step 4: No commit needed — verification only.**

---

### Task 25: PR description + final commit

**Files:**
- (Nothing to modify — this task covers the PR creation.)

- [ ] **Step 1: Confirm branch status**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
git status
git log --oneline origin/main..HEAD
```

Expected: the branch shows Task 1–24 commits ahead of `origin/main`; working tree clean.

- [ ] **Step 2: Open PR**

```bash
git push -u origin trust-arch-hardening
gh pr create --title "feat: StagingBisectLoop — RC-red attribution + auto-revert (§4.3)" --body "$(cat <<'EOF'
## Summary
- Implements spec §4.3 "Staging-red attribution + auto-revert" end-to-end.
- Adds six `StateData` fields (`last_green_rc_sha`, `last_rc_red_sha`, `rc_cycle_id`, `auto_reverts_in_cycle`, `auto_reverts_successful`, `flake_reruns_total`) and the `StagingBisectStateMixin` accessors.
- Extends `StagingPromotionLoop` to write `last_green_rc_sha` on `promoted` and `last_rc_red_sha` (+ cycle bump) on `ci_failed` — the §8 prerequisite.
- Adds `make bisect-probe` mirroring the RC gate scenario job so `git bisect run` and the gate cannot diverge (§5).
- New `StagingBisectLoop` (`src/staging_bisect_loop.py`): state-tracker poll trigger, flake filter (`make bisect-probe` re-run), 45-minute-capped bisect in a dedicated worktree, PR attribution via `gh api commits/<sha>/pulls`, second-revert-in-cycle guardrail, auto-revert PR (`-m 1` for merges), `Retry:` issue, and 2-RC-cycle/8-hour outcome watchdog.
- Full five-checkpoint wiring (service registry, orchestrator, UI constants, route bounds, config).

## Test plan
- [x] Unit tests for the state mixin (`tests/test_state_staging_bisect.py`).
- [x] Unit tests for promotion-loop SHA writes on `promoted` and `ci_failed` paths.
- [x] Unit tests for every bisect subroutine (flake filter, bisect harness, attribution, guardrail, revert PR, retry issue, watchdog).
- [x] Edge-case tests: bisect timeout, invalid range, revert conflict.
- [x] E2E test with a three-commit fixture repo that drives the real `git bisect` to completion.
- [x] Loop-wiring completeness test still green (auto-discovery picks up the new loop).
- [x] `make quality` passes.

## Decisions locked in this PR
- **Event mechanism:** state-tracker poll (no event bus). Ticks every `staging_bisect_interval` (default 600s) and fires when `last_rc_red_sha` changes.
- **Runtime cap:** 45 min (`staging_bisect_runtime_cap_seconds = 2700`). Timeout → `hitl-escalation`, `bisect-timeout`.
- **Watchdog cap:** 2 RC cycles or 8 hours, whichever comes first.
- **`current_red_rc_sha`:** `PRManager.get_pr_head_sha(pr_number)` — the SHA CI actually ran against.
- **No LLM model override:** the loop makes no LLM calls.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Do NOT push to main.** Branch protection forbids it.

---

## Self-Review

**1. Spec coverage.** Walk §4.3:

| Spec requirement | Task(s) |
|---|---|
| `rc_red` event prerequisite (§8) | Task 3 + Task 4 (state-tracker poll instead of event) |
| `last_green_rc_sha` persisted (§8) | Task 1 + Task 3 |
| `StagingBisectLoop` as `BaseBackgroundLoop` subclass | Task 8 |
| Trigger detection (state-tracker poll) | Task 8 + Task 9 |
| Flake filter re-run (§4.3 step 1) | Task 10 |
| Bisect in dedicated worktree under `<data_root>/<repo_slug>/bisect/<rc_ref>/` (§4.3 step 2) | Task 11 |
| `git bisect run` against RC-gate command set — `make bisect-probe` (§4.3 step 2 + §5) | Task 6 + Task 11 |
| 45-minute runtime cap (§9 open question 5) | Task 7 + Task 11 (timeout branch) |
| Attribution via `gh api commits/<sha>/pulls` (§4.3 step 3) | Task 12 |
| Safety guardrail — second revert blocked (§4.3 step 4) | Task 13 |
| Revert branch `auto-revert/pr-{N}-rc-{YYYYMMDDHHMM}` (§4.3 step 5) | Task 14 |
| `git revert -m 1` for merges (§4.3 step 5 edge) | Task 14 (`_is_merge_commit` branch) |
| Revert PR title + body + labels (§4.3 step 5) | Task 14 |
| Retry issue `Retry: {original PR title}` (§4.3 step 6) | Task 15 |
| Auto-merge path (§4.3 step 7, §3.2) | implicit — labels route through standard reviewer |
| Outcome watchdog — green/still-red/timeout (§4.3 step 8) | Task 16 |
| Worktree cleanup (§4.3 step 9) | Task 11 (`_cleanup_worktree` in `finally`) |
| Revert conflict edge (§4.3 edge cases) | Task 14 + Task 17 |
| Invalid range edge (§4.3 idempotency) | Task 17 + Task 18 |
| Harness-failure edge (§4.3 error handling) | Task 17 |
| `DedupStore` idempotency (§4.3) | Task 9 + Task 17 |
| Five-checkpoint wiring (§4.3) | Tasks 19–22 |
| Config: `staging_bisect_interval` + no LLM override (§4.3) | Task 7 |
| Unit test `tests/test_staging_bisect_loop.py` (§7) | Tasks 8–18 |
| Loop-wiring completeness test (§7) | Task 24 |
| E2E three-commit fixture (§7) | Task 23 |

**Gaps identified and fixed.** None after walk-through.

**2. Placeholder scan.** All steps contain concrete code/commands. No "TBD", "fill in", or "similar to Task N" references. Each exception class (`BisectTimeoutError`, `BisectRangeError`, `BisectHarnessError`, `RevertConflictError`) is defined in Task 11 or 14 before it is referenced in Task 17.

**3. Type consistency.** State-field names are used identically in every task that reads them:

- `last_green_rc_sha` — Task 1 (field), Task 2 (accessor), Task 3 (writer in `StagingPromotionLoop`), Task 8 (ignored by skeleton), Task 17 (read at pipeline start).
- `last_rc_red_sha` — Task 1, Task 2 (`set_last_rc_red_sha_and_bump_cycle`), Task 4 (writer), Task 8 (poll trigger), Tasks 10+17.
- `rc_cycle_id` — Task 1, Task 2 (bumped in setter), Tasks 13+16 (guardrail + watchdog compare).
- `auto_reverts_in_cycle` — Task 1, Task 2 (`increment_auto_reverts_in_cycle`/`reset_auto_reverts_in_cycle`), Task 3 (reset on promoted), Task 13 (guardrail check), Task 17 (increment after revert).
- `auto_reverts_successful` — Task 1, Task 2 (`increment_auto_reverts_successful`), Task 16 (incremented on watchdog green).
- `flake_reruns_total` — Task 1, Task 2 (`increment_flake_reruns_total`), Task 10 + Task 17 (incremented on flake-dismiss).

Method names used consistently across tasks:
- `_run_bisect_probe` — Task 10 (added), Task 17 (called).
- `_run_bisect` — Task 11 (added), Task 17 (called), Task 23 (mocked/overridden in E2E).
- `_attribute_culprit` — Task 12 (added), Task 17 (called).
- `_check_guardrail_and_maybe_escalate` — Task 13 (added), Task 17 (called).
- `_create_revert_pr` — Task 14 (added), Task 17 (called).
- `_file_retry_issue` — Task 15 (added), Task 17 (called).
- `_check_pending_watchdog` — Task 16 (added), Task 17 (called at top of `_do_work`).
- `_run_full_bisect_pipeline` — Task 10 (stub), Task 17 (replaced).
- `_run_git`, `_run_gh` — Task 11 + Task 12 (added).
- `_setup_worktree` / `_cleanup_worktree` — Task 11 (added), Task 23 (overridden in E2E).
- `_is_merge_commit`, `_create_pr_via_gh`, `_parse_failing_tests`, `_escalate_harness_failure` — all single-task signatures.

Config field names (`staging_bisect_interval`, `staging_bisect_runtime_cap_seconds`, `staging_bisect_watchdog_rc_cycles`) used identically in Task 7 (declared), Task 11 (runtime cap), Task 8 (interval), Task 16 (watchdog cycles).

Worker name string `"staging_bisect"` is used identically in: Task 8 (`super().__init__(worker_name=...)`), Task 20 (`bg_loop_registry` key), Task 20 (run-loop list), Task 21 (UI constants three locations), Task 22 (interval bounds), Task 24 (completeness auto-discovery).

No inconsistencies found.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-staging-red-attribution-bisect.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
