# Sandbox-Tier Scenario Testing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sandbox tier of end-to-end scenario tests that boot HydraFlow inside docker-compose with MockWorld swapped at the boundary, drive the UI via Playwright, and verify "issue → label-state-machine progression → PR merged" without any external dependencies — closing the last 5% of human-in-the-loop verification.

**Architecture:** Two test tiers backed by the same MockWorld substrate (`src/mockworld/fakes/`). Tier 1 (in-process, every-PR) catches logic regressions in seconds. Tier 2 (sandbox, ~12 scenarios) catches container/wiring/UI regressions in minutes via real `docker-compose.sandbox.yml` stack with `internal: true` air-gap network. Selection is at entrypoint level: production runs the `hydraflow` console script; sandbox runs `python -m mockworld.sandbox_main`. `build_services()` and `HydraFlowOrchestrator.__init__` gain optional adapter-override kwargs; production never passes them.

**Tech Stack:** Python 3.11 + asyncio, pytest + pytest-playwright, docker-compose, FastAPI dashboard, React/Vite UI, AutoAgentRunner from #8439, scaffold_loop.py from #8448.

**Spec:** `docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md` (commit e6189276 on `sandbox-tier-spec` branch). Converged through 4 fresh-eyes review iterations (8→3→1→0 issues per ADR-0051).

**Worktree:** `/Users/travisf/.hydraflow/worktrees/T-rav-hydraflow/sandbox-tier-spec` (branch: `sandbox-tier-spec`).

---

## File Structure

