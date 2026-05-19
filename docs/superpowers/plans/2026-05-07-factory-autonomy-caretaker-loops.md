# Factory Autonomy Caretaker Loops Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Three new background loops that automate the recurring manual fixes the factory autonomy standard describes, so factory autonomy holds without an LLM session being live.

**Architecture:** Each loop is a `BaseBackgroundLoop` subclass per ADR-0029. Shared port-method addition (`update_pr_base`). Per-loop kill-switch flag, GitHub-label processed-marker, `do-not-touch` opt-out. Tests in unit + MockWorld scenario layers; sandbox e2e as placeholder per current harness limits (#8483).

**Tech Stack:** Python 3.11, asyncio, FastAPI/orchestrator boundary, `gh` CLI for GitHub I/O, pytest + MockWorld, sandbox runner.

**Spec:** `docs/superpowers/specs/2026-05-07-factory-autonomy-caretaker-loops-design.md` (PR #8489).

**Worktree:** `/Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/caretaker-loops-spec` (branch: `feat/caretaker-loops-spec`).

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `src/ports.py` | MOD | Add `PRPort.update_pr_base` method |
| `src/pr_manager.py` | MOD | Implement `update_pr_base` |
| `src/mockworld/fakes/fake_github.py` | MOD | Fake of `update_pr_base` |
| `tests/test_pr_manager_update_pr_base.py` | NEW | Unit tests for the port method |
| `src/config.py` | MOD | 3 new bool kill-switch fields + env overrides |
| `src/loop_catalog.py` | MOD | Register 3 new loops |
| `src/service_registry.py` | MOD | Wire 3 new loop instances |
| `src/base_branch_autoretarget_loop.py` | NEW | The retarget loop |
| `tests/test_base_branch_autoretarget_loop.py` | NEW | Unit tests |
| `tests/scenarios/test_base_branch_autoretarget_scenario.py` | NEW | MockWorld scenario |
| `tests/sandbox_scenarios/scenarios/s14_base_branch_autoretarget.py` | NEW | Sandbox placeholder |
| `docs/adr/0056-base-branch-autoretarget-loop.md` | NEW | ADR (smallest loop, ships first) |
| `src/arch_regen_autofixer_loop.py` | NEW | The arch-regen loop |
| `tests/test_arch_regen_autofixer_loop.py` | NEW | Unit tests |
| `tests/scenarios/test_arch_regen_autofixer_scenario.py` | NEW | MockWorld scenario |
| `tests/sandbox_scenarios/scenarios/s15_arch_regen_autofix.py` | NEW | Sandbox placeholder |
| `docs/adr/0057-arch-regen-autofixer-loop.md` | NEW | ADR |
| `src/skip_adr_advisor_loop.py` | NEW | The advisor loop |
| `src/skip_adr_classifier.py` | NEW | Touchpoint classifier (split for testability) |
| `tests/test_skip_adr_classifier.py` | NEW | Unit tests for classifier |
| `tests/test_skip_adr_advisor_loop.py` | NEW | Unit tests for loop |
| `tests/scenarios/test_skip_adr_advisor_scenario.py` | NEW | MockWorld scenario |
| `tests/sandbox_scenarios/scenarios/s16_skip_adr_advisor.py` | NEW | Sandbox placeholder |
| `docs/adr/0058-skip-adr-advisor-loop.md` | NEW | ADR |
| `.env.sample` | MOD | Document the 3 new flags |

---

## Suggested PR Decomposition

The plan can ship as **one bundled PR** (all loops together) or **four stacked PRs** (foundation + 3 loops). The four-PR path is recommended for review velocity:

- **PR α**: `update_pr_base` port method (Tasks 1–6)
- **PR β**: `BaseBranchAutoRetargeter` (Tasks 7–14)
- **PR γ**: `ArchRegenAutoFixer` (Tasks 15–22)
- **PR δ**: `SkipADRAdvisor` (Tasks 23–32)

Each PR is independently reviewable + mergeable. β/γ/δ depend on α. Each PR ships through the test pyramid per `docs/standards/testing/`.

---

## PR α: `update_pr_base` port method

### Task 1: Write failing tests for `update_pr_base`

**Files:**
- Create: `tests/test_pr_manager_update_pr_base.py`

- [ ] **Step 1: Write the test file**

```python
"""Unit tests for PRManager.update_pr_base — retargeting a PR's base branch."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _make_pr_manager() -> Any:
    config = ConfigFactory.create(repo="owner/repo")
    return make_pr_manager(config=config, event_bus=AsyncMock())


@pytest.mark.asyncio
async def test_update_pr_base_calls_gh_pr_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    pm = _make_pr_manager()
    captured: dict[str, Any] = {}

    async def _fake_run_subprocess(*cmd: str, **_kw: Any) -> str:
        captured["cmd"] = cmd
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _fake_run_subprocess)

    ok = await pm.update_pr_base(123, base="staging")

    assert ok is True
    cmd = captured["cmd"]
    assert "pr" in cmd
    assert "edit" in cmd
    assert "123" in cmd
    assert "--base" in cmd
    assert "staging" in cmd


@pytest.mark.asyncio
async def test_update_pr_base_returns_false_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = _make_pr_manager()

    async def _failing_subprocess(*_cmd: str, **_kw: Any) -> str:
        raise RuntimeError("gh pr edit failed: not found")

    monkeypatch.setattr("pr_manager.run_subprocess", _failing_subprocess)

    ok = await pm.update_pr_base(123, base="staging")
    assert ok is False


@pytest.mark.asyncio
async def test_update_pr_base_dry_run_returns_true_without_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = _make_pr_manager()
    pm._config.dry_run = True
    called = False

    async def _fake_run_subprocess(*_cmd: str, **_kw: Any) -> str:
        nonlocal called
        called = True
        return ""

    monkeypatch.setattr("pr_manager.run_subprocess", _fake_run_subprocess)

    ok = await pm.update_pr_base(99, base="staging")
    assert ok is True
    assert called is False
```

- [ ] **Step 2: Run test to verify FAIL**

```bash
cd /Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/caretaker-loops-spec
uv run pytest tests/test_pr_manager_update_pr_base.py -v
```

Expected: All 3 tests fail with `AttributeError: 'PRManager' object has no attribute 'update_pr_base'`

### Task 2: Implement `PRManager.update_pr_base`

**Files:**
- Modify: `src/pr_manager.py` (add method near `merge_pr` and `update_pr_branch`)

- [ ] **Step 1: Add the method**

Locate `update_pr_branch` (added by ADR-0042's auto-rebase work). Add immediately after:

```python
    @port_span("hf.port.pr.update_pr_base")
    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Retarget a PR's base branch via `gh pr edit --base`.

        Used by ``BaseBranchAutoRetargeter`` to retarget PRs opened against
        the wrong base after the two-tier branch model is activated. Idempotent
        from GitHub's side (re-targeting to the same base is a no-op).

        Returns True on success, False on failure.
        """
        self._assert_repo()
        if self._config.dry_run:
            logger.info("[dry-run] Would update PR #%d base to %s", pr_number, base)
            return True
        try:
            await run_subprocess(
                "gh",
                "pr",
                "edit",
                str(pr_number),
                "--repo",
                self._repo,
                "--base",
                base,
                cwd=self._config.repo_root,
                gh_token=self._credentials.gh_token,
            )
            return True
        except RuntimeError as exc:
            logger.warning(
                "update_pr_base(#%d, base=%s) failed: %s", pr_number, base, exc
            )
            return False
```

- [ ] **Step 2: Run test to verify PASS**

```bash
uv run pytest tests/test_pr_manager_update_pr_base.py -v
```

Expected: All 3 tests pass.

### Task 3: Add `PRPort.update_pr_base` to the protocol

**Files:**
- Modify: `src/ports.py` (add to `PRPort` Protocol class)

- [ ] **Step 1: Add Protocol method**

Locate `update_pr_branch` in `class PRPort(Protocol):`. Add immediately after:

```python
    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Retarget a PR's base branch.

        Wraps ``gh pr edit --base``. Returns True on success.

        Matches ``pr_manager.PRManager.update_pr_base`` exactly.
        """
        ...
```

- [ ] **Step 2: Run pyright to verify protocol compliance**

```bash
uv run pyright src/pr_manager.py src/ports.py 2>&1 | tail -5
```

Expected: 0 errors.

### Task 4: Add `update_pr_base` fake to FakeGitHub

**Files:**
- Modify: `src/mockworld/fakes/fake_github.py`

- [ ] **Step 1: Add the fake**

Locate `update_pr_branch` fake in `FakeGitHub`. Add immediately after:

```python
    async def update_pr_base(self, pr_number: int, *, base: str) -> bool:
        """Fake retarget: records the new base on the in-memory PR."""
        self._maybe_rate_limit()
        if pr_number in self._prs:
            self._prs[pr_number].base = base
            return True
        return False
```

- [ ] **Step 2: Verify FakePR has a `base` field**

Run:
```bash
grep -A20 "class FakePR" src/mockworld/fakes/fake_github.py | head -25
```

If `base` is not in the FakePR dataclass: add it as a field with default `"main"`. If it IS already there: no change needed.

### Task 5: Run full test suite to verify no regressions

- [ ] **Step 1: Run pyright + tests**

```bash
uv run pyright src/pr_manager.py src/ports.py src/mockworld/fakes/fake_github.py 2>&1 | tail -3
uv run pytest tests/test_pr_manager_update_pr_base.py tests/test_pr_manager_core.py tests/test_pr_manager_promotion.py tests/test_fake_github.py -v 2>&1 | tail -5
```

Expected: 0 pyright errors; all tests pass.

### Task 6: Commit + open PR

- [ ] **Step 1: Commit**

```bash
git add src/ports.py src/pr_manager.py src/mockworld/fakes/fake_github.py tests/test_pr_manager_update_pr_base.py
git commit -m "feat(pr): add update_pr_base port method for retargeting PRs

Foundation for BaseBranchAutoRetargeter (ADR-0057) — wraps
gh pr edit --base. Mirrors update_pr_branch from ADR-0042's
auto-rebase work. Idempotent. 3 unit tests covering happy
path, failure path, dry-run.
"
```

- [ ] **Step 2: Push + open PR**

```bash
git push -u origin feat/caretaker-loops-spec
gh pr create --base staging \
  --title "feat(pr): update_pr_base port method (foundation for ADR-0057)" \
  --body "Foundation method for BaseBranchAutoRetargeter (the next PR). Wraps gh pr edit --base. Stacks under spec PR #8489."
```

Expected: PR opens, CI runs, monitor for merge.

---

## PR β: `BaseBranchAutoRetargeter` loop

(Tasks 7–14: ADR + config field + loop unit tests + loop impl + scenario test + sandbox placeholder + wiring + commit. Mirror Task structure of PR α with these specifics:)

### Task 7: Write ADR-0056

**Files:**
- Create: `docs/adr/0056-base-branch-autoretarget-loop.md`

- [ ] **Step 1: Author the ADR**

Use the ADR template (modeled after `docs/adr/0050-auto-agent-hitl-preflight.md`). Required sections: Status, Date, Enforced by, Context, Decision, Consequences, Touchpoints, Source-file citations.

Decision section:
- Loop targets PRs with `base=main` and `head !~ rc/*` while `staging_enabled=true`
- Action: `update_pr_base(N, base="staging")` + canonical retarget comment + `hydraflow-retargeted` label
- Honors `do-not-touch` label
- Re-trigger: remove `hydraflow-retargeted` label

Source-file citations: list this PR's files.

### Task 8: Add config field

**Files:**
- Modify: `src/config.py`

- [ ] **Step 1: Add field to `HydraFlowConfig`**

Locate `staging_enabled: bool` field. Add nearby:

```python
    base_branch_autoretarget_enabled: bool = Field(
        default=False,
        description="Enable BaseBranchAutoRetargeter loop (ADR-0056)",
    )
    base_branch_autoretarget_interval: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Tick interval seconds for BaseBranchAutoRetargeter",
    )
```

Add to `_ENV_BOOL_OVERRIDES`:
```python
    ("base_branch_autoretarget_enabled", "HYDRAFLOW_BASE_BRANCH_AUTORETARGET_ENABLED", False),
```

Add to `_ENV_INT_OVERRIDES`:
```python
    ("base_branch_autoretarget_interval", "HYDRAFLOW_BASE_BRANCH_AUTORETARGET_INTERVAL", 300),
```

- [ ] **Step 2: Verify config parses**

```bash
PYTHONPATH=src uv run python -c "from config import HydraFlowConfig; c=HydraFlowConfig(); print(c.base_branch_autoretarget_enabled, c.base_branch_autoretarget_interval)"
```

Expected: `False 300`

### Task 9: Write failing unit tests for the loop

**Files:**
- Create: `tests/test_base_branch_autoretarget_loop.py`

- [ ] **Step 1: Write tests covering: disabled-skips, do-not-touch-skips, retargets PRs, marks processed, skips already-processed, max-actions-cap.**

```python
"""Unit tests for BaseBranchAutoRetargeter loop."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import ConfigFactory


def _make_loop(*, enabled: bool, staging_enabled: bool = True, **extra: Any) -> Any:
    """Build the loop with controlled config + a MagicMock prs."""
    from base_background_loop import LoopDeps
    from base_branch_autoretarget_loop import BaseBranchAutoRetargeter
    from events import EventBus

    base = ConfigFactory.create()
    config = base.model_copy(
        update={
            "base_branch_autoretarget_enabled": enabled,
            "staging_enabled": staging_enabled,
            **extra,
        }
    )
    bus = EventBus()
    stop = asyncio.Event()
    stop.set()
    deps = LoopDeps(
        event_bus=bus,
        stop_event=stop,
        status_cb=MagicMock(),
        enabled_cb=lambda _: True,
        sleep_fn=AsyncMock(),
    )
    prs = MagicMock()
    prs.list_prs_by_label = AsyncMock(return_value=[])
    prs.update_pr_base = AsyncMock(return_value=True)
    prs.add_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    return BaseBranchAutoRetargeter(config=config, prs=prs, deps=deps), prs


@pytest.mark.asyncio
async def test_disabled_returns_skipped() -> None:
    loop, _ = _make_loop(enabled=False)
    result = await loop._do_work()
    assert result == {"status": "disabled"}


@pytest.mark.asyncio
async def test_staging_disabled_returns_skipped() -> None:
    loop, _ = _make_loop(enabled=True, staging_enabled=False)
    result = await loop._do_work()
    assert result == {"status": "two_tier_inactive"}


@pytest.mark.asyncio
async def test_do_not_touch_label_skips_pr() -> None:
    loop, prs = _make_loop(enabled=True)
    prs.list_open_prs_targeting_main = AsyncMock(
        return_value=[
            {"number": 42, "headRefName": "feat/x", "labels": ["do-not-touch"]},
        ]
    )
    result = await loop._do_work()
    prs.update_pr_base.assert_not_called()
    assert result == {"status": "ok", "actions_taken": 0}


@pytest.mark.asyncio
async def test_already_processed_skips_pr() -> None:
    loop, prs = _make_loop(enabled=True)
    prs.list_open_prs_targeting_main = AsyncMock(
        return_value=[
            {"number": 42, "headRefName": "feat/x", "labels": ["hydraflow-retargeted"]},
        ]
    )
    result = await loop._do_work()
    prs.update_pr_base.assert_not_called()
    assert result == {"status": "ok", "actions_taken": 0}


@pytest.mark.asyncio
async def test_rc_branch_pr_skipped() -> None:
    loop, prs = _make_loop(enabled=True)
    prs.list_open_prs_targeting_main = AsyncMock(
        return_value=[
            {"number": 42, "headRefName": "rc/2026-05-07-1200", "labels": []},
        ]
    )
    result = await loop._do_work()
    prs.update_pr_base.assert_not_called()
    assert result == {"status": "ok", "actions_taken": 0}


@pytest.mark.asyncio
async def test_retargets_eligible_pr() -> None:
    loop, prs = _make_loop(enabled=True)
    prs.list_open_prs_targeting_main = AsyncMock(
        return_value=[
            {"number": 42, "headRefName": "feat/some-feature", "labels": []},
        ]
    )
    result = await loop._do_work()
    prs.update_pr_base.assert_awaited_once_with(42, base="staging")
    prs.add_labels.assert_awaited()
    prs.post_comment.assert_awaited()
    assert result == {"status": "ok", "actions_taken": 1}


@pytest.mark.asyncio
async def test_max_actions_per_tick_cap() -> None:
    loop, prs = _make_loop(enabled=True, base_branch_autoretarget_max_per_tick=2)
    prs.list_open_prs_targeting_main = AsyncMock(
        return_value=[
            {"number": i, "headRefName": f"feat/x{i}", "labels": []} for i in range(5)
        ]
    )
    result = await loop._do_work()
    assert prs.update_pr_base.await_count == 2
    assert result["actions_taken"] == 2
```

- [ ] **Step 2: Run tests, expect FAIL**

```bash
uv run pytest tests/test_base_branch_autoretarget_loop.py -v
```

Expected: All fail with `ModuleNotFoundError: No module named 'base_branch_autoretarget_loop'`.

### Task 10: Implement the loop

**Files:**
- Create: `src/base_branch_autoretarget_loop.py`

- [ ] **Step 1: Write the loop**

```python
"""BaseBranchAutoRetargeter — auto-retargets PRs from main to staging.

Per ADR-0056. When the two-tier branch model is active
(staging_enabled=true), PRs opened against `main` from non-rc/* heads
are retargeted to `staging` automatically. The factory removes the
manual retarget step that would otherwise burn operator attention.
"""

from __future__ import annotations

import logging
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from ports import PRPort

logger = logging.getLogger("hydraflow.base_branch_autoretarget")

_RETARGET_COMMENT_TEMPLATE = """**Auto-retargeted to `staging`**

This repo uses a two-tier branch model (per [ADR-0042](../../adr/0042-two-tier-branch-release-promotion.md)):
agent and human PRs target `staging`; `main` advances only via auto-promoted
`rc/YYYY-MM-DD-HHMM` PRs cut by `StagingPromotionLoop`. The factory's
`BaseBranchAutoRetargeter` did this automatically — no action needed.

Reference: [`docs/standards/factory_autonomy/README.md`](../../standards/factory_autonomy/README.md).

If this is wrong (e.g. you specifically need to target `main` for a release
operation), apply the `do-not-touch` label and re-target via `gh pr edit
--base main`.

🤖 Posted by `BaseBranchAutoRetargeter` (ADR-0056).
"""

_PROCESSED_LABEL = "hydraflow-retargeted"
_DO_NOT_TOUCH_LABEL = "do-not-touch"


class BaseBranchAutoRetargeter(BaseBackgroundLoop):
    """Retargets PRs from main to staging when two-tier model is active."""

    name = "base_branch_autoretarget"

    def __init__(
        self, *, config: HydraFlowConfig, prs: PRPort, deps: LoopDeps
    ) -> None:
        super().__init__(deps=deps, worker_name=self.name)
        self._config = config
        self._prs = prs

    def _get_default_interval(self) -> int:
        return self._config.base_branch_autoretarget_interval

    async def _do_work(self) -> dict[str, Any]:
        if not self._config.base_branch_autoretarget_enabled:
            return {"status": "disabled"}
        if not self._config.staging_enabled:
            return {"status": "two_tier_inactive"}

        prs = await self._prs.list_open_prs_targeting_main()
        actions = 0
        cap = getattr(
            self._config, "base_branch_autoretarget_max_per_tick", 5
        )
        for pr in prs:
            if actions >= cap:
                break
            labels = pr.get("labels", [])
            if _DO_NOT_TOUCH_LABEL in labels or _PROCESSED_LABEL in labels:
                continue
            head = pr.get("headRefName", "")
            if head.startswith("rc/"):
                continue
            number = pr["number"]
            ok = await self._prs.update_pr_base(number, base="staging")
            if not ok:
                logger.warning("Failed to retarget PR #%d", number)
                continue
            await self._prs.post_comment(number, _RETARGET_COMMENT_TEMPLATE)
            await self._prs.add_labels(number, [_PROCESSED_LABEL])
            actions += 1
        return {"status": "ok", "actions_taken": actions}
```

- [ ] **Step 2: Add new port method `list_open_prs_targeting_main`**

The loop calls `self._prs.list_open_prs_targeting_main()`. Add it to `src/ports.py` PRPort and implement on PRManager:

```python
# In ports.py PRPort:
    async def list_open_prs_targeting_main(self) -> list[dict[str, Any]]:
        """Return open PRs whose base is main, with number/headRefName/labels.

        Each entry: {"number": int, "headRefName": str, "labels": list[str]}.
        """
        ...

# In pr_manager.py PRManager:
    async def list_open_prs_targeting_main(self) -> list[dict[str, Any]]:
        self._assert_repo()
        if self._config.dry_run:
            return []
        try:
            raw = await self._run_gh(
                "gh",
                "pr",
                "list",
                "--repo",
                self._repo,
                "--base",
                self._config.main_branch,
                "--state",
                "open",
                "--json",
                "number,headRefName,labels",
            )
            data = json.loads(raw or "[]")
            # Normalize labels into list[str]
            for entry in data:
                entry["labels"] = [
                    lbl["name"] if isinstance(lbl, dict) else lbl
                    for lbl in entry.get("labels", [])
                ]
            return data
        except (RuntimeError, json.JSONDecodeError):
            return []
```

Add fake equivalent in `src/mockworld/fakes/fake_github.py`.

- [ ] **Step 3: Run loop unit tests**

```bash
uv run pytest tests/test_base_branch_autoretarget_loop.py -v
```

Expected: All 7 tests pass.

### Task 11: Wire into loop_catalog + service_registry

**Files:**
- Modify: `src/loop_catalog.py` (add registration)
- Modify: `src/service_registry.py` (instantiate)

- [ ] **Step 1: Register in catalog**

Find `loop_registrations` list. Add:

```python
    LoopRegistration(
        name="base_branch_autoretarget",
        cls=BaseBranchAutoRetargeter,
        ports=("github",),
    ),
```

- [ ] **Step 2: Instantiate in service_registry**

Find `staging_promotion_loop = StagingPromotionLoop(...)` block. Add nearby:

```python
    base_branch_autoretarget_loop = BaseBranchAutoRetargeter(  # noqa: F841
        config=config,
        prs=pr_manager,
        deps=loop_deps,
    )
```

Add to the `ServiceRegistry`:
```python
    base_branch_autoretarget_loop: BaseBranchAutoRetargeter
```

And the registry build:
```python
        base_branch_autoretarget_loop=base_branch_autoretarget_loop,
```

- [ ] **Step 3: Verify wiring**

```bash
uv run pytest tests/test_service_registry.py tests/test_loop_catalog.py -v 2>&1 | tail -5
```

Expected: All pass.

### Task 12: Write MockWorld scenario test

**Files:**
- Create: `tests/scenarios/test_base_branch_autoretarget_scenario.py`

- [ ] **Step 1: Write scenario test (Pattern B with FakeGitHub seeded)**

Pattern: build the loop with REAL FakeGitHub (not mocked), seed FakeGitHub with PRs of various shapes, drive `_do_work`, assert FakeGitHub state changed correctly.

Use the same shape as `tests/scenarios/test_rebase_on_conflict_scenario.py`. Mark with `pytestmark = pytest.mark.scenario_loops`.

- [ ] **Step 2: Run scenario test**

```bash
uv run pytest tests/scenarios/test_base_branch_autoretarget_scenario.py -m scenario_loops -v
```

Expected: pass.

### Task 13: Sandbox e2e placeholder

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s14_base_branch_autoretarget.py`

- [ ] **Step 1: Write placeholder scenario per s10/s11/s13 pattern (soft-pass + stderr note + #8483 link)**

### Task 14: Commit + push + PR β

- [ ] **Step 1: Run quality gate**

```bash
make quality 2>&1 | tail -10
```

Expected: green (or only pre-existing failures).

- [ ] **Step 2: Commit**

```bash
git add docs/adr/ src/ tests/ .env.sample
git commit -m "feat(loop): BaseBranchAutoRetargeter (ADR-0056)

Auto-retargets PRs from main to staging when two-tier model is
active. Honors do-not-touch label, marks processed via
hydraflow-retargeted label, capped at 5 actions/tick.
"
git push
```

- [ ] **Step 3: Open PR β** (or extend the open spec PR if stacking)

---

## PR γ: `ArchRegenAutoFixer` loop

(Tasks 15–22 — same shape as PR β with these specifics:)

- ADR-0057 documents the loop
- Config flag: `arch_regen_autofixer_enabled` + `arch_regen_autofixer_interval`
- Loop class: `ArchRegenAutoFixer` in `src/arch_regen_autofixer_loop.py`
- Worker name: `arch_regen_autofixer`
- Processed label: `hydraflow-arch-regened`; failure label: `hydraflow-arch-regen-failed`; needs-author label: `hydraflow-arch-regen-needs-author`
- Trigger: Tests check failed AND log contains "test_curated_drift"
- Action (same-org PR): clone PR head → run `make arch-regen` → if diff non-empty, commit + push to PR head + label processed; if diff empty, label fail (the failure isn't drift)
- Action (fork PR): post comment with the diff that would have been applied + label needs-author
- Sandbox: `s15_arch_regen_autofix.py` placeholder

The implementation is the heaviest of the three because of the subprocess interaction. Plan tasks for this PR will need:
- A new port method `get_pr_failed_check_logs(pr_number, check_name) -> str`
- A new port method `is_fork_pr(pr_number) -> bool`
- A new port method `clone_pr_head(pr_number) -> Path` (returns local clone dir)

Each gets its own TDD task.

## PR δ: `SkipADRAdvisor` loop

(Tasks 23–32 — same shape with these specifics:)

- ADR-0058 documents the loop AND the touchpoint classifier
- Config flag: `skip_adr_advisor_enabled` + `skip_adr_advisor_interval`
- Loop class: `SkipADRAdvisor` in `src/skip_adr_advisor_loop.py`
- Classifier in separate module: `src/skip_adr_classifier.py` (testable independently)
- Worker name: `skip_adr_advisor`
- Processed labels: `hydraflow-skip-adr-advised` (auto-applied); `hydraflow-skip-adr-needs-review` (escalated)
- Trigger: ADR gate failed AND PR body lacks `^Skip-ADR:` line
- Action (all implementation-level touchpoints): edit PR body with `Skip-ADR: <reason>` prepended; label processed
- Action (any decision-changing touchpoint): post comment with proposed Skip-ADR text and reasoning; label needs-review
- Classifier rules from spec §3.5
- New port method `get_pr_failed_check_logs` (shared with PR γ — extract first or duplicate then refactor)
- New port method `update_pr_body(pr_number, new_body) -> bool`
- Sandbox: `s16_skip_adr_advisor.py` placeholder

The classifier is the trickiest piece — needs ~12 unit tests covering each touchpoint shape (decorator-add, kwarg-add, import-path, method-rename, removed-method, signature-change, etc.).

---

## Self-Review

**1. Spec coverage:** Each spec section maps to tasks. §2 (three loops) → PRs β/γ/δ; §3.1 (signal sources) → loop trigger logic in each PR; §3.2-3.4 (per-loop flow) → loop impl tasks; §3.5 (classifier heuristics) → ADR-0058 + classifier module + classifier tests; §4 (components) → file structure section; §"Fork PRs" → ArchRegenAutoFixer fork-detection logic; §"All three loops share" → shared label + budget + opt-out logic in each loop.

**2. Placeholder scan:** The PR γ + PR δ sections summarize but don't enumerate all sub-tasks (they say "same shape with these specifics"). For a fully-bite-sized plan an executor would need to expand each into 8–10 tasks like PR α/β. This is a deliberate plan-shape choice — keeps the document readable while preserving the per-PR independence. **Action for executor:** when starting PR γ or δ, expand the summarized tasks following the PR β template.

**3. Type consistency:** Class names match across files; port method names match between port + impl + fake; label name strings match between loops + tests. `_PROCESSED_LABEL` constants per loop.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-07-factory-autonomy-caretaker-loops.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, two-stage review

**2. Inline Execution** — execute in this session via `superpowers:executing-plans`

Per the dark-factory autonomy directive, I'm proceeding with Subagent-Driven without waiting for explicit confirmation — the spec is approved in principle (you said "ok action all 3"), the plan follows. PR α (the small port-method foundation) starts now.
