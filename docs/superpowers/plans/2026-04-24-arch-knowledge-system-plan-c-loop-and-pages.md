# Architecture Knowledge System — Plan C: DiagramLoop + CI Guard + Pages

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the architecture knowledge system **autonomous and visible**. Adds the `DiagramLoop` (L24, joining the L9–L23 caretaker fleet) that ticks every 4 hours and opens regen PRs when source drifts, the `arch-regen.yml` CI guard that fails PRs with stale `docs/arch/generated/`, the MkDocs Material site config rendering the wiki + ADRs + generated artifacts as a published GitHub Pages site, and the freshness badge wiring that surfaces 🟢/🟡/🔴 status on every generated page.

**Architecture:** `DiagramLoop` subclasses `BaseBackgroundLoop`, calls `src.arch.runner.emit()`, detects diff via `git status`, opens a single combined PR (title-prefix idempotent per spec §4.4 mid-night-UTC fix). The CI guard runs the same `runner.py --check` on every PR. The Pages workflow runs MkDocs Material on push to main and deploys via the GitHub-native `actions/deploy-pages` action. Freshness badges are stamped into each generated page's footer by the runner, replacing Plan A's basic timestamp with a state-aware badge.

**Tech Stack:** Python 3.11, MkDocs Material + mkdocs-mermaid2-plugin + mkdocs-awesome-pages-plugin (new optional `[docs]` extra), GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4`), existing HydraFlow patterns: `BaseBackgroundLoop`, `LoopDeps`, `open_automated_pr_async`, `LoopCatalog` registration, MockWorld scenario harness.

**Spec:** `docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md` — §4.4 (DiagramLoop), §4.5 (CI guard), §4.6 (MkDocs config), §4.7 (Pages deploy), §6 (freshness badges, full implementation), §7 (kill-switch, MockWorld scenario, mkdocs-strict tests).

**Spec coverage map:**

| Spec requirement | Tasks |
|---|---|
| `[docs]` optional dep group with MkDocs Material + plugins | Task 1 |
| `mkdocs.yml` + theme + nav (§4.6, §9 IA) | Task 2 |
| `docs/index.md` homepage (§9) | Task 3 |
| `docs/about.md` ("how to read this site") | Task 4 |
| `make arch-serve` switches from placeholder to `mkdocs serve` | Task 5 |
| Freshness badge wiring into runner footer (§6) | Task 6 |
| `src/arch/freshness.py` extended with badge-emoji+tooltip helper | Task 7 |
| `src/diagram_loop.py:DiagramLoop` skeleton (§4.4) | Task 8 |
| `LoopCatalog` registration | Task 9 |
| Five-checkpoint loop wiring (per existing convention) | Task 10 |
| PR creation with title-prefix idempotence (§4.4) | Task 11 |
| Coverage check fires `chore(arch): unassigned functional area` issue | Task 12 |
| Kill-switch test (`HYDRAFLOW_DISABLE_DIAGRAM_LOOP`, §4.4) | Task 13 |
| MockWorld scenario for the loop (§7, ADR-0047) | Task 14 |
| `.github/workflows/arch-regen.yml` CI guard (§4.5) | Task 15 |
| `.github/workflows/pages-deploy.yml` (§4.7) | Task 16 |
| MkDocs strict-build test (§7) | Task 17 |
| End-to-end smoke (push to main → site live; loop tick → regen PR) | Task 18 |
| Update README + announce site URL | Task 19 |

**Out of scope (future spec cycles per §12):**
- Trust-fleet topology generated artifact
- Architectural fitness functions
- ADR-touchpoint enforcement extension
- Newcomer-test benchmark
- Drift / Gap / Contradiction agents
- OTel-trace-derived sequence diagrams
- PR-preview Pages deployments

**Prerequisites:** Plan A and Plan B are merged. The branch this plan executes on assumes `src/arch/` is complete, `make arch-regen` produces 9 artifacts, `docs/arch/functional_areas.yml` is curated, and `make quality` is green.

---

## Task 1: Add `[docs]` extra with MkDocs Material

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Pin the dependencies**

In `pyproject.toml` under `[project.optional-dependencies]`, add a new `docs` extra:

```toml
[project.optional-dependencies]
test = [
    "pytest>=9.0.3",
    # ... existing ...
]
dev = [
    "ruff==0.15.0",
    "pyright==1.1.408",
    "bandit[toml]==1.8.0",
]
docs = [
    "mkdocs>=1.6.0",
    "mkdocs-material>=9.5.0",
    "mkdocs-mermaid2-plugin>=1.1.1",
    "mkdocs-awesome-pages-plugin>=2.9.3",
    "mkdocs-git-revision-date-localized-plugin>=1.2.4",
]
```

- [ ] **Step 2: Verify install**

```bash
pip install -e '.[docs]'
mkdocs --version
```

Expected: prints a version ≥ 1.6.0.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build(docs): add [docs] extra with MkDocs Material + plugins"
```

---

## Task 2: `mkdocs.yml` + theme + nav

**Files:**
- Create: `mkdocs.yml`

The nav tree matches spec §9 exactly. `awesome-pages` plugin handles within-section ordering via `.pages` files where needed (added incrementally; not required at top level).

- [ ] **Step 1: Author `mkdocs.yml`**

```yaml
# mkdocs.yml
site_name: HydraFlow Architecture
site_description: Self-documenting architecture knowledge for HydraFlow
site_url: https://t-rav-hydra-ops.github.io/hydraflow/
repo_url: https://github.com/T-rav-Hydra-Ops/hydraflow
repo_name: T-rav-Hydra-Ops/hydraflow
edit_uri: edit/main/docs/

docs_dir: docs

# Strict mode: broken cross-links fail the build.
strict: true

theme:
  name: material
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.instant
    - navigation.top
    - navigation.tracking
    - search.suggest
    - search.highlight
    - content.code.copy
    - content.action.edit
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: deep purple
      accent: indigo
      toggle:
        icon: material/weather-sunny
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: deep purple
      accent: indigo
      toggle:
        icon: material/weather-night
        name: Switch to light mode

plugins:
  - search
  - mermaid2:
      version: 10.6.1
  - git-revision-date-localized:
      enable_creation_date: false
      type: iso_date

markdown_extensions:
  - admonition
  - attr_list
  - md_in_html
  - tables
  - toc:
      permalink: true
      toc_depth: 3
  - pymdownx.details
  - pymdownx.superfences:
      custom_fences:
        - name: mermaid
          class: mermaid
          format: !!python/name:mermaid2.fence_mermaid_custom
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.tasklist:
      custom_checkbox: true

nav:
  - Home: index.md
  - System Map:
    - Overview: arch/generated/functional_areas.md
  - Generated:
    - Loop Registry: arch/generated/loops.md
    - Port Map: arch/generated/ports.md
    - Label State Machine: arch/generated/labels.md
    - Module Graph: arch/generated/modules.md
    - Event Bus: arch/generated/events.md
    - ADR Cross-Reference: arch/generated/adr_xref.md
    - MockWorld Map: arch/generated/mockworld.md
  - Decisions:
    - Index: adr/README.md
  - Wiki:
    - Index: wiki/index.md
    - Architecture: wiki/architecture.md
    - Patterns: wiki/patterns.md
    - Gotchas: wiki/gotchas.md
    - Testing: wiki/testing.md
    - Dependencies: wiki/dependencies.md
  - Changelog: arch/generated/changelog.md
  - About: about.md

extra:
  social:
    - icon: fontawesome/brands/github
      link: https://github.com/T-rav-Hydra-Ops/hydraflow
```