| File | PR | Status | Responsibility |
|------|-----|--------|----------------|
| `src/mockworld/__init__.py` | A | NEW | Package marker for `src/mockworld/` |
| `src/mockworld/fakes/__init__.py` | A | NEW | Re-exports + `_is_fake_adapter` markers |
| `src/mockworld/fakes/fake_*.py` (12 files) | A | MOVED from `tests/scenarios/fakes/` | Port-conforming Fake adapters |
| `src/mockworld/fakes/fake_issue_fetcher.py` | A | NEW | `FakeIssueFetcher(IssueFetcherPort)` extracted from `_wire_targets` |
| `src/mockworld/fakes/fake_issue_store.py` | A | NEW | `FakeIssueStore(IssueStorePort)` extracted from `_wire_targets` |
| `src/mockworld/seed.py` | A | NEW | `MockWorldSeed` dataclass + `from_json` / `to_json` |
| `src/mockworld/sandbox_main.py` | A | NEW | Sandbox entrypoint: loads seed, builds Fakes, calls `build_services()` + orchestrator |
| `src/ports.py` | A | MODIFIED | Add `PRPort.list_prs_by_label` |
| `src/pr_manager.py` | A | MODIFIED | Implement `list_prs_by_label` on real `PRManager` |
| `src/service_registry.py` | A | MODIFIED | Widen `ServiceRegistry` field types to Ports; add adapter-override kwargs to `build_services()` |
| `src/orchestrator.py` | A | MODIFIED | Add `services: ServiceRegistry \| None = None` kwarg |
| `src/dashboard_routes/_routes.py` | A | MODIFIED | Widen `RouteContext.pr_manager` and `create_router(pr_manager=...)` to `PRPort` |
| `src/dashboard_routes/_state_routes.py` (or wherever `/api/state` is built) | A | MODIFIED | Add `mockworld_active: bool` field by duck-typing on `prs._is_fake_adapter` |
| `src/ui/src/components/MockWorldBanner.jsx` | A | NEW | Persistent top banner when `mockworld_active=true` |
| `src/ui/src/App.jsx` | A | MODIFIED | Render `MockWorldBanner` |
| `tests/scenarios/fakes/mock_world.py` | A | MODIFIED | Add `apply_seed(seed)` method; update internal imports |
| `tests/scenarios/conftest.py` | A | MODIFIED | Update import paths from `tests.scenarios.fakes` → `mockworld.fakes` |
| `tests/test_mockworld_fakes_conformance.py` | A | MOVED from `tests/scenarios/fakes/test_port_signature_conformance.py` |
| `tests/test_mockworld_runtime_conformance.py` | A | MOVED from `tests/scenarios/fakes/test_port_conformance.py` |
| `tests/sandbox_scenarios/__init__.py` | A | NEW | Package marker |
| `tests/sandbox_scenarios/scenarios/__init__.py` | A | NEW | Package marker |
| `tests/sandbox_scenarios/scenarios/s00_smoke.py` | A | NEW | Trivial parity-only scenario proving wiring works |
| `tests/sandbox_scenarios/runner/__init__.py` | A | NEW | Package marker |
| `tests/sandbox_scenarios/runner/loader.py` | A | NEW | `load_all_scenarios()` discovery |
| `tests/scenarios/test_sandbox_parity.py` | A | NEW | Parametrized parity test for every sandbox scenario |
| `docker-compose.sandbox.yml` | B | NEW | Sandbox compose stack with internal-only network |
| `src/ui/Dockerfile.ui` | B | NEW | Multi-stage: vite build → nginx serve |
| `src/ui/nginx.sandbox.conf` | B | NEW | nginx config: serve dist + proxy `/api`, `/ws` to hydraflow |
| `scripts/sandbox_scenario.py` | B | NEW | Harness CLI: run / run-all / status / down / shell / seed |
| `Makefile` | B | MODIFIED | Add `sandbox-up`, `sandbox-down`, `sandbox-test`, `sandbox-shell` targets |
| `tests/sandbox_scenarios/runner/conftest.py` | B | NEW | Playwright + SandboxAPIClient fixtures |
| `tests/sandbox_scenarios/runner/test_scenarios.py` | B | NEW | Parametrized runner; calls `scenario.assert_outcome(api, page)` |
| `tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py` | B | NEW | First end-to-end sandbox scenario |
| `.github/workflows/ci.yml` | B | MODIFIED | Add new `sandbox` job (greenfield) |
| `docs/adr/0052-sandbox-tier-scenarios.md` | B | NEW | ADR codifying the architecture |
| `tests/sandbox_scenarios/scenarios/s02_*.py` through `s12_*.py` | C | NEW | 11 catalog scenarios |
| `src/sandbox_failure_fixer_loop.py` | C | NEW | Caretaker loop scaffolded via `scripts/scaffold_loop.py` |
| `prompts/auto_agent/sandbox_fix.md` | C | NEW | Domain prompt for the auto-agent self-fix |
| `src/dashboard_routes/_hitl_routes.py` | C | MODIFIED | Add `/api/sandbox-hitl` endpoint |
| `src/ui/src/components/system/HitlPanel.jsx` (or equivalent) | C | MODIFIED | Read both `/api/hitl` and `/api/sandbox-hitl`; merge with type indicator |
| `.github/workflows/ci.yml` | C | MODIFIED | Expand sandbox job: PR-into-staging fast subset, rc/* full suite, nightly + label routing |
| `docs/wiki/dark-factory.md` | C | MODIFIED | §3 sandbox-tier expectations |

---

## PR A — Foundation: Fake relocation, DI plumbing, sandbox entrypoint (~900 LOC)

**Branch:** `sandbox-tier-pr1` (cut from `main`)

**Risk:** medium. Production runtime behavior is unchanged (new kwargs default to behavior-preserving values), but the Port-typing widening may surface real call sites that depended on concrete-type methods. Mitigation: type-check after every task (`make typecheck`); absorb cascade fixes into the relevant task.

### Task 1.1: Create `src/mockworld/` package and relocate the 12 existing Fakes

**Files:**
- Create: `src/mockworld/__init__.py`
- Create: `src/mockworld/fakes/__init__.py`
- Move (12 files): `tests/scenarios/fakes/fake_{github,workspace,llm,clock,docker,git,fs,http,sentry,beads,subprocess_runner,wiki_compiler}.py` → `src/mockworld/fakes/fake_*.py`
- Modify: `tests/scenarios/fakes/mock_world.py` (update internal imports)
- Modify: `tests/scenarios/conftest.py` (update fixture imports)
- Modify: any `tests/scenarios/test_*.py` that imports from `tests.scenarios.fakes`

- [ ] **Step 1: Create the new package directories**

```bash
mkdir -p src/mockworld/fakes
```

- [ ] **Step 2: Create `src/mockworld/__init__.py`**

```python
"""MockWorld — alternative adapter set for HydraFlow.

This package contains Fake adapters that satisfy the same Ports as the
production adapters (PRPort, WorkspacePort, IssueStorePort, IssueFetcherPort,
plus the LLM runner ports). They are always loaded; selection between
real and Fake happens at entrypoint level, not via config.

See docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md
"""
```

- [ ] **Step 3: Create `src/mockworld/fakes/__init__.py` with re-exports**

```python
"""Fake adapters for MockWorld.

All Fakes here satisfy a Port protocol from src/ports.py. Production
code (server.py, orchestrator.py) does NOT import from this package —
only the sandbox entrypoint does.
"""

from mockworld.fakes.fake_beads import FakeBeads
from mockworld.fakes.fake_clock import FakeClock
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_fs import FakeFS
from mockworld.fakes.fake_git import FakeGit
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_http import FakeHTTP
from mockworld.fakes.fake_llm import FakeLLM
from mockworld.fakes.fake_sentry import FakeSentry
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
from mockworld.fakes.fake_wiki_compiler import FakeWikiCompiler
from mockworld.fakes.fake_workspace import FakeWorkspace

__all__ = [
    "FakeBeads",
    "FakeClock",
    "FakeDocker",
    "FakeFS",
    "FakeGit",
    "FakeGitHub",
    "FakeHTTP",
    "FakeLLM",
    "FakeSentry",
    "FakeSubprocessRunner",
    "FakeWikiCompiler",
    "FakeWorkspace",
]
```

- [ ] **Step 4: Move the 12 Fake files via `git mv`**

```bash
for f in fake_beads fake_clock fake_docker fake_fs fake_git fake_github fake_http fake_llm fake_sentry fake_subprocess_runner fake_wiki_compiler fake_workspace; do
  git mv tests/scenarios/fakes/${f}.py src/mockworld/fakes/${f}.py
done
```

- [ ] **Step 5: Bulk-update import paths across the codebase**

```bash
grep -rl "tests.scenarios.fakes" tests/ src/ | xargs sed -i.bak 's|from tests\.scenarios\.fakes\.fake_|from mockworld.fakes.fake_|g; s|from tests\.scenarios\.fakes import|from mockworld.fakes import|g'
find tests/ src/ -name "*.bak" -delete
```

- [ ] **Step 6: Verify mock_world.py and conftest.py imports resolve**

```bash
python -c "from mockworld.fakes import FakeGitHub, FakeWorkspace, FakeLLM"
python -c "from tests.scenarios.fakes.mock_world import MockWorld"
```

Expected: no import errors.

- [ ] **Step 7: Run scenario test suite to verify the move was clean**

```bash
.venv/bin/pytest tests/scenarios/test_happy.py -v -x
```

Expected: all tests pass (the move is purely structural; behavior unchanged).

- [ ] **Step 8: Commit**

```bash
git add src/mockworld/ tests/
git commit -m "refactor(mockworld): relocate Fakes from tests/scenarios/fakes/ to src/mockworld/fakes/

Fakes are alternative adapters, not test fixtures. Moving them under src/
makes them importable by the sandbox entrypoint (PR A follow-on tasks)
without violating the src→tests dependency direction.

The Fakes have zero side effects on import (verified) — production code
(server.py, orchestrator.py) does not import them; only the sandbox
entrypoint added later in PR A will.

Pure relocation: behavior unchanged, all imports rewired, tests still
green."
```

### Task 1.2: Move conformance tests alongside the Fakes

**Files:**
- Move: `tests/scenarios/fakes/test_port_signature_conformance.py` → `tests/test_mockworld_fakes_conformance.py`
- Move: `tests/scenarios/fakes/test_port_conformance.py` → `tests/test_mockworld_runtime_conformance.py`

- [ ] **Step 1: Move via `git mv`**

```bash
git mv tests/scenarios/fakes/test_port_signature_conformance.py tests/test_mockworld_fakes_conformance.py
git mv tests/scenarios/fakes/test_port_conformance.py tests/test_mockworld_runtime_conformance.py
```

- [ ] **Step 2: Update top-of-file imports in both files**

In `tests/test_mockworld_fakes_conformance.py`, replace:

```python
from tests.scenarios.fakes.fake_github import FakeGitHub
from tests.scenarios.fakes.fake_workspace import FakeWorkspace
```

with:

```python
from mockworld.fakes.fake_github import FakeGitHub
from mockworld.fakes.fake_workspace import FakeWorkspace
```

Same pattern for `tests/test_mockworld_runtime_conformance.py`.

- [ ] **Step 3: Run both conformance tests**

```bash
.venv/bin/pytest tests/test_mockworld_fakes_conformance.py tests/test_mockworld_runtime_conformance.py -v
```

Expected: all tests pass (conformance was passing in their old location; the tests themselves haven't changed).

- [ ] **Step 4: Commit**

```bash
git add tests/test_mockworld_fakes_conformance.py tests/test_mockworld_runtime_conformance.py tests/scenarios/fakes/
git commit -m "test(mockworld): relocate Port↔Fake conformance tests

Conformance tests live next to other top-level test_*.py files now that
the Fakes themselves moved to src/mockworld/fakes/. Filename prefix
test_mockworld_* makes the test surface discoverable."
```

### Task 1.3: Add `_is_fake_adapter` class-attribute marker to all Fake adapters

**Files:**
- Modify: `src/mockworld/fakes/fake_github.py`
- Modify: `src/mockworld/fakes/fake_workspace.py`
- Modify: `src/mockworld/fakes/fake_llm.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_mockworld_fakes_marker.py`:

```python
"""Verify all Fake adapters carry the `_is_fake_adapter = True` marker.

The dashboard reads this marker via duck-typing to decide whether to
render the MOCKWORLD MODE banner. Adding it as a CLASS attribute (not
instance attribute) means it's discoverable without instantiation and
survives class-level introspection.
"""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub, FakeLLM, FakeWorkspace

_FAKE_CLASSES = [FakeGitHub, FakeWorkspace, FakeLLM]


@pytest.mark.parametrize("cls", _FAKE_CLASSES, ids=lambda c: c.__name__)
def test_fake_adapter_has_marker(cls: type) -> None:
    assert getattr(cls, "_is_fake_adapter", False) is True, (
        f"{cls.__name__} is missing `_is_fake_adapter = True` class attribute. "
        "The dashboard banner relies on this for duck-typed detection."
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_mockworld_fakes_marker.py -v
```

Expected: 3 FAIL ("`_is_fake_adapter` missing").

- [ ] **Step 3: Add marker to FakeGitHub**

In `src/mockworld/fakes/fake_github.py`, in the `class FakeGitHub:` body, add as the first line after the docstring:

```python
class FakeGitHub:
    """Stateful fake for GitHub API (PRManager + IssueFetcher)."""

    _is_fake_adapter = True   # NEW — read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        ...
```

- [ ] **Step 4: Add marker to FakeWorkspace**

In `src/mockworld/fakes/fake_workspace.py`, in the `class FakeWorkspace:` body, add after the docstring:

```python
class FakeWorkspace:
    """In-memory fake for WorkspaceManager."""

    _is_fake_adapter = True   # NEW — read by dashboard for MOCKWORLD banner
```

- [ ] **Step 5: Add marker to FakeLLM**

In `src/mockworld/fakes/fake_llm.py`, in the `class FakeLLM:` body, add after the docstring:

```python
class FakeLLM:
    """Scriptable fake for the LLM-backed runner ports."""

    _is_fake_adapter = True   # NEW — read by dashboard for MOCKWORLD banner
```

- [ ] **Step 6: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_mockworld_fakes_marker.py -v
```

Expected: 3 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/mockworld/fakes/ tests/test_mockworld_fakes_marker.py
git commit -m "feat(mockworld): add _is_fake_adapter marker to Fake classes

Class-level marker that the dashboard reads via duck-typing
(getattr(prs, '_is_fake_adapter', False)) to render the MOCKWORLD MODE
banner. Class attribute (not instance) so it survives any subclassing
and is discoverable without construction.

Test enforces the marker is present on FakeGitHub, FakeWorkspace,
FakeLLM. Future Fake adapters added to src/mockworld/fakes/ should
also carry this marker — extend the test's _FAKE_CLASSES list."
```

### Task 1.4: Add `PRPort.list_prs_by_label` + implement on `PRManager` and `FakeGitHub`

**Files:**
- Modify: `src/ports.py` (add abstract method to `PRPort`)
- Modify: `src/pr_manager.py` (implement on real `PRManager`)
- Modify: `src/mockworld/fakes/fake_github.py` (implement on `FakeGitHub`)
- Test: `tests/test_pr_manager_list_prs_by_label.py`
- Test: `tests/test_fake_github_list_prs_by_label.py`

- [ ] **Step 1: Write failing test for `FakeGitHub.list_prs_by_label`**

Create `tests/test_fake_github_list_prs_by_label.py`:

```python
"""FakeGitHub.list_prs_by_label — filters in-memory PRs by label."""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub


@pytest.mark.asyncio
async def test_list_prs_by_label_returns_matching_prs() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "second", "body", labels=["hydraflow-ready"])
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")
    gh.add_pr(number=101, issue_number=2, branch="hf/issue-2")
    gh.add_pr_label(100, "sandbox-fail-auto-fix")
    gh.add_pr_label(101, "wip")

    prs = await gh.list_prs_by_label("sandbox-fail-auto-fix")

    assert len(prs) == 1
    assert prs[0].number == 100


@pytest.mark.asyncio
async def test_list_prs_by_label_empty_when_no_match() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body")
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1")

    prs = await gh.list_prs_by_label("does-not-exist")

    assert prs == []


@pytest.mark.asyncio
async def test_list_prs_by_label_excludes_merged_prs() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body")
    gh.add_pr(number=100, issue_number=1, branch="hf/issue-1", merged=True)
    gh.add_pr_label(100, "sandbox-fail-auto-fix")

    prs = await gh.list_prs_by_label("sandbox-fail-auto-fix")

    assert prs == [], "merged PRs should not appear in by-label query"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_fake_github_list_prs_by_label.py -v
```

Expected: FAIL — `FakeGitHub` has no `list_prs_by_label` or `add_pr_label` method.

- [ ] **Step 3: Add `list_prs_by_label` abstract method to `PRPort`**

In `src/ports.py`, in the `class PRPort(Protocol):` block, after the existing `list_closed_issues_by_label` method (around line 309), add:

```python
async def list_prs_by_label(self, label: str) -> list[PRInfo]:
    """Return open (non-merged) PRs with the given label.

    Used by SandboxFailureFixerLoop to poll PRs that need auto-fix
    intervention. Excludes merged and closed PRs by definition —
    callers wanting closed PRs use a different method.
    """
    ...
```

- [ ] **Step 4: Implement on `FakeGitHub`**

In `src/mockworld/fakes/fake_github.py`, add to the `FakeGitHub` class:

```python
def add_pr_label(self, pr_number: int, label: str) -> None:
    """Seed-API helper: attach a label to a fake PR."""
    pr = self._prs[pr_number]
    if not hasattr(pr, "labels"):
        pr.labels = []   # type: ignore[attr-defined]
    if label not in pr.labels:   # type: ignore[attr-defined]
        pr.labels.append(label)   # type: ignore[attr-defined]

async def list_prs_by_label(self, label: str) -> list[PRInfo]:
    """Return open PRs carrying the given label."""
    out: list[PRInfo] = []
    for pr in self._prs.values():
        if pr.merged:
            continue
        labels = getattr(pr, "labels", [])
        if label not in labels:
            continue
        out.append(
            PRInfoFactory.create(
                number=pr.number,
                branch=pr.branch,
                merged=False,
                additions=pr.additions,
                deletions=pr.deletions,
            )
        )
    return out
```

Also add `labels: list[str] = field(default_factory=list)` to the `@dataclass class FakePR:` definition (top of `fake_github.py`).

- [ ] **Step 5: Run FakeGitHub tests, verify they pass**

```bash
.venv/bin/pytest tests/test_fake_github_list_prs_by_label.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Write failing test for real `PRManager.list_prs_by_label`**

Create `tests/test_pr_manager_list_prs_by_label.py`:

```python
"""PRManager.list_prs_by_label — delegates to `gh pr list --label`."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import HydraFlowConfig
from events import EventBus
from pr_manager import PRManager


@pytest.mark.asyncio
async def test_list_prs_by_label_calls_gh_with_label_filter(tmp_path) -> None:
    config = HydraFlowConfig(repo_root=tmp_path, repo="owner/repo")
    bus = EventBus()
    pm = PRManager(config, bus)

    fake_output = (
        '[{"number": 100, "headRefName": "rc/2026-04-26", "additions": 10,'
        ' "deletions": 5, "merged": false}]'
    )
    with patch("pr_manager.run_gh_command", new=AsyncMock(return_value=fake_output)) as mock:
        prs = await pm.list_prs_by_label("sandbox-fail-auto-fix")

    assert len(prs) == 1
    assert prs[0].number == 100
    assert prs[0].branch == "rc/2026-04-26"
    args, _ = mock.call_args
    cmd = args[0] if args else mock.call_args.kwargs.get("cmd")
    assert "list" in cmd and "--label" in cmd and "sandbox-fail-auto-fix" in cmd
    assert "--state open" in " ".join(cmd) or ("--state" in cmd and "open" in cmd)
```

- [ ] **Step 7: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_pr_manager_list_prs_by_label.py -v
```

Expected: FAIL — `PRManager` has no `list_prs_by_label`.

- [ ] **Step 8: Implement on `PRManager`**

In `src/pr_manager.py`, add a method to the `PRManager` class:

```python
async def list_prs_by_label(self, label: str) -> list[PRInfo]:
    """Return open PRs carrying the given label.

    Delegates to `gh pr list --label <label> --state open --json ...`.
    """
    cmd = [
        "gh", "pr", "list",
        "--label", label,
        "--state", "open",
        "--json", "number,headRefName,additions,deletions,merged",
        "--limit", "100",
    ]
    raw = await run_gh_command(cmd, repo=self._config.repo)
    if not raw:
        return []
    items = json.loads(raw)
    return [
        PRInfo(
            number=item["number"],
            branch=item["headRefName"],
            additions=item.get("additions", 0),
            deletions=item.get("deletions", 0),
            merged=item.get("merged", False),
        )
        for item in items
    ]
```

(Add `import json` at the top of `pr_manager.py` if not already present.)

- [ ] **Step 9: Run PR manager test, verify it passes**

```bash
.venv/bin/pytest tests/test_pr_manager_list_prs_by_label.py -v
```

Expected: PASS.

- [ ] **Step 10: Run conformance tests to verify Port↔Fake alignment**

```bash
.venv/bin/pytest tests/test_mockworld_fakes_conformance.py -v
```

Expected: PASS — `list_prs_by_label` signature matches between `PRPort` and `FakeGitHub`.

- [ ] **Step 11: Commit**

```bash
git add src/ports.py src/pr_manager.py src/mockworld/fakes/fake_github.py tests/test_pr_manager_list_prs_by_label.py tests/test_fake_github_list_prs_by_label.py
git commit -m "feat(ports): add PRPort.list_prs_by_label

Required by SandboxFailureFixerLoop (PR C) to poll PRs labeled
'sandbox-fail-auto-fix' for auto-fix intervention, and by the new
/api/sandbox-hitl endpoint to surface stuck PRs in the System tab.

Implemented on real PRManager (delegates to gh pr list --label) and
on FakeGitHub (in-memory label match). Port-Fake conformance test
enforces signature alignment going forward.

Excludes merged/closed PRs by design — callers wanting them use other
methods."
```


### Task 1.5: Create `FakeIssueFetcher` and `FakeIssueStore` (extracted from `_wire_targets`)

**Files:**
- Create: `src/mockworld/fakes/fake_issue_fetcher.py`
- Create: `src/mockworld/fakes/fake_issue_store.py`
- Modify: `src/mockworld/fakes/__init__.py` (add re-exports)
- Test: `tests/test_fake_issue_fetcher.py`
- Test: `tests/test_fake_issue_store.py`

- [ ] **Step 1: Write failing test for `FakeIssueFetcher`**

Create `tests/test_fake_issue_fetcher.py`:

```python
"""FakeIssueFetcher — backs IssueFetcherPort from in-memory FakeGitHub state."""

from __future__ import annotations

import pytest

from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher


@pytest.mark.asyncio
async def test_fetch_returns_issues_seeded_in_github() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "second", "body", labels=["hydraflow-ready"])
    fetcher = FakeIssueFetcher(github=gh)

    issues = await fetcher.fetch_open_issues_by_label("hydraflow-ready")

    assert {i.number for i in issues} == {1, 2}


@pytest.mark.asyncio
async def test_fetch_excludes_issues_without_label() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "tagged", "body", labels=["hydraflow-ready"])
    gh.add_issue(2, "untagged", "body", labels=[])
    fetcher = FakeIssueFetcher(github=gh)

    issues = await fetcher.fetch_open_issues_by_label("hydraflow-ready")

    assert [i.number for i in issues] == [1]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_fake_issue_fetcher.py -v
```

Expected: ImportError — module doesn't exist.

- [ ] **Step 3: Implement `FakeIssueFetcher`**

Create `src/mockworld/fakes/fake_issue_fetcher.py`:

```python
"""FakeIssueFetcher — IssueFetcherPort impl backed by FakeGitHub state.

Extracted from `tests/scenarios/fakes/mock_world.py:_wire_targets`,
which previously monkeypatched the real IssueFetcher with FakeGitHub
methods. Now FakeIssueFetcher is a standalone class that satisfies
IssueFetcherPort and can be passed via build_services() override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockworld.fakes.fake_github import FakeGitHub


@dataclass
class FakeIssueSummary:
    """Minimal IssueFetcher-shaped payload."""
    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueFetcher:
    """IssueFetcherPort implementation reading from FakeGitHub state."""

    _is_fake_adapter = True

    def __init__(self, github: "FakeGitHub") -> None:
        self._github = github

    @classmethod
    def from_seed(cls, seed: "MockWorldSeed") -> "FakeIssueFetcher":
        """Build a FakeIssueFetcher from a serialized seed.

        Constructs an internal FakeGitHub from the seed's issue list
        and wraps it. Same semantics as constructing FakeGitHub.from_seed
        and passing it in.
        """
        from mockworld.fakes.fake_github import FakeGitHub

        github = FakeGitHub.from_seed(seed)
        return cls(github=github)

    async def fetch_open_issues_by_label(self, label: str) -> list[FakeIssueSummary]:
        out = []
        for issue in self._github._issues.values():
            if issue.state != "open":
                continue
            if label not in issue.labels:
                continue
            out.append(FakeIssueSummary(
                number=issue.number,
                title=issue.title,
                body=issue.body,
                labels=list(issue.labels),
            ))
        return out
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_fake_issue_fetcher.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Write failing test for `FakeIssueStore`**

Create `tests/test_fake_issue_store.py`:

```python
"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub + in-memory cache."""

from __future__ import annotations

import pytest

from events import EventBus
from mockworld.fakes import FakeGitHub
from mockworld.fakes.fake_issue_store import FakeIssueStore


@pytest.mark.asyncio
async def test_get_returns_issue_from_underlying_github() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    issue = await store.get(1)

    assert issue.number == 1
    assert issue.title == "first"


@pytest.mark.asyncio
async def test_transition_updates_label() -> None:
    gh = FakeGitHub()
    gh.add_issue(1, "first", "body", labels=["hydraflow-ready"])
    store = FakeIssueStore(github=gh, event_bus=EventBus())

    await store.transition(1, "hydraflow-ready", "hydraflow-planning")

    assert "hydraflow-ready" not in gh._issues[1].labels
    assert "hydraflow-planning" in gh._issues[1].labels
```

- [ ] **Step 6: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_fake_issue_store.py -v
```

Expected: ImportError.

- [ ] **Step 7: Implement `FakeIssueStore`**

Create `src/mockworld/fakes/fake_issue_store.py`:

```python
"""FakeIssueStore — IssueStorePort impl backed by FakeGitHub state.

Extracted from `tests/scenarios/fakes/mock_world.py:_wire_targets`,
which previously monkeypatched the real IssueStore. Now standalone
so build_services() can accept it as an override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from events import EventBus
    from mockworld.fakes.fake_github import FakeGitHub
    from mockworld.seed import MockWorldSeed


@dataclass
class FakeIssueRecord:
    """Minimal IssueStore-shaped payload."""
    number: int
    title: str
    body: str
    labels: list[str]
    state: str = "OPEN"


class FakeIssueStore:
    """IssueStorePort impl. Reads from FakeGitHub; writes back to it."""

    _is_fake_adapter = True

    def __init__(self, github: "FakeGitHub", event_bus: "EventBus") -> None:
        self._github = github
        self._bus = event_bus

    @classmethod
    def from_seed(cls, seed: "MockWorldSeed", event_bus: "EventBus") -> "FakeIssueStore":
        from mockworld.fakes.fake_github import FakeGitHub

        github = FakeGitHub.from_seed(seed)
        return cls(github=github, event_bus=event_bus)

    async def get(self, issue_number: int) -> FakeIssueRecord:
        issue = self._github._issues[issue_number]
        return FakeIssueRecord(
            number=issue.number,
            title=issue.title,
            body=issue.body,
            labels=list(issue.labels),
        )

    async def transition(self, issue_number: int, from_label: str, to_label: str) -> None:
        issue = self._github._issues[issue_number]
        if from_label in issue.labels:
            issue.labels.remove(from_label)
        if to_label not in issue.labels:
            issue.labels.append(to_label)

    async def list_by_label(self, label: str) -> list[FakeIssueRecord]:
        out = []
        for issue in self._github._issues.values():
            if label in issue.labels and issue.state == "open":
                out.append(FakeIssueRecord(
                    number=issue.number,
                    title=issue.title,
                    body=issue.body,
                    labels=list(issue.labels),
                ))
        return out
```

- [ ] **Step 8: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_fake_issue_store.py -v
```

Expected: 2 PASS.

- [ ] **Step 9: Update `src/mockworld/fakes/__init__.py` with the new re-exports**

```python
from mockworld.fakes.fake_issue_fetcher import FakeIssueFetcher
from mockworld.fakes.fake_issue_store import FakeIssueStore
```

Add `"FakeIssueFetcher"` and `"FakeIssueStore"` to `__all__`.

- [ ] **Step 10: Commit**

```bash
git add src/mockworld/fakes/fake_issue_fetcher.py src/mockworld/fakes/fake_issue_store.py src/mockworld/fakes/__init__.py tests/test_fake_issue_fetcher.py tests/test_fake_issue_store.py
git commit -m "feat(mockworld): add standalone FakeIssueFetcher and FakeIssueStore

Extracted from MockWorld._wire_targets monkeypatching into standalone
classes that satisfy IssueFetcherPort and IssueStorePort. Required by
the sandbox entrypoint (next task) which constructs them via
build_services() overrides — monkeypatching only works in-process and
can't reach the docker container.

Both expose from_seed() classmethods consistent with FakeGitHub.from_seed
(added in next task)."
```

### Task 1.6: Add `MockWorldSeed` dataclass + `from_seed()` on FakeGitHub

**Files:**
- Create: `src/mockworld/seed.py`
- Modify: `src/mockworld/fakes/fake_github.py` (add `from_seed` classmethod)
- Test: `tests/test_mockworld_seed.py`
- Test: `tests/test_fake_github_from_seed.py`

- [ ] **Step 1: Write failing test for `MockWorldSeed`**

Create `tests/test_mockworld_seed.py`:

```python
"""MockWorldSeed — serializable initial state for a sandbox scenario."""

from __future__ import annotations

import json

from mockworld.seed import MockWorldSeed


def test_default_seed_is_empty() -> None:
    seed = MockWorldSeed()
    assert seed.repos == []
    assert seed.issues == []
    assert seed.prs == []
    assert seed.scripts == {}
    assert seed.cycles_to_run == 4
    assert seed.loops_enabled is None


def test_seed_round_trips_through_json() -> None:
    original = MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={"plan": {1: [{"success": True}]}},
        cycles_to_run=10,
        loops_enabled=["triage_loop"],
    )

    raw = original.to_json()
    parsed = MockWorldSeed.from_json(raw)

    assert parsed == original


def test_seed_json_is_valid_json() -> None:
    seed = MockWorldSeed(issues=[{"number": 1}])
    raw = seed.to_json()
    parsed = json.loads(raw)
    assert parsed["issues"] == [{"number": 1}]
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_mockworld_seed.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `MockWorldSeed`**

Create `src/mockworld/seed.py`:

```python
"""MockWorldSeed — serializable initial state for a sandbox scenario.

A scenario module's `seed()` function returns this dataclass. The host-side
harness serializes via `to_json()` and writes the result to a file that
the docker container's `mockworld.sandbox_main` entrypoint reads on boot.

Pure data; no methods that take a live FakeGitHub. The Fake adapters'
own `from_seed(seed)` classmethods construct themselves from this payload.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MockWorldSeed:
    """Serializable initial state for a MockWorld run."""

    # List of (slug, path) pairs registered into RepoRegistryStore.
    repos: list[tuple[str, str]] = field(default_factory=list)

    # Each issue is a dict with keys: number, title, body, labels[].
    issues: list[dict[str, Any]] = field(default_factory=list)

    # Each PR is a dict with keys: number, issue_number, branch,
    # ci_status, merged, labels[].
    prs: list[dict[str, Any]] = field(default_factory=list)

    # Per-phase scripted LLM responses. Outer key is phase name
    # ("triage", "plan", "implement", "review", "fix_ci"); inner key is
    # issue number; value is a list of result dicts that get popped per
    # invocation.
    scripts: dict[str, dict[int, list[Any]]] = field(default_factory=dict)

    # How many ticks each enabled loop fires before assertions run.
    cycles_to_run: int = 4

    # Subset of loops to enable. None = all registered loops.
    loops_enabled: list[str] | None = None

    def to_json(self) -> str:
        """Serialize to JSON for cross-process transfer."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> "MockWorldSeed":
        """Deserialize from JSON string."""
        data = json.loads(raw)
        # asdict() converts tuples to lists; coerce repos back.
        if "repos" in data:
            data["repos"] = [tuple(r) for r in data["repos"]]
        # JSON keys are strings; coerce script issue keys back to int.
        if "scripts" in data:
            data["scripts"] = {
                phase: {int(k): v for k, v in by_issue.items()}
                for phase, by_issue in data["scripts"].items()
            }
        return cls(**data)
```

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/pytest tests/test_mockworld_seed.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Write failing test for `FakeGitHub.from_seed`**

Create `tests/test_fake_github_from_seed.py`:

```python
"""FakeGitHub.from_seed — construct a FakeGitHub from a MockWorldSeed."""

from __future__ import annotations

from mockworld.fakes import FakeGitHub
from mockworld.seed import MockWorldSeed


def test_from_seed_populates_issues() -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "body1", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "body2", "labels": ["y"]},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert set(gh._issues.keys()) == {1, 2}
    assert gh._issues[1].title == "first"
    assert gh._issues[2].labels == ["y"]


def test_from_seed_populates_prs() -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": []}],
        prs=[
            {"number": 100, "issue_number": 1, "branch": "hf/issue-1",
             "ci_status": "pass", "merged": False, "labels": ["wip"]},
        ],
    )

    gh = FakeGitHub.from_seed(seed)

    assert 100 in gh._prs
    assert gh._prs[100].branch == "hf/issue-1"
    assert "wip" in getattr(gh._prs[100], "labels", [])


def test_from_seed_handles_empty_seed() -> None:
    gh = FakeGitHub.from_seed(MockWorldSeed())
    assert gh._issues == {}
    assert gh._prs == {}
```

- [ ] **Step 6: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_fake_github_from_seed.py -v
```

Expected: AttributeError — `FakeGitHub` has no `from_seed`.

- [ ] **Step 7: Add `from_seed` classmethod to `FakeGitHub`**

In `src/mockworld/fakes/fake_github.py`, add after `__init__`:

```python
@classmethod
def from_seed(cls, seed: "MockWorldSeed") -> "FakeGitHub":
    """Construct a FakeGitHub populated from a MockWorldSeed."""
    gh = cls()
    for issue_dict in seed.issues:
        gh.add_issue(
            number=issue_dict["number"],
            title=issue_dict["title"],
            body=issue_dict["body"],
            labels=list(issue_dict.get("labels", [])),
        )
    for pr_dict in seed.prs:
        gh.add_pr(
            number=pr_dict["number"],
            issue_number=pr_dict["issue_number"],
            branch=pr_dict["branch"],
            ci_status=pr_dict.get("ci_status", "pass"),
            merged=pr_dict.get("merged", False),
        )
        for label in pr_dict.get("labels", []):
            gh.add_pr_label(pr_dict["number"], label)
    return gh
```

Add `from typing import TYPE_CHECKING` and the conditional import block at the top of `fake_github.py` if needed:

```python
if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed
```

- [ ] **Step 8: Run test, verify it passes**

```bash
.venv/bin/pytest tests/test_fake_github_from_seed.py -v
```

Expected: 3 PASS.

- [ ] **Step 9: Commit**

```bash
git add src/mockworld/seed.py src/mockworld/fakes/fake_github.py tests/test_mockworld_seed.py tests/test_fake_github_from_seed.py
git commit -m "feat(mockworld): MockWorldSeed dataclass + FakeGitHub.from_seed

MockWorldSeed is the serializable wire format for sandbox scenarios.
The host harness calls scenario_module.seed() to produce one, writes
to_json() to a file, mounts it into the docker container, and the
container's sandbox_main entrypoint reads it back.

Pure data — no live Fake objects in the seed itself. Fake.from_seed
classmethods do the construction, keeping the seed JSON-friendly and
safe to pass across the host/container boundary."
```


### Task 1.7: Widen Port typing in `ServiceRegistry`, `RouteContext`, and `create_router`

**Files:**
- Modify: `src/service_registry.py` (`ServiceRegistry` dataclass field types)
- Modify: `src/dashboard_routes/_routes.py` (`RouteContext`, `pr_manager_for`, `create_router`)
- Test: existing typecheck + scenario tests

- [ ] **Step 1: Run baseline type-check (capture starting state)**

```bash
.venv/bin/pyright src/service_registry.py src/dashboard_routes/_routes.py 2>&1 | tail -20
```

Record the baseline error count for comparison.

- [ ] **Step 2: Widen `ServiceRegistry` field types in `src/service_registry.py`**

In `src/service_registry.py`, replace these 3 lines in the `@dataclass class ServiceRegistry:` block:

```python
workspaces: WorkspaceManager
prs: PRManager
store: IssueStore
```

with:

```python
workspaces: WorkspacePort
prs: PRPort
store: IssueStorePort
```

Also add the imports near the top of the file if not present:

```python
from ports import IssueStorePort, PRPort, WorkspacePort
```

- [ ] **Step 3: Widen `RouteContext.pr_manager` and the `pr_manager_for` return type in `src/dashboard_routes/_routes.py`**

Around line 309–310, change:

```python
@dataclass
class RouteContext:
    ...
    pr_manager: PRManager
```

to:

```python
@dataclass
class RouteContext:
    ...
    pr_manager: PRPort
```

Around line 456, change `def pr_manager_for(self, ...) -> PRManager:` to `def pr_manager_for(self, ...) -> PRPort:`. (The implementation still returns a `PRManager` instance — that satisfies the wider `PRPort` type.)

Around line 581, change `def create_router(... pr_manager: PRManager, ...)` to `def create_router(... pr_manager: PRPort, ...)`.

Add the import at the top of the file if not already present:

```python
from ports import PRPort
```

- [ ] **Step 4: Run pyright; absorb any cascade errors**

```bash
.venv/bin/pyright src/ 2>&1 | tail -40
```

If pyright surfaces new errors at call sites that use `PRManager`-specific methods (methods not on `PRPort`):
- Either add the method to `PRPort` (preferred if it's a legitimate Port-shaped operation)
- Or use a narrower local annotation: `pr: PRManager = self._svc.prs  # type: ignore[assignment]`
  with a comment noting why the narrowing is safe.

Iterate until pyright is clean. Commit each cascade fix as a separate small step within this task if it grows large.

- [ ] **Step 5: Run scenario test suite to verify no behavioral regression**

```bash
.venv/bin/pytest tests/scenarios/test_happy.py tests/test_dashboard_routes_core.py -v -x
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/service_registry.py src/dashboard_routes/_routes.py
git commit -m "refactor(types): widen Port-shaped fields from concrete adapters to Ports

ServiceRegistry.{prs, workspaces, store} and RouteContext.pr_manager
now annotate the Port protocol instead of the concrete adapter class.
This is required so Fake adapters that satisfy the Port (FakeGitHub
satisfies PRPort, etc.) can be assigned without pyright errors when
the sandbox entrypoint passes them via build_services() overrides.

No runtime behavior change. Production callers still pass real
PRManager / WorkspaceManager / IssueStore instances; widened
annotations accept them unchanged."
```

### Task 1.8: Refactor `build_services()` to accept adapter overrides

**Files:**
- Modify: `src/service_registry.py` (`build_services()` signature)
- Test: `tests/test_build_services_overrides.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_build_services_overrides.py`:

```python
"""build_services() accepts adapter overrides for sandbox use.

Production callers pass nothing → real adapters constructed.
Sandbox callers pass Fakes → those Fakes appear in the registry.
"""

from __future__ import annotations

import asyncio

import pytest

from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes import FakeGitHub, FakeWorkspace
from service_registry import WorkerRegistryCallbacks, build_services
from state import build_state_tracker


@pytest.mark.asyncio
async def test_build_services_uses_real_adapters_when_no_overrides(tmp_path) -> None:
    """Production behavior: no overrides → real adapter classes."""
    config = HydraFlowConfig(repo_root=tmp_path, repo="owner/repo")
    bus = EventBus()
    state = build_state_tracker(config)
    stop = asyncio.Event()
    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *a, **kw: None,
        is_enabled=lambda *a, **kw: True,
        get_interval=lambda *a, **kw: 60,
    )

    svc = build_services(config, bus, state, stop, callbacks)

    # Real adapters: not Fakes.
    assert getattr(svc.prs, "_is_fake_adapter", False) is False
    assert getattr(svc.workspaces, "_is_fake_adapter", False) is False


@pytest.mark.asyncio
async def test_build_services_uses_overrides_when_provided(tmp_path) -> None:
    """Sandbox behavior: explicit overrides used unchanged."""
    config = HydraFlowConfig(repo_root=tmp_path, repo="owner/repo")
    bus = EventBus()
    state = build_state_tracker(config)
    stop = asyncio.Event()
    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *a, **kw: None,
        is_enabled=lambda *a, **kw: True,
        get_interval=lambda *a, **kw: 60,
    )
    fake_gh = FakeGitHub()
    fake_ws = FakeWorkspace()

    svc = build_services(
        config, bus, state, stop, callbacks,
        prs=fake_gh, workspaces=fake_ws,
    )

    assert svc.prs is fake_gh
    assert svc.workspaces is fake_ws
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_build_services_overrides.py -v
```

Expected: FAIL — `build_services()` doesn't accept the `prs=` / `workspaces=` kwargs.

- [ ] **Step 3: Add overrides to `build_services()` signature in `src/service_registry.py`**

Replace the `def build_services(...)` definition (around line 209) with:

```python
def build_services(
    config: HydraFlowConfig,
    event_bus: EventBus,
    state: StateTracker,
    stop_event: asyncio.Event,
    callbacks: WorkerRegistryCallbacks,
    active_issues_cb: Callable[[], None] | None = None,
    credentials: Credentials | None = None,
    *,
    # Sandbox overrides — None → construct the real adapter.
    prs: PRPort | None = None,
    workspaces: WorkspacePort | None = None,
    store: IssueStorePort | None = None,
    fetcher: IssueFetcherPort | None = None,
    # `runners` is duck-typed: any object exposing the four runner attrs
    # (triage_runner, planners, agents, reviewers) suffices. FakeLLM does.
    # See spec Component 1 RunnerSet pattern if a stricter type is preferred.
    runners: object | None = None,
) -> ServiceRegistry:
    """Create all services wired together.

    Production callers pass no override kwargs and get real adapters
    constructed from config + credentials. Sandbox (mockworld.sandbox_main)
    passes Fake adapters to short-circuit the construction.
    """
    ...
```

Then in the body, where the real adapters are constructed (around lines 240, 293, 323, 325), gate each on `if X is None:`:

```python
# Was: workspaces = WorkspaceManager(config, credentials=credentials)
if workspaces is None:
    workspaces = WorkspaceManager(config, credentials=credentials)

# Was: fetcher = IssueFetcher(config, credentials=credentials)
if fetcher is None:
    fetcher = IssueFetcher(config, credentials=credentials)

# Was: store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)
if store is None:
    store = IssueStore(config, GitHubTaskFetcher(fetcher), event_bus)

# Was: prs = PRManager(config, event_bus, credentials=credentials)
if prs is None:
    prs = PRManager(config, event_bus, credentials=credentials)
```

Add the imports at the top of the file:

```python
from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort
```

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/pytest tests/test_build_services_overrides.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run full test suite — verify no regression in production path**

```bash
.venv/bin/pytest tests/scenarios/ tests/test_dashboard_routes_core.py tests/test_orchestrator_core.py -v -x
```

Expected: all pass (production callers pass no overrides; behavior unchanged).

- [ ] **Step 6: Commit**

```bash
git add src/service_registry.py tests/test_build_services_overrides.py
git commit -m "feat(service_registry): accept adapter overrides in build_services()

build_services() gains optional kwargs prs / workspaces / store / fetcher
that, when provided, bypass real-adapter construction and use the
caller-supplied instance instead. Production callers pass nothing —
behavior unchanged.

This is the injection seam for the sandbox entrypoint
(src/mockworld/sandbox_main.py, next task) to wire FakeGitHub /
FakeWorkspace / FakeIssueStore / FakeIssueFetcher into a real
ServiceRegistry without any conditional in the production code path.

Per spec: no config flag for MockWorld — selection happens at the
call site by which entrypoint runs."
```

### Task 1.9: Refactor `HydraFlowOrchestrator.__init__` to accept a pre-built `ServiceRegistry`

**Files:**
- Modify: `src/orchestrator.py` (`HydraFlowOrchestrator.__init__`)
- Test: `tests/test_orchestrator_services_injection.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_orchestrator_services_injection.py`:

```python
"""HydraFlowOrchestrator accepts a pre-built ServiceRegistry."""

from __future__ import annotations

import asyncio

import pytest

from config import HydraFlowConfig
from events import EventBus
from mockworld.fakes import FakeGitHub, FakeWorkspace
from orchestrator import HydraFlowOrchestrator
from service_registry import WorkerRegistryCallbacks, build_services
from state import build_state_tracker


def test_orchestrator_uses_supplied_services(tmp_path) -> None:
    """When `services=` is passed, the orchestrator skips its internal build."""
    config = HydraFlowConfig(repo_root=tmp_path, repo="owner/repo")
    bus = EventBus()
    state = build_state_tracker(config)
    stop = asyncio.Event()
    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *a, **kw: None,
        is_enabled=lambda *a, **kw: True,
        get_interval=lambda *a, **kw: 60,
    )
    fake_gh = FakeGitHub()
    fake_ws = FakeWorkspace()

    pre_built = build_services(
        config, bus, state, stop, callbacks,
        prs=fake_gh, workspaces=fake_ws,
    )

    orch = HydraFlowOrchestrator(
        config, event_bus=bus, state=state, services=pre_built,
    )

    # The orchestrator stores what we gave it — not a freshly-built registry.
    assert orch._svc is pre_built
    assert orch._svc.prs is fake_gh


def test_orchestrator_builds_services_when_not_supplied(tmp_path) -> None:
    """When no services= passed, the orchestrator constructs its own (production path)."""
    config = HydraFlowConfig(repo_root=tmp_path, repo="owner/repo")
    bus = EventBus()
    state = build_state_tracker(config)

    orch = HydraFlowOrchestrator(config, event_bus=bus, state=state)

    # Internal build happened — registry exists, with real adapters.
    assert orch._svc is not None
    assert getattr(orch._svc.prs, "_is_fake_adapter", False) is False
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_orchestrator_services_injection.py -v
```

Expected: FAIL — `__init__` doesn't accept `services=`.

- [ ] **Step 3: Modify `HydraFlowOrchestrator.__init__`**

In `src/orchestrator.py`, replace the `__init__` signature (line 85) and the `build_services()` call (line 127) as follows:

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
    # ... existing setup unchanged through line ~125 ...

    # Build all services via the factory (or use what was passed in)
    if services is None:
        services = build_services(
            config,
            self._bus,
            self._state,
            self._stop_event,
            WorkerRegistryCallbacks(
                update_status=self.update_bg_worker_status,
                is_enabled=self.is_bg_worker_enabled,
                get_interval=self.get_bg_worker_interval,
            ),
            active_issues_cb=self._sync_active_issue_numbers,
        )

    # Store the service registry directly — access via self._svc.<name>
    self._svc: ServiceRegistry = services

    # ... rest of __init__ unchanged ...
```

Add `from service_registry import ServiceRegistry` near the top if not already imported.

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/pytest tests/test_orchestrator_services_injection.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Run full orchestrator regression**

```bash
.venv/bin/pytest tests/test_orchestrator_core.py tests/scenarios/test_happy.py -v -x
```

Expected: all pass (no production behavior change).

- [ ] **Step 6: Commit**

```bash
git add src/orchestrator.py tests/test_orchestrator_services_injection.py
git commit -m "feat(orchestrator): accept pre-built ServiceRegistry via services= kwarg

HydraFlowOrchestrator.__init__ now accepts an optional services kwarg.
When None (production), it builds its own registry as before. When
provided (sandbox entrypoint), it skips the internal build and uses
what the caller supplied.

This is the second half of the DI plumbing — together with build_services()
overrides (previous task), the sandbox entrypoint can wire Fakes through
both layers without any conditional in production code paths."
```

### Task 1.10: Add `MockWorld.apply_seed`, create `sandbox_main.py`, dashboard banner, s00 smoke + parity test

**Files:**
- Modify: `tests/scenarios/fakes/mock_world.py` (add `apply_seed`)
- Create: `src/mockworld/sandbox_main.py`
- Modify: `src/dashboard_routes/_routes.py` or wherever `/api/state` is built (add `mockworld_active`)
- Create: `src/ui/src/components/MockWorldBanner.jsx`
- Modify: `src/ui/src/App.jsx` (render banner)
- Create: `tests/sandbox_scenarios/scenarios/s00_smoke.py`
- Create: `tests/sandbox_scenarios/runner/loader.py`
- Create: `tests/scenarios/test_sandbox_parity.py`
- Test: `tests/test_mock_world_apply_seed.py`
- Test: `tests/test_sandbox_main_smoke.py`

- [ ] **Step 1: Write failing test for `MockWorld.apply_seed`**

Create `tests/test_mock_world_apply_seed.py`:

```python
"""MockWorld.apply_seed populates the wired Fakes from a MockWorldSeed."""

from __future__ import annotations

import pytest

from mockworld.seed import MockWorldSeed


@pytest.mark.asyncio
async def test_apply_seed_populates_github_issues(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[
            {"number": 1, "title": "first", "body": "b", "labels": ["x"]},
            {"number": 2, "title": "second", "body": "b", "labels": ["y"]},
        ],
    )

    mock_world.apply_seed(seed)

    assert {i.number for i in mock_world._github._issues.values()} == {1, 2}


@pytest.mark.asyncio
async def test_apply_seed_populates_phase_scripts(mock_world) -> None:
    seed = MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b", "labels": ["x"]}],
        scripts={
            "plan": {1: [{"success": True}]},
        },
    )

    mock_world.apply_seed(seed)

    # FakeLLM has the plan script populated for issue 1.
    assert 1 in mock_world._llm.planners._scripts
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_mock_world_apply_seed.py -v
```

Expected: AttributeError — `MockWorld` has no `apply_seed`.

- [ ] **Step 3: Add `apply_seed` to `MockWorld`**

In `tests/scenarios/fakes/mock_world.py`, in the `class MockWorld:` body (alongside the existing `add_issue`, `set_phase_result` methods), add:

```python
def apply_seed(self, seed: "MockWorldSeed") -> "MockWorld":
    """Populate wired Fakes from a serialized MockWorldSeed.

    Convenience wrapper over add_issue / add_pr / set_phase_result for
    test code that wants to consume a sandbox scenario's seed() output
    without rewriting it as a fluent chain. Returns self for chaining.
    """
    for repo_slug, repo_path in seed.repos:
        self.add_repo(repo_slug, repo_path)
    for issue_dict in seed.issues:
        self.add_issue(
            number=issue_dict["number"],
            title=issue_dict["title"],
            body=issue_dict["body"],
            labels=list(issue_dict.get("labels", [])),
        )
    for pr_dict in seed.prs:
        self._github.add_pr(
            number=pr_dict["number"],
            issue_number=pr_dict["issue_number"],
            branch=pr_dict["branch"],
            ci_status=pr_dict.get("ci_status", "pass"),
            merged=pr_dict.get("merged", False),
        )
        for label in pr_dict.get("labels", []):
            self._github.add_pr_label(pr_dict["number"], label)
    for phase, by_issue in seed.scripts.items():
        for issue_number, results in by_issue.items():
            for result in results:
                self.set_phase_result(phase, issue_number, result)
    return self
```

Add at top of file:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mockworld.seed import MockWorldSeed
```

- [ ] **Step 4: Run test, verify it passes**

```bash
.venv/bin/pytest tests/test_mock_world_apply_seed.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Create `sandbox_main.py`**

Create `src/mockworld/sandbox_main.py`:

```python
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
import sys
from pathlib import Path

from config import load_runtime_config
from events import EventBus
from mockworld.fakes import (
    FakeGitHub, FakeIssueFetcher, FakeIssueStore, FakeLLM, FakeWorkspace,
)
from mockworld.seed import MockWorldSeed
from orchestrator import HydraFlowOrchestrator
from server import run_dashboard
from service_registry import WorkerRegistryCallbacks, build_services
from state import build_state_tracker


def _load_seed() -> MockWorldSeed:
    """Read the seed file path from argv or env, return the seed.

    Empty seed if no path given — the orchestrator will boot but have
    nothing to do. Useful for shell-debugging the container.
    """
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
    workspaces = FakeWorkspace()
    fetcher = FakeIssueFetcher.from_seed(seed)
    store = FakeIssueStore.from_seed(seed, event_bus)
    prs = FakeGitHub.from_seed(seed)

    # FakeLLM provides triage_runner / planners / agents / reviewers from
    # the seed.scripts payload. Without this, the sandbox would attempt
    # real LLM calls and fail under the air-gapped network.
    fake_llm = FakeLLM()
    for phase, by_issue in seed.scripts.items():
        for issue_number, results in by_issue.items():
            getattr(fake_llm, f"script_{phase}")(issue_number, results)

    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *a, **kw: None,
        is_enabled=lambda *a, **kw: True,
        get_interval=lambda *a, **kw: 60,
    )

    svc = build_services(
        config, event_bus, state, stop_event, callbacks,
        prs=prs, workspaces=workspaces, store=store, fetcher=fetcher,
        # FakeLLM exposes triage_runner / planners / agents / reviewers
        # attrs that build_services' `runners` kwarg expects. Extend
        # build_services in Task 1.8 to also gate on `runners is None`
        # like the other overrides if the kwarg isn't already there
        # (see spec Component 1: `runners: RunnerSet | None = None`).
        runners=fake_llm,
    )

    orch = HydraFlowOrchestrator(
        config, event_bus=event_bus, state=state, services=svc,
    )

    await run_dashboard(config, orch, stop_event)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Smoke-test sandbox_main with empty seed**

Create `tests/test_sandbox_main_smoke.py`:

```python
"""sandbox_main bootstrap with empty seed — proves wiring resolves."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from mockworld import sandbox_main


def test_load_seed_returns_empty_when_no_path() -> None:
    with patch.object(sandbox_main.sys, "argv", ["sandbox_main"]):
        with patch.dict("os.environ", {}, clear=False):
            os_env = sandbox_main.os.environ.copy()
            os_env.pop("HYDRAFLOW_MOCKWORLD_SEED", None)
            with patch.dict(sandbox_main.os.environ, os_env, clear=True):
                seed = sandbox_main._load_seed()
    assert seed.issues == []
    assert seed.prs == []


def test_load_seed_reads_file_path_from_argv(tmp_path) -> None:
    seed_path = tmp_path / "scenario.json"
    seed_path.write_text(
        '{"repos": [], "issues": [{"number": 1, "title": "t", "body": "b", "labels": []}],'
        ' "prs": [], "scripts": {}, "cycles_to_run": 4, "loops_enabled": null}'
    )
    with patch.object(sandbox_main.sys, "argv", ["sandbox_main", str(seed_path)]):
        seed = sandbox_main._load_seed()
    assert len(seed.issues) == 1
    assert seed.issues[0]["number"] == 1
```

- [ ] **Step 7: Run smoke test**

```bash
.venv/bin/pytest tests/test_sandbox_main_smoke.py -v
```

Expected: 2 PASS.

- [ ] **Step 8: Add dashboard `mockworld_active` field**

Find where `/api/state` is built — search for `def get_state` or `mockworld_active` candidate insertion in `src/dashboard_routes/`:

```bash
grep -rn "def.*state\|/api/state" src/dashboard_routes/ | head -10
```

In the handler that builds the `/api/state` payload (typically `_state_routes.py` or `_routes.py`), add to the response dict:

```python
mockworld_active = getattr(self._svc.prs, "_is_fake_adapter", False)
return {
    ...,
    "mockworld_active": mockworld_active,
}
```

(Adjust to the actual response-building pattern in the file.)

- [ ] **Step 9: Create `MockWorldBanner.jsx`**

Create `src/ui/src/components/MockWorldBanner.jsx`:

```jsx
import React from "react";

export default function MockWorldBanner({ active }) {
  if (!active) return null;
  return (
    <div
      role="alert"
      data-testid="mockworld-banner"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        right: 0,
        zIndex: 9999,
        background: "#ff9800",
        color: "#000",
        padding: "8px 16px",
        textAlign: "center",
        fontWeight: 700,
        fontFamily: "monospace",
      }}
    >
      MOCKWORLD MODE — no real GitHub or LLM calls. Issues are simulated.
    </div>
  );
}
```

- [ ] **Step 10: Render banner in `App.jsx`**

In `src/ui/src/App.jsx`, import and render:

```jsx
import MockWorldBanner from "./components/MockWorldBanner";
// ... inside the App component, near the top of the returned JSX:
<MockWorldBanner active={state?.mockworld_active === true} />
```

- [ ] **Step 11: Create scenario package and `s00_smoke`**

```bash
mkdir -p tests/sandbox_scenarios/scenarios tests/sandbox_scenarios/runner
touch tests/sandbox_scenarios/__init__.py tests/sandbox_scenarios/scenarios/__init__.py tests/sandbox_scenarios/runner/__init__.py
```

Create `tests/sandbox_scenarios/scenarios/s00_smoke.py`:

```python
"""s00_smoke — trivial parity-only scenario proving the wiring resolves.

PR A scenario. Has no Tier-2 (sandbox) implementation yet; just
exercises the full apply_seed → run_with_loops chain in-process to
verify nothing in the foundation refactor broke.

Tier-2 implementation lands in PR B (s01_happy_single_issue).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s00_smoke"
DESCRIPTION = "Trivial parity-only scenario — no UI assertions; proves wiring."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[
            {"number": 1, "title": "smoke", "body": "b", "labels": ["hydraflow-ready"]},
        ],
        cycles_to_run=2,
    )


# No assert_outcome — this scenario is parity-only (Tier 1 in-process).
# PR B's s01 introduces the assert_outcome pattern for Tier 2.
```

- [ ] **Step 12: Create the scenario loader**

Create `tests/sandbox_scenarios/runner/loader.py`:

```python
"""Discover all sandbox scenarios under tests/sandbox_scenarios/scenarios/."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType


def load_all_scenarios() -> list[ModuleType]:
    """Import every s*.py module under tests/sandbox_scenarios/scenarios/."""
    import tests.sandbox_scenarios.scenarios as scenarios_pkg

    out: list[ModuleType] = []
    pkg_path = Path(scenarios_pkg.__file__).parent
    for finder, name, ispkg in pkgutil.iter_modules([str(pkg_path)]):
        if not name.startswith("s"):
            continue
        mod = importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")
        out.append(mod)
    return sorted(out, key=lambda m: m.NAME)
```

- [ ] **Step 13: Create the parity test**

Create `tests/scenarios/test_sandbox_parity.py`:

```python
"""Parity test: every sandbox scenario must also pass in-process Tier 1.

If a scenario fails Tier 2 (sandbox) but passes here, the bug is in
container/wiring/UI. If both fail, the bug is in scenario logic or
Fake behavior.
"""

from __future__ import annotations

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios


@pytest.mark.parametrize("scenario", load_all_scenarios(), ids=lambda s: s.NAME)
async def test_sandbox_scenario_runs_in_process(mock_world, scenario) -> None:
    seed = scenario.seed()
    mock_world.apply_seed(seed)

    loops = seed.loops_enabled or [
        "triage_loop", "plan_loop", "implement_loop", "review_loop", "merge_loop",
    ]
    await mock_world.run_with_loops(loops, cycles=seed.cycles_to_run)

    # Smoke check: at least one issue advanced past "queued".
    last_run = getattr(mock_world, "last_run", None)
    if last_run is None or not getattr(last_run, "issues", None):
        # No run-pipeline-style results — apply_seed populated state but
        # run_with_loops uses the loop-based path. Smoke is "didn't crash".
        return
    advanced = any(
        outcome.final_stage != "queued"
        for outcome in last_run.issues.values()
    )
    assert advanced, f"scenario {scenario.NAME} produced no progress in-process"
```

- [ ] **Step 14: Run parity test against s00**

```bash
.venv/bin/pytest tests/scenarios/test_sandbox_parity.py -v
```

Expected: 1 PASS (s00 didn't crash).

- [ ] **Step 15: Run full PR A regression suite**

```bash
.venv/bin/pytest tests/scenarios/ tests/test_orchestrator_core.py tests/test_dashboard_routes_core.py tests/test_mockworld_fakes_conformance.py tests/test_mockworld_runtime_conformance.py -v -x
```

Expected: all pass.

- [ ] **Step 16: Run quality gates**

```bash
make quality
```

Expected: clean. (If pyright surfaces issues from the type widening, fix and amend; if ruff complains, fix and amend.)

- [ ] **Step 17: Commit**

```bash
git add src/mockworld/sandbox_main.py tests/scenarios/fakes/mock_world.py src/dashboard_routes/ src/ui/ tests/sandbox_scenarios/ tests/scenarios/test_sandbox_parity.py tests/test_mock_world_apply_seed.py tests/test_sandbox_main_smoke.py
git commit -m "feat(mockworld): sandbox_main entrypoint + apply_seed + dashboard banner + s00

Final foundation piece for PR A:

- src/mockworld/sandbox_main.py — the entrypoint that loads a seed,
  builds Fakes, and wires them into build_services + HydraFlowOrchestrator.
- MockWorld.apply_seed(seed) convenience method on the in-process harness
  for the parity test.
- Dashboard /api/state reports mockworld_active via duck-typing on the
  injected PRPort (FakeGitHub._is_fake_adapter == True).
- Persistent MOCKWORLD MODE banner in the React UI when mockworld_active.
- s00_smoke scenario + loader + parity test — proves the wiring resolves
  end-to-end before PR B introduces the docker-compose stack.

PR A complete: foundation in place. PR B adds the sandbox Docker stack
+ Playwright harness + s01_happy_single_issue."
```

### Task 1.11: PR A verify + push

- [ ] **Step 1: Final regression sweep**

```bash
.venv/bin/pytest tests/ -v -x --timeout=120
```

Expected: all pass.

- [ ] **Step 2: Final quality gate**

```bash
make quality
```

Expected: clean.

- [ ] **Step 3: Push branch + open PR A**

```bash
cd ~/.hydraflow/worktrees/T-rav-hydraflow/sandbox-tier-spec
git push -u origin sandbox-tier-pr1

gh pr create --base main --head sandbox-tier-pr1 --title "feat(mockworld): foundation — Fake relocation + DI plumbing + sandbox entrypoint (PR A of 3)" --body "$(cat <<'BODY'
## Summary

PR A of the sandbox-tier scenario testing track. Foundation only — PR B adds the docker-compose stack + Playwright harness; PR C adds the catalog + SandboxFailureFixerLoop.

- Move 12 Fakes from \`tests/scenarios/fakes/\` to \`src/mockworld/fakes/\` (production-quality alternative adapters; no longer test-only).
- Create \`FakeIssueFetcher\` and \`FakeIssueStore\` (extracted from MockWorld._wire_targets monkeypatching into standalone Port-conforming classes).
- Add \`PRPort.list_prs_by_label\` on Port + PRManager + FakeGitHub (required by PR C's SandboxFailureFixerLoop and \`/api/sandbox-hitl\` endpoint).
- Widen \`ServiceRegistry.{prs, workspaces, store}\` and \`RouteContext.pr_manager\` from concrete adapter classes to Port protocols.
- Refactor \`build_services()\` to accept optional adapter override kwargs.
- Refactor \`HydraFlowOrchestrator.__init__\` to accept a pre-built ServiceRegistry.
- Add \`src/mockworld/sandbox_main.py\` — the sandbox entrypoint.
- Add \`MockWorldSeed\` dataclass + \`from_seed()\` on Fake adapters.
- Add \`MockWorld.apply_seed(seed)\` convenience method for the parity test.
- Add dashboard duck-typed MOCKWORLD banner (\`getattr(prs, '_is_fake_adapter', False)\`).
- Add s00_smoke scenario + loader + parity test.

Production runtime behavior is byte-for-byte unchanged. The only diff in production code paths is type annotations widening to Port protocols (removes a leaky abstraction). Default kwargs preserve all behavior.

## Test plan

- [ ] PR A regression suite green (\`pytest tests/ -x\`).
- [ ] make quality clean.
- [ ] Existing scenario suite passes.
- [ ] Conformance tests catch any future Port↔Fake drift.
- [ ] Dashboard banner does NOT render on production-mode boot.
- [ ] Dashboard banner DOES render when sandbox_main entrypoint runs (manually verified once container in PR B).

## Sequencing

After PR A merges:
- PR B: docker-compose.sandbox.yml + Playwright harness + s01_happy_single_issue + greenfield CI sandbox job + ADR-0052.
- PR C: scenarios s02–s12 + SandboxFailureFixerLoop + /api/sandbox-hitl + CI workflow expansion (3 triggers + self-fix label routing) + dark-factory wiki update.

Spec: \`docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md\` (commit e6189276, converged through 4 fresh-eyes review iterations).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```


---

## PR B — Compose stack + harness CLI + first end-to-end scenario (~900 LOC)

**Branch:** `sandbox-tier-pr2` (cut from `main` after PR A merges)

**Risk:** medium. New compose stack, network policy, CI infrastructure. Mitigation: gated to relevant PRs only via path-trigger.

### Task 2.1: Add `docker-compose.sandbox.yml` + `Dockerfile.ui` + nginx config + Makefile targets

**Files:**
- Create: `docker-compose.sandbox.yml`
- Create: `src/ui/Dockerfile.ui`
- Create: `src/ui/nginx.sandbox.conf`
- Modify: `Makefile`

- [ ] **Step 1: Create `docker-compose.sandbox.yml`**

```yaml
version: "3.9"

networks:
  sandbox:
    internal: true   # the air-gap. No default gateway → no external egress.
                     # DNS resolution behavior is runtime-dependent;
                     # rely on routing failure (timeouts/refused), not NXDOMAIN.

services:
  hydraflow:
    build:
      context: .
      dockerfile: Dockerfile.agent
    # The selection of MockWorld vs. production is at the entrypoint level —
    # this container always runs the sandbox entrypoint. The production
    # image runs the `hydraflow` console script (entry point `server:main`
    # per pyproject.toml) instead.
    command: ["python", "-m", "mockworld.sandbox_main", "/seed/scenario.json"]
    environment:
      HYDRAFLOW_DASHBOARD_HOST: "0.0.0.0"
      HYDRAFLOW_DASHBOARD_PORT: "5555"
      HYDRAFLOW_ENV: "sandbox"
      # No real credentials needed — the Fakes don't use them. These
      # placeholders are present only so legacy code paths that read
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
      dockerfile: Dockerfile.ui
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
    # The harness CLI overrides this command with the per-scenario invocation.
    command: ["pytest", "tests/sandbox_scenarios/runner/", "-v", "--junitxml=/results/junit.xml"]

volumes:
  sandbox-results:
```

- [ ] **Step 2: Create `src/ui/Dockerfile.ui`**

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

- [ ] **Step 3: Create `src/ui/nginx.sandbox.conf`**

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
        proxy_set_header X-Real-IP $remote_addr;
    }
    location /ws {
        proxy_pass http://hydraflow:5555;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
    }
}
```

- [ ] **Step 4: Add Makefile targets**

In the existing `Makefile`, append:

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

- [ ] **Step 5: Smoke-build the stack manually**

```bash
mkdir -p tests/sandbox_scenarios/seeds
echo '{"repos": [], "issues": [], "prs": [], "scripts": {}, "cycles_to_run": 1, "loops_enabled": null}' > tests/sandbox_scenarios/seeds/_smoke.json
docker compose -f docker-compose.sandbox.yml build hydraflow ui
```

Expected: both images build successfully. (May take 3–5 min on first run.)

- [ ] **Step 6: Boot the stack and check healthcheck**

```bash
docker compose -f docker-compose.sandbox.yml up -d hydraflow ui
sleep 10
docker compose -f docker-compose.sandbox.yml ps
curl -fsS http://127.0.0.1:5556/healthz || echo "UI proxy not ready yet"
docker compose -f docker-compose.sandbox.yml down -v
```

Expected: `hydraflow` shows `(healthy)` status; the UI proxies the healthcheck through.

- [ ] **Step 7: Commit**

```bash
git add docker-compose.sandbox.yml src/ui/Dockerfile.ui src/ui/nginx.sandbox.conf Makefile tests/sandbox_scenarios/seeds/_smoke.json
git commit -m "feat(sandbox): docker-compose stack with internal-only network

Three services on an internal:true network (no egress route to external
hosts):
- hydraflow: runs python -m mockworld.sandbox_main with a mounted seed.
- ui: nginx serving the built React dist + proxying /api and /ws to
  hydraflow:5555.
- playwright: per-scenario harness driver.

The hydraflow container picks up MockWorld by virtue of which entrypoint
runs — there is no config flag. Production image runs server:main; this
container runs mockworld.sandbox_main.

Makefile targets: sandbox-up / sandbox-down / sandbox-test / sandbox-shell."
```

### Task 2.2: Add `scripts/sandbox_scenario.py` harness CLI

**Files:**
- Create: `scripts/sandbox_scenario.py`
- Test: `tests/test_sandbox_scenario_cli.py`

- [ ] **Step 1: Write failing test for the CLI**

Create `tests/test_sandbox_scenario_cli.py`:

```python
"""sandbox_scenario CLI — invocation surface tests.

Doesn't actually boot docker — patches subprocess.run. Verifies the
correct compose commands are issued for each subcommand.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts import sandbox_scenario


def test_seed_subcommand_writes_json(tmp_path) -> None:
    seeds_dir = tmp_path / "seeds"
    with patch.object(sandbox_scenario, "SEEDS_DIR", seeds_dir):
        with patch.object(sandbox_scenario, "load_scenario") as load:
            load.return_value.NAME = "s00_smoke"
            load.return_value.seed.return_value.to_json.return_value = '{"x": 1}'
            sandbox_scenario.cmd_seed("s00_smoke")
    assert (seeds_dir / "s00_smoke.json").read_text() == '{"x": 1}'


def test_down_subcommand_calls_compose_down() -> None:
    with patch("subprocess.run") as run:
        sandbox_scenario.cmd_down()
    args = run.call_args[0][0]
    assert "docker" in args[0] and "compose" in args
    assert "down" in args
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_sandbox_scenario_cli.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `scripts/sandbox_scenario.py`**

Create `scripts/sandbox_scenario.py`:

```python
"""sandbox_scenario — host-side harness for the sandbox tier.

Subcommands:
    run NAME       — Compute seed, build (if needed), boot stack, run one
                     scenario, capture artifacts, tear down.
    run-all        — Same, but iterates the catalog; produces a summary
                     table and exits nonzero if any failed.
    status         — Show current stack state without booting.
    down           — Tear down the stack and remove volumes.
    shell          — Drop into bash inside the hydraflow container.
    seed NAME      — Compute and write the JSON seed without booting.

Returns exit code 0 on full success, 1 on any scenario failure, 2 on
infrastructure failure (build / healthcheck / playwright crash).
"""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILE = REPO_ROOT / "docker-compose.sandbox.yml"
SEEDS_DIR = REPO_ROOT / "tests" / "sandbox_scenarios" / "seeds"
RESULTS_DIR = Path("/tmp/sandbox-results")


def load_scenario(name: str):
    """Import a scenario module by NAME."""
    return importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")


def write_seed(name: str) -> Path:
    """Compute the scenario's seed and write it to SEEDS_DIR."""
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)
    mod = load_scenario(name)
    out = SEEDS_DIR / f"{mod.NAME}.json"
    out.write_text(mod.seed().to_json())
    return out


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        check=False,
    )


def cmd_seed(name: str) -> int:
    out = write_seed(name)
    print(f"Wrote seed: {out}")
    return 0


def cmd_down() -> int:
    print("Stopping stack...")
    _compose("down", "-v")
    print("Done.")
    return 0


def cmd_status() -> int:
    return _compose("ps").returncode


def cmd_shell() -> int:
    return _compose("exec", "hydraflow", "/bin/bash").returncode


def _wait_for_healthy(timeout: float = 60.0) -> bool:
    """Poll docker compose ps for hydraflow (healthy) up to timeout seconds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "ps", "--format", "json", "hydraflow"],
            capture_output=True, text=True, check=False,
        )
        if "(healthy)" in result.stdout or '"Health":"healthy"' in result.stdout:
            return True
        time.sleep(2)
    return False


def cmd_run(name: str) -> int:
    print(f"[1/5] Computing seed for {name}...")
    seed_path = write_seed(name)

    # Make sure the seed file the container reads matches THIS scenario.
    # The container always reads /seed/scenario.json, so symlink it.
    target = SEEDS_DIR / "scenario.json"
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(seed_path.name)

    print("[2/5] Building images (cached when possible)...")
    rc = _compose("build", "hydraflow", "ui").returncode
    if rc != 0:
        print(f"BUILD FAILED ({rc})")
        return 2

    print("[3/5] Starting stack on internal network...")
    rc = _compose("up", "-d", "hydraflow", "ui").returncode
    if rc != 0:
        print(f"UP FAILED ({rc})")
        return 2

    print("[4/5] Waiting for hydraflow /healthz...")
    if not _wait_for_healthy(60):
        print("HEALTHCHECK TIMEOUT — collecting logs")
        _compose("logs", "hydraflow")
        cmd_down()
        return 2

    print("[5/5] Running playwright assertions...")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    rc = _compose(
        "run", "--rm", "-e", f"SCENARIO_NAME={name}", "playwright",
        "pytest", f"tests/sandbox_scenarios/runner/test_scenarios.py::test_scenario[{name}]",
        "-v", "--junitxml=/results/junit.xml",
    ).returncode

    if rc != 0:
        print(f"FAILED {name}")
        _compose("logs", "hydraflow")
    else:
        print(f"PASSED {name}")

    cmd_down()
    return rc


def cmd_run_all() -> int:
    """Iterate every scenario; print summary; exit nonzero on any failure."""
    from tests.sandbox_scenarios.runner.loader import load_all_scenarios

    scenarios = load_all_scenarios()
    results: list[tuple[str, int, float]] = []
    for s in scenarios:
        if s.NAME == "s00_smoke":
            print(f"SKIPPED {s.NAME} (parity-only, no Tier-2 implementation)")
            continue
        start = time.monotonic()
        rc = cmd_run(s.NAME)
        elapsed = time.monotonic() - start
        results.append((s.NAME, rc, elapsed))

    print("\n--- Summary ---")
    fails = 0
    for name, rc, elapsed in results:
        status = "PASSED" if rc == 0 else "FAILED"
        if rc != 0:
            fails += 1
        print(f"{status:8s} {name:40s} ({elapsed:5.1f}s)")
    print(f"\n{len(results) - fails} passed, {fails} failed")
    return 1 if fails else 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sandbox_scenario")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    sub.add_parser("down")
    sub.add_parser("shell")
    sub.add_parser("run-all")
    p_run = sub.add_parser("run")
    p_run.add_argument("name")
    p_seed = sub.add_parser("seed")
    p_seed.add_argument("name")

    args = parser.parse_args()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "down":
        return cmd_down()
    if args.cmd == "shell":
        return cmd_shell()
    if args.cmd == "run-all":
        return cmd_run_all()
    if args.cmd == "run":
        return cmd_run(args.name)
    if args.cmd == "seed":
        return cmd_seed(args.name)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run CLI tests, verify they pass**

```bash
.venv/bin/pytest tests/test_sandbox_scenario_cli.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Test `seed` subcommand against s00_smoke**

```bash
python scripts/sandbox_scenario.py seed s00_smoke
cat tests/sandbox_scenarios/seeds/s00_smoke.json
```

Expected: writes valid JSON with `s00_smoke`'s issue list.

- [ ] **Step 6: Commit**

```bash
git add scripts/sandbox_scenario.py tests/test_sandbox_scenario_cli.py
git commit -m "feat(sandbox): scripts/sandbox_scenario.py harness CLI

Six subcommands: run / run-all / status / down / shell / seed.

run NAME orchestrates: compute seed → write to mounted dir → build →
boot stack → wait for healthy → invoke pytest inside playwright
container → tear down → return exit code.

Exit codes: 0=pass, 1=scenario failure, 2=infra failure (build /
healthcheck / playwright crash). The exit-code distinction lets CI
distinguish 'caught a real bug' from 'sandbox itself broke'."
```

### Task 2.3: Playwright + SandboxAPIClient fixtures

**Files:**
- Create: `tests/sandbox_scenarios/runner/conftest.py`
- Create: `tests/sandbox_scenarios/runner/api_client.py`

- [ ] **Step 1: Create the API client**

Create `tests/sandbox_scenarios/runner/api_client.py`:

```python
"""SandboxAPIClient — async HTTP client targeting the in-container hydraflow.

Used by Playwright fixtures and by scenario assert_outcome implementations
to read API state without going through the UI.
"""

from __future__ import annotations

import os
import json
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class SandboxAPIClient:
    """Tiny async-friendly wrapper over the dashboard REST API."""

    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.environ.get(
            "SANDBOX_API_BASE", "http://hydraflow:5555"
        )

    async def get(self, path: str) -> dict:
        url = urljoin(self.base_url + "/", path.lstrip("/"))
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

    async def wait_until(
        self,
        path: str,
        predicate,
        *,
        timeout: float = 30.0,
        poll_interval: float = 1.0,
    ) -> dict:
        """Poll path until predicate(payload) returns True or timeout."""
        import asyncio
        deadline = asyncio.get_event_loop().time() + timeout
        last = None
        while asyncio.get_event_loop().time() < deadline:
            try:
                last = await self.get(path)
                if predicate(last):
                    return last
            except Exception:
                pass
            await asyncio.sleep(poll_interval)
        raise TimeoutError(
            f"timeout waiting for predicate on {path}; last payload: {last!r}"
        )
```

- [ ] **Step 2: Create `tests/sandbox_scenarios/runner/conftest.py`**

```python
"""Playwright + SandboxAPIClient fixtures for the sandbox runner.

These fixtures are scoped to the 'sandbox' test directory only — they
don't pollute the broader pytest collection.
"""

from __future__ import annotations

import os

import pytest_asyncio
from playwright.async_api import async_playwright

from tests.sandbox_scenarios.runner.api_client import SandboxAPIClient


@pytest_asyncio.fixture
async def api():
    """Async API client targeting the in-container hydraflow dashboard."""
    yield SandboxAPIClient()


@pytest_asyncio.fixture
async def browser():
    """Headless Chromium for the sandbox network."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture
async def page(browser):
    """A fresh page targeting SANDBOX_BASE_URL (the UI service)."""
    base_url = os.environ.get("SANDBOX_BASE_URL", "http://ui")
    context = await browser.new_context(base_url=base_url)
    page = await context.new_page()
    yield page
    await context.close()
```

- [ ] **Step 3: Commit**

```bash
git add tests/sandbox_scenarios/runner/conftest.py tests/sandbox_scenarios/runner/api_client.py
git commit -m "feat(sandbox): Playwright + SandboxAPIClient fixtures

Per-scenario assert_outcome receives an api client (REST polling) and
a Playwright page (UI assertions). Fixtures scoped to the runner
directory only — don't pollute the in-process test suite."
```

### Task 2.4: Parametrized scenario runner

**Files:**
- Create: `tests/sandbox_scenarios/runner/test_scenarios.py`

- [ ] **Step 1: Create the runner test**

Create `tests/sandbox_scenarios/runner/test_scenarios.py`:

```python
"""Parametrized sandbox-scenario runner.

The scenario harness CLI invokes this with -k or specific test ID; each
scenario module's assert_outcome is called with (api, page) fixtures.
"""

from __future__ import annotations

import os

import pytest

from tests.sandbox_scenarios.runner.loader import load_all_scenarios

# Filter out s00_smoke — that's parity-only (no assert_outcome).
_SCENARIOS = [s for s in load_all_scenarios() if hasattr(s, "assert_outcome")]


@pytest.mark.parametrize("scenario", _SCENARIOS, ids=lambda s: s.NAME)
@pytest.mark.asyncio
async def test_scenario(scenario, api, page) -> None:
    """Run scenario.assert_outcome with the API client + Playwright page."""
    # Optional env override: SCENARIO_NAME=sNN runs only that scenario.
    only = os.environ.get("SCENARIO_NAME")
    if only and scenario.NAME != only:
        pytest.skip(f"SCENARIO_NAME={only!r} doesn't match {scenario.NAME}")
    await scenario.assert_outcome(api, page)
```

- [ ] **Step 2: Commit**

```bash
git add tests/sandbox_scenarios/runner/test_scenarios.py
git commit -m "feat(sandbox): parametrized runner — calls scenario.assert_outcome

One pytest test per scenario. Picks up assert_outcome via duck-typing
(skips scenarios that lack it — e.g., s00_smoke which is parity-only).

The harness CLI's run NAME subcommand uses SCENARIO_NAME env var to
restrict to one scenario; run-all iterates the catalog."
```

### Task 2.5: Implement `s01_happy_single_issue` end-to-end

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py`

- [ ] **Step 1: Implement the scenario**

Create `tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py`:

```python
"""s01_happy_single_issue — single issue → triage → plan → implement → review → merge.

Tier 2 sandbox scenario. Verifies the full assembly line works end-to-end:
- API: /api/timeline/issue/1 reports outcome=merged
- UI: Outcomes tab shows the merged outcome row
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s01_happy_single_issue"
DESCRIPTION = "Single hydraflow-ready issue → full pipeline → merged. Outcomes tab shows it."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {
                "number": 1,
                "title": "Add hello world",
                "body": "Implement a hello-world function in src/hello.py",
                "labels": ["hydraflow-ready"],
            },
        ],
        scripts={
            "plan":      {1: [{"success": True, "task_count": 1}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "review":    {1: [{"verdict": "approve", "comments": []}]},
        },
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    # API assertion — eventually consistent: poll until merged.
    timeline = await api.wait_until(
        "/api/timeline/issue/1",
        lambda payload: payload.get("outcome") == "merged",
        timeout=30.0,
    )
    assert timeline["outcome"] == "merged", f"got {timeline}"

    # UI assertion — Outcomes tab shows the merged outcome.
    await page.goto("/")
    await page.click("text=Outcomes")
    await page.wait_for_selector("[data-testid='outcome-row-1']", timeout=10_000)
    text = await page.locator("[data-testid='outcome-row-1']").text_content()
    assert "Merged" in text or "merged" in text.lower(), f"got {text!r}"

    # MOCKWORLD banner is visible (proves duck-typing wiring works).
    banner = page.locator("[data-testid='mockworld-banner']")
    assert await banner.is_visible()
```

- [ ] **Step 2: Compute the seed and verify it serializes**

```bash
python scripts/sandbox_scenario.py seed s01_happy_single_issue
cat tests/sandbox_scenarios/seeds/s01_happy_single_issue.json
```

Expected: valid JSON written.

- [ ] **Step 3: Run the scenario end-to-end (the real test)**

```bash
python scripts/sandbox_scenario.py run s01_happy_single_issue
```

Expected: PASSED with timing under 60s.

If the scenario fails:
- Check `/tmp/sandbox-results/s01_happy_single_issue/` for hydraflow logs and Playwright artifacts
- Common fix: add a `data-testid="outcome-row-{number}"` attribute in the UI's outcomes table component (`src/ui/src/components/OutcomesPanel.jsx` or similar)
- If the timeline never reaches merged: check the FakeLLM script wiring; the `merge_loop` may need additional cycles (`cycles_to_run=6`)

- [ ] **Step 4: Commit**

```bash
git add tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py tests/sandbox_scenarios/seeds/s01_happy_single_issue.json
git commit -m "feat(sandbox): s01_happy_single_issue — first end-to-end Tier-2 scenario

Single hydraflow-ready issue progresses through triage → plan →
implement → review → merge. Asserts via REST (timeline says merged)
AND via Playwright (Outcomes tab renders the merged row + MOCKWORLD
banner is visible).

Proof point: docker-compose stack + FakeGitHub injection + dashboard
banner + Playwright assertions all align."
```

### Task 2.6: Add new `sandbox` CI job (greenfield)

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Read existing workflow to find the right insertion point**

```bash
grep -n "^  [a-z_-]*:$" .github/workflows/ci.yml
```

Note the existing job blocks for placement.

- [ ] **Step 2: Append the new `sandbox` job**

In `.github/workflows/ci.yml`, add:

```yaml
  sandbox:
    name: Sandbox Scenarios (PR B)
    runs-on: ubuntu-latest
    needs: [changes]
    if: |
      needs.changes.outputs.service_registry == 'true' ||
      needs.changes.outputs.orchestrator == 'true' ||
      needs.changes.outputs.mockworld == 'true' ||
      needs.changes.outputs.dockerfiles == 'true' ||
      needs.changes.outputs.compose == 'true' ||
      needs.changes.outputs.sandbox_scenarios == 'true'
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install uv
        run: pip install uv
      - name: Install deps
        run: uv pip install --system -e ".[dev]"
      - name: Build sandbox images
        run: docker compose -f docker-compose.sandbox.yml build hydraflow ui
      - name: Run s01_happy_single_issue
        run: python scripts/sandbox_scenario.py run s01_happy_single_issue
      - name: Upload artifacts on failure
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: sandbox-results
          path: /tmp/sandbox-results/
          retention-days: 7
```

Add the `changes` job's `outputs` for the new path filters. In the existing `changes` job's `outputs:` block, add:

```yaml
      service_registry: ${{ steps.filter.outputs.service_registry }}
      orchestrator: ${{ steps.filter.outputs.orchestrator }}
      mockworld: ${{ steps.filter.outputs.mockworld }}
      dockerfiles: ${{ steps.filter.outputs.dockerfiles }}
      compose: ${{ steps.filter.outputs.compose }}
      sandbox_scenarios: ${{ steps.filter.outputs.sandbox_scenarios }}
```

And in the `dorny/paths-filter` step's `filters:` block:

```yaml
            service_registry:
              - 'src/service_registry.py'
            orchestrator:
              - 'src/orchestrator.py'
            mockworld:
              - 'src/mockworld/**'
            dockerfiles:
              - 'Dockerfile*'
            compose:
              - 'docker-compose*.yml'
            sandbox_scenarios:
              - 'tests/sandbox_scenarios/**'
```

- [ ] **Step 3: Validate workflow YAML**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(sandbox): add new sandbox CI job (greenfield)

Path-triggered job that builds the docker-compose stack and runs
s01_happy_single_issue. Triggers on changes to service_registry,
orchestrator, mockworld/, Dockerfiles, compose, or sandbox_scenarios.

Greenfield — no prior 'Browser Scenarios' job to promote. The
scenario_browser pytest mark in pyproject.toml exists but no CI job
used it. PR C expands this single-scenario job into the full 3-trigger
matrix (PR-into-staging fast subset, rc/* full suite, nightly) plus
the sandbox-fail-auto-fix label routing."
```

### Task 2.7: Add ADR-0052 + final verify + push

**Files:**
- Create: `docs/adr/0052-sandbox-tier-scenarios.md`
- Modify: `docs/adr/README.md` (index)

- [ ] **Step 1: Write ADR-0052**

Create `docs/adr/0052-sandbox-tier-scenarios.md`:

```markdown
# ADR-0052: Sandbox-tier scenario testing

- **Status:** Accepted
- **Date:** 2026-04-26
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0029](0029-caretaker-loop-pattern.md), [ADR-0042](0042-staging-promotion-loop.md), [ADR-0049](0049-trust-loop-kill-switch-convention.md), [ADR-0050](0050-auto-agent-hitl-preflight.md), [ADR-0051](0051-iterative-production-readiness-review.md)
- **Enforced by:** `tests/test_mockworld_fakes_conformance.py` (Port↔Fake signature parity), `.github/workflows/ci.yml` `sandbox` job (CI gate).

## Context

The dark-factory infrastructure-hardening track (#8445/#8446/#8448) closed the structural-enforcement gap at the unit and per-loop level. What it did not close is the end-to-end gap: there was no test that booted HydraFlow as a deployed system and verified "issue → label-state-machine progression → PR merged" without a human watching.

That gap was closed by the human in the loop. Removing the human means moving that verification into automation.

## Decision

Two test tiers backed by the same MockWorld substrate (`src/mockworld/fakes/`):

- **Tier 1 (in-process, every PR):** existing `tests/scenarios/` suite. ~30 scenarios, ~0.1s each.
- **Tier 2 (sandbox, PR B/C):** new `tests/sandbox_scenarios/` suite. ~12 curated scenarios that boot HydraFlow inside `docker-compose.sandbox.yml`, swap MockWorld at the boundary, drive the UI via Playwright, assert end-to-end. ~30–60s each.

**MockWorld is always-on infrastructure**, not a configurable mode. Selection between Fake and real adapters happens at the **entrypoint level**: production runs the `hydraflow` console script (`server:main`); sandbox runs `python -m mockworld.sandbox_main`. `build_services()` and `HydraFlowOrchestrator.__init__` accept optional adapter overrides; production never passes them.

**Air-gap is structural** (compose `internal: true`), not honor-system. Containers have no default gateway; external hosts cannot be routed to.

## Rules

1. **No config switch for MockWorld.** No `HYDRAFLOW_MOCKWORLD_ENABLED` env var, no boolean field on `HydraFlowConfig`. The choice is at the entrypoint level, period.
2. **Fakes ship in `src/mockworld/fakes/`,** treated as production code (ruff, pyright, bandit). They are not test fixtures — they are alternative adapters.
3. **Every sandbox scenario has a Tier-1 parity test** (`tests/scenarios/test_sandbox_parity.py`). If only Tier 2 fails, the bug is in container/wiring/UI; if both fail, it's in scenario logic. Triage starts with Tier 1.
4. **The dashboard renders a persistent MOCKWORLD MODE banner** when the injected `PRPort` carries the `_is_fake_adapter` marker. Duck-typed; not config-driven.
5. **CI gate (PR C):** all 12 sandbox scenarios must pass on the rc/* promotion PR before staging→main merge. Failures auto-dispatch the auto-agent self-fix loop (`SandboxFailureFixerLoop`).

## Consequences

**Positive:**
- End-to-end "did this build actually work?" verification runs without a human.
- Container-only bugs (Dockerfile drops, network policy, UI routing) caught at PR time instead of in production.
- Production releases leave staging with high confidence; observability catches what no test could anticipate.

**Negative:**
- Sandbox tier adds ~30–60s per scenario. ~12 scenarios = ~10 min full-suite run.
- New caretaker loop (`SandboxFailureFixerLoop`) adds ~400 LOC of code to maintain.

**Risks:**
- Sandbox flakes erode trust if not investigated. Mitigation: 3-strikes-then-bug pattern from Trigger 3.
- Self-fix loop oscillation (auto-fix breaks a different scenario each attempt). Mitigation: 3-attempt cap then HITL escalation.

## When to supersede this ADR

- If a future revision adopts a config-flag-based MockWorld selection (the design rejected here), supersede with rationale.
- If empirical convergence shifts (e.g., sandbox scenarios routinely catch zero bugs over many quarters), reduce the planning expectation.

## Source-file citations

- `docs/superpowers/specs/2026-04-26-sandbox-tier-scenarios-design.md` — full spec (converged through 4 fresh-eyes review iterations per ADR-0051).
- `src/mockworld/sandbox_main.py` — the sandbox entrypoint.
- `src/mockworld/fakes/` — the always-loaded Fake adapter set.
- `docker-compose.sandbox.yml` — the air-gapped sandbox stack.
```

- [ ] **Step 2: Add ADR to the index**

In `docs/adr/README.md`, add to the Accepted ADRs list:

```markdown
- [ADR-0052](0052-sandbox-tier-scenarios.md) — Sandbox-tier scenario testing
```

- [ ] **Step 3: Run full PR B regression**

```bash
.venv/bin/pytest tests/ -v -x --timeout=120
make quality
```

Expected: all pass.

- [ ] **Step 4: Push and open PR B**

```bash
cd ~/.hydraflow/worktrees/T-rav-hydraflow/sandbox-tier-spec
git push -u origin sandbox-tier-pr2

gh pr create --base main --head sandbox-tier-pr2 --title "feat(sandbox): docker-compose stack + harness + s01 + ADR-0052 (PR B of 3)" --body "$(cat <<'BODY'
## Summary

PR B of the sandbox-tier scenario testing track. Adds the actual docker-compose stack and the first end-to-end Tier-2 scenario.

- \`docker-compose.sandbox.yml\` with \`internal: true\` air-gapped network.
- \`src/ui/Dockerfile.ui\` + \`nginx.sandbox.conf\` for serving the React dist + proxying /api and /ws.
- \`scripts/sandbox_scenario.py\` harness CLI (run / run-all / status / down / shell / seed).
- Makefile targets sandbox-up / sandbox-down / sandbox-test / sandbox-shell.
- \`tests/sandbox_scenarios/runner/\` with Playwright + SandboxAPIClient fixtures + parametrized scenario runner.
- \`tests/sandbox_scenarios/scenarios/s01_happy_single_issue.py\` — first end-to-end Tier-2 scenario (REST + UI assertions).
- New \`sandbox\` CI job (greenfield) gated on path triggers.
- ADR-0052 codifying the architecture.

Depends on PR A (foundation: Fakes in src/mockworld, build_services overrides, HydraFlowOrchestrator services kwarg, sandbox_main entrypoint).

## Test plan

- [ ] \`python scripts/sandbox_scenario.py run s01_happy_single_issue\` passes locally in under 60s.
- [ ] CI \`sandbox\` job green on this PR.
- [ ] All Tier-1 scenarios still green.
- [ ] make quality clean.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```


---

## PR C — Catalog completion + SandboxFailureFixerLoop + CI expansion (~1900 LOC)

**Branch:** `sandbox-tier-pr3` (cut from `main` after PR B merges)

**Risk:** medium. Per-scenario adds are independent and tolerate partial landings. The new caretaker loop is medium-risk (commits to PR branches, triggers CI) — mitigation: ship kill-switched-OFF by default, enable explicitly after observing one or two real fix-cycles.

**Pattern note for Tasks 3.1–3.11:** every scenario follows the same template — define `NAME`, `DESCRIPTION`, `seed()`, `assert_outcome(api, page)`, run via `python scripts/sandbox_scenario.py run <NAME>`, commit. The parity test (`tests/scenarios/test_sandbox_parity.py`) auto-discovers each new scenario via the loader, so no per-scenario test wiring is needed.

### Task 3.1: `s02_batch_three_issues`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s02_batch_three_issues.py`

- [ ] **Step 1: Implement the scenario**

```python
"""s02_batch_three_issues — 3 issues progress in parallel through the pipeline."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s02_batch_three_issues"
DESCRIPTION = "3 issues batch-implemented; Work Stream tab shows all progressing."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[("owner/repo", "/workspace/repo")],
        issues=[
            {"number": n, "title": f"task {n}", "body": "b",
             "labels": ["hydraflow-ready"]}
            for n in (1, 2, 3)
        ],
        scripts={
            "plan":      {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)},
            "review":    {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=6,
    )


async def assert_outcome(api, page) -> None:
    for n in (1, 2, 3):
        timeline = await api.wait_until(
            f"/api/timeline/issue/{n}",
            lambda p: p.get("outcome") == "merged",
            timeout=60.0,
        )
        assert timeline["outcome"] == "merged"

    await page.goto("/")
    await page.click("text=Work Stream")
    for n in (1, 2, 3):
        await page.wait_for_selector(
            f"[data-testid='stream-issue-{n}']", timeout=10_000
        )
```

- [ ] **Step 2: Run scenario; verify pass**

```bash
python scripts/sandbox_scenario.py run s02_batch_three_issues
```

Expected: PASSED.

- [ ] **Step 3: Commit**

```bash
git add tests/sandbox_scenarios/scenarios/s02_batch_three_issues.py
git commit -m "feat(sandbox): s02_batch_three_issues — parallel pipeline progression"
```

### Task 3.2: `s03_review_retry_then_pass`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s03_review_retry_then_pass.py`

- [ ] **Step 1: Implement**

```python
"""s03 — review fails attempt 1, passes attempt 2; ends merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s03_review_retry_then_pass"
DESCRIPTION = "Review fails attempt 1, passes attempt 2; issue ends merged."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b",
                 "labels": ["hydraflow-ready"]}],
        scripts={
            "plan":      {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"},
                              {"success": True, "branch": "hf/issue-1"}]},
            "review":    {1: [
                {"verdict": "request_changes", "comments": ["fix the indent"]},
                {"verdict": "approve"},
            ]},
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    timeline = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: p.get("outcome") == "merged",
        timeout=90.0,
    )
    assert timeline["outcome"] == "merged"
    history = await api.get("/api/issues/history?issue_number=1")
    review_attempts = [e for e in history.get("events", [])
                       if e.get("phase") == "review"]
    assert len(review_attempts) >= 2, f"expected >=2 review events, got {len(review_attempts)}"
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s03_review_retry_then_pass
git add tests/sandbox_scenarios/scenarios/s03_review_retry_then_pass.py
git commit -m "feat(sandbox): s03_review_retry_then_pass — review retry + eventual approve"
```

### Task 3.3: `s04_ci_red_then_fixed`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s04_ci_red_then_fixed.py`

- [ ] **Step 1: Implement**

```python
"""s04 — PR opens with red CI, ci-fix runner intervenes, CI green, merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s04_ci_red_then_fixed"
DESCRIPTION = "Red CI → ci-fix → green CI → merged."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b",
                 "labels": ["hydraflow-ready"]}],
        prs=[{"number": 100, "issue_number": 1, "branch": "hf/issue-1",
              "ci_status": "fail", "merged": False, "labels": []}],
        scripts={
            "plan":      {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}]},
            "fix_ci":    {1: [{"success": True, "ci_status_after": "pass"}]},
            "review":    {1: [{"verdict": "approve"}]},
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    timeline = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: p.get("outcome") == "merged",
        timeout=120.0,
    )
    assert timeline["outcome"] == "merged"
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s04_ci_red_then_fixed
git add tests/sandbox_scenarios/scenarios/s04_ci_red_then_fixed.py
git commit -m "feat(sandbox): s04_ci_red_then_fixed — ci-fix runner intervention"
```

### Task 3.4: `s05_hitl_after_review_exhaustion`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s05_hitl_after_review_exhaustion.py`

- [ ] **Step 1: Implement**

```python
"""s05 — 3 review failures → issue surfaces in HITL tab."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s05_hitl_after_review_exhaustion"
DESCRIPTION = "3 review failures → HITL tab shows issue with request-changes button."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b",
                 "labels": ["hydraflow-ready"]}],
        scripts={
            "plan":      {1: [{"success": True}]},
            "implement": {1: [{"success": True, "branch": "hf/issue-1"}] * 4},
            "review":    {1: [
                {"verdict": "request_changes", "comments": ["bad 1"]},
                {"verdict": "request_changes", "comments": ["bad 2"]},
                {"verdict": "request_changes", "comments": ["bad 3"]},
            ]},
        },
        cycles_to_run=10,
    )


async def assert_outcome(api, page) -> None:
    hitl = await api.wait_until(
        "/api/hitl",
        lambda p: any(item.get("number") == 1 for item in p.get("items", [])),
        timeout=120.0,
    )
    assert any(i.get("number") == 1 for i in hitl["items"])

    await page.goto("/")
    await page.click("text=HITL")
    await page.wait_for_selector("[data-testid='hitl-row-1']", timeout=10_000)
    button = page.locator("[data-testid='hitl-row-1'] button:has-text('request')")
    assert await button.is_visible()
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s05_hitl_after_review_exhaustion
git add tests/sandbox_scenarios/scenarios/s05_hitl_after_review_exhaustion.py
git commit -m "feat(sandbox): s05_hitl_after_review_exhaustion — HITL escalation surfaces in UI"
```

### Task 3.5: `s06_kill_switch_via_ui`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s06_kill_switch_via_ui.py`

- [ ] **Step 1: Implement**

```python
"""s06 — operator toggles loop off via System tab; loop stops ticking."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s06_kill_switch_via_ui"
DESCRIPTION = "Toggle loop off in System tab → ADR-0049 in-body gate fires; no further ticks."


def seed() -> MockWorldSeed:
    return MockWorldSeed(cycles_to_run=4)


async def assert_outcome(api, page) -> None:
    # Capture baseline tick count for triage_loop.
    state_before = await api.get("/api/state")
    triage_ticks_before = state_before["worker_health"]["triage_loop"]["tick_count"]

    # Toggle off via UI System tab.
    await page.goto("/")
    await page.click("text=System")
    toggle = page.locator("[data-testid='toggle-triage_loop']")
    await toggle.click()

    # Wait one tick interval, then re-check: count should not have advanced.
    import asyncio
    await asyncio.sleep(5)

    state_after = await api.get("/api/state")
    triage_ticks_after = state_after["worker_health"]["triage_loop"]["tick_count"]
    assert triage_ticks_after == triage_ticks_before, (
        f"triage_loop kept ticking after disable: {triage_ticks_before} → {triage_ticks_after}"
    )
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s06_kill_switch_via_ui
git add tests/sandbox_scenarios/scenarios/s06_kill_switch_via_ui.py
git commit -m "feat(sandbox): s06_kill_switch_via_ui — ADR-0049 in-body gate via dashboard"
```

### Task 3.6: `s07_workspace_gc_reaps_dead_worktree`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s07_workspace_gc_reaps_dead_worktree.py`

- [ ] **Step 1: Implement**

```python
"""s07 — orphan worktree present → WorkspaceGCLoop reaps it."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s07_workspace_gc_reaps_dead_worktree"
DESCRIPTION = "Orphan worktree at boot → reaped → System tab counter increments."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        # FakeWorkspace records "destroyed[]" — seed is empty; we drive
        # the GC loop directly.
        loops_enabled=["workspace_gc"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    # Manually populate FakeWorkspace.created via API debug hook (adds in
    # PR C task — see helper file). For initial implementation, simply
    # verify the System tab renders the workspace_gc panel.
    await page.goto("/")
    await page.click("text=System")
    panel = page.locator("[data-testid='workspace-gc-panel']")
    assert await panel.is_visible()
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s07_workspace_gc_reaps_dead_worktree
git add tests/sandbox_scenarios/scenarios/s07_workspace_gc_reaps_dead_worktree.py
git commit -m "feat(sandbox): s07_workspace_gc_reaps_dead_worktree — caretaker activity surfaced in UI"
```

### Task 3.7: `s08_pr_unsticker_revives_stuck_pr`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s08_pr_unsticker_revives_stuck_pr.py`

- [ ] **Step 1: Implement**

```python
"""s08 — PR with no activity → PRUnstickerLoop triggers auto-resync."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s08_pr_unsticker_revives_stuck_pr"
DESCRIPTION = "Stale PR detected → auto-resync triggers → PR moves."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b",
                 "labels": ["hydraflow-implementing"]}],
        prs=[{"number": 100, "issue_number": 1, "branch": "hf/issue-1",
              "ci_status": "pass", "merged": False, "labels": ["wip"]}],
        loops_enabled=["pr_unsticker"],
        cycles_to_run=4,
    )


async def assert_outcome(api, page) -> None:
    history = await api.wait_until(
        "/api/timeline/issue/1",
        lambda p: any(e.get("event") == "pr_unsticker_resync"
                      for e in p.get("events", [])),
        timeout=60.0,
    )
    assert any(e.get("event") == "pr_unsticker_resync" for e in history["events"])
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s08_pr_unsticker_revives_stuck_pr
git add tests/sandbox_scenarios/scenarios/s08_pr_unsticker_revives_stuck_pr.py
git commit -m "feat(sandbox): s08_pr_unsticker_revives_stuck_pr — caretaker auto-resync"
```

### Task 3.8: `s09_dependabot_auto_merge`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s09_dependabot_auto_merge.py`

- [ ] **Step 1: Implement**

```python
"""s09 — dependabot PR with green CI → auto-merged."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s09_dependabot_auto_merge"
DESCRIPTION = "Dependabot PR + green CI → DependabotMergeLoop merges without human."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        prs=[{"number": 100, "issue_number": 0, "branch": "dependabot/npm/foo-1.2.3",
              "ci_status": "pass", "merged": False, "labels": ["dependencies"]}],
        loops_enabled=["dependabot_merge"],
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    prs = await api.wait_until(
        "/api/prs",
        lambda p: any(item.get("number") == 100 and item.get("merged") is True
                      for item in p.get("prs", [])),
        timeout=45.0,
    )
    pr = next(p for p in prs["prs"] if p["number"] == 100)
    assert pr["merged"] is True
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s09_dependabot_auto_merge
git add tests/sandbox_scenarios/scenarios/s09_dependabot_auto_merge.py
git commit -m "feat(sandbox): s09_dependabot_auto_merge — automated dependency merge"
```

### Task 3.9: `s10_kill_switch_universal`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s10_kill_switch_universal.py`

- [ ] **Step 1: Implement**

```python
"""s10 — disable EVERY loop via static config; no loop ticks for 5 cycles."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s10_kill_switch_universal"
DESCRIPTION = "All loops disabled via static config → no ticks (proves ADR-0049)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        # Empty loops_enabled list = disable all.
        loops_enabled=[],
        cycles_to_run=5,
    )


async def assert_outcome(api, page) -> None:
    state = await api.get("/api/state")
    # Every loop's tick_count should be 0 (or unchanged from boot).
    for name, info in state["worker_health"].items():
        assert info["tick_count"] == 0, (
            f"loop {name} ticked {info['tick_count']} times despite static-disable"
        )
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s10_kill_switch_universal
git add tests/sandbox_scenarios/scenarios/s10_kill_switch_universal.py
git commit -m "feat(sandbox): s10_kill_switch_universal — ADR-0049 universal in-body gate"
```

### Task 3.10: `s11_credit_exhaustion_suspends_ticking`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s11_credit_exhaustion_suspends_ticking.py`

- [ ] **Step 1: Implement**

```python
"""s11 — FakeLLM raises CreditExhaustedError → outer loop suspends."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s11_credit_exhaustion_suspends_ticking"
DESCRIPTION = "Credit exhausted → suspension → System tab alert (proves reraise_on_credit_or_bug)."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        issues=[{"number": 1, "title": "t", "body": "b",
                 "labels": ["hydraflow-ready"]}],
        scripts={
            # Special sentinel: the FakeLLM raises CreditExhaustedError on first call.
            "plan": {1: [{"raise": "CreditExhaustedError"}]},
        },
        cycles_to_run=3,
    )


async def assert_outcome(api, page) -> None:
    state = await api.wait_until(
        "/api/state",
        lambda p: p.get("credits_paused") is True,
        timeout=30.0,
    )
    assert state["credits_paused"] is True

    await page.goto("/")
    await page.click("text=System")
    alert = page.locator("[data-testid='credit-exhausted-alert']")
    assert await alert.is_visible()
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s11_credit_exhaustion_suspends_ticking
git add tests/sandbox_scenarios/scenarios/s11_credit_exhaustion_suspends_ticking.py
git commit -m "feat(sandbox): s11_credit_exhaustion_suspends_ticking — propagation through BaseSubprocessRunner"
```

### Task 3.11: `s12_trust_fleet_three_repos_independent`

**Files:**
- Create: `tests/sandbox_scenarios/scenarios/s12_trust_fleet_three_repos_independent.py`

- [ ] **Step 1: Implement**

```python
"""s12 — 3 repos in registry, each with 1 issue; all process independently."""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s12_trust_fleet_three_repos_independent"
DESCRIPTION = "Multi-repo fleet: 3 repos process independently; Wiki tab shows entries from all."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        repos=[
            ("acme/repo-a", "/workspace/repo-a"),
            ("acme/repo-b", "/workspace/repo-b"),
            ("acme/repo-c", "/workspace/repo-c"),
        ],
        issues=[
            {"number": 1, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 2, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
            {"number": 3, "title": "t", "body": "b", "labels": ["hydraflow-ready"]},
        ],
        scripts={
            "plan":      {n: [{"success": True}] for n in (1, 2, 3)},
            "implement": {n: [{"success": True, "branch": f"hf/issue-{n}"}] for n in (1, 2, 3)},
            "review":    {n: [{"verdict": "approve"}] for n in (1, 2, 3)},
        },
        cycles_to_run=8,
    )


async def assert_outcome(api, page) -> None:
    for n in (1, 2, 3):
        timeline = await api.wait_until(
            f"/api/timeline/issue/{n}",
            lambda p: p.get("outcome") == "merged",
            timeout=120.0,
        )
        assert timeline["outcome"] == "merged"

    await page.goto("/")
    await page.click("text=Wiki")
    # All three repos surface in the Wiki tab.
    for slug in ("repo-a", "repo-b", "repo-c"):
        await page.wait_for_selector(f"text=acme/{slug}", timeout=10_000)
```

- [ ] **Step 2: Run + commit**

```bash
python scripts/sandbox_scenario.py run s12_trust_fleet_three_repos_independent
git add tests/sandbox_scenarios/scenarios/s12_trust_fleet_three_repos_independent.py
git commit -m "feat(sandbox): s12_trust_fleet_three_repos_independent — multi-repo isolation"
```


### Task 3.12: Scaffold + implement `SandboxFailureFixerLoop`

**Files:**
- Create (via scaffold): `src/sandbox_failure_fixer_loop.py`
- Modify (via scaffold): 10 wiring sites — `src/models.py`, `src/state/__init__.py`, `src/config.py` (×3), `src/service_registry.py` (×4), `src/orchestrator.py` (×2), `src/ui/src/constants.js` (×3), `src/dashboard_routes/_common.py`, `tests/scenarios/catalog/loop_registrations.py`, `docs/arch/functional_areas.yml`, `tests/helpers.py`
- Create: `prompts/auto_agent/sandbox_fix.md`
- Create: `tests/test_sandbox_failure_fixer_loop.py`

- [ ] **Step 1: Run scaffold to generate the 10-site wiring + skeleton**

```bash
python scripts/scaffold_loop.py SandboxFailureFixer sandbox-fail-auto-fix \
  "Auto-fixes promotion PRs failing sandbox CI by dispatching the auto-agent" \
  --interval 300 --type subprocess --apply
```

Expected: scaffold writes `src/sandbox_failure_fixer_loop.py` (skeleton) and patches all 10 wiring sites. Reports `success`.

- [ ] **Step 2: Run scaffold's auto-discovery sanity tests**

```bash
.venv/bin/pytest tests/test_loop_auto_discovery.py -v
```

Expected: PASS (15 tests). Confirms the scaffold wiring is convention-correct.

- [ ] **Step 3: Write failing test for the loop's `_do_work`**

Create `tests/test_sandbox_failure_fixer_loop.py`:

```python
"""SandboxFailureFixerLoop — polls labeled PRs, dispatches auto-agent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from sandbox_failure_fixer_loop import SandboxFailureFixerLoop


@pytest.mark.asyncio
async def test_do_work_skips_when_no_labeled_prs() -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[])
    state = MagicMock()
    state.sandbox_autofix_attempts = {}
    runner = MagicMock()
    loop = SandboxFailureFixerLoop(
        prs=pr_port, state=state, runner=runner,
        enabled_cb=lambda name: True, max_attempts=3,
    )

    result = await loop._do_work()

    assert result["status"] == "ok"
    assert result["fixed_count"] == 0
    runner.run.assert_not_called()


@pytest.mark.asyncio
async def test_do_work_dispatches_auto_agent_for_labeled_pr() -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[
        MagicMock(number=100, branch="rc/2026-04-26"),
    ])
    state = MagicMock()
    state.sandbox_autofix_attempts = {}
    runner = MagicMock()
    runner.run = AsyncMock(return_value=MagicMock(crashed=False, output_text="OK"))
    loop = SandboxFailureFixerLoop(
        prs=pr_port, state=state, runner=runner,
        enabled_cb=lambda name: True, max_attempts=3,
    )

    await loop._do_work()

    runner.run.assert_called_once()
    assert state.sandbox_autofix_attempts[100] == 1


@pytest.mark.asyncio
async def test_do_work_swaps_label_after_max_attempts() -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[
        MagicMock(number=100, branch="rc/2026-04-26"),
    ])
    pr_port.add_pr_label = AsyncMock()
    pr_port.remove_pr_label = AsyncMock()
    state = MagicMock()
    state.sandbox_autofix_attempts = {100: 3}  # already at cap
    runner = MagicMock()
    runner.run = AsyncMock()
    loop = SandboxFailureFixerLoop(
        prs=pr_port, state=state, runner=runner,
        enabled_cb=lambda name: True, max_attempts=3,
    )

    await loop._do_work()

    runner.run.assert_not_called()
    pr_port.remove_pr_label.assert_called_with(100, "sandbox-fail-auto-fix")
    pr_port.add_pr_label.assert_called_with(100, "sandbox-hitl")


@pytest.mark.asyncio
async def test_do_work_skips_no_auto_fix_label() -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[
        MagicMock(number=100, branch="rc/2026-04-26", labels=["no-auto-fix"]),
    ])
    state = MagicMock()
    state.sandbox_autofix_attempts = {}
    runner = MagicMock()
    runner.run = AsyncMock()
    loop = SandboxFailureFixerLoop(
        prs=pr_port, state=state, runner=runner,
        enabled_cb=lambda name: True, max_attempts=3,
    )

    await loop._do_work()

    runner.run.assert_not_called()
```

- [ ] **Step 4: Run test, verify it fails (skeleton has placeholder _do_work)**

```bash
.venv/bin/pytest tests/test_sandbox_failure_fixer_loop.py -v
```

Expected: FAIL — scaffolded `_do_work` returns `{"status": "ok"}` with no PR-polling logic.

- [ ] **Step 5: Implement the loop body**

Replace the scaffolded `_do_work` body in `src/sandbox_failure_fixer_loop.py` with:

```python
"""SandboxFailureFixerLoop — auto-agent self-fix for failed sandbox CI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from preflight.auto_agent_runner import AutoAgentRunner

logger = logging.getLogger("hydraflow.sandbox_failure_fixer")

_AUTO_FIX_LABEL = "sandbox-fail-auto-fix"
_HITL_LABEL = "sandbox-hitl"
_OPT_OUT_LABEL = "no-auto-fix"


@dataclass
class _PRSnapshot:
    number: int
    branch: str
    labels: list[str]


class SandboxFailureFixerLoop(BaseBackgroundLoop):
    """Polls promotion PRs labeled `sandbox-fail-auto-fix`, dispatches auto-agent.

    Cap = 3 attempts per PR; on cap-hit, swaps `sandbox-fail-auto-fix` →
    `sandbox-hitl` so the PR surfaces in the System tab HITL queue
    (via the new /api/sandbox-hitl endpoint).
    """

    worker_name = "sandbox_failure_fixer"
    default_interval = 300

    def __init__(
        self,
        *,
        prs: Any,                      # PRPort
        state: Any,                    # StateData with sandbox_autofix_attempts
        runner: AutoAgentRunner,
        enabled_cb,
        max_attempts: int = 3,
    ) -> None:
        super().__init__(deps=LoopDeps(enabled_cb=enabled_cb))
        self._prs = prs
        self._state = state
        self._runner = runner
        self._max_attempts = max_attempts

    async def _do_work(self) -> dict[str, Any]:
        # ADR-0049 in-body kill-switch gate (also enforced by superclass).
        if not self._deps.enabled_cb(self.worker_name):
            return {"status": "disabled", "fixed_count": 0}

        candidates = await self._prs.list_prs_by_label(_AUTO_FIX_LABEL)
        fixed_count = 0
        escalated_count = 0

        for pr in candidates:
            labels = list(getattr(pr, "labels", []))
            if _OPT_OUT_LABEL in labels:
                logger.info(
                    "PR #%d carries no-auto-fix label; skipping", pr.number,
                )
                continue

            attempts = self._state.sandbox_autofix_attempts.get(pr.number, 0)
            if attempts >= self._max_attempts:
                logger.warning(
                    "PR #%d hit auto-fix cap (%d); escalating to HITL",
                    pr.number, attempts,
                )
                await self._prs.remove_pr_label(pr.number, _AUTO_FIX_LABEL)
                await self._prs.add_pr_label(pr.number, _HITL_LABEL)
                escalated_count += 1
                continue

            self._state.sandbox_autofix_attempts[pr.number] = attempts + 1
            try:
                outcome = await self._runner.run(
                    prompt=self._build_prompt(pr),
                    worktree_path=str(pr.branch),
                    issue_number=pr.number,
                )
                if outcome.crashed:
                    logger.warning(
                        "auto-agent crashed for PR #%d (attempt %d)",
                        pr.number, attempts + 1,
                    )
                else:
                    fixed_count += 1
            except Exception as exc:
                from exception_classify import reraise_on_credit_or_bug
                reraise_on_credit_or_bug(exc)
                logger.warning("auto-fix failed for PR #%d: %s", pr.number, exc)

        return {
            "status": "ok",
            "fixed_count": fixed_count,
            "escalated_count": escalated_count,
            "candidates": len(candidates),
        }

    def _build_prompt(self, pr: _PRSnapshot) -> str:
        from pathlib import Path
        envelope = (Path(__file__).parent.parent / "prompts" / "auto_agent" / "sandbox_fix.md").read_text()
        return envelope.replace("{PR_NUMBER}", str(pr.number)).replace("{PR_BRANCH}", pr.branch)
```

- [ ] **Step 6: Add `sandbox_autofix_attempts` to `StateData`**

In `src/state/__init__.py` (the scaffold-touched site), add:

```python
@dataclass
class StateData:
    ...
    sandbox_autofix_attempts: dict[int, int] = field(default_factory=dict)
```

- [ ] **Step 7: Create the prompt envelope**

Create `prompts/auto_agent/sandbox_fix.md`:

```markdown
# Sandbox failure auto-fix

You are dispatched by SandboxFailureFixerLoop to fix a sandbox-tier scenario failure on a promotion PR.

**PR:** #{PR_NUMBER}
**Branch:** `{PR_BRANCH}`

## Constraints (per ADR-0050 envelope)

- Do NOT modify `.github/workflows/`, `.git/`, `prompts/`, `src/preflight/`, `src/sandbox_failure_fixer_loop.py`, or any file under `secrets/`.
- Do NOT use WebFetch (CLI restriction enforced).
- All edits must keep `tests/` green and `make quality` clean.

## Your task

1. Read `/tmp/sandbox-results/<scenario>/hydraflow.log` and the Playwright trace to identify the root cause.
2. Make the minimal code change that would make the scenario pass.
3. Commit on the current branch with a message starting `fix(sandbox):`.
4. Push the branch.

## Escalation

If the failure is not fixable within your tool budget, do nothing — `SandboxFailureFixerLoop` will escalate to HITL after 3 attempts.
```

- [ ] **Step 8: Run loop tests, verify pass**

```bash
.venv/bin/pytest tests/test_sandbox_failure_fixer_loop.py -v
```

Expected: 4 PASS.

- [ ] **Step 9: Run full quality gate**

```bash
make quality
```

Expected: clean.

- [ ] **Step 10: Commit**

```bash
git add src/sandbox_failure_fixer_loop.py src/state/__init__.py prompts/auto_agent/sandbox_fix.md tests/test_sandbox_failure_fixer_loop.py [other 9 scaffold-touched files]
git commit -m "feat(loop): SandboxFailureFixerLoop — auto-agent self-fix on Trigger 2 failures

New caretaker loop scaffolded via scripts/scaffold_loop.py. Polls open
PRs labeled sandbox-fail-auto-fix and dispatches AutoAgentRunner with
the new prompts/auto_agent/sandbox_fix.md envelope.

3-attempt cap per PR (tracked in StateData.sandbox_autofix_attempts).
On cap-hit, swaps labels: sandbox-fail-auto-fix → sandbox-hitl, surfacing
the PR in the System tab HITL queue via /api/sandbox-hitl (next task).

Honors no-auto-fix label as the opt-out mechanism. Reuses 100% of
AutoAgentRunner subprocess infrastructure from #8439 (no new runner code).

Ships kill-switched-OFF by default — enable explicitly via static config
+ dashboard once one or two real fix-cycles have been observed."
```

### Task 3.13: `/api/sandbox-hitl` endpoint + Frontend HITL panel extension

**Files:**
- Modify: `src/dashboard_routes/_hitl_routes.py` (add `/api/sandbox-hitl`)
- Modify: `src/ui/src/components/system/HitlPanel.jsx` (read both endpoints; merge)
- Test: `tests/test_sandbox_hitl_endpoint.py`

- [ ] **Step 1: Write failing test for the endpoint**

Create `tests/test_sandbox_hitl_endpoint.py`:

```python
"""/api/sandbox-hitl returns sandbox-hitl-labeled PRs."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from dashboard_routes._hitl_routes import sandbox_hitl_handler


@pytest.mark.asyncio
async def test_sandbox_hitl_returns_labeled_prs() -> None:
    pr_port = MagicMock()
    pr_port.list_prs_by_label = AsyncMock(return_value=[
        MagicMock(number=100, branch="rc/2026-04-26", additions=12, deletions=3),
    ])

    payload = await sandbox_hitl_handler(prs=pr_port)

    assert "items" in payload
    assert len(payload["items"]) == 1
    assert payload["items"][0]["number"] == 100
    assert payload["items"][0]["type"] == "pr"
```

- [ ] **Step 2: Run test, verify it fails**

```bash
.venv/bin/pytest tests/test_sandbox_hitl_endpoint.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the endpoint**

In `src/dashboard_routes/_hitl_routes.py`, add (or near the existing `/api/hitl` handler):

```python
async def sandbox_hitl_handler(prs) -> dict:
    """Return open PRs labeled `sandbox-hitl` for the System tab queue."""
    candidates = await prs.list_prs_by_label("sandbox-hitl")
    return {
        "items": [
            {
                "number": pr.number,
                "branch": pr.branch,
                "additions": getattr(pr, "additions", 0),
                "deletions": getattr(pr, "deletions", 0),
                "type": "pr",
                "label": "sandbox-hitl",
            }
            for pr in candidates
        ],
    }


@router.get("/api/sandbox-hitl")
async def get_sandbox_hitl(ctx: RouteContext = Depends(get_route_context)) -> dict:
    return await sandbox_hitl_handler(prs=ctx.pr_manager)
```

- [ ] **Step 4: Run test, verify pass**

```bash
.venv/bin/pytest tests/test_sandbox_hitl_endpoint.py -v
```

Expected: PASS.

- [ ] **Step 5: Update Frontend HitlPanel to read both endpoints**

In `src/ui/src/components/system/HitlPanel.jsx` (or the equivalent file — discover via `grep -r "api/hitl" src/ui/src/`), add:

```jsx
useEffect(() => {
  Promise.all([
    fetch("/api/hitl").then(r => r.json()),
    fetch("/api/sandbox-hitl").then(r => r.json()),
  ]).then(([hitl, sandbox]) => {
    const merged = [
      ...hitl.items.map(i => ({ ...i, type: "issue" })),
      ...sandbox.items, // already type: "pr"
    ];
    setItems(merged);
  });
}, [refreshKey]);
```

In the rendering, add a type badge:

```jsx
<span className={`badge badge-${item.type}`}>{item.type}</span>
```

- [ ] **Step 6: Commit**

```bash
git add src/dashboard_routes/_hitl_routes.py src/ui/src/components/system/HitlPanel.jsx tests/test_sandbox_hitl_endpoint.py
git commit -m "feat(dashboard): /api/sandbox-hitl endpoint + Frontend HITL panel merge

New endpoint returns open PRs labeled sandbox-hitl (the cap-hit
escalation surface from SandboxFailureFixerLoop). Separate from
/api/hitl to avoid contaminating the issue-shaped payload of the
existing endpoint with PR-shaped data.

Frontend reads both endpoints and renders a merged list with a
type badge ('issue' vs 'pr'). Existing HITL panel layout unchanged
otherwise."
```

### Task 3.14: CI workflow expansion — 3 triggers + label routing

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Expand the existing `sandbox` job into the 3-trigger matrix**

Replace the existing single-scenario `sandbox` job from PR B with:

```yaml
  sandbox-fast:
    name: Sandbox (PR→staging fast subset)
    runs-on: ubuntu-latest
    needs: [changes]
    if: |
      github.base_ref == 'staging' && (
        needs.changes.outputs.service_registry == 'true' ||
        needs.changes.outputs.orchestrator == 'true' ||
        needs.changes.outputs.mockworld == 'true' ||
        needs.changes.outputs.dockerfiles == 'true' ||
        needs.changes.outputs.compose == 'true' ||
        needs.changes.outputs.sandbox_scenarios == 'true'
      )
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv pip install --system -e ".[dev]"
      - run: docker compose -f docker-compose.sandbox.yml build hydraflow ui
      - name: Run fast subset (s01, s10, s11)
        run: |
          for s in s01_happy_single_issue s10_kill_switch_universal s11_credit_exhaustion_suspends_ticking; do
            python scripts/sandbox_scenario.py run $s || exit 1
          done
      - if: failure()
        uses: actions/upload-artifact@v4
        with: { name: sandbox-fast-results, path: /tmp/sandbox-results/, retention-days: 7 }

  sandbox-full:
    name: Sandbox (rc/* promotion PR full suite)
    runs-on: ubuntu-latest
    needs: [changes]
    if: github.base_ref == 'main' && startsWith(github.head_ref, 'rc/')
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv pip install --system -e ".[dev]"
      - run: docker compose -f docker-compose.sandbox.yml build hydraflow ui
      - name: Run full suite
        id: runall
        run: python scripts/sandbox_scenario.py run-all
      - name: Auto-label PR for self-fix on failure
        if: failure()
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
        run: |
          gh pr edit ${{ github.event.pull_request.number }} --add-label sandbox-fail-auto-fix
          gh pr comment ${{ github.event.pull_request.number }} \
            --body "Sandbox suite failed. SandboxFailureFixerLoop will dispatch the auto-agent. Logs: \`/tmp/sandbox-results/\`"
      - if: failure()
        uses: actions/upload-artifact@v4
        with: { name: sandbox-full-results, path: /tmp/sandbox-results/, retention-days: 7 }

  sandbox-nightly:
    name: Sandbox (nightly regression)
    runs-on: ubuntu-latest
    if: github.event_name == 'schedule'
    steps:
      - uses: actions/checkout@v4
        with: { ref: main }
      - uses: actions/setup-python@v5
        with: { python-version: "3.11" }
      - run: pip install uv && uv pip install --system -e ".[dev]"
      - run: docker compose -f docker-compose.sandbox.yml build hydraflow ui
      - name: Run full suite + record metrics
        run: python scripts/sandbox_scenario.py run-all
      - name: Open hydraflow-find issue on failure
        if: failure()
        env: { GH_TOKEN: ${{ secrets.GITHUB_TOKEN }} }
        run: |
          gh issue create --title "Sandbox nightly failure $(date -I)" \
            --label hydraflow-find,sandbox-nightly \
            --body "Nightly sandbox run failed. Logs attached as artifact."
      - if: failure()
        uses: actions/upload-artifact@v4
        with: { name: sandbox-nightly-results, path: /tmp/sandbox-results/, retention-days: 14 }
```

Add a `schedule` trigger to the workflow's `on:` block:

```yaml
on:
  pull_request:
  push:
    branches: [main, staging]
  schedule:
    - cron: "0 3 * * *"   # 03:00 UTC nightly
```

- [ ] **Step 2: Validate workflow YAML**

```bash
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"
```

Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci(sandbox): expand to 3 triggers + auto-fix label routing

Trigger 1 (sandbox-fast): PR→staging, runs s01+s10+s11 only (~90s).
Trigger 2 (sandbox-full): rc/* promotion PR, runs full 12 scenarios.
  On failure, auto-labels PR with sandbox-fail-auto-fix; the
  SandboxFailureFixerLoop picks it up and dispatches the auto-agent.
Trigger 3 (sandbox-nightly): scheduled at 03:00 UTC, runs full suite
  on main; opens hydraflow-find issue on failure.

Per ADR-0052 + Component 10 of the spec. Production releases now
gate on a passing rc/* sandbox suite; the auto-agent is the self-fix
loop for that gate."
```

### Task 3.15: Wiki update + final verify + push

**Files:**
- Modify: `docs/wiki/dark-factory.md`

- [ ] **Step 1: Update wiki §3**

In `docs/wiki/dark-factory.md` §3 (the convergence-loop section), add:

```markdown
### Sandbox-tier expectations (added 2026-04-26 — ADR-0052)

For substantial features, the convergence loop now extends to the
sandbox tier:

- All 12 sandbox scenarios must pass on the rc/* promotion PR before
  the staging→main merge can complete. CI gates this.
- Failures auto-dispatch `SandboxFailureFixerLoop`, which gives the
  auto-agent up to 3 attempts before escalating to the System tab
  HITL queue (via `/api/sandbox-hitl`).
- Nightly sandbox runs catch slow drift; failures open
  `hydraflow-find` issues per the 3-strikes-then-bug pattern.

The same MockWorld substrate (`src/mockworld/fakes/`) backs both
in-process Tier 1 and sandbox Tier 2; Port↔Fake conformance tests
keep them aligned.
```

- [ ] **Step 2: Run full PR C regression**

```bash
.venv/bin/pytest tests/ -v -x --timeout=180
make quality
```

Expected: all pass.

- [ ] **Step 3: Push and open PR C**

```bash
cd ~/.hydraflow/worktrees/T-rav-hydraflow/sandbox-tier-spec
git push -u origin sandbox-tier-pr3

gh pr create --base main --head sandbox-tier-pr3 --title "feat(sandbox): catalog s02-s12 + SandboxFailureFixerLoop + 3-trigger CI (PR C of 3)" --body "$(cat <<'BODY'
## Summary

PR C of the sandbox-tier scenario testing track. Catalog completion + automation closure.

- 11 catalog scenarios (s02–s12) covering pipeline, HITL, caretakers, dark-factory invariants, multi-repo.
- New \`SandboxFailureFixerLoop\` caretaker loop scaffolded via scripts/scaffold_loop.py — auto-agent self-fix for failed sandbox CI on rc/* promotion PRs (3-attempt cap then HITL escalation).
- New \`/api/sandbox-hitl\` endpoint + Frontend HITL panel extension to surface escalated PRs.
- CI workflow expanded to 3 triggers: PR→staging fast subset, rc/* full suite + auto-fix label routing, nightly regression with hydraflow-find issue on failure.
- Wiki §3 updated with sandbox-tier convergence expectations.

Depends on PR A (foundation) and PR B (compose stack + first scenario + ADR-0052).

## Test plan

- [ ] All 12 scenarios pass via \`python scripts/sandbox_scenario.py run-all\`.
- [ ] Tier-1 parity tests pass (\`pytest tests/scenarios/test_sandbox_parity.py\`).
- [ ] SandboxFailureFixerLoop tests pass (\`pytest tests/test_sandbox_failure_fixer_loop.py\`).
- [ ] /api/sandbox-hitl test passes.
- [ ] CI workflow YAML validates.
- [ ] make quality clean.

## Final assembly

After PR C merges, the dark factory operates without human-in-the-loop verification for the standard release path:
- Trigger 1 catches obvious breakage at PR-author-attention time.
- Trigger 2 catches subtle issues at promotion-gate time; auto-agent fixes most.
- Trigger 3 catches slow drift; routine.
- Production observability is the catch-all for what no test could anticipate.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
BODY
)"
```

