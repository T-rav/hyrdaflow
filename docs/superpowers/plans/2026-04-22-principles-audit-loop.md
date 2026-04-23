# Principles Audit Loop + Onboarding Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `PrinciplesAuditLoop` — the foundational caretaker that (a) runs `make audit` weekly against HydraFlow-self and every managed target repo, (b) diffs against a last-green snapshot and files `hydraflow-find` issues for every check_id regression, (c) blocks the factory pipeline on a newly-added managed repo until its P1–P5 structural checks pass, and (d) runs `make audit` on every PR via a new CI job so HydraFlow-self principle drift cannot land between weekly audits.

**Architecture:** A new `BaseBackgroundLoop` subclass (`src/principles_audit_loop.py`) runs on a weekly cadence (`principles_audit_interval=604800`), also triggerable on demand. A new pydantic v2 `ManagedRepo` config model plus a top-level `managed_repos: list[ManagedRepo]` field (with `HYDRAFLOW_MANAGED_REPOS` JSON env override) is the single source of truth for repos under factory management. A new `PrinciplesAuditStateMixin` on `StateTracker` persists `managed_repos_onboarding_status: dict[str, Literal["pending","blocked","ready"]]` and a per-repo `last_green_audit: dict[str, dict[str, Any]]` snapshot map. The loop reads `managed_repos` from config, diffs each current audit against the last-green snapshot for that slug, and files issues via `PRManager.create_issue`. `DedupStore` keyed on `(repo_slug, check_id, attempt_index)` holds escalation state; STRUCTURAL/BEHAVIORAL regressions escalate after 3 attempts, CULTURAL after 1. The kill-switch uses `LoopDeps.enabled_cb` with `worker_name="principles_audit"` — **no new config enabled field**. Telemetry flows through `trace_collector.emit_loop_subprocess_trace` (stubbed locally if Plan 6 hasn't landed). The orchestrator's pipeline dispatch skips any slug whose onboarding status is `blocked`. A new `audit` job in `.github/workflows/ci.yml` (or `rc-promotion-scenario.yml` per Task 0 benchmark) runs `make audit` on every PR.

**Tech Stack:** Python 3.11, `asyncio`, `pydantic` v2 (`ManagedRepo` BaseModel + `StateData` field), `git` (shallow checkout + fetch), `gh` CLI, `scripts.hydraflow_audit` (existing ADR-0044 runner), `pytest`, `pytest-asyncio`, `MagicMock`/`AsyncMock`, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md` §4.4 (full), §3.2 (escalation lifecycle + kill-switch), §12.2 (worker_name registry), §6 (fail-mode rows), §7 (unit tests), §11.1 (principles-as-foundation rationale).

**Decisions locked in this plan (spec deferred or implied):**

1. **State-mixin location:** `src/state/_principles_audit.py` (new), registered in the `StateTracker` MRO in `src/state/__init__.py`. Matches the mixin-per-domain pattern already established for `_ci_monitor`, `_sentry`, `_shape`, etc.
2. **Managed-repo audit checkout directory:** `<data_root>/<repo_slug>/audit-checkout/` — per-spec §4.4 step 1. Refreshed via `git fetch --depth 1 origin <main_branch>` when the directory already exists; created via `git clone --depth 1` otherwise.
3. **Snapshot storage path:** `<data_root>/<repo_slug>/audit/<YYYY-MM-DD>.json` (per-spec §4.4 step 1). Last-green reference lives in `StateTracker.last_green_audit[slug]` — a dict keyed by `check_id` → `"PASS"|"FAIL"|"WARN"|"NA"|"NOT_IMPLEMENTED"` so the diff is a simple set comparison.
4. **Attempt tracking:** `StateTracker.principles_drift_attempts: dict[str, int]` keyed by the dedup key `{slug}:{check_id}`. Incremented on every re-fire; escalation fires when it crosses the severity-specific threshold.
5. **Onboarding trigger:** the loop's `_do_work` first reconciles `config.managed_repos` against `state.managed_repos_onboarding_status`. Any slug present in config but missing from the state map (or currently `"pending"`) triggers an onboarding audit *before* the weekly drift sweep.
6. **HydraFlow-self slug:** `"hydraflow-self"` — a sentinel that means "audit the working tree at `config.repo_root`, not a managed checkout." Never added to `managed_repos`.
7. **No LLM model override:** the loop dispatches no LLM — `make audit` is pure Python; the filed issues are picked up by the standard factory implementer.
8. **Task 0 benchmark decision:** `make audit` p95 ≤ 30s → add `audit` job to `ci.yml` (per-PR). p95 > 30s → add to `rc-promotion-scenario.yml` (per-RC, slower feedback). The benchmark output is attached to the final PR body so the choice is visible.

---

## File Structure

| File | Role | Created / Modified |
|---|---|---|
| `src/models.py` | Add two fields to `StateData` (`managed_repos_onboarding_status`, `last_green_audit`, `principles_drift_attempts`) — ref `src/models.py:1688-1767` | Modify |
| `src/state/_principles_audit.py` | New `PrinciplesAuditStateMixin` — getters/setters/incrementers for the three new state fields | Create |
| `src/state/__init__.py` | Register mixin in imports (line 28-46) and `StateTracker` MRO (line 55-75) | Modify |
| `src/config.py` | Add `ManagedRepo` BaseModel, `managed_repos` field on `HydraFlowConfig`, `principles_audit_interval` field, JSON env override for `HYDRAFLOW_MANAGED_REPOS`, INT env override for `HYDRAFLOW_PRINCIPLES_AUDIT_INTERVAL` | Modify |
| `src/principles_audit_loop.py` | New `BaseBackgroundLoop` subclass — onboarding reconcile, HydraFlow-self audit, managed-repo audit, diff, filing, escalation, dedup, telemetry | Create |
| `src/orchestrator.py` | Skip blocked repos in pipeline dispatch (Task 5). Add `principles_audit` to `bg_loop_registry` dict (line 138-159) + run-loop list (line 879-910) | Modify |
| `src/service_registry.py` | Add `principles_audit_loop: PrinciplesAuditLoop` dataclass field + wire in `build_services()` | Modify |
| `src/ui/src/constants.js` | Add `principles_audit` to `BACKGROUND_WORKERS`, `SYSTEM_WORKER_INTERVALS`, `EDITABLE_INTERVAL_WORKERS` | Modify |
| `src/dashboard_routes/_common.py` | Add `principles_audit` to `_INTERVAL_BOUNDS` | Modify |
| `.github/workflows/ci.yml` **or** `.github/workflows/rc-promotion-scenario.yml` | New `audit` job per Task 0 decision | Modify |
| `tests/test_config_managed_repos.py` | Unit test for `ManagedRepo` + `managed_repos` field + JSON env override | Create |
| `tests/test_state_principles_audit.py` | Unit test for the new mixin | Create |
| `tests/test_orchestrator_blocked_repos.py` | Unit test that blocked slugs are skipped in pipeline dispatch | Create |
| `tests/test_principles_audit_loop.py` | Unit tests for loop skeleton, diff, filing, escalation, onboarding transitions | Create |
| `tests/scenarios/test_principles_audit_scenario.py` | MockWorld scenario covering onboarding-blocked + drift-regression paths | Create |
| `tests/test_loop_wiring_completeness.py` | Implicitly picks up the new loop via regex auto-discovery — Task 20 verifies | Covered by Task 20 |
| `docs/bench/principles-audit-benchmark.md` | Task 0 benchmark record | Create |

---

### Task 0: Benchmark `make audit` runtime, decide CI placement

**Files:**
- Create: `docs/bench/principles-audit-benchmark.md`

Spec §4.4 sets a 30-second p95 budget for adding `make audit` to every-PR CI; over budget and the gate moves to the RC workflow.

- [ ] **Step 1: Run the benchmark**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/trust-arch-hardening
for i in 1 2 3 4 5; do
  /usr/bin/time -p make audit > /dev/null 2>bench-$i.txt
  grep real bench-$i.txt
done
rm bench-*.txt
```

Record each "real" value in seconds.

- [ ] **Step 2: Compute p50/p95**

```bash
python3 -c "
import statistics
xs = sorted([float(x) for x in input('enter 5 space-separated seconds: ').split()])
print(f'p50={statistics.median(xs):.2f}s p95={xs[-1]:.2f}s')
"
```

- [ ] **Step 3: Write the benchmark record**

Create `docs/bench/principles-audit-benchmark.md`:

```markdown
# `make audit` runtime benchmark

Captured: <DATE>
Runs: 5
Host: <`uname -a` one-line>

| Run | Wall-clock (s) |
|---|---|
| 1 | <value> |
| 2 | <value> |
| 3 | <value> |
| 4 | <value> |
| 5 | <value> |

**p50:** <value>s
**p95:** <value>s

**Budget:** 30s (spec §4.4 "Runtime budget for the CI gate").

**Decision:**
- p95 ≤ 30s → add `audit` job to `.github/workflows/ci.yml` (Task 17a).
- p95 > 30s → add `audit` job to `.github/workflows/rc-promotion-scenario.yml` instead (Task 17b).

**Selected:** ci.yml | rc-promotion-scenario.yml (strike one)
```

- [ ] **Step 4: Commit**

```bash
git add docs/bench/principles-audit-benchmark.md
git commit -m "docs(bench): record make audit runtime for CI placement decision"
```

---

### Task 1: Add `ManagedRepo` config model + `managed_repos` field + JSON env override

**Files:**
- Modify: `src/config.py` (add model class near `Credentials` at line 28-69, add field on `HydraFlowConfig` at line 328, add JSON env override block in `_apply_env_overrides` near line 2238)

- [ ] **Step 1: Write the failing test**

Create `tests/test_config_managed_repos.py`:

```python
"""Tests for the ManagedRepo config model + managed_repos field + JSON env override."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from config import HydraFlowConfig, ManagedRepo, _apply_env_overrides


def test_managed_repo_defaults():
    repo = ManagedRepo(slug="acme/widget")
    assert repo.slug == "acme/widget"
    assert repo.staging_branch == "staging"
    assert repo.main_branch == "main"
    assert repo.labels_namespace == ""
    assert repo.enabled is True


def test_managed_repo_rejects_bad_slug():
    with pytest.raises(ValueError):
        ManagedRepo(slug="not-a-slug")


def test_hydraflow_config_has_managed_repos_field():
    cfg = HydraFlowConfig()
    assert cfg.managed_repos == []


def test_hydraflow_managed_repos_json_env_override():
    payload = '[{"slug":"acme/widget","enabled":false}]'
    with patch.dict(os.environ, {"HYDRAFLOW_MANAGED_REPOS": payload}):
        cfg = HydraFlowConfig()
        _apply_env_overrides(cfg)
    assert len(cfg.managed_repos) == 1
    assert cfg.managed_repos[0].slug == "acme/widget"
    assert cfg.managed_repos[0].enabled is False


def test_hydraflow_principles_audit_interval_default():
    cfg = HydraFlowConfig()
    assert cfg.principles_audit_interval == 604800
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_config_managed_repos.py -v
```

Expected: FAIL with `ImportError: cannot import name 'ManagedRepo'`.

- [ ] **Step 3: Add `ManagedRepo` BaseModel and `managed_repos` field to `src/config.py`**

In `src/config.py`, immediately after the `Credentials` class (after line 69), add:

```python
class ManagedRepo(BaseModel):
    """A GitHub repo under HydraFlow factory management.

    Source of truth for which repos the orchestrator dispatches
    pipelines against and which repos `PrinciplesAuditLoop` audits
    for drift + onboarding. See spec §4.4.
    """

    model_config = ConfigDict(frozen=True)

    slug: str = Field(description="GitHub slug 'owner/repo'")
    staging_branch: str = "staging"
    main_branch: str = "main"
    labels_namespace: str = ""
    enabled: bool = Field(
        default=True,
        description="Operator kill-switch per repo; disabled repos are skipped",
    )

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, v: str) -> str:
        if "/" not in v or len(v.split("/")) != 2 or not all(v.split("/")):
            raise ValueError(f"invalid slug {v!r}; expected 'owner/repo'")
        return v
```

In `HydraFlowConfig` (line 328+), add the field next to other top-level `list[...]` fields:

```python
    managed_repos: list[ManagedRepo] = Field(
        default_factory=list,
        description="Repos under HydraFlow factory management (spec §4.4)",
    )

    principles_audit_interval: int = Field(
        default=604800,
        ge=60,
        description=(
            "Seconds between PrinciplesAuditLoop ticks. "
            "Default 604800 = 7 days (spec §4.4)."
        ),
    )
```

- [ ] **Step 4: Add env override handling**

Modify `src/config.py:165-175` — add to the `_ENV_INT_OVERRIDES` tuple list (after `retrospective_interval`):

```python
    ("principles_audit_interval", "HYDRAFLOW_PRINCIPLES_AUDIT_INTERVAL", 604800),
```

Modify `src/config.py:2238-2360` — at the end of `_apply_env_overrides(config)`, after the existing int/str/float/bool loops, append the JSON-shaped override:

```python
    # JSON-shaped overrides (spec §4.4 — managed repos)
    mr_raw = _get_env("HYDRAFLOW_MANAGED_REPOS")
    if mr_raw:
        try:
            decoded = json.loads(mr_raw)
            if isinstance(decoded, list):
                config.managed_repos = [ManagedRepo(**item) for item in decoded]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Ignoring malformed HYDRAFLOW_MANAGED_REPOS: %s", exc
            )
```

- [ ] **Step 5: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_config_managed_repos.py -v
```

Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config_managed_repos.py
git commit -m "feat(config): ManagedRepo + managed_repos field + principles_audit_interval (§4.4)"
```

---

### Task 2: Config model test — merged into Task 1

`tests/test_config_managed_repos.py` (4 cases) was written + committed as part of Task 1. Run `make quality` after Task 1; fix + amend if ruff/pyright flag anything.

---

### Task 3: Add `managed_repos_onboarding_status` + `last_green_audit` + `principles_drift_attempts` to `StateData`

**Files:**
- Modify: `src/models.py:1688-1767` — add three fields to `StateData`

- [ ] **Step 1: Write the failing test**

Create `tests/test_state_principles_audit.py`:

```python
"""Tests for PrinciplesAuditStateMixin fields + accessors."""

from __future__ import annotations

from pathlib import Path

from state import StateTracker


def test_state_data_has_principles_audit_fields(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    data = tracker._data  # type: ignore[attr-defined]
    assert data.managed_repos_onboarding_status == {}
    assert data.last_green_audit == {}
    assert data.principles_drift_attempts == {}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_state_principles_audit.py::test_state_data_has_principles_audit_fields -v
```

Expected: FAIL with `AttributeError: 'StateData' object has no attribute 'managed_repos_onboarding_status'`.

- [ ] **Step 3: Add the three fields to `StateData` in `src/models.py`**

In `src/models.py`, after line 1766 (`trace_runs:`) and before `last_updated:` at line 1767, insert:

```python
    # PrinciplesAuditLoop state (spec §4.4).
    # Keys are repo slugs ("owner/repo"); sentinel "hydraflow-self" = working tree.
    managed_repos_onboarding_status: dict[
        str, Literal["pending", "blocked", "ready"]
    ] = Field(default_factory=dict)
    # last_green_audit[slug] maps check_id -> status string (PASS/WARN/FAIL/NA/
    # NOT_IMPLEMENTED). The loop diffs the current audit against this reference.
    last_green_audit: dict[str, dict[str, str]] = Field(default_factory=dict)
    # principles_drift_attempts[f"{slug}:{check_id}"] = attempt count.
    # STRUCTURAL/BEHAVIORAL escalate at 3; CULTURAL at 1.
    principles_drift_attempts: dict[str, int] = Field(default_factory=dict)
```

`Literal` is already imported at `src/models.py:14-15`.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_state_principles_audit.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/models.py tests/test_state_principles_audit.py
git commit -m "feat(state): add three fields for PrinciplesAuditLoop (§4.4)"
```

---

### Task 4: Add `PrinciplesAuditStateMixin` with accessors

**Files:**
- Create: `src/state/_principles_audit.py`
- Modify: `src/state/__init__.py:28-46` (imports), `src/state/__init__.py:55-75` (MRO)

- [ ] **Step 1: Extend the failing test**

Append to `tests/test_state_principles_audit.py`:

```python
def test_onboarding_status_setter_roundtrip(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.set_onboarding_status("acme/widget", "pending")
    assert tracker.get_onboarding_status("acme/widget") == "pending"
    assert tracker.get_onboarding_status("nope/nope") is None
    tracker.set_onboarding_status("acme/widget", "ready")
    assert tracker.get_onboarding_status("acme/widget") == "ready"


def test_last_green_audit_roundtrip(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    tracker.set_last_green_audit("hydraflow-self", {"P1.1": "PASS", "P2.4": "PASS"})
    assert tracker.get_last_green_audit("hydraflow-self") == {
        "P1.1": "PASS",
        "P2.4": "PASS",
    }
    assert tracker.get_last_green_audit("missing") == {}


def test_drift_attempts_increment_and_reset(tmp_path: Path) -> None:
    tracker = StateTracker(state_file=tmp_path / "state.json")
    assert tracker.get_drift_attempts("acme/widget", "P1.1") == 0
    assert tracker.increment_drift_attempts("acme/widget", "P1.1") == 1
    assert tracker.increment_drift_attempts("acme/widget", "P1.1") == 2
    tracker.reset_drift_attempts("acme/widget", "P1.1")
    assert tracker.get_drift_attempts("acme/widget", "P1.1") == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
PYTHONPATH=src uv run pytest tests/test_state_principles_audit.py -v
```

Expected: 3 FAILs with `AttributeError: 'StateTracker' object has no attribute 'set_onboarding_status'`.

- [ ] **Step 3: Create the mixin**

Create `src/state/_principles_audit.py`:

```python
"""PrinciplesAuditLoop state: onboarding status, last-green audit, drift attempts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from models import StateData

logger = logging.getLogger("hydraflow.state")

_OnboardingStatus = Literal["pending", "blocked", "ready"]


class PrinciplesAuditStateMixin:
    """Getters/setters for PrinciplesAuditLoop state (spec §4.4)."""

    _data: StateData

    def save(self) -> None: ...  # provided by core StateTracker

    # --- onboarding status ---

    def get_onboarding_status(self, slug: str) -> _OnboardingStatus | None:
        return self._data.managed_repos_onboarding_status.get(slug)

    def set_onboarding_status(self, slug: str, status: _OnboardingStatus) -> None:
        self._data.managed_repos_onboarding_status[slug] = status
        self.save()

    def blocked_slugs(self) -> set[str]:
        return {
            slug
            for slug, status in self._data.managed_repos_onboarding_status.items()
            if status == "blocked"
        }

    # --- last-green audit snapshot ---

    def get_last_green_audit(self, slug: str) -> dict[str, str]:
        return dict(self._data.last_green_audit.get(slug, {}))

    def set_last_green_audit(self, slug: str, snapshot: dict[str, str]) -> None:
        self._data.last_green_audit[slug] = dict(snapshot)
        self.save()

    # --- drift attempts ---

    @staticmethod
    def _attempt_key(slug: str, check_id: str) -> str:
        return f"{slug}:{check_id}"

    def get_drift_attempts(self, slug: str, check_id: str) -> int:
        return self._data.principles_drift_attempts.get(
            self._attempt_key(slug, check_id), 0
        )

    def increment_drift_attempts(self, slug: str, check_id: str) -> int:
        key = self._attempt_key(slug, check_id)
        n = self._data.principles_drift_attempts.get(key, 0) + 1
        self._data.principles_drift_attempts[key] = n
        self.save()
        return n

    def reset_drift_attempts(self, slug: str, check_id: str) -> None:
        self._data.principles_drift_attempts.pop(
            self._attempt_key(slug, check_id), None
        )
        self.save()
```

- [ ] **Step 4: Register the mixin**

In `src/state/__init__.py`, add the import alongside the other mixin imports (line 28-46):

```python
from ._principles_audit import PrinciplesAuditStateMixin
```

In the `StateTracker` MRO block (line 55-75), add `PrinciplesAuditStateMixin` to the inheritance list just after `WorkerStateMixin`:

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
    PrinciplesAuditStateMixin,
    ReportStateMixin,
    # ... existing mixins
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
PYTHONPATH=src uv run pytest tests/test_state_principles_audit.py -v
```

Expected: all 4 PASS.

- [ ] **Step 6: Commit**

```bash
git add src/state/_principles_audit.py src/state/__init__.py tests/test_state_principles_audit.py
git commit -m "feat(state): PrinciplesAuditStateMixin — onboarding + drift accessors (§4.4)"
```

---

### Task 5: Orchestrator skips blocked repos in pipeline dispatch

**Files:**
- Modify: `src/orchestrator.py` (pipeline loop handlers `_plan_loop`, `_implement_loop`, `_review_loop`, `_triage_loop`, `_discover_loop`, `_shape_loop`, `_hitl_loop` — line 1075-1142)

For single-repo HydraFlow-self runs this is a no-op; it only engages when `managed_repos` contains entries. The check is centralized on a new `_is_slug_blocked(slug)` helper used wherever a repo slug is dispatched.

- [ ] **Step 1: Write the failing test (Task 6 bundled here for TDD)**

Create `tests/test_orchestrator_blocked_repos.py`:

```python
"""Blocked managed repos are skipped in the pipeline dispatch loop."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from orchestrator import HydraFlowOrchestrator


def test_is_slug_blocked_reads_state_tracker():
    state = MagicMock()
    state.blocked_slugs.return_value = {"acme/widget"}
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state
    assert orch._is_slug_blocked("acme/widget") is True
    assert orch._is_slug_blocked("acme/other") is False
    assert orch._is_slug_blocked("hydraflow-self") is False


def test_is_slug_blocked_empty_state():
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    orch = HydraFlowOrchestrator.__new__(HydraFlowOrchestrator)
    orch._state = state
    assert orch._is_slug_blocked("anything") is False
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_orchestrator_blocked_repos.py -v
```

Expected: FAIL with `AttributeError: ... has no attribute '_is_slug_blocked'`.

- [ ] **Step 3: Add `_is_slug_blocked` and wire it into dispatch**

In `src/orchestrator.py`, inside `HydraFlowOrchestrator` (after `_has_active_processes` near line 258), add:

```python
    def _is_slug_blocked(self, slug: str) -> bool:
        """Return True if this repo slug is blocked by onboarding gate (§4.4)."""
        return slug in self._state.blocked_slugs()
```

Modify `src/orchestrator.py:1105-1123` (the `_plan_loop` / `_implement_loop` / `_review_loop` bodies) — they currently dispatch via `self._svc.planner_phase.plan_issues`. These run against `config.repo` (HydraFlow-self) today; multi-repo fan-out lands with a later plan. For now, add a guard at the top of each `_polling_loop` wrapper's work callback:

In `src/orchestrator.py`, add a helper near line 1075:

```python
    async def _pipeline_work_wrapper(
        self, slug: str, inner: Callable[[], Coroutine[Any, Any, bool]]
    ) -> bool:
        """Skip this cycle if slug is onboarding-blocked (§4.4)."""
        if self._is_slug_blocked(slug):
            logger.debug("Skipping %s — onboarding blocked", slug)
            return False
        return await inner()
```

Then inside each of `_plan_loop`, `_implement_loop`, `_review_loop`, `_triage_loop`, `_discover_loop`, `_shape_loop`, replace the direct work callable with a wrapper. For example `_plan_loop` (line 1105-1113):

```python
    async def _plan_loop(self) -> None:
        """Continuously poll for planner-labeled issues."""

        async def _work() -> bool:
            return await self._pipeline_work_wrapper(
                self._config.repo, self._svc.planner_phase.plan_issues
            )

        await self._polling_loop(
            "plan",
            _work,
            self._config.poll_interval,
            enabled_name="plan",
            is_pipeline=True,
        )
```

Apply the same shape to `_implement_loop`, `_review_loop`, `_triage_loop`, `_discover_loop`, `_shape_loop`, `_hitl_loop`. Each uses `self._config.repo` as the slug because multi-repo dispatch is not yet wired; when it is, the slug argument changes but the gate stays identical.

- [ ] **Step 4: Run Task-6 test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_orchestrator_blocked_repos.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator_blocked_repos.py
git commit -m "feat(orchestrator): skip onboarding-blocked slugs in pipeline dispatch (§4.4)"
```

---

### Task 6: Orchestrator block-skip test — merged into Task 5

Covered in Task 5's commit.

---

### Task 7: `PrinciplesAuditLoop` skeleton

**Files:**
- Create: `src/principles_audit_loop.py`

This task creates the loop shell with `worker_name="principles_audit"`, `_get_default_interval`, an empty `_do_work` that emits `{"status": "noop"}`. Subsequent tasks fill it in.

- [ ] **Step 1: Write the failing test (Task 8 bundled here)**

Create `tests/test_principles_audit_loop.py`:

```python
"""Tests for PrinciplesAuditLoop."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig, ManagedRepo
from events import EventBus
from principles_audit_loop import PrinciplesAuditLoop


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    cfg.managed_repos = []
    state = MagicMock()
    state.blocked_slugs.return_value = set()
    state.get_onboarding_status.return_value = None
    state.get_last_green_audit.return_value = {}
    state.get_drift_attempts.return_value = 0
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    return cfg, state, pr_manager


def test_skeleton_worker_name_and_interval(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(
        config=cfg,
        state=state,
        pr_manager=pr,
        deps=_deps(stop),
    )
    assert loop._worker_name == "principles_audit"  # type: ignore[attr-defined]
    assert loop._get_default_interval() == 604800  # spec §4.4
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=src uv run pytest tests/test_principles_audit_loop.py::test_skeleton_worker_name_and_interval -v
```

Expected: FAIL with `ImportError: cannot import name 'PrinciplesAuditLoop'`.

- [ ] **Step 3: Create the skeleton**

Create `src/principles_audit_loop.py`:

```python
"""PrinciplesAuditLoop — weekly ADR-0044 drift detector + onboarding gate.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.4. Foundational caretaker — enforces principle conformance on
HydraFlow-self and every managed target repo before the other trust
subsystems take effect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig, ManagedRepo
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.principles_audit_loop")

_HYDRAFLOW_SELF = "hydraflow-self"
_STRUCTURAL_ATTEMPTS = 3
_BEHAVIORAL_ATTEMPTS = 3
_CULTURAL_ATTEMPTS = 1


class PrinciplesAuditLoop(BaseBackgroundLoop):
    """Weekly audit against ADR-0044 + onboarding trigger (spec §4.4)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="principles_audit",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager

    def _get_default_interval(self) -> int:
        return self._config.principles_audit_interval

    async def _do_work(self) -> WorkCycleResult:
        """One audit cycle: onboarding reconcile, HydraFlow-self, managed repos."""
        stats: dict[str, Any] = {
            "onboarded": 0,
            "audited": 0,
            "regressions_filed": 0,
            "escalations_filed": 0,
            "ready_flips": 0,
        }
        return stats
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=src uv run pytest tests/test_principles_audit_loop.py::test_skeleton_worker_name_and_interval -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): PrinciplesAuditLoop skeleton (§4.4)"
```

---

### Task 8: Skeleton test — merged into Task 7

Covered.

---

### Task 9: HydraFlow-self audit + snapshot save

**Files:**
- Modify: `src/principles_audit_loop.py` — add `_audit_hydraflow_self` + `_save_snapshot`
- Modify: `tests/test_principles_audit_loop.py` — add coverage

- [ ] **Step 1: Write the failing test**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_audit_hydraflow_self_saves_snapshot(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    fake_findings = [
        {"check_id": "P1.1", "status": "PASS", "severity": "STRUCTURAL",
         "principle": "P1", "source": "docs/adr", "what": "doc exists",
         "remediation": "write docs", "message": ""},
        {"check_id": "P2.4", "status": "PASS", "severity": "BEHAVIORAL",
         "principle": "P2", "source": "Makefile", "what": "target runs",
         "remediation": "fix target", "message": ""},
    ]

    async def fake_run_audit(slug, repo_root):
        return {"summary": {}, "findings": fake_findings}

    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)

    snapshot = await loop._audit_hydraflow_self()
    assert snapshot == {"P1.1": "PASS", "P2.4": "PASS"}
    snap_dir = cfg.data_root / "hydraflow-self" / "audit"
    saved = list(snap_dir.glob("*.json"))
    assert len(saved) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL with `AttributeError: ... '_audit_hydraflow_self'`.

- [ ] **Step 3: Implement `_run_audit` and `_audit_hydraflow_self`**

Append to `src/principles_audit_loop.py` inside `PrinciplesAuditLoop`:

```python
    async def _run_audit(
        self, slug: str, repo_root: Path
    ) -> dict[str, Any]:
        """Invoke `make audit` → JSON report. Returns parsed report dict."""
        proc = await asyncio.create_subprocess_exec(
            "make",
            "audit-json",
            f"DIR={repo_root}",
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):  # audit uses 1 for "failures present"
            logger.warning(
                "make audit-json exit=%d for %s: %s",
                proc.returncode,
                slug,
                stderr.decode(errors="replace")[:400],
            )
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"audit-json emitted non-JSON for {slug}: {exc}"
            ) from exc

    def _snapshot_from_report(self, report: dict[str, Any]) -> dict[str, str]:
        return {f["check_id"]: f["status"] for f in report.get("findings", [])}

    def _save_snapshot(self, slug: str, report: dict[str, Any]) -> Path:
        date = datetime.now(UTC).strftime("%Y-%m-%d")
        out = self._config.data_root / slug / "audit" / f"{date}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2))
        return out

    async def _audit_hydraflow_self(self) -> dict[str, str]:
        report = await self._run_audit(_HYDRAFLOW_SELF, self._config.repo_root)
        self._save_snapshot(_HYDRAFLOW_SELF, report)
        return self._snapshot_from_report(report)
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): HydraFlow-self audit + dated snapshot save (§4.4)"
```

---

### Task 10: Managed-repo shallow checkout + audit

**Files:**
- Modify: `src/principles_audit_loop.py` — add `_refresh_checkout` + `_audit_managed_repo`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_audit_managed_repo_clones_or_fetches(loop_env, tmp_path, monkeypatch):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    mr = ManagedRepo(slug="acme/widget")
    commands: list[list[str]] = []

    async def fake_run_git(*args, cwd=None):
        commands.append(list(args))
        return 0, ""

    async def fake_run_audit(slug, repo_root):
        return {"findings": [
            {"check_id": "P1.1", "status": "PASS", "severity": "STRUCTURAL",
             "principle": "P1", "source": "", "what": "", "remediation": "",
             "message": ""}
        ]}

    monkeypatch.setattr(loop, "_run_git", fake_run_git)
    monkeypatch.setattr(loop, "_run_audit", fake_run_audit)
    snap = await loop._audit_managed_repo(mr)
    assert snap == {"P1.1": "PASS"}
    # first run → clone
    assert any("clone" in c for c in commands)

    # second call with dir present → fetch
    (cfg.data_root / "acme/widget" / "audit-checkout").mkdir(parents=True, exist_ok=True)
    commands.clear()
    await loop._audit_managed_repo(mr)
    assert any("fetch" in c for c in commands)
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `_audit_managed_repo` undefined.

- [ ] **Step 3: Implement the method**

Append to `PrinciplesAuditLoop`:

```python
    async def _run_git(self, *args: str, cwd: Path | None = None) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        return proc.returncode or 0, out.decode(errors="replace")

    async def _refresh_checkout(self, mr: ManagedRepo) -> Path:
        """Shallow-clone or fetch the managed repo. Returns the checkout root."""
        checkout = self._config.data_root / mr.slug / "audit-checkout"
        if checkout.exists():
            code, out = await self._run_git(
                "fetch", "--depth", "1", "origin", mr.main_branch, cwd=checkout
            )
            if code != 0:
                raise RuntimeError(f"git fetch failed for {mr.slug}: {out[:400]}")
            await self._run_git("reset", "--hard", f"origin/{mr.main_branch}", cwd=checkout)
        else:
            checkout.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://github.com/{mr.slug}.git"
            code, out = await self._run_git(
                "clone", "--depth", "1", "--branch", mr.main_branch, url, str(checkout)
            )
            if code != 0:
                raise RuntimeError(f"git clone failed for {mr.slug}: {out[:400]}")
        return checkout

    async def _audit_managed_repo(self, mr: ManagedRepo) -> dict[str, str]:
        checkout = await self._refresh_checkout(mr)
        report = await self._run_audit(mr.slug, checkout)
        self._save_snapshot(mr.slug, report)
        return self._snapshot_from_report(report)
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): managed-repo shallow checkout + audit (§4.4)"
```

---

### Task 11: Pass/fail diff + check-type branching

**Files:**
- Modify: `src/principles_audit_loop.py` — add `_diff_regressions`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_principles_audit_loop.py`:

```python
def test_diff_regressions_identifies_pass_to_fail(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    last = {"P1.1": "PASS", "P2.4": "PASS", "P8.2": "WARN"}
    current = {"P1.1": "FAIL", "P2.4": "PASS", "P8.2": "FAIL"}
    regressions = loop._diff_regressions(last, current)
    # Only PASS→FAIL is a regression; WARN→FAIL is not (spec §4.4 "PASS to FAIL")
    assert set(regressions) == {"P1.1"}


def test_diff_regressions_no_reference_is_noop(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    # Empty last-green means "we don't know what green is yet" — no regressions.
    assert loop._diff_regressions({}, {"P1.1": "FAIL"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL — `_diff_regressions` missing.

- [ ] **Step 3: Implement the method**

```python
    @staticmethod
    def _diff_regressions(
        last_green: dict[str, str], current: dict[str, str]
    ) -> list[str]:
        """Return check_ids that went PASS→FAIL vs last-green (spec §4.4)."""
        if not last_green:
            return []
        return sorted(
            cid
            for cid, prev in last_green.items()
            if prev == "PASS" and current.get(cid) == "FAIL"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): PASS→FAIL diff against last-green snapshot (§4.4)"
```

---

### Task 12: Issue filing + severity-based escalation

**Files:**
- Modify: `src/principles_audit_loop.py` — add `_file_drift_issue`, `_maybe_escalate`, `_fire_for_slug`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_file_drift_issue_creates_hydraflow_find(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    finding = {
        "check_id": "P1.1", "severity": "STRUCTURAL", "principle": "P1",
        "source": "docs/adr/0001", "what": "doc exists",
        "remediation": "write docs", "message": "missing file",
    }
    issue_num = await loop._file_drift_issue("acme/widget", finding, "PASS")
    assert issue_num == 42
    pr.create_issue.assert_awaited_once()
    args = pr.create_issue.await_args.kwargs or pr.create_issue.await_args.args
    # title contains both slug and check_id
    call_args = pr.create_issue.await_args
    title = call_args.args[0] if call_args.args else call_args.kwargs["title"]
    assert "acme/widget" in title and "P1.1" in title


async def test_structural_escalates_after_three_attempts(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    state.increment_drift_attempts.side_effect = [1, 2, 3]
    # Three consecutive failures → third call fires escalation
    escalated_last = None
    for i in range(3):
        escalated = await loop._maybe_escalate("acme/widget", "P1.1", "STRUCTURAL")
        escalated_last = escalated
    assert escalated_last is True


async def test_cultural_escalates_after_one_attempt(loop_env):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    state.increment_drift_attempts.return_value = 1
    escalated = await loop._maybe_escalate("acme/widget", "P10.2", "CULTURAL")
    assert escalated is True
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: 3 FAILs.

- [ ] **Step 3: Implement filing + escalation**

Append to `PrinciplesAuditLoop`:

```python
    async def _file_drift_issue(
        self, slug: str, finding: dict[str, Any], last_status: str
    ) -> int:
        """File a `hydraflow-find` + `principles-drift` issue for one regression."""
        check_id = finding["check_id"]
        title = f"Principles drift: {check_id} regressed in {slug}"
        body = (
            f"**Principle:** {finding['principle']}\n"
            f"**Severity:** {finding['severity']}\n"
            f"**Source:** {finding['source']}\n"
            f"**Check:** {finding['what']}\n"
            f"**Remediation:** {finding['remediation']}\n\n"
            f"**Last-green status:** {last_status}\n"
            f"**Current status:** {finding['status']}\n"
            f"**Audit message:** {finding.get('message', '')}\n\n"
            f"Filed by PrinciplesAuditLoop (spec §4.4)."
        )
        labels = [
            "hydraflow-find",
            "principles-drift",
            f"check-{check_id}",
        ]
        return await self._pr.create_issue(title, body, labels)

    async def _maybe_escalate(
        self, slug: str, check_id: str, severity: str
    ) -> bool:
        """Increment attempt counter and file hitl-escalation if threshold reached."""
        attempts = self._state.increment_drift_attempts(slug, check_id)
        threshold = _CULTURAL_ATTEMPTS if severity == "CULTURAL" else _STRUCTURAL_ATTEMPTS
        if attempts < threshold:
            return False
        title = f"Principles drift stuck: {check_id} in {slug}"
        body = (
            f"PrinciplesAuditLoop has filed {attempts} repair issues for "
            f"`{check_id}` in `{slug}` without a successful remediation.\n\n"
            f"Severity: {severity}. Threshold: {threshold}.\n\n"
            f"Operator action required — verify the check, the ADR-0044 row, "
            f"and branch protection / review settings if applicable. "
            f"Closing this issue clears the attempt counter (§3.2 lifecycle)."
        )
        labels = [
            "hitl-escalation",
            "principles-stuck",
            f"check-{check_id}",
        ]
        if severity == "CULTURAL":
            labels.append("cultural-check")
        await self._pr.create_issue(title, body, labels)
        return True

    async def _fire_for_slug(
        self,
        slug: str,
        regressions: list[str],
        report: dict[str, Any],
        last_green: dict[str, str],
    ) -> dict[str, int]:
        """File drift issues + escalations for every regression on this slug."""
        stats = {"filed": 0, "escalated": 0}
        findings_by_id = {f["check_id"]: f for f in report.get("findings", [])}
        for check_id in regressions:
            finding = findings_by_id.get(check_id)
            if not finding:
                continue
            last_status = last_green.get(check_id, "PASS")
            await self._file_drift_issue(slug, finding, last_status)
            stats["filed"] += 1
            if await self._maybe_escalate(slug, check_id, finding["severity"]):
                stats["escalated"] += 1
        return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): drift-issue filing + severity-based escalation (§4.4)"
```

---

### Task 13: Diff + filing integration test — merged into Tasks 11–12

Unit tests in 11 + 12 cover diff and filing; scenario in Task 21 exercises end-to-end.

---

### Task 14: Onboarding detection + initial audit

**Files:**
- Modify: `src/principles_audit_loop.py` — add `_reconcile_onboarding`, `_p1_p5_fails`, `_run_onboarding_audit`

P1–P5 FAILs block; P6–P10 FAILs warn but do not block (§4.4 "P6–P10 FAILs warn but do not block").

- [ ] **Step 1: Write the failing test**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_onboarding_pending_triggers_initial_audit(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = None  # unseen → pending
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_audit(mr):
        # P1.1 FAIL (structural P1–P5) — must block
        return {"P1.1": "FAIL", "P6.1": "PASS"}

    async def fake_report(mr):
        return {
            "findings": [
                {"check_id": "P1.1", "status": "FAIL", "severity": "STRUCTURAL",
                 "principle": "P1", "source": "", "what": "", "remediation": "",
                 "message": ""},
                {"check_id": "P6.1", "status": "PASS", "severity": "BEHAVIORAL",
                 "principle": "P6", "source": "", "what": "", "remediation": "",
                 "message": ""},
            ]
        }

    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_report)

    await loop._reconcile_onboarding()

    state.set_onboarding_status.assert_called_with("acme/widget", "blocked")
    pr.create_issue.assert_awaited()  # onboarding-blocked issue filed


async def test_p1_p5_fails_filter():
    # Module-level helper check
    from principles_audit_loop import PrinciplesAuditLoop as PAL
    findings = [
        {"check_id": "P1.1", "status": "FAIL", "principle": "P1"},
        {"check_id": "P5.2", "status": "FAIL", "principle": "P5"},
        {"check_id": "P6.1", "status": "FAIL", "principle": "P6"},
        {"check_id": "P2.1", "status": "PASS", "principle": "P2"},
    ]
    assert PAL._p1_p5_fails(findings) == ["P1.1", "P5.2"]
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: 2 FAILs.

- [ ] **Step 3: Implement onboarding helpers**

Append to `PrinciplesAuditLoop`:

```python
    @staticmethod
    def _p1_p5_fails(findings: list[dict[str, Any]]) -> list[str]:
        """check_ids whose principle is P1–P5 and whose status is FAIL."""
        return [
            f["check_id"]
            for f in findings
            if f.get("status") == "FAIL" and f.get("principle") in {
                "P1", "P2", "P3", "P4", "P5",
            }
        ]

    async def _fetch_last_report(self, mr: ManagedRepo) -> dict[str, Any]:
        """Read the most recent saved report for this slug; re-audit if absent."""
        base = self._config.data_root / mr.slug / "audit"
        if not base.exists():
            checkout = await self._refresh_checkout(mr)
            return await self._run_audit(mr.slug, checkout)
        latest = max(base.glob("*.json"), default=None)
        if latest is None:
            checkout = await self._refresh_checkout(mr)
            return await self._run_audit(mr.slug, checkout)
        return json.loads(latest.read_text())

    async def _run_onboarding_audit(self, mr: ManagedRepo) -> None:
        """Audit a newly-added managed repo and set its onboarding status."""
        snapshot = await self._audit_managed_repo(mr)
        report = await self._fetch_last_report(mr)
        fails = self._p1_p5_fails(report.get("findings", []))
        if fails:
            self._state.set_onboarding_status(mr.slug, "blocked")
            await self._file_onboarding_issue(mr, fails, report)
        else:
            self._state.set_onboarding_status(mr.slug, "ready")
            self._state.set_last_green_audit(mr.slug, snapshot)

    async def _file_onboarding_issue(
        self,
        mr: ManagedRepo,
        fails: list[str],
        report: dict[str, Any],
    ) -> int:
        findings_by_id = {f["check_id"]: f for f in report.get("findings", [])}
        bullets = "\n".join(
            f"- **{cid}** ({findings_by_id[cid]['severity']}): "
            f"{findings_by_id[cid]['what']} — {findings_by_id[cid]['remediation']}"
            for cid in fails
        )
        title = f"Onboarding blocked: {mr.slug} fails P1–P5"
        body = (
            f"Managed repo `{mr.slug}` cannot enter the HydraFlow pipeline "
            f"until the following P1–P5 checks pass (spec §4.4):\n\n"
            f"{bullets}\n\n"
            f"Factory dispatch is blocked for this slug until a re-audit "
            f"reports all P1–P5 as PASS. Run `make audit DIR=<checkout>` "
            f"locally to reproduce."
        )
        return await self._pr.create_issue(
            title,
            body,
            labels=["hydraflow-find", "onboarding-blocked"],
        )

    async def _reconcile_onboarding(self) -> int:
        """For every managed_repos entry, ensure onboarding status is set."""
        count = 0
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            status = self._state.get_onboarding_status(mr.slug)
            if status is None:
                self._state.set_onboarding_status(mr.slug, "pending")
                await self._run_onboarding_audit(mr)
                count += 1
            elif status == "pending":
                await self._run_onboarding_audit(mr)
                count += 1
        return count
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): onboarding detection + P1–P5 blocking gate (§4.4)"
```

---

### Task 15: Onboarding ready-on-green flow + full `_do_work` assembly

**Files:**
- Modify: `src/principles_audit_loop.py` — fill `_do_work`, add `_retry_blocked` transition

- [ ] **Step 1: Write the failing test**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_blocked_flips_to_ready_on_green(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = [ManagedRepo(slug="acme/widget")]
    state.get_onboarding_status.return_value = "blocked"
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_audit(mr):
        return {"P1.1": "PASS", "P5.1": "PASS"}

    async def fake_report(mr):
        return {"findings": [
            {"check_id": "P1.1", "status": "PASS", "severity": "STRUCTURAL",
             "principle": "P1", "source": "", "what": "", "remediation": "",
             "message": ""},
            {"check_id": "P5.1", "status": "PASS", "severity": "STRUCTURAL",
             "principle": "P5", "source": "", "what": "", "remediation": "",
             "message": ""},
        ]}

    monkeypatch.setattr(loop, "_audit_managed_repo", fake_audit)
    monkeypatch.setattr(loop, "_fetch_last_report", fake_report)

    await loop._retry_blocked()

    # Should flip to ready and persist the snapshot as last_green.
    state.set_onboarding_status.assert_called_with("acme/widget", "ready")
    state.set_last_green_audit.assert_called_with("acme/widget",
                                                  {"P1.1": "PASS", "P5.1": "PASS"})


async def test_do_work_runs_end_to_end(loop_env, monkeypatch):
    cfg, state, pr = loop_env
    cfg.managed_repos = []
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))

    async def fake_self_audit():
        return {"P1.1": "PASS"}

    async def fake_report(slug, root):
        return {"findings": [
            {"check_id": "P1.1", "status": "PASS", "severity": "STRUCTURAL",
             "principle": "P1", "source": "", "what": "", "remediation": "",
             "message": ""},
        ]}

    monkeypatch.setattr(loop, "_audit_hydraflow_self", fake_self_audit)
    monkeypatch.setattr(loop, "_run_audit", fake_report)

    state.get_last_green_audit.return_value = {}

    stats = await loop._do_work()
    assert stats["audited"] >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Expected: 2 FAILs (`_retry_blocked` missing; `_do_work` is still the stub from Task 7).

- [ ] **Step 3: Implement `_retry_blocked` and fill `_do_work`**

Append to `PrinciplesAuditLoop`:

```python
    async def _retry_blocked(self) -> int:
        """For every blocked slug, re-audit; flip to ready if P1–P5 green."""
        flipped = 0
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            if self._state.get_onboarding_status(mr.slug) != "blocked":
                continue
            snapshot = await self._audit_managed_repo(mr)
            report = await self._fetch_last_report(mr)
            fails = self._p1_p5_fails(report.get("findings", []))
            if not fails:
                self._state.set_onboarding_status(mr.slug, "ready")
                self._state.set_last_green_audit(mr.slug, snapshot)
                flipped += 1
        return flipped
```

Replace the stub `_do_work` with:

```python
    async def _do_work(self) -> WorkCycleResult:
        """One audit cycle: onboarding reconcile, self audit, managed audits, diffs."""
        stats: dict[str, int] = {
            "onboarded": 0,
            "audited": 0,
            "regressions_filed": 0,
            "escalations_filed": 0,
            "ready_flips": 0,
        }

        # 1) Onboarding reconcile — new or pending slugs.
        stats["onboarded"] = await self._reconcile_onboarding()

        # 2) Retry blocked — may flip to ready.
        stats["ready_flips"] = await self._retry_blocked()

        # 3) HydraFlow-self audit.
        self_snapshot = await self._audit_hydraflow_self()
        stats["audited"] += 1
        self_report = json.loads(
            (self._config.data_root / _HYDRAFLOW_SELF / "audit" /
             f"{datetime.now(UTC).strftime('%Y-%m-%d')}.json").read_text()
        )
        self_last = self._state.get_last_green_audit(_HYDRAFLOW_SELF)
        self_regressions = self._diff_regressions(self_last, self_snapshot)
        if self_regressions:
            fire = await self._fire_for_slug(
                _HYDRAFLOW_SELF, self_regressions, self_report, self_last
            )
            stats["regressions_filed"] += fire["filed"]
            stats["escalations_filed"] += fire["escalated"]
        else:
            # All green — update the last-green reference.
            self._state.set_last_green_audit(_HYDRAFLOW_SELF, self_snapshot)

        # 4) Managed-repo audits (only `ready` slugs — blocked handled in step 2).
        for mr in self._config.managed_repos:
            if not mr.enabled:
                continue
            if self._state.get_onboarding_status(mr.slug) != "ready":
                continue
            snapshot = await self._audit_managed_repo(mr)
            stats["audited"] += 1
            report = await self._fetch_last_report(mr)
            last = self._state.get_last_green_audit(mr.slug)
            regressions = self._diff_regressions(last, snapshot)
            if regressions:
                fire = await self._fire_for_slug(mr.slug, regressions, report, last)
                stats["regressions_filed"] += fire["filed"]
                stats["escalations_filed"] += fire["escalated"]
            else:
                self._state.set_last_green_audit(mr.slug, snapshot)

        return stats
```

- [ ] **Step 4: Run tests to verify they pass**

Expected: all new tests PASS. Run the full loop test file:

```bash
PYTHONPATH=src uv run pytest tests/test_principles_audit_loop.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/principles_audit_loop.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): full _do_work assembly + ready-on-green flip (§4.4)"
```

---

### Task 16: Onboarding transition tests — covered by Tasks 14–15

pending→blocked, pending→ready, and blocked→ready are all tested already.

---

### Task 17: Add `audit` job to CI workflow

Task 0's benchmark decides which workflow file to touch.

#### Task 17a — if `p95 ≤ 30s` → `.github/workflows/ci.yml`

**Files:**
- Modify: `.github/workflows/ci.yml` — append job at end of `jobs:` block (after line 188 `regression` job)

- [ ] **Step 1: Add the `audit` job**

Append at `.github/workflows/ci.yml` end of jobs list (before `ui-build` at line 190, or after `regression` at line 188):

```yaml
  audit:
    name: Principles Audit
    needs: changes
    if: needs.changes.outputs.python == 'true' || needs.changes.outputs.ci == 'true'
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install dependencies
        run: uv sync --all-extras
      - name: Run principles audit
        run: make audit
```

- [ ] **Step 2: Push the branch and observe the job runs**

Handled in Task 22 (final PR).

#### Task 17b — if `p95 > 30s` → `.github/workflows/rc-promotion-scenario.yml`

**Files:**
- Modify: `.github/workflows/rc-promotion-scenario.yml` — append a new `audit` job as a dependency of the RC promotion gate

- [ ] **Step 1: Add the `audit` job**

Append to `.github/workflows/rc-promotion-scenario.yml` (identical YAML to 17a but named `audit` and gated on the RC branch trigger).

- [ ] **Step 2: Commit (either branch — 17a or 17b)**

```bash
git add .github/workflows/ci.yml   # or rc-promotion-scenario.yml
git commit -m "ci(audit): run make audit on every PR (§4.4)"
```

---

### Task 18: Telemetry instrumentation (stub `emit_loop_subprocess_trace` if absent)

**Files:**
- Modify: `src/principles_audit_loop.py` — wrap `_run_audit` call sites
- Modify: `src/trace_collector.py` — add `emit_loop_subprocess_trace` shim if not present (Plan 6 owns the real impl)

- [ ] **Step 1: Check for existing helper**

```bash
grep -n "emit_loop_subprocess_trace" src/trace_collector.py || echo MISSING
```

If `MISSING`, proceed to Step 2. Otherwise skip to Step 3.

- [ ] **Step 2: Add a minimal stub to `src/trace_collector.py`**

Append to `src/trace_collector.py` at module bottom:

```python
def emit_loop_subprocess_trace(
    *,
    worker_name: str,
    command: list[str],
    exit_code: int,
    duration_s: float,
    stdout_tail: str = "",
    stderr_tail: str = "",
) -> None:
    """Record a subprocess invocation from a background loop.

    Plan 6 (§4.11 Factory Cost) owns the real implementation that writes
    to the traces store. Until then this is a best-effort log that keeps
    the call sites correct — replace body when the store lands.
    """
    logger.info(
        "loop_subprocess_trace worker=%s exit=%d dur=%.2fs cmd=%r",
        worker_name,
        exit_code,
        duration_s,
        command,
    )
```

- [ ] **Step 3: Wrap `_run_audit` timing**

Modify `src/principles_audit_loop.py` — replace `_run_audit`:

```python
    async def _run_audit(
        self, slug: str, repo_root: Path
    ) -> dict[str, Any]:
        from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        import time  # noqa: PLC0415
        cmd = ["make", "audit-json", f"DIR={repo_root}"]
        t0 = time.perf_counter()
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        dur = time.perf_counter() - t0
        emit_loop_subprocess_trace(
            worker_name=self._worker_name,
            command=cmd,
            exit_code=proc.returncode or 0,
            duration_s=dur,
            stdout_tail=stdout.decode(errors="replace")[-400:],
            stderr_tail=stderr.decode(errors="replace")[-400:],
        )
        if proc.returncode not in (0, 1):
            logger.warning(
                "make audit-json exit=%d for %s: %s",
                proc.returncode, slug, stderr.decode(errors="replace")[:400],
            )
        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"audit-json emitted non-JSON for {slug}: {exc}"
            ) from exc
```

- [ ] **Step 4: Add a test that the telemetry call is issued**

Append to `tests/test_principles_audit_loop.py`:

```python
async def test_run_audit_emits_subprocess_trace(loop_env, monkeypatch, tmp_path):
    cfg, state, pr = loop_env
    stop = asyncio.Event()
    loop = PrinciplesAuditLoop(config=cfg, state=state, pr_manager=pr, deps=_deps(stop))
    emitted: list[dict] = []

    import trace_collector
    def fake_emit(**kwargs):
        emitted.append(kwargs)
    monkeypatch.setattr(trace_collector, "emit_loop_subprocess_trace", fake_emit)

    async def fake_subproc(*args, **kwargs):
        class P:
            returncode = 0
            async def communicate(self):
                return (b'{"findings": []}', b"")
        return P()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    await loop._run_audit("hydraflow-self", tmp_path)
    assert len(emitted) == 1
    assert emitted[0]["worker_name"] == "principles_audit"
    assert "audit-json" in emitted[0]["command"][1]
```

- [ ] **Step 5: Run + commit**

```bash
PYTHONPATH=src uv run pytest tests/test_principles_audit_loop.py::test_run_audit_emits_subprocess_trace -v
git add src/principles_audit_loop.py src/trace_collector.py tests/test_principles_audit_loop.py
git commit -m "feat(loop): emit_loop_subprocess_trace around make audit (§4.4 + §4.11)"
```

---

### Task 19: Five-checkpoint wiring

Five small sub-steps, one commit each. The exact string `principles_audit` must be used identically in all five places (auto-discovered by `test_loop_wiring_completeness.py`).

- [ ] **Step 19.1: `service_registry.py`**

Modify `src/service_registry.py:63` (imports) — add:

```python
from principles_audit_loop import PrinciplesAuditLoop  # noqa: TCH001
```

Modify `src/service_registry.py:145-168` (ServiceRegistry dataclass) — add field:

```python
    principles_audit_loop: PrinciplesAuditLoop
```

Modify `src/service_registry.py:210+` (`build_services`) — after the existing `retrospective_loop = RetrospectiveLoop(...)` block near line 806, add:

```python
    principles_audit_loop = PrinciplesAuditLoop(
        config=config,
        state=state,
        pr_manager=prs,
        deps=loop_deps,
    )
```

And in the `ServiceRegistry(...)` constructor call (around line 846-871), append the keyword:

```python
        principles_audit_loop=principles_audit_loop,
```

Commit:

```bash
git add src/service_registry.py
git commit -m "feat(wiring): register PrinciplesAuditLoop in service registry"
```

- [ ] **Step 19.2: `orchestrator.py`**

Modify `src/orchestrator.py:138-159` (`bg_loop_registry` dict) — add entry:

```python
            "principles_audit": svc.principles_audit_loop,
```

Modify `src/orchestrator.py:879-910` (run-loop `loop_factories` list) — add:

```python
            ("principles_audit", self._svc.principles_audit_loop.run),
```

Commit:

```bash
git add src/orchestrator.py
git commit -m "feat(wiring): orchestrator runs PrinciplesAuditLoop + registers worker"
```

- [ ] **Step 19.3: `src/ui/src/constants.js`**

Modify `src/ui/src/constants.js` — three places:

1. `BACKGROUND_WORKERS` (line 293+): add `{ key: 'principles_audit', label: 'Principles Audit', group: 'trust' }` (follow existing entry shape).
2. `SYSTEM_WORKER_INTERVALS` (line 259+): add `principles_audit: 604800,`.
3. `EDITABLE_INTERVAL_WORKERS` (line 252): add `'principles_audit'` inside the Set literal.

Commit:

```bash
git add src/ui/src/constants.js
git commit -m "feat(ui): register principles_audit in BACKGROUND_WORKERS"
```

- [ ] **Step 19.4: `src/dashboard_routes/_common.py`**

Modify `src/dashboard_routes/_common.py:32+` — add to `_INTERVAL_BOUNDS`:

```python
    "principles_audit": (3600, 2_592_000),  # 1h min, 30d max
```

Commit:

```bash
git add src/dashboard_routes/_common.py
git commit -m "feat(dashboard): interval bounds for principles_audit (1h–30d)"
```

- [ ] **Step 19.5: `tests/test_loop_wiring_completeness.py`**

Auto-discovers via regex — no explicit entry. But the test *includes* the new loop in its assertion set. Run:

```bash
PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v
```

Expected: PASS (new loop picked up because all 4 sources now contain `principles_audit`).

If failing, fix the missing spot and commit:

```bash
git add -u
git commit -m "chore(wiring): fix principles_audit wiring gap flagged by completeness test"
```

---

### Task 20: `test_loop_wiring_completeness.py` verification — covered by Step 19.5

---

### Task 21: MockWorld scenario — onboarding-blocked + drift-regression

**Files:**
- Create: `tests/scenarios/test_principles_audit_scenario.py`

Single file, two test methods under one class, following the `test_caretaker_loops.py` shape.

- [ ] **Step 1: Write the scenario**

Create `tests/scenarios/test_principles_audit_scenario.py`:

```python
"""MockWorld scenario for PrinciplesAuditLoop (spec §4.4).

Two scenarios:
1. Onboarding-blocked: adding a new managed repo with P1 FAIL must flip
   onboarding_status to "blocked" and file an `onboarding-blocked` issue.
2. Drift-regression: HydraFlow-self goes from all-green to one PASS→FAIL
   must file a `principles-drift` issue on first fire.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops


class TestPrinciplesAudit:
    """§4.4 — onboarding gate + drift detector."""

    async def test_onboarding_blocked_files_issue(self, tmp_path) -> None:
        from config import ManagedRepo  # noqa: PLC0415

        world = MockWorld(tmp_path)
        world.config.managed_repos = [ManagedRepo(slug="acme/widget")]

        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=101)
        fake_report = {
            "findings": [
                {"check_id": "P1.1", "status": "FAIL", "severity": "STRUCTURAL",
                 "principle": "P1", "source": "docs/adr/0001", "what": "doc exists",
                 "remediation": "write", "message": ""},
            ]
        }
        fake_loop_ports = {
            "pr_manager": fake_pr,
            "audit_runner": AsyncMock(return_value=fake_report),
            "refresh_checkout": AsyncMock(return_value=tmp_path / "acme/widget/checkout"),
        }
        _seed_ports(world, **fake_loop_ports)

        await world.run_with_loops(["principles_audit"], cycles=1)

        # Assert: state flipped to "blocked", issue filed with onboarding-blocked label.
        status = world.state.get_onboarding_status("acme/widget")
        assert status == "blocked"
        assert fake_pr.create_issue.await_count >= 1
        args = fake_pr.create_issue.await_args_list[0]
        labels = args.kwargs.get("labels") or args.args[2]
        assert "onboarding-blocked" in labels

    async def test_drift_regression_files_find_issue(self, tmp_path) -> None:
        world = MockWorld(tmp_path)
        world.config.managed_repos = []
        # Seed HydraFlow-self with all-green last known.
        world.state.set_last_green_audit("hydraflow-self", {"P1.1": "PASS", "P2.4": "PASS"})

        fake_pr = AsyncMock()
        fake_pr.create_issue = AsyncMock(return_value=202)
        fake_report = {
            "findings": [
                {"check_id": "P1.1", "status": "FAIL", "severity": "STRUCTURAL",
                 "principle": "P1", "source": "docs/adr/0001", "what": "doc exists",
                 "remediation": "write", "message": "file missing"},
                {"check_id": "P2.4", "status": "PASS", "severity": "BEHAVIORAL",
                 "principle": "P2", "source": "Makefile", "what": "target",
                 "remediation": "fix", "message": ""},
            ]
        }
        _seed_ports(
            world,
            pr_manager=fake_pr,
            audit_runner=AsyncMock(return_value=fake_report),
        )

        await world.run_with_loops(["principles_audit"], cycles=1)

        assert fake_pr.create_issue.await_count == 1
        title = fake_pr.create_issue.await_args.args[0]
        labels = fake_pr.create_issue.await_args.args[2]
        assert "P1.1" in title and "hydraflow-self" in title
        assert "principles-drift" in labels
        assert "check-P1.1" in labels
```

- [ ] **Step 2: Run the scenario**

```bash
PYTHONPATH=src uv run pytest tests/scenarios/test_principles_audit_scenario.py -v -m scenario_loops
```

Expected: 2 PASS. If `MockWorld` doesn't know how to seed `audit_runner`/`refresh_checkout` ports, wire the port keys in `tests/scenarios/helpers/loop_port_seeding.py` — the loop skeleton reads its subprocess helpers through `self._run_audit`/`self._refresh_checkout` which the scenario monkeypatches via the port map.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_principles_audit_scenario.py
git commit -m "test(scenario): PrinciplesAudit onboarding-blocked + drift-regression (§4.4)"
```

---

### Task 22: Final PR

- [ ] **Step 1: Run full quality gate**

```bash
make quality
```

Expected: PASS.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin trust-arch-hardening
```

- [ ] **Step 3: Create the PR**

```bash
gh pr create --title "feat(trust): PrinciplesAuditLoop + onboarding gate (§4.4)" --body "$(cat <<'EOF'
## Summary

- New `PrinciplesAuditLoop` (`src/principles_audit_loop.py`) runs weekly against HydraFlow-self and every managed repo, diffs against last-green snapshot, files `hydraflow-find` + `principles-drift` issues for PASS→FAIL regressions (spec §4.4).
- New `ManagedRepo` pydantic v2 model + `managed_repos` config field + `HYDRAFLOW_MANAGED_REPOS` JSON env override. Single source of truth for repos under factory management.
- New `PrinciplesAuditStateMixin` on `StateTracker` — `managed_repos_onboarding_status`, `last_green_audit`, `principles_drift_attempts`.
- Orchestrator pipeline loops skip any slug whose onboarding status is `blocked` — factory won't dispatch against non-conformant repos.
- New `audit` CI job runs `make audit` on every PR (or every RC per Task 0 benchmark).
- STRUCTURAL/BEHAVIORAL regressions escalate after 3 repair attempts; CULTURAL after 1.
- Kill-switch via `LoopDeps.enabled_cb` (worker_name `principles_audit`) — no new config enabled field (§12.2).
- Telemetry via `trace_collector.emit_loop_subprocess_trace` (local stub until Plan 6 lands).
- MockWorld scenario `tests/scenarios/test_principles_audit_scenario.py` covers onboarding-blocked + drift-regression branches.

## Task 0 benchmark

See `docs/bench/principles-audit-benchmark.md`. Decision: **ci.yml | rc-promotion-scenario.yml** (strike one based on measured p95).

## Test plan

- [ ] `PYTHONPATH=src uv run pytest tests/test_config_managed_repos.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_state_principles_audit.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_orchestrator_blocked_repos.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_principles_audit_loop.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/test_loop_wiring_completeness.py -v`
- [ ] `PYTHONPATH=src uv run pytest tests/scenarios/test_principles_audit_scenario.py -m scenario_loops -v`
- [ ] `make quality`
- [ ] CI `audit` job passes against this PR.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review

**1. Spec coverage.**

| Spec requirement (§4.4) | Task |
|---|---|
| `PrinciplesAuditLoop` skeleton + weekly cadence | Task 7 |
| HydraFlow-self audit via `make audit --json` + dated snapshot | Task 9 |
| Managed-repo audit via shallow checkout + `make audit` | Task 10 |
| PASS→FAIL diff at `check_id` level | Task 11 |
| Issue filing: `hydraflow-find`, `principles-drift`, `check-{check_id}` | Task 12 |
| Title `Principles drift: {check_id} regressed in {repo_slug}` | Task 12 |
| STRUCTURAL/BEHAVIORAL escalate after 3 attempts | Task 12 |
| CULTURAL escalate after 1 attempt | Task 12 |
| `managed_repos` config shape + `HYDRAFLOW_MANAGED_REPOS` JSON env | Task 1 |
| `managed_repos_onboarding_status` on StateTracker | Tasks 3, 4 |
| Onboarding gate blocks factory — P1–P5 FAILs → `blocked` | Task 14 |
| Orchestrator skips blocked repos in pipeline dispatch | Task 5 |
| `onboarding-blocked` issue filed with failing checks | Task 14 |
| Re-audit green → flip to `ready` | Task 15 |
| P6–P10 FAIL warns but doesn't block | Task 14 (`_p1_p5_fails` filter is P1–P5 only) |
| `audit` job on `.github/workflows/ci.yml` per PR | Task 17a |
| Fallback to RC workflow if p95 > 30s | Task 17b |
| Benchmark task (5 runs, p50/p95) | Task 0 |
| `principles_audit_interval = 604800` config field | Task 1 |
| No LLM override (the loop dispatches nothing) | Task 7 (skeleton) |
| Kill-switch via `LoopDeps.enabled_cb`, worker_name = `principles_audit` | Task 7 + §3.2 inheritance |
| Telemetry via `trace_collector.emit_loop_subprocess_trace` | Task 18 |
| Stub `emit_loop_subprocess_trace` locally if Plan 6 absent | Task 18 Step 2 |
| Five-checkpoint wiring | Task 19 (five sub-steps) |
| `test_loop_wiring_completeness.py` entry | Task 19.5 / Task 20 |
| Unit tests `tests/test_principles_audit_loop.py` | Tasks 7, 9–15, 18 |
| MockWorld scenario | Task 21 |

All spec §4.4 requirements mapped to a task. §3.2 kill-switch honored by inheritance from `BaseBackgroundLoop` + `LoopDeps.enabled_cb`; the run-loop already exits `_sleep_or_trigger` → `enabled_cb` check per line 275/277 of `src/base_background_loop.py`.

**2. Placeholder scan.** No `TBD`, `TODO`, `similar to Task N`, or `add appropriate` strings. Every step shows concrete code or an exact file+line edit. `Task 17a` / `17b` are both written out; the plan chooses based on Task 0's measured p95.

**3. Type consistency.** Walk-through: `worker_name="principles_audit"` matches across Task 7 (declared), 19.2 (registry), 19.3 (UI), 19.4 (bounds). State-field names match across Task 3 (field) / Task 4 (accessors) / consumption tasks. All private loop methods (`_run_audit`, `_refresh_checkout`, `_audit_managed_repo`, `_audit_hydraflow_self`, `_snapshot_from_report`, `_save_snapshot`, `_diff_regressions`, `_file_drift_issue`, `_maybe_escalate`, `_fire_for_slug`, `_fetch_last_report`, `_run_onboarding_audit`, `_file_onboarding_issue`, `_reconcile_onboarding`, `_retry_blocked`) are each declared exactly once and called only in later tasks. Escalation thresholds (`_STRUCTURAL_ATTEMPTS = 3`, `_BEHAVIORAL_ATTEMPTS = 3`, `_CULTURAL_ATTEMPTS = 1`) declared in Task 7, used only in Task 12. No inconsistencies.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-22-principles-audit-loop.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