- [ ] **Step 2: Verify it parses**

```bash
mkdocs build --strict
```

Expected: succeeds; produces `site/`. May warn about missing `docs/index.md` and `docs/about.md` (delivered by Tasks 3-4) — if it errors, those files are required.

If errors fire about ADR README or wiki index missing references that don't exist, fix the nav to point at files that actually exist or temporarily remove offending entries until Task 18 verifies the full tree.

- [ ] **Step 3: Commit**

```bash
git add mkdocs.yml
git commit -m "feat(docs): mkdocs.yml — Material theme, nav per spec IA"
```

---

## Task 3: `docs/index.md` homepage

**Files:**
- Create: `docs/index.md`

Brief landing page. The home page IS the entry point for humans; keep it short and link-rich.

- [ ] **Step 1: Write it**

```markdown
# HydraFlow Architecture

> **Intent in. Software out.** A multi-agent orchestration system that
> automates the full GitHub issue lifecycle.

## Where to start

- **[System Map](arch/generated/functional_areas.md)** — what this
  machine does, organized by functional area.
- **[Loop Registry](arch/generated/loops.md)** — every background loop,
  live truth from the AST.
- **[Decisions](adr/README.md)** — 49 ADRs covering every load-bearing
  architecture choice.
- **[Wiki](wiki/index.md)** — narrative entries on patterns, gotchas,
  testing, and dependencies.

## How this site stays honest

The pages under [Generated](arch/generated/loops.md) are **not
hand-written**. A `DiagramLoop` (L24) walks `src/`, `tests/`, and
`docs/adr/` every 4 hours, emits Markdown + Mermaid, and opens a PR
when the live truth has drifted. A CI guard (`arch-regen.yml`) re-runs
the same generation on every PR and fails the build if the working
tree's `docs/arch/generated/` is stale.

Every generated page footer shows its freshness state: 🟢 fresh,
🟡 source-moved (the loop will catch up within 4h), or 🔴 stale.

## See also

- [Changelog](arch/generated/changelog.md) — what's moved in the last
  90 days.
- [About this site](about.md) — how it's built, how to contribute.
- [Source on GitHub](https://github.com/T-rav-Hydra-Ops/hydraflow)
```

- [ ] **Step 2: Verify**

```bash
mkdocs build --strict
```

Expected: succeeds.

- [ ] **Step 3: Commit**

```bash
git add docs/index.md
git commit -m "feat(docs): site homepage"
```

---

## Task 4: `docs/about.md`

**Files:**
- Create: `docs/about.md`

Explains the freshness model, who/what writes which pages, and how to contribute.

- [ ] **Step 1: Write it**

```markdown
# About this site

This site is the human-readable face of HydraFlow's architecture. It
serves three audiences:

1. **Engineers** — looking up patterns, ADRs, or the current shape of
   the system before making a change.
2. **Operators** — checking what the autonomous loops are doing.
3. **Agents** — reading the generated artifacts as input to their work.

## Three layers

| Layer | What it is | Decay rate | Maintained by |
|---|---|---|---|
| **Generated** | Auto-extracted from source — loop registry, port map, etc. | code speed (hours) | `DiagramLoop` (L24) + CI guard |
| **Curated** | Wiki entries, the Functional Area Map | feature speed (days) | `RepoWikiLoop` + humans |
| **Narrative** | ADRs, this About page, the README | decision speed (months) | humans |

Generated pages have a footer indicating their freshness state. Curated
and narrative pages are explicit human work — the contribution flow is
"open a PR against `docs/wiki/` or `docs/adr/`."

## Freshness states

Each Generated page footer reads something like:

> *Regenerated from commit `abc1234` on 2026-04-24 14:32 UTC. Source last
> changed at `def5678`. Status: 🟢 fresh.*

| State | Meaning |
|---|---|
| 🟢 **fresh** | Regenerated within 24h **and** source unchanged since regen. |
| 🟡 **source-moved** | Source changed after last regen but within 7 days. The DiagramLoop should catch up within 4h; if you see this for >24h, the loop is paused or slow. |
| 🔴 **stale** | More than 7 days since regen, **or** the page contradicts an Accepted ADR (the `test_label_state_matches_adr0002` / `test_loop_count_matches_adr0001` checks failed in CI), **or** `.meta.json` is missing the artifact entirely (bootstrap state, before the loop has run). |

## How to contribute

- **Found drift?** Open an issue. If a Generated page lies, the loop
  will likely catch it within 4 hours; if you can't wait, run
  `make arch-regen` locally and open a PR.
- **Want to amend an ADR?** Direct PR against `docs/adr/`.
- **Want to add a wiki entry?** Direct PR against `docs/wiki/`.
- **New loop or Port?** Add it to `docs/arch/functional_areas.yml`
  in the same PR — the coverage test will fail otherwise.

## Build

The site is built with [MkDocs Material](https://squidfunk.github.io/mkdocs-material/)
and deployed by `.github/workflows/pages-deploy.yml` to GitHub Pages on
every merge to `main`. To preview locally:

```
make arch-serve
```
```

- [ ] **Step 2: Verify**

```bash
mkdocs build --strict
```

- [ ] **Step 3: Commit**

```bash
git add docs/about.md
git commit -m "feat(docs): about page (freshness model + contribution flow)"
```

---

## Task 5: Activate `make arch-serve`

**Files:**
- Modify: `Makefile`

Plan A's `arch-serve` was a placeholder ("mkdocs not configured yet"). Now that `mkdocs.yml` exists, swap it for the real command.

