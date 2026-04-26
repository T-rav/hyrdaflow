# Dark-Factory Infrastructure Hardening — Design Spec

**Status:** Draft (2026-04-26)
**ADR:** Will need a new ADR (`ADR-0051-iterative-production-readiness-review.md`) — landed as part of this track's PR 1.
**Related ADRs:** ADR-0029 (caretaker loop pattern), ADR-0044 (principles), ADR-0045 (trust architecture), ADR-0049 (kill-switch convention), ADR-0050 (auto-agent HITL pre-flight).
**Related wiki:** `docs/wiki/dark-factory.md` (lessons inventory; sets up this spec).

## §1 Motivation

### The pattern that keeps biting us

Across the trust-fleet (#8390) and auto-agent (#8430, #8431, #8439) feature
builds, **every single Critical finding caught in fresh-eyes code review was
a missed load-bearing convention** — not a logic bug, not a typo, but a
convention a careful engineer was supposed to remember:

- ADR-0049 in-body kill-switch gate missing on 18 caretaker loops (#8430).
- `reraise_on_credit_or_bug` missing from `AutoAgentRunner`, silently
  eating `CreditExhaustedError` (#8439, C1).
- Auth-retry loop missing from `AutoAgentRunner`, burning per-issue attempt
  budget on transient OAuth blips (#8439, C2).
- `apply_decision` calling `pr.remove_labels` (plural) when `PRPort` only
  has `remove_label` (singular) — hidden by `AsyncMock` (#8439, C2).
- `gather_context` calling `pr.list_issue_comments` which didn't exist on
  `PRPort` at all — also hidden by `AsyncMock` (#8439, C3).
- New caretaker loop missing `functional_areas.yml` assignment (#8431
  smoke-test fallout).
- New module not regenerated in `docs/arch/generated/` (recurring across
  every PR that adds source files).

### Why "remembered" isn't enough

These are not bugs the engineer didn't know about — they're conventions
documented in `docs/wiki/dark-factory.md` (just landed in #8443) and
referenced in CLAUDE.md. The pattern is: **knowledge of the convention
exists, but nothing structurally enforces it at code-write time or PR
time.** Every Critical finding above was caught only by an iterative
fresh-eyes review pass, and only because the human remembered to dispatch
the reviewer.

The dark-factory contract (ADR-0050 §1, `docs/wiki/dark-factory.md` §1)
is "humans paged only for raging fires." Today, humans are paged for
every "Did you remember the auth-retry loop?" type of review-time
catch — that's not a fire, that's a pattern we should have made
impossible to miss.

### The systematic fix

Move conventions from "remembered" to "structurally enforced":

- **Base classes** that auto-apply load-bearing patterns to all subclasses.
- **Scaffold scripts** that generate boilerplate with all conventions
  correct.
- **Conformance tests** that catch contract drift between Ports and Fakes.
- **Pre-commit checks** that block the most common omissions before push.
- **A formal review process** that ratifies the iterative-convergence
  approach as the standard, not a heroic ad-hoc effort.

### What this spec is NOT

- Not a refactor of all existing runners. New `BaseSubprocessRunner`
  replaces `AutoAgentRunner`'s duplicated logic as the proof point;
  other runners migrate later if they need it. `BaseRunner` (the broader,
  older class) stays as-is.
- Not the auto-fix-everything pattern. Pre-commit `arch-regen` fails the
  commit with a helpful message; it does NOT auto-stage. Same UX as
  ruff's "run `ruff check --fix`" message.
- Not a Claude Code workflow change. The originally-considered
  "subagent-verify wrapper" (auto-`git status` after subagent DONE
  reports) is out of scope — it's an SDK / hook concern, not HydraFlow
  infrastructure. The CLAUDE.md Quick Rule covers the manual case.

## §2 Architecture

```
                        ┌─────────────────────────────────────┐
                        │   ADR-0051: iterative production-   │
                        │   readiness review (process)        │
                        │   ─────── lands first ───────       │
                        └─────────────────────────────────────┘
                                        │
                ┌───────────────────────┼───────────────────────┐
                ▼                       ▼                       ▼
        ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
        │ BaseSubprocess│       │ Auto-PRPort   │       │ Pre-commit    │
        │ Runner        │       │ conformance   │       │ arch-regen    │
        │ (encapsulate) │       │ (auto-gen)    │       │ (workflow)    │
        └───────────────┘       └───────────────┘       └───────────────┘
                │                       │
                └───────────┬───────────┘
                            ▼
                    ┌───────────────┐
                    │ scaffold-loop │
                    │ (consumes the │
                    │  base classes)│
                    └───────────────┘
```

Five components delivered across three PRs (sequencing in §6).

### §2.1 Five components, by impact

| # | Component | Critical findings prevented | Blast radius |
|---|---|---|---|
| 1 | `BaseSubprocessRunner` | #8439 C1 (no `reraise_on_credit_or_bug`), #8439 C2 (no auth-retry) | Every future subprocess-spawning runner |
| 2 | `scripts/scaffold-loop.py` | #8430 (18-loop ADR-0049 retrofit) | Every future caretaker loop |
| 3 | Auto-PRPort signature conformance | #8439 C2 (`remove_labels` plural typo), #8439 C3 (nonexistent `list_issue_comments`) | Every Port↔Adapter pair |
| 4 | Pre-commit `arch-regen` | Recurring rebase pain on every PR that adds source files | Every PR touching arch source |
| 5 | ADR-0051: iterative production-readiness review | Substantial features merged before convergence | Every multi-task feature |

### §2.2 Out-of-scope (explicit)

- Subagent-verify wrapper (Claude Code SDK concern, not HydraFlow code).
- Migration of every existing runner to `BaseSubprocessRunner` —
  `AutoAgentRunner` is the proof point; other runners migrate when they
  need to (e.g., next time someone touches them).
- A `superpowers:production-readiness-review` skill that automates the
  iteration. Mentioned as a future follow-up in ADR-0051 but not built
  here.
- Retrofit of existing loops to use `scaffold-loop.py` — the script is
  for new loops. Existing loops keep their hand-written boilerplate.

## §3 Components in detail

### §3.1 `BaseSubprocessRunner` (the load-bearing piece)

**File:** `src/runners/base_subprocess_runner.py` (new directory).

Encapsulates the four conventions PR #8439 surfaced as load-bearing.

**Generic over the subclass result type.** The base class does not impose
a single shared dataclass — different runners want different field
shapes (`AutoAgentRunner` returns `PreflightSpawn`; future runners may
return their own dataclass). Instead, the base accepts a `SpawnOutcome`
internal record (the raw subprocess result) and the subclass packages it
into whatever typed result it wants:

```python
@dataclass(frozen=True)
class SpawnOutcome:
    """Internal record passed from base.run() to subclass._make_result.

    Internal to BaseSubprocessRunner — not part of any subclass's public
    API. Subclass converts this into its own dataclass (e.g., PreflightSpawn)
    via _make_result.
    """
    transcript: str
    usage_stats: dict[str, object]
    wall_clock_s: float
    crashed: bool
    prompt_hash: str
    cost_usd: float


T_Result = TypeVar("T_Result")


class BaseSubprocessRunner(abc.ABC, Generic[T_Result]):
    """Subprocess spawn with auth-retry + telemetry + reraise + never-raises.

    Inherit for any runner that spawns a Claude Code / codex / gemini
    subprocess. You get for free:

    - 3-attempt auth-retry loop with exponential backoff (5s, 10s, 20s)
      on AuthenticationRetryError from runner_utils.
    - reraise_on_credit_or_bug propagates CreditExhaustedError + terminal
      AuthenticationError so caretaker loops can suspend.
    - PromptTelemetry.record() with subclass-provided source attribution.
    - Cost estimation via model_pricing — overridable per subclass.
    - Never-raises contract: every failure path returns a typed result,
      never propagates a generic RuntimeError to the caller.

    Subclasses override:
    - `_telemetry_source()` → str (e.g., "auto_agent_preflight")
    - `_build_command(prompt, worktree)` → list[str] (the CLI command)
    - `_make_result(outcome: SpawnOutcome)` → T_Result — the subclass's
      own dataclass shape (e.g., PreflightSpawn). This is the
      never-raises contract.

    Subclasses MAY override:
    - `_default_timeout_s()` → int (default: config.agent_timeout)
    - `_pre_spawn_hook(prompt)` → None (logging, validation, etc.)
    - `_estimate_cost(usage_stats)` → float — defaults to model_pricing
      lookup; subclass can override for custom pricing or no-op for
      free-tier runs.
    """

    _AUTH_RETRY_MAX = 3
    _AUTH_RETRY_BASE_DELAY = 5.0  # seconds

    def __init__(self, *, config: HydraFlowConfig, event_bus: EventBus) -> None:
        ...

    async def run(
        self, *, prompt: str, worktree_path: str, issue_number: int
    ) -> T_Result:
        """Run one subprocess attempt; never raises (collapses to crashed)."""
        ...

    @abc.abstractmethod
    def _telemetry_source(self) -> str: ...

    @abc.abstractmethod
    def _build_command(self, prompt: str, worktree: Path) -> list[str]: ...

    @abc.abstractmethod
    def _make_result(self, outcome: SpawnOutcome) -> T_Result: ...

    def _estimate_cost(self, usage_stats: dict[str, object]) -> float:
        """Default cost estimate via model_pricing; subclasses override."""
        ...
```

The `Generic[T_Result]` parametrisation lets `AutoAgentRunner(BaseSubprocessRunner[PreflightSpawn])` declare its return type without forcing other future runners to use the same shape.

**Migration of `AutoAgentRunner` as proof point:**

Before: `AutoAgentRunner.run()` is ~120 lines containing the auth-retry
loop, the reraise_on_credit_or_bug call, the telemetry record, and the
crash-collapse logic.

After: `AutoAgentRunner` inherits `BaseSubprocessRunner`, defines:
- `_telemetry_source` → `"auto_agent_preflight"`
- `_build_command` → calls `build_agent_command(disallowed_tools="WebFetch")`
- `_make_result` → constructs a `PreflightSpawn`

Roughly 30 lines instead of 120. All 11 existing tests still pass (no
behavior change).

### §3.2 `scripts/scaffold-loop.py`

Generates a new caretaker loop with all conventions correct.

**Usage:**

```bash
python scripts/scaffold-loop.py NEW_NAME \
    --description "What this loop does (one line)" \
    --type caretaker  # or "subprocess" — determines base class
```

**What it does (in order):**

1. **Generates new files** from Jinja2 templates at `scripts/scaffold_templates/`:
   - `src/new_name_loop.py` — loop class inheriting `BaseBackgroundLoop`
     (caretaker) or `BaseSubprocessRunner` (subprocess), with kill-switch
     gate, static config gate, and stub `_do_work` body.
   - `src/state/_new_name.py` — state mixin with stub accessors.
   - `tests/test_new_name_loop.py` — basic kill-switch + interval tests.
2. **Patches the five-checkpoint files** atomically (temp branch + apply +
   verify + checkout if any single edit fails):
   - `src/models.py` — appends `StateData` field stubs.
   - `src/state/__init__.py` — adds mixin import + MRO.
   - `src/config.py` — adds config fields (interval, enabled) + env overrides.
   - `src/service_registry.py` — import + dataclass + construction +
     ServiceRegistry kwarg.
   - `src/orchestrator.py` — `bg_loop_registry` + `loop_factories` entries.
   - `src/ui/src/constants.js` — `EDITABLE_INTERVAL_WORKERS` +
     `SYSTEM_WORKER_INTERVALS` + `BACKGROUND_WORKERS`.
   - `src/dashboard_routes/_common.py` — `_INTERVAL_BOUNDS`.
   - `tests/scenarios/catalog/loop_registrations.py` — `_build_NEW_NAME` +
     `_BUILDERS` entry.
   - `tests/scenarios/catalog/test_loop_*.py` — appends to expected-name
     list.
   - `docs/arch/functional_areas.yml` — area assignment (asks user which area).
3. **Dry-run by default**: prints unified diff of all planned edits, asks
   `Apply all edits? [y/N]`. Only proceeds on explicit `y`.
4. **Atomic apply (file-level transaction)**: writes all planned edits
   to a tempdir mirror of the repo, validates the result compiles
   (`uv run python -c "import src.new_name_loop"`), then bulk-copies
   the tempdir contents into the real working tree. If validation fails,
   the tempdir is discarded and the working tree is untouched. Then runs
   `make arch-regen` to refresh generated docs. (This is file-level
   atomicity, not a git branch — the working tree never has half-applied
   edits.)
5. **Prints next-step checklist**: "Implement `_do_work` body, customize
   the prompt, run tests, commit."

**Constraints:**

- Must succeed against a clean working tree only (refuses to run if
  `git status` is dirty).
- Dry-run mode (`--dry-run` flag) prints planned edits and exits without
  modifying anything — useful for CI and reviews.
- Generated code passes `make quality` immediately on apply.

### §3.3 Auto-generated PRPort signature conformance

**File:** `tests/scenarios/fakes/test_port_signature_conformance.py` (new).

**Existing coverage (don't duplicate):**

- `tests/scenarios/fakes/test_port_conformance.py` does
  `isinstance(FakeGitHub(), PRPort)` — passes when method names match,
  but Protocol's structural subtyping doesn't compare signatures.
  C2/C3 from PR #8439 (`remove_labels` plural typo, nonexistent
  `list_issue_comments`) slipped through this test even though the
  Fake's surface was wrong.
- `tests/test_ports.py` (lines 350–372) already does `inspect.signature`
  parameter-name comparison for `IssueStorePort` against the real
  `IssueStore` adapter. This is Port↔Adapter coverage at the signature
  level for that one Port pair only.

**The gap this spec closes — Port↔Fake at the signature level for ALL
Port/Fake pairs:**

The new test asserts that for every `(Port, Fake)` pair, the Fake has a
method with the same name AND the same kwarg signature as the Port for
every public Port method. Signature compatibility check uses
`inspect.signature` and asserts:

- Same parameter names (kwargs must match — all Ports use keyword-only
  args by convention).
- Same required vs optional status.
- Type annotations: equal OR fake's is a wider type (e.g., `Any`).

**Strict signature test:**

```python
import inspect
from typing import Protocol, get_type_hints

import pytest

from ports import PRPort, WorkspacePort, IssueStorePort  # all formal Ports
from tests.scenarios.fakes.fake_github import FakeGitHub
# ... other fakes

_PORT_FAKE_PAIRS = [
    (PRPort, FakeGitHub),
    (WorkspacePort, FakeWorkspace),
    # IssueStorePort: no Fake; Port↔Adapter signature parity is already
    # covered by tests/test_ports.py against the real IssueStore adapter.
    # ... add other Port/Fake pairs as Fakes are introduced.
]


@pytest.mark.parametrize("port_cls, fake_cls", _PORT_FAKE_PAIRS)
def test_fake_signatures_match_port(port_cls, fake_cls):
    """For every method on the Port, the Fake must have a method with
    the same name AND the same kwarg signature."""
    port_methods = _public_methods(port_cls)
    fake_methods = _public_methods(fake_cls)

    missing = port_methods.keys() - fake_methods.keys()
    assert not missing, (
        f"{fake_cls.__name__} missing methods from {port_cls.__name__}: "
        f"{sorted(missing)}"
    )

    for name in port_methods:
        port_sig = inspect.signature(port_methods[name])
        fake_sig = inspect.signature(fake_methods[name])
        assert _signatures_compatible(port_sig, fake_sig), (
            f"{fake_cls.__name__}.{name} signature mismatch:\n"
            f"  Port: {port_sig}\n"
            f"  Fake: {fake_sig}"
        )
```

**Compatibility check (`_signatures_compatible`):**

- Same parameter names (kwargs must match)
- Same required vs optional status
- Type annotations: equal OR fake's is a wider type (e.g., `Any`).

**Auto-discovery (later iteration):**

Initially the `_PORT_FAKE_PAIRS` list is hand-maintained. A follow-up
could auto-discover via the convention `Fake<PortStem>` (already used
by `tests/scenarios/fakes/test_port_conformance.py`'s extractor).
Out of scope for v1; hand-maintained list works fine for the ~5 Ports.

**Will surface pre-existing drift:**

Running this test for the first time will likely flag drift on
existing Port/Fake pairs that has been silently OK because of
`AsyncMock`. The PR that introduces this test must either fix the
drift OR add explicit `xfail` markers with linked follow-up issues.

### §3.4 Pre-commit `arch-regen` check

**Approach: fail-fast with helpful message; do NOT auto-stage.**

The existing Makefile already has an `arch-check` target (line 572) that
runs the regen in `--check` mode and fails the build when generated docs
are stale. The pre-commit infrastructure just needs to invoke it:

**Update `.githooks/pre-commit`** (the existing hook):

The current hook short-circuits when no Python files are staged
(line 30: `if [ -z "$STAGED_PY" ]; then exit 0`). This creates a
coverage gap — adding a new `.likec4` diagram, editing
`docs/arch/functional_areas.yml`, or any non-Python arch source change
silently skips the check.

Replace the early-exit with a broader trigger condition:

```bash
# After the existing STAGED_PY check, also detect arch source changes.
STAGED_ARCH=$(git diff --cached --name-only --diff-filter=ACM \
    -- 'docs/arch/*.likec4' \
       'docs/arch/functional_areas.yml' \
       'docs/arch/source/*' \
       'src/*.py' || true)

if [ -n "$STAGED_ARCH" ]; then
    if ! make -s arch-check >/tmp/arch-check.out 2>&1; then
        echo "❌ docs/arch/generated/ is out of sync with source."
        echo ""
        echo "Run:"
        echo "  make arch-regen && git add docs/arch/"
        echo ""
        echo "First 20 lines of arch-check output:"
        head -20 /tmp/arch-check.out
        exit 1
    fi
fi
```

No new Makefile target is needed — `arch-check` already does the right
thing (it's the same target CI uses via
`tests/architecture/test_curated_drift.py`). The pre-commit hook just
shifts the failure point earlier, saving a CI cycle.

**Why this trigger condition matches the regen surface:**

The arch extractors (`src/arch/extractors/`) read from `src/*.py`,
`docs/arch/*.likec4`, and `docs/arch/functional_areas.yml`. Any change
to those source files can produce stale generated docs.

**Why fail-fast not auto-stage:**

- Auto-staging surprises the engineer ("why did this commit grow 8 files?").
- The fail message tells them exactly what to do (single command to
  paste-and-run).
- Same UX as ruff's "run `ruff check --fix`" message — well-understood
  pattern.
- No risk of staging unintended changes if the regen has a bug.

**Coverage:**

The CI architecture-tests already check `test_curated_drift` post-push.
This pre-commit hook just shifts the failure point earlier (pre-commit
instead of post-push), saving a CI cycle.

### §3.5 ADR-0051: Iterative production-readiness review

**File:** `docs/adr/0051-iterative-production-readiness-review.md` (new).

Codifies the multi-pass review pattern as an ADR. Format mirrors ADR-0049
(the kill-switch convention) — explicit "this is how we do it".

```markdown
# ADR-0051: Iterative Production-Readiness Review

**Status:** Accepted
**Date:** 2026-04-26
**Related:** ADR-0049 (kill-switch convention), ADR-0050 (auto-agent
  HITL pre-flight), `docs/wiki/dark-factory.md` (lessons inventory)
**Enforced by:** subagent-driven-development workflow, this ADR

## Context

Across the trust-fleet (#8390) and auto-agent (#8431, #8439) feature
builds, every Critical finding caught in fresh-eyes review was a missed
load-bearing convention. Each feature took 3–5 review iterations before
converging to "no Critical findings on the next pass." Without an
explicit policy, convergence is a heroic ad-hoc effort that depends on
the engineer remembering to dispatch reviewers; with one, it's the
standard workflow.

## Decision

For substantial features (new caretaker loop, new runner, spec →
multi-task implementation), after the implementation passes its per-task
reviews, run **fresh-eyes review iterations** until convergence.

- Each iteration uses `superpowers:code-reviewer` (or equivalent reviewer
  with no conversation context) on the cumulative diff against `main`.
- The reviewer reads the spec + the diff + the live codebase, and
  reports Critical / Important / Minor findings.
- After fixes, the next iteration repeats.
- **Convergence = next pass finds nothing material** (Critical = 0,
  Important ≤ 1, all explained as deliberate).

Plan for **3 iterations** before merge. Empirical convergence point on
recent features:

- Trust-fleet (#8390): 5 passes
- Auto-Agent spec (#8431): 3 passes
- Auto-Agent wiring (#8439): 3 passes

## Consequences

**Positive:**
- Critical bugs caught at PR time, not in production.
- Reviews surface architectural drift while still cheap to fix.
- "Substantial features take 3 review passes" becomes a planning
  expectation, not a surprise.

**Negative:**
- Substantial features take longer to merge (~30–60 min of reviewer
  time per pass).
- Reviewers must read live code (not just the diff) — but
  `code-reviewer` agent already does this.

**Risks:**
- Reviewer fatigue / noise from repeated passes. Mitigation: skip
  iterations once convergence reached; Minor-only findings don't
  re-trigger.

## Alternatives Considered

- **Single review pass.** Rejected — empirically misses bugs.
- **Reviewer in CI (mandatory).** Rejected — too much friction; reviewer
  needs codebase access and runs ~5 minutes per pass.
- **Pre-merge checklist.** Rejected — doesn't catch what reviewers do
  (cross-cutting drift, contract holes).

## Source-file citations

- `docs/wiki/dark-factory.md` §3 — the convergence loop documentation
- `superpowers:code-reviewer` — the reviewer skill (existing)
- `superpowers:subagent-driven-development` — per-task reviews already
  use this pattern
```

**CLAUDE.md addition:**

The Workflow skills section gets a new line:

```markdown
For substantial features, end with **2–3 fresh-eyes review iterations**
per ADR-0051 until convergence (next pass finds nothing material).
```

(Already added in PR #8443; this spec confirms the wording matches.)

## §4 Sequencing

Three PRs, each independently mergeable in order. Each PR's risk is
explicitly named so reviewers know what to scrutinise.

### §4.1 PR 1: ADR-0051 + pre-commit `arch-regen`

**Files:** `docs/adr/0051-iterative-production-readiness-review.md`
(new), `Makefile` (one new target + pre-commit hook addition),
`CLAUDE.md` (one workflow-section line).

**Risk: zero.** Docs + Makefile only. No runtime code changes.

**Lands first** so the process expectation is in writing before the
infrastructure work begins.

### §4.2 PR 2: `BaseSubprocessRunner` + `AutoAgentRunner` migration + auto-PRPort signature conformance

**Files (new):**

- `src/runners/__init__.py`
- `src/runners/base_subprocess_runner.py`
- `tests/test_base_subprocess_runner.py`
- `tests/scenarios/fakes/test_port_signature_conformance.py`

**Files (modified):**

- `src/preflight/auto_agent_runner.py` — refactored to inherit from
  `BaseSubprocessRunner`. Removes ~90 lines of duplicated logic.

**Risk: medium.** Refactor of a recently-merged loop. Mitigations:

- All 11 existing `AutoAgentRunner` tests must still pass post-migration.
- The new strict signature-conformance test will likely flag pre-existing
  Port/Fake drift — the PR addresses what's flagged or marks `xfail` with
  linked follow-up issues.
- BaseSubprocessRunner has its own unit tests covering auth-retry,
  reraise propagation, never-raises contract.

### §4.3 PR 3: `scripts/scaffold-loop.py`

**Files (new):**

- `scripts/scaffold-loop.py` — the script itself.
- `scripts/scaffold_templates/` — Jinja2 templates for generated files.
- `tests/test_scaffold_loop.py` — golden-file tests.

**Risk: medium.** Scaffold script is non-trivial (atomically patches
~10 files). Mitigations:

- Dry-run by default — script never modifies anything without explicit
  `y` confirmation.
- Refuses to run on a dirty working tree.
- Atomic apply via temp branch — reverts on any single-edit failure.
- Golden-file tests cover the diff shape against a fixture loop name.
- Self-validation: scaffold a throwaway `_test_scaffold_canary` loop,
  verify it passes `make quality`, then revert.

## §5 Testing

Per layer:

| Layer | PR 1 | PR 2 | PR 3 |
|---|---|---|---|
| **Unit** | — | `BaseSubprocessRunner` auth-retry loop, reraise propagation, never-raises contract, telemetry source attribution | Scaffold template rendering, dry-run output formatting, atomic-apply rollback on failure |
| **Integration / scenario** | — | `AutoAgentRunner` continues to pass all 11 existing tests post-migration | Scaffold runs end-to-end against a fixture name; generated loop instantiates cleanly via `LoopCatalog` |
| **Architecture** | Pre-commit dry-run targets the same regen logic the existing CI test does | New strict-signature port-conformance test runs against ALL Port/Fake pairs | Scaffold output passes `test_loop_wiring_completeness.py`, `test_functional_area_coverage.py`, `test_curated_drift.py` |
| **Adversarial** | — | `AutoAgentRunner`'s existing adversarial corpus (12 entries: 9 sub-label happy paths + 3 negative cases) continues to pass | — |

**Self-validation criterion:** before merging PR 3, scaffold a throwaway
loop named `_test_scaffold_canary`, verify all checkpoints pass, then
revert. If the scaffold output passes every test the codebase enforces,
the abstraction works. If it doesn't, fix the scaffold templates until
it does.

## §6 Failure modes

| Failure | Handling |
|---|---|
| `BaseSubprocessRunner` migration breaks AutoAgentRunner behavior | All 11 existing tests + 12 corpus entries catch this. PR 2 doesn't merge if any fail. |
| Port-signature conformance flags pre-existing Port/Fake drift | The PR addresses the drift OR marks `xfail` with linked follow-up issues. The drift was always there; surfacing it is a feature, not a regression. |
| Pre-commit `arch-regen` check is slow | Should be ≤2s (regen runs against in-memory representation, not full file rewrite). If it crosses 5s, gate behind `--enable-arch-check` flag. |
| Scaffold script fails mid-apply | Atomic via temp branch — reverts everything cleanly. Engineer's working tree is unchanged. |
| Scaffold-generated loop has subtle bugs | Golden-file tests + the canary self-validation catch the diff shape. Logic bugs in the generated `_do_work` body are the engineer's responsibility (the scaffold generates a stub). |
| Pre-existing Port/Fake drift surfaces too many issues to fix in PR 2 | Mark all flagged drift as `xfail` with linked follow-up issues; the strict conformance test still catches NEW drift introduced going forward. |

## §7 Migration & rollout

### §7.1 No code-side migration required

- New runners inherit from `BaseSubprocessRunner`.
- Existing runners (besides `AutoAgentRunner`) keep their hand-written
  logic. Migration is opportunistic — when someone next touches them,
  they can refactor.
- New caretaker loops use `scripts/scaffold-loop.py`. Existing loops
  keep their boilerplate.
- The strict signature-conformance test starts passing the day PR 2
  merges (with `xfail` markers on existing drift if any).

### §7.2 Adoption signal

Three weeks after PR 3 lands:

- How many PRs touched `scripts/scaffold-loop.py` to add a new loop?
  (Expected: 1–2.)
- How many PRs touched the strict signature-conformance test? (Expected:
  0 — the test fails on drift, doesn't get touched directly.)
- How many PRs got blocked by the pre-commit `arch-regen` check?
  (Expected: 1–3 per week, blocked then fixed within minutes.)

If adoption is zero, revisit whether the conventions are well-known
enough to use, or whether the scaffold UX needs work.

## §8 Out of scope (explicit)

- Subagent-verify wrapper — Claude Code SDK / hook concern.
- Migration of every existing runner to `BaseSubprocessRunner`.
- A `superpowers:production-readiness-review` skill that automates the
  iteration. Mentioned as a future follow-up in ADR-0051.
- Retrofit of existing loops to use `scaffold-loop.py`.
- Auto-discovery of Port/Fake pairs (hand-maintained list works for v1).

---

**End of design spec.**