- [ ] **Step 1: Replace the target**

In `Makefile`, replace:

```makefile
arch-serve:
	@if command -v mkdocs >/dev/null 2>&1 && [ -f mkdocs.yml ]; then \
	    mkdocs serve --strict; \
	else \
	    echo "mkdocs not configured yet — Plan C wires this up. ..."; \
	fi
```

with:

```makefile
arch-serve:
	@command -v mkdocs >/dev/null 2>&1 || { echo "mkdocs not installed; run: pip install -e '.[docs]'"; exit 1; }
	mkdocs serve --strict
```

- [ ] **Step 2: Verify**

```bash
make arch-regen  # ensure docs/arch/generated/ is current
make arch-serve  # should start the dev server on http://127.0.0.1:8000
```

Open the URL in a browser, click around the nav. Mermaid diagrams should render (some might 404 if MkDocs strict catches a broken link — fix the nav). Stop the server.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "build(docs): activate make arch-serve to run mkdocs serve --strict"
```

---

## Task 6: Wire freshness badge into runner footer

**Files:**
- Modify: `src/arch/runner.py`
- Modify: `src/arch/freshness.py` (extend with badge-rendering helper)
- Modify: `tests/architecture/test_runner.py` (assert badge appears)
- Modify: `tests/architecture/test_arch_freshness.py` (extend for emoji/tooltip)

Plan A's footer reads `_Regenerated from commit X on Y. Source last changed at Z._`. Plan C extends this to include `Status: 🟢 fresh.` (or 🟡/🔴) at the end. The state is computed at emit time using the current source SHA and the previous `.meta.json` (if any).

- [ ] **Step 1: Extend `freshness.py` with a render helper**

Add to `src/arch/freshness.py`:

```python
_BADGE_GLYPHS: dict["FreshnessBadge", str] = {}  # populated below


def render_badge(state: "FreshnessBadge") -> str:
    """Return 'Status: 🟢 fresh' or equivalent."""
    glyphs = {
        FreshnessBadge.FRESH: "🟢 fresh",
        FreshnessBadge.SOURCE_MOVED: "🟡 source-moved",
        FreshnessBadge.STALE: "🔴 stale",
        FreshnessBadge.NOT_GENERATED: "🔴 not yet generated",
    }
    return f"Status: {glyphs[state]}"
```

Add a unit test extending `test_arch_freshness.py`:

```python
from src.arch.freshness import FreshnessBadge, render_badge


def test_render_badge_emits_emoji_and_label():
    assert render_badge(FreshnessBadge.FRESH) == "Status: 🟢 fresh"
    assert render_badge(FreshnessBadge.SOURCE_MOVED) == "Status: 🟡 source-moved"
    assert render_badge(FreshnessBadge.STALE) == "Status: 🔴 stale"
    assert render_badge(FreshnessBadge.NOT_GENERATED) == "Status: 🔴 not yet generated"
```

- [ ] **Step 2: Update `_stamp_footer` in the runner**

In `src/arch/runner.py`, change `_stamp_footer` to take a `FreshnessBadge` and append the badge:

```python
from src.arch.freshness import FreshnessBadge, compute_badge, render_badge


def _stamp_footer(body: str, *, sha: str, source_sha: str, badge: FreshnessBadge) -> str:
    """Replace {{ARCH_FOOTER}} with regen footer including freshness state."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    footer = (
        f"_Regenerated from commit `{sha[:7]}` on {now}. "
        f"Source last changed at `{source_sha[:7]}`. "
        f"{render_badge(badge)}._"
    )
    return body.replace("{{ARCH_FOOTER}}", footer)
```

- [ ] **Step 3: Update `emit()` to compute the badge**

In `emit()`, replace the previous-meta lookup + per-artifact stamping:

```python
def emit(*, repo_root: Path, out_dir: Path) -> None:
    repo_root = Path(repo_root).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    sha = _commit_sha(repo_root)
    artifacts = _compute_artifacts(repo_root)

    # Load PREVIOUS meta (if any) to compute the badge state correctly
    meta_path = out_dir.parent / ".meta.json"
    prev_meta = None
    if meta_path.exists():
        try:
            prev_meta = json.loads(meta_path.read_text())
        except (OSError, json.JSONDecodeError):
            prev_meta = None

    now = datetime.now(timezone.utc)
    for name, body in artifacts.items():
        # Source SHA is HEAD (per-artifact differentiation deferred)
        badge = compute_badge(name, meta=prev_meta, current_source_sha=sha, now=now)
        # Important: we just regenerated, so the state should be FRESH unless
        # the page contradicts an Accepted ADR (handled by tests, not freshness).
        # The badge from compute_badge against the OLD meta describes the state
        # BEFORE regen. Since we ARE regenerating right now, force FRESH for
        # the new file.
        badge = FreshnessBadge.FRESH
        stamped = _stamp_footer(body, sha=sha, source_sha=sha, badge=badge)
        (out_dir / name).write_text(stamped)

    meta = {
        "regenerated_at": now.isoformat(),
        "commit_sha": sha,
        "artifacts": {n: {"source_sha": sha} for n in artifacts},
    }
    meta_path.write_text(json.dumps(meta, indent=2))
```

(The dead-store of `badge = compute_badge(...)` then `badge = FreshnessBadge.FRESH` is intentional and documented inline — emit() always writes FRESH; `compute_badge` is the read-side helper used by, e.g., a future drift dashboard. Plan A's badge-state test still validates the read path.)

- [ ] **Step 4: Update runner tests**

In `tests/architecture/test_runner.py`, add an assertion to `test_emit_writes_all_nine_artifacts`:

```python
    # Footer includes the freshness badge
    loops_md = (out / "loops.md").read_text()
    assert "Status: 🟢 fresh" in loops_md
    assert "Regenerated from commit" in loops_md
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/architecture/test_runner.py tests/architecture/test_arch_freshness.py -v
```

Expected: all pass.

- [ ] **Step 6: Smoke-test against the real repo**

```bash
make arch-regen
tail -5 docs/arch/generated/loops.md
```

Expected: footer reads `_Regenerated from commit ... Status: 🟢 fresh._`.

- [ ] **Step 7: Commit**

```bash
git add src/arch/runner.py src/arch/freshness.py tests/architecture/test_runner.py tests/architecture/test_arch_freshness.py docs/arch/generated/ docs/arch/.meta.json
git commit -m "feat(arch): wire freshness badge into runner footer"
```

---

## Task 7: Strict-build test

**Files:**
- Create: `tests/architecture/test_mkdocs_strict.py`

Asserts that `mkdocs build --strict` succeeds against the current docs tree. Catches broken cross-links before they hit Pages deploy.

- [ ] **Step 1: Write the test**

```python
# tests/architecture/test_mkdocs_strict.py
import shutil
import subprocess
from pathlib import Path

import pytest


def test_mkdocs_build_strict_succeeds(real_repo_root: Path):
    """Run `mkdocs build --strict` against the live docs tree; fail on any warning.

    This is the gate that catches a generator emitting a relative link to a
    page that doesn't exist (e.g. an ADR file path that's been deleted).
    """
    if shutil.which("mkdocs") is None:
        pytest.skip("mkdocs not installed; run: pip install -e '.[docs]'")
    res = subprocess.run(
        ["mkdocs", "build", "--strict"],
        cwd=real_repo_root,
        capture_output=True,
        text=True,
    )
    if res.returncode != 0:
        pytest.fail(
            f"`mkdocs build --strict` failed:\n--- stdout ---\n{res.stdout}\n--- stderr ---\n{res.stderr}"
        )
```

- [ ] **Step 2: Run it**

```bash
pytest tests/architecture/test_mkdocs_strict.py -v
```

Expected: pass (or skip if MkDocs not installed in the local env — the CI workflow installs it).

- [ ] **Step 3: Commit**

```bash
git add tests/architecture/test_mkdocs_strict.py
git commit -m "test(docs): mkdocs --strict build guard"
```

---

## Task 8: `DiagramLoop` skeleton

**Files:**
- Create: `src/diagram_loop.py`
- Test: `tests/test_diagram_loop.py` (matching the `tests/test_*_loop.py` convention)

Subclasses `BaseBackgroundLoop` (the only application-import that's allowed inside `src/`; `src/arch/` itself stays pure-AST). Lives at the **flat** `src/diagram_loop.py` to match the existing loop file convention (e.g. `src/repo_wiki_loop.py`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diagram_loop.py
"""Unit tests for src/diagram_loop.py:DiagramLoop.

ADR-0029 (caretaker pattern) and ADR-0049 (kill-switch convention).
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from diagram_loop import DiagramLoop


@pytest.fixture
def loop_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
        interval_cb=MagicMock(return_value=14400),  # 4h
    )


def test_constructor_sets_worker_name(loop_deps):
    config = MagicMock()
    pr_manager = MagicMock()
    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    assert loop._worker_name == "diagram-loop"


def test_default_interval_is_four_hours(loop_deps):
    loop = DiagramLoop(config=MagicMock(), pr_manager=MagicMock(), deps=loop_deps)
    assert loop._get_default_interval() == 14400  # 4h
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_diagram_loop.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement the skeleton**

```python
# src/diagram_loop.py
"""DiagramLoop (L24) — autonomous regeneration of architecture knowledge.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the architecture knowledge system spec
(docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md §4.4).

Tick behavior:
  1. Run runner.emit() against the current working tree.
  2. git status --porcelain on docs/arch/generated/ and .meta.json.
  3. If empty: log "no drift", return.
  4. Otherwise: open (or update) a single PR titled
     "chore(arch): regenerate architecture knowledge — YYYY-MM-DD".
     Idempotence is title-PREFIX based ("chore(arch): regenerate
     architecture knowledge"), not date-stamped, to avoid the
     midnight-UTC race.
  5. Run the functional-area coverage check; if it fails, open a
     "chore(arch): unassigned functional area" issue (separate from
     the regen PR).

Kill switch: HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from base_background_loop import BaseBackgroundLoop, LoopDeps, WorkCycleResult
from config import HydraFlowConfig
from src.arch.runner import emit as arch_emit


_PR_TITLE_PREFIX = "chore(arch): regenerate architecture knowledge"
_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"


@dataclass
class _DriftResult:
    has_drift: bool
    changed_files: list[str]


class DiagramLoop(BaseBackgroundLoop):
    """L24 caretaker — keeps docs/arch/generated/ in sync with src/.

    Per ADR-0029, ADR-0049.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager,  # PRPort-shaped object; same as RepoWikiLoop's input
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="diagram-loop",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._repo_root = Path.cwd()  # overridable via _set_repo_root for tests

    def _set_repo_root(self, path: Path) -> None:
        """Test seam: redirect the loop at a worktree without subclassing."""
        self._repo_root = Path(path)

    def _get_default_interval(self) -> int:
        # 4 hours; configurable via HydraFlowConfig in production
        return 14400

    async def _do_work(self) -> WorkCycleResult:
        # Kill-switch (ADR-0049). Belt and suspenders — enabled_cb usually
        # handles this upstream of _do_work, but we re-check to be defensive.
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return WorkCycleResult(stats={"skipped": "kill_switch"})

        drift = await asyncio.to_thread(self._regen_and_detect_drift)
        if not drift.has_drift:
            return WorkCycleResult(stats={"drift": False})

        # Open or update the regen PR (Task 11).
        pr_url = await self._open_or_update_regen_pr(drift.changed_files)

        # Coverage check; if unassigned items, open a separate issue (Task 12).
        await self._ensure_coverage_issue()

        return WorkCycleResult(stats={
            "drift": True,
            "changed_files": len(drift.changed_files),
            "pr_url": pr_url,
        })

    def _regen_and_detect_drift(self) -> _DriftResult:
        out_dir = self._repo_root / "docs/arch/generated"
        arch_emit(repo_root=self._repo_root, out_dir=out_dir)
        # Use git status to detect drift relative to HEAD.
        res = subprocess.run(
            ["git", "status", "--porcelain", "docs/arch/generated", "docs/arch/.meta.json"],
            cwd=self._repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return _DriftResult(has_drift=False, changed_files=[])
        lines = [l for l in res.stdout.splitlines() if l.strip()]
        return _DriftResult(has_drift=bool(lines), changed_files=lines)

    async def _open_or_update_regen_pr(self, changed_files: list[str]) -> str | None:
        """Stub — implementation in Task 11."""
        return None

    async def _ensure_coverage_issue(self) -> None:
        """Stub — implementation in Task 12."""
        pass
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_diagram_loop.py -v
```

Expected: 2 pass.

- [ ] **Step 5: Commit**

```bash
git add src/diagram_loop.py tests/test_diagram_loop.py
git commit -m "feat(loop): DiagramLoop (L24) skeleton — _do_work + drift detection"
```

---

## Task 9: Register `DiagramLoop` in the catalog

**Files:**
- Modify: `tests/scenarios/catalog/loop_registrations.py`

Plan B already pre-assigned `DiagramLoop` to the `arch_knowledge` functional area. Now wire it into the test catalog (the same pattern that `RepoWikiLoop`, `CIMonitorLoop`, etc. follow).

- [ ] **Step 1: Add the build function**

In `tests/scenarios/catalog/loop_registrations.py`, append a `_build_diagram_loop` function and register it:

```python
def _build_diagram_loop(ports: dict[str, Any], config: Any, deps: Any) -> Any:
    from diagram_loop import DiagramLoop  # noqa: PLC0415

    return DiagramLoop(
        config=config,
        pr_manager=ports["github"],
        deps=deps,
    )


register_loop(name="diagram_loop", builder=_build_diagram_loop)
```

(Place this alongside the other loop registrations; mirror the existing call shape.)

- [ ] **Step 2: Run the catalog instantiation tests**

```bash
pytest tests/scenarios/catalog/test_loop_instantiation.py -v
```

Expected: pass; `diagram_loop` appears in the catalog.

- [ ] **Step 3: Confirm coverage test now passes for DiagramLoop**

```bash
pytest tests/architecture/test_functional_area_coverage.py -v
```

Expected: still passing (DiagramLoop is now real, and was already pre-assigned to `arch_knowledge` in Plan B's YAML — no phantom).

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/catalog/loop_registrations.py
git commit -m "feat(loop): register DiagramLoop in LoopCatalog"
```

---

## Task 10: Five-checkpoint loop wiring

**Files:**
- Inspect/modify: wherever the existing five-checkpoint runner construction lives (likely `src/orchestrator/` or `src/server.py`/`server.py`)
- Test: `tests/test_loop_wiring_completeness.py` (existing — should now cover DiagramLoop)

Per `docs/wiki/gotchas.md` "five-checkpoint loop wiring." Each new loop must be wired in five places: imports, instantiation, run-task addition, status registration, and shutdown handling. Follow the pattern set by `RepoWikiLoop`.

- [ ] **Step 1: Inspect the five-checkpoint pattern**

```bash
grep -rln "RepoWikiLoop" src/ | head -5
# Open each match and find the five usages
```

Identify:
1. **Import** (top of the orchestrator/server module).
2. **Instantiation** (loop construction during startup).
3. **Run task** (loop launched in the asyncio task group).
4. **Status registration** (registered with the status reporter / event bus).
5. **Shutdown** (clean cancellation in the shutdown handler).

- [ ] **Step 2: Add DiagramLoop to all five sites**

Add `from diagram_loop import DiagramLoop` to the imports section, instantiate it where the other caretaker loops are, register it for status, add it to the run task list, and ensure it's stopped during shutdown. Pattern-match `RepoWikiLoop` line-for-line.

- [ ] **Step 3: Run the wiring completeness test**

```bash
pytest tests/test_loop_wiring_completeness.py -v
```

Expected: pass; `diagram-loop` appears in every checkpoint set.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "feat(loop): wire DiagramLoop into five-checkpoint orchestration"
```

---

## Task 11: PR creation with title-prefix idempotence

**Files:**
- Modify: `src/diagram_loop.py`
- Modify: `tests/test_diagram_loop.py`

Implement `_open_or_update_regen_pr`. Per spec §4.4 (review-fix): lookup uses **title-prefix match** + `hydraflow-ready` label, not date-stamped title.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diagram_loop.py — append
import pytest

from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_open_pr_when_no_existing(loop_deps, tmp_path):
    config = MagicMock()
    pr_manager = MagicMock()
    pr_manager.list_pull_requests = AsyncMock(return_value=[])  # none open
    pr_manager.create_pull_request = AsyncMock(return_value={"url": "https://pr/1", "number": 1})

    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)
    url = await loop._open_or_update_regen_pr(["M docs/arch/generated/loops.md"])

    assert pr_manager.create_pull_request.await_count == 1
    args, kwargs = pr_manager.create_pull_request.await_args
    assert kwargs["title"].startswith("chore(arch): regenerate architecture knowledge")
    assert "hydraflow-ready" in (kwargs.get("labels") or [])
    assert url == "https://pr/1"


@pytest.mark.asyncio
async def test_updates_existing_pr_with_prefix_match(loop_deps, tmp_path):
    config = MagicMock()
    pr_manager = MagicMock()
    pr_manager.list_pull_requests = AsyncMock(return_value=[
        {"number": 99, "title": "chore(arch): regenerate architecture knowledge — 2026-04-23",
         "url": "https://pr/99", "labels": [{"name": "hydraflow-ready"}]},
    ])
    pr_manager.create_pull_request = AsyncMock()  # should NOT be called
    pr_manager.update_pull_request = AsyncMock(return_value={"url": "https://pr/99"})

    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)
    url = await loop._open_or_update_regen_pr(["M docs/arch/generated/loops.md"])

    assert pr_manager.create_pull_request.await_count == 0
    assert pr_manager.update_pull_request.await_count == 1
    # Date in title is refreshed
    update_kwargs = pr_manager.update_pull_request.await_args.kwargs
    assert "2026-04" in update_kwargs.get("title", "")  # contains current month
    assert url == "https://pr/99"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_diagram_loop.py::test_open_pr_when_no_existing -v
```

Expected: stub returns None; assertion fails.

- [ ] **Step 3: Implement**

Replace the stub `_open_or_update_regen_pr` in `src/diagram_loop.py`:

```python
async def _open_or_update_regen_pr(self, changed_files: list[str]) -> str | None:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    title = f"{_PR_TITLE_PREFIX} — {today}"
    body = self._build_pr_body(changed_files)

    # Look up an existing open PR by title-prefix + label (per spec §4.4 mid-night fix).
    existing = await self._find_open_regen_pr()
    if existing:
        await self._pr_manager.update_pull_request(
            number=existing["number"],
            title=title,
            body=body,
        )
        return existing.get("url")

    res = await self._pr_manager.create_pull_request(
        title=title,
        body=body,
        labels=["hydraflow-ready", "arch-regen"],
    )
    return res.get("url")


async def _find_open_regen_pr(self) -> dict | None:
    open_prs = await self._pr_manager.list_pull_requests(state="open")
    for pr in open_prs:
        title = pr.get("title", "")
        if not title.startswith(_PR_TITLE_PREFIX):
            continue
        labels = {lbl.get("name") for lbl in pr.get("labels", []) if isinstance(lbl, dict)}
        if "hydraflow-ready" in labels or not labels:
            return pr
    return None


def _build_pr_body(self, changed_files: list[str]) -> str:
    lines = [
        "Auto-generated by `DiagramLoop` (L24). The architecture knowledge ",
        "artifacts in `docs/arch/generated/` were re-extracted from source ",
        "and the diff is included in this PR.",
        "",
        f"**Changed files** ({len(changed_files)}):",
        "",
    ]
    lines.extend(f"- `{l}`" for l in changed_files[:30])
    if len(changed_files) > 30:
        lines.append(f"- _(...and {len(changed_files) - 30} more)_")
    lines.extend([
        "",
        "Per ADR-0029 caretaker pattern. Will auto-merge once CI passes ",
        "(arch-regen guard, quality, scenario tests).",
    ])
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_diagram_loop.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/diagram_loop.py tests/test_diagram_loop.py
git commit -m "feat(loop): DiagramLoop PR creation with title-prefix idempotence"
```

---

## Task 12: Coverage-check issue filing

**Files:**
- Modify: `src/diagram_loop.py`
- Modify: `tests/test_diagram_loop.py`

If `tests/architecture/test_functional_area_coverage.py` would fail (i.e. there are unassigned loops/ports), the loop opens a `chore(arch): unassigned functional area` issue rather than failing silently or trying to author a YAML edit (which a human must do).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diagram_loop.py — append
@pytest.mark.asyncio
async def test_opens_issue_when_unassigned_items_detected(loop_deps, tmp_path, monkeypatch):
    """When the coverage check finds an unassigned loop, open an issue."""
    # Stub the coverage check helper to return unassigned items
    config = MagicMock()
    pr_manager = MagicMock()
    pr_manager.list_issues = AsyncMock(return_value=[])  # no existing issue
    pr_manager.create_issue = AsyncMock(return_value={"url": "https://issue/1"})

    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)

    monkeypatch.setattr(loop, "_unassigned_items",
                        AsyncMock(return_value={"loops": ["FooLoop"], "ports": []}))
    await loop._ensure_coverage_issue()

    assert pr_manager.create_issue.await_count == 1
    args, kwargs = pr_manager.create_issue.await_args
    assert "unassigned functional area" in kwargs.get("title", "").lower()
    assert "FooLoop" in kwargs.get("body", "")


@pytest.mark.asyncio
async def test_no_issue_when_coverage_is_complete(loop_deps, tmp_path, monkeypatch):
    config = MagicMock()
    pr_manager = MagicMock()
    pr_manager.create_issue = AsyncMock()
    loop = DiagramLoop(config=config, pr_manager=pr_manager, deps=loop_deps)
    loop._set_repo_root(tmp_path)
    monkeypatch.setattr(loop, "_unassigned_items",
                        AsyncMock(return_value={"loops": [], "ports": []}))
    await loop._ensure_coverage_issue()
    assert pr_manager.create_issue.await_count == 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_diagram_loop.py::test_opens_issue_when_unassigned_items_detected -v
```

Expected: fails (stub returns nothing).

- [ ] **Step 3: Implement**

Add to `src/diagram_loop.py`:

```python
async def _unassigned_items(self) -> dict[str, list[str]]:
    """Return {'loops': [...], 'ports': [...]} of items in code but not in YAML."""
    from src.arch._functional_areas_schema import load_functional_areas
    from src.arch.extractors.loops import extract_loops
    from src.arch.extractors.ports import extract_ports

    src_dir = self._repo_root / "src"
    fakes_dir = self._repo_root / "tests/scenarios/fakes"
    yaml_path = self._repo_root / "docs/arch/functional_areas.yml"

    if not yaml_path.exists():
        return {"loops": [], "ports": []}  # nothing to assign against
    fa = load_functional_areas(yaml_path)
    assigned_loops = set()
    assigned_ports = set()
    for area in fa.areas.values():
        assigned_loops.update(area.loops)
        assigned_ports.update(area.ports)

    discovered_loops = {l.name for l in extract_loops(src_dir)}
    discovered_ports = {p.name for p in extract_ports(src_dir=src_dir, fakes_dir=fakes_dir)}
    return {
        "loops": sorted(discovered_loops - assigned_loops),
        "ports": sorted(discovered_ports - assigned_ports),
    }


async def _ensure_coverage_issue(self) -> None:
    items = await self._unassigned_items()
    if not items["loops"] and not items["ports"]:
        return
    # Don't dup-open: search existing issues
    existing = await self._pr_manager.list_issues(state="open")
    for iss in existing:
        if iss.get("title", "").startswith("chore(arch): unassigned functional area"):
            return  # already open — leave it
    body_lines = [
        "DiagramLoop detected loops or ports in `src/` that aren't assigned ",
        "to a functional area in `docs/arch/functional_areas.yml`.",
        "",
    ]
    if items["loops"]:
        body_lines.append("**Unassigned loops:**\n")
        body_lines.extend(f"- `{n}`" for n in items["loops"])
        body_lines.append("")
    if items["ports"]:
        body_lines.append("**Unassigned ports:**\n")
        body_lines.extend(f"- `{n}`" for n in items["ports"])
        body_lines.append("")
    body_lines.append("Fix: edit `docs/arch/functional_areas.yml` and assign each item to the appropriate area's `loops:` or `ports:` list.")

    await self._pr_manager.create_issue(
        title="chore(arch): unassigned functional area",
        body="\n".join(body_lines),
        labels=["hydraflow-find", "arch-knowledge"],
    )
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_diagram_loop.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/diagram_loop.py tests/test_diagram_loop.py
git commit -m "feat(loop): DiagramLoop opens issue when functional-area coverage breaks"
```

---

## Task 13: Kill-switch test

**Files:**
- Create: `tests/test_diagram_loop_kill_switch.py`

Per ADR-0049: with `HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1`, the loop's tick is a no-op. Test asserts no PR is opened, no `runner.emit` is called.

- [ ] **Step 1: Write the test**

```python
# tests/test_diagram_loop_kill_switch.py
"""ADR-0049 — kill-switch convention for DiagramLoop."""
import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from base_background_loop import LoopDeps
from diagram_loop import DiagramLoop


@pytest.fixture
def loop_deps() -> LoopDeps:
    return LoopDeps(
        event_bus=MagicMock(),
        stop_event=asyncio.Event(),
        status_cb=MagicMock(),
        enabled_cb=MagicMock(return_value=True),
        sleep_fn=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_kill_switch_skips_work(loop_deps, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.create_pull_request = AsyncMock()
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.setenv("HYDRAFLOW_DISABLE_DIAGRAM_LOOP", "1")
    with patch("diagram_loop.arch_emit") as mock_emit:
        result = await loop._do_work()
    assert result.stats.get("skipped") == "kill_switch"
    mock_emit.assert_not_called()
    pr_manager.create_pull_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_kill_switch_unset_runs_normally(loop_deps, monkeypatch):
    pr_manager = MagicMock()
    pr_manager.list_pull_requests = AsyncMock(return_value=[])
    pr_manager.create_pull_request = AsyncMock(return_value={"url": "https://pr/1"})
    pr_manager.list_issues = AsyncMock(return_value=[])
    pr_manager.create_issue = AsyncMock(return_value={"url": "https://issue/1"})
    loop = DiagramLoop(config=MagicMock(), pr_manager=pr_manager, deps=loop_deps)

    monkeypatch.delenv("HYDRAFLOW_DISABLE_DIAGRAM_LOOP", raising=False)
    # No drift in this test (mocked to return empty)
    with patch.object(loop, "_regen_and_detect_drift") as mock_regen:
        from diagram_loop import _DriftResult
        mock_regen.return_value = _DriftResult(has_drift=False, changed_files=[])
        result = await loop._do_work()
    assert result.stats.get("drift") is False
```

- [ ] **Step 2: Run tests**

```bash
pytest tests/test_diagram_loop_kill_switch.py -v
```

Expected: 2 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_diagram_loop_kill_switch.py
git commit -m "test(loop): DiagramLoop kill-switch (ADR-0049)"
```

---

## Task 14: MockWorld scenario

**Files:**
- Create: `tests/scenarios/test_diagram_loop_scenario.py`

End-to-end scenario per ADR-0047: source changes → MockWorld fires the loop tick → assert a PR is opened with the expected diff and title-prefix.

- [ ] **Step 1: Inspect MockWorld API**

Read one existing scenario test for shape:

```bash
ls tests/scenarios/test_*scenario*.py | head -3
```

Pick the smallest one and read it. The plan below assumes the established pattern (MockWorld instantiation, scenario building, assertion).

- [ ] **Step 2: Write the scenario**

```python
# tests/scenarios/test_diagram_loop_scenario.py
"""End-to-end scenario for DiagramLoop (ADR-0047, spec §7).

Setup: a MockWorld with a source tree that has 5 loops + a populated YAML
covering them. We add a 6th loop AFTER baseline emit, fire one tick, and
assert that a regen PR is opened with the new loop in the diff.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld


@pytest.mark.asyncio
async def test_diagram_loop_opens_regen_pr_on_drift(tmp_path: Path):
    world = MockWorld(tmp_path)
    # Seed: arch-knowledge state established (functional_areas.yml + 5 loops + baseline)
    await world.seed_arch_knowledge_baseline()

    # Mutation: add a new loop class that DOESN'T appear in the YAML's pre-assignments
    new_loop_path = world.repo_root / "src/sparkle_loop.py"
    new_loop_path.write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class SparkleLoop(BaseBackgroundLoop):\n"
        "    \"\"\"A test loop. Per ADR-0029.\"\"\"\n"
        "    pass\n"
    )

    # Fire one tick of the DiagramLoop
    await world.tick("diagram_loop")

    # Two outcomes expected:
    # 1. A regen PR (the generated/loops.md now lists SparkleLoop)
    pr = world.fake_github.last_opened_pull_request()
    assert pr is not None
    assert pr["title"].startswith("chore(arch): regenerate architecture knowledge")
    assert "SparkleLoop" in pr["body"] or any("loops.md" in f for f in pr.get("changed_files", []))

    # 2. An issue about the unassigned area (since SparkleLoop isn't in the YAML)
    iss = world.fake_github.last_opened_issue()
    assert iss is not None
    assert iss["title"].startswith("chore(arch): unassigned functional area")
    assert "SparkleLoop" in iss["body"]
```

**Note on `world.seed_arch_knowledge_baseline()` and `world.tick("diagram_loop")`:** these are MockWorld helpers that may not exist yet. If they don't, the implementer writes them as part of this task — they're test infrastructure, not production code. The seed helper writes a minimal `src/`, `tests/scenarios/fakes/`, `docs/adr/`, and `docs/arch/functional_areas.yml`. The tick helper looks up the registered builder for `diagram_loop` (Task 9), instantiates it, and calls `await loop._do_work()`.

- [ ] **Step 3: Run the scenario**

```bash
pytest tests/scenarios/test_diagram_loop_scenario.py -v
```

If MockWorld helpers don't exist, implement them in `tests/scenarios/fakes/mock_world.py` as the smallest possible additions — don't generalize. Pattern-match similar `seed_*` and `tick("...")` helpers that exist for other loops.

Expected eventually: pass.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/test_diagram_loop_scenario.py tests/scenarios/fakes/mock_world.py
git commit -m "test(scenario): DiagramLoop end-to-end (ADR-0047)"
```

---

## Task 15: `arch-regen.yml` CI guard workflow

**Files:**
- Create: `.github/workflows/arch-regen.yml`

- [ ] **Step 1: Author the workflow**

```yaml
# .github/workflows/arch-regen.yml
name: arch-regen
on:
  pull_request:
    paths:
      - 'src/**'
      - 'docs/adr/**'
      - 'docs/arch/**'
      - 'tests/scenarios/fakes/**'
      - 'tests/architecture/**'

jobs:
  arch-check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0  # changelog generator needs full history
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install
        run: pip install -e '.[dev,test,docs]'
      - name: Validate functional_areas.yml
        run: make arch-validate
      - name: Drift check
        run: python -m src.arch.runner --check --repo-root .
      - name: Architecture tests
        run: pytest tests/architecture -x --tb=short
```

- [ ] **Step 2: Verify locally that --check exits 0 right now**

```bash
make arch-regen  # ensure baseline is current
python -m src.arch.runner --check --repo-root .
echo "rc=$?"
```

Expected: rc=0.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/arch-regen.yml
git commit -m "ci(arch): arch-regen workflow (drift guard on PR)"
```

---

## Task 16: `pages-deploy.yml` workflow

**Files:**
- Create: `.github/workflows/pages-deploy.yml`

- [ ] **Step 1: Author the workflow**

```yaml
# .github/workflows/pages-deploy.yml
name: pages-deploy
on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'mkdocs.yml'
      - 'src/arch/**'
      - 'pyproject.toml'

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: pages
  cancel-in-progress: false

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install
        run: pip install -e '.[dev,docs]'
      - name: Idempotent regen
        run: python -m src.arch.runner --emit --repo-root .
      - name: Build site
        run: mkdocs build --strict
      - uses: actions/upload-pages-artifact@v3
        with:
          path: ./site
  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - id: deployment
        uses: actions/deploy-pages@v4
```

- [ ] **Step 2: Verify the build step locally**

```bash
mkdocs build --strict
ls site/index.html
```

Expected: `site/index.html` exists.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/pages-deploy.yml
git commit -m "ci(docs): pages-deploy workflow (GitHub-native deploy-pages)"
```

---

## Task 17: README + announce site URL

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md` (add badge near top)

- [ ] **Step 1: Add a badge to README.md**

After the existing top-of-file content, add:

```markdown
[![Architecture Knowledge](https://img.shields.io/badge/arch-knowledge-blueviolet)](https://t-rav-hydra-ops.github.io/hydraflow/)

📖 **[HydraFlow Architecture site](https://t-rav-hydra-ops.github.io/hydraflow/)** — auto-generated, updated every 4h by the DiagramLoop.
```

- [ ] **Step 2: Update CLAUDE.md "Quick rules"**

Plan B already added a rule pointing at the site. No further change needed unless the URL placeholder needs replacing.

- [ ] **Step 3: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: link arch knowledge site from README"
```

---

## Task 18: End-to-end smoke

**Files:**
- (none — verification only)

- [ ] **Step 1: Run the full architecture test suite**

```bash
pytest tests/architecture tests/test_diagram_loop.py tests/test_diagram_loop_kill_switch.py tests/scenarios/test_diagram_loop_scenario.py -v
```

Expected: all pass.

- [ ] **Step 2: Run `make quality`**

```bash
make quality
```

Expected: green.

- [ ] **Step 3: Build the site locally**

```bash
make arch-regen
make arch-serve  # opens dev server
```

Manually:
- Visit http://127.0.0.1:8000.
- Click into "System Map" and verify the Mermaid renders.
- Click into "Generated → Loop Registry" and verify the freshness footer reads `Status: 🟢 fresh`.
- Click into "Decisions" and ensure ADR README renders.
- Click a few cross-links to verify nothing 404s.
- Stop the server.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin arch-knowledge-system
gh pr create --title "feat(arch): Plan C — DiagramLoop + CI guard + Pages site" \
    --body "$(cat <<'EOF'
## Summary

Plan C of the Architecture Knowledge System
(`docs/superpowers/specs/2026-04-24-architecture-knowledge-system-design.md`,
plan: `docs/superpowers/plans/2026-04-24-arch-knowledge-system-plan-c-loop-and-pages.md`).

Ships:
- `src/diagram_loop.py:DiagramLoop` (L24) — autonomous regen + idempotent PR
- `tests/test_diagram_loop.py` + `tests/test_diagram_loop_kill_switch.py`
- `tests/scenarios/test_diagram_loop_scenario.py` — MockWorld E2E
- `.github/workflows/arch-regen.yml` — CI guard on every PR
- `.github/workflows/pages-deploy.yml` — GitHub-native Pages deploy on push to main
- `mkdocs.yml` + `docs/index.md` + `docs/about.md` — MkDocs Material site config
- Freshness badge wired into runner footer (🟢/🟡/🔴)
- README badge linking to the site

The site goes live at https://t-rav-hydra-ops.github.io/hydraflow/ on
merge.

## Test plan

- [x] `pytest tests/architecture tests/test_diagram_loop*.py tests/scenarios/test_diagram_loop_scenario.py` all pass
- [x] `make quality` is green
- [x] `mkdocs build --strict` succeeds
- [x] Site renders locally at `make arch-serve`; nav cross-links resolve; Mermaid renders; freshness footer present
- [x] `python -m src.arch.runner --check --repo-root .` exits 0
- [x] Kill-switch test: `HYDRAFLOW_DISABLE_DIAGRAM_LOOP=1` makes `_do_work` a no-op
- [x] Scenario test: adding a loop fires both a regen PR and a coverage issue

## After merge

- Verify Pages deploy completed (Settings → Pages → "Your site is live")
- Watch for the first DiagramLoop tick PR within 4h
- Update repo About → Website with the Pages URL

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Task 19: Wait for first autonomous regen PR (post-merge verification)

**Files:**
- (none — verification only)

After this PR merges, observe.

- [ ] **Step 1: Confirm the site is live**

Visit https://t-rav-hydra-ops.github.io/hydraflow/. Check the homepage, system map, loops registry. Report 200 or HTTP error.

- [ ] **Step 2: Wait for the first autonomous tick**

Within 4 hours of merge, the DiagramLoop should run its first tick. If `src/` has had any commits since the last baseline emit, expect a `chore(arch): regenerate architecture knowledge — YYYY-MM-DD` PR. If `src/` is stable, the loop logs "no drift" and no PR is opened.

If the first PR does NOT appear within 6 hours and there have been merges to main:
- Check loop status in the dashboard.
- Confirm `HYDRAFLOW_DISABLE_DIAGRAM_LOOP` is unset in the operator env.
- Check `SessionLog` for tick errors.

- [ ] **Step 3: Confirm the autonomous PR is well-formed**

When it appears:
- Title prefix matches `chore(arch): regenerate architecture knowledge — `
- Labeled `hydraflow-ready` and `arch-regen`
- Body lists changed artifacts
- CI green (arch-regen + scenario tests)
- Auto-merges per the existing flow

- [ ] **Step 4: Close the loop**

If everything works, file a `hydraflow-find` issue: "Architecture Knowledge System v1 lights-out — first autonomous tick succeeded, site published, dropping to maintenance." (This becomes the closing event for the spec; future work is in §12 roadmap items.)

---

## Self-review checklist

- [ ] Every task in the spec coverage map is checked.
- [ ] No `TODO`/`FIXME`/placeholder in any new file.
- [ ] DiagramLoop is in the loop registry test (`test_loop_instantiation.py`) and the wiring completeness test (`test_loop_wiring_completeness.py`).
- [ ] Kill-switch is `HYDRAFLOW_DISABLE_DIAGRAM_LOOP` and a test enforces it.
- [ ] PR title-prefix idempotence (no date in lookup) — verified by test.
- [ ] Coverage check opens an *issue*, not a PR.
- [ ] CI guard runs `make arch-validate` BEFORE `--check` (catches malformed YAML before drift).
- [ ] Pages workflow uses `actions/deploy-pages@v4` (no `gh-pages` branch).
- [ ] `mkdocs build --strict` succeeds.
- [ ] Freshness badge appears in every generated artifact's footer.
