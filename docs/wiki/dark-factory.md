# Dark-factory engineering

The lights-off operating contract: any HydraFlow-managed project meeting the
spec runs autonomously, with humans paged only for raging fires. This entry
distills the load-bearing conventions that make that contract real, the
recurring footguns that break it, and the pattern for delivering substantial
features that survive production.

## §1 — The contract

Auto-Agent (ADR-0050) is the issue-queue layer of the contract: every
`hitl-escalation` issue is intercepted by `AutoAgentPreflightLoop`, which
attempts autonomous resolution before the issue surfaces to a human via
`human-required`. The trust fleet (ADR-0045) is the runtime layer: ten
caretaker loops watch for drift, anomalies, principles violations, RC budget
overruns, etc., and either auto-repair or escalate. ADR-0049 is the universal
kill-switch convention that lets operators flip any loop off live.

What "dark-factory ready" means concretely:

- Every escalation has an autonomous fix-attempt path before a human sees it.
- Every loop is independently kill-switchable at the UI without a redeploy.
- Every cost is observable on the dashboard with attribution to a `source`.
- Every repair is auditable post-hoc via JSONL streams.
- Every "new thing" inherits or replicates the load-bearing conventions —
  there is no single load-bearing convention you can skip without breaking
  the contract.

## §2 — Load-bearing conventions for new code

### 2.1 New caretaker loop checklist

Every new loop must:

1. **Five-checkpoint wire.** `config.py` field + env override, `service_registry.py`
   import + dataclass field + construction + ServiceRegistry kwarg,
   `orchestrator.py` `bg_loop_registry` + `loop_factories`,
   `src/ui/src/constants.js` `EDITABLE_INTERVAL_WORKERS` +
   `SYSTEM_WORKER_INTERVALS` + `BACKGROUND_WORKERS`,
   `src/dashboard_routes/_common.py::_INTERVAL_BOUNDS`,
   `tests/scenarios/catalog/loop_registrations.py` builder + entry.
   Verify with `tests/test_loop_wiring_completeness.py` (regex auto-discovery).

2. **ADR-0049 in-body kill-switch gate** at the top of `_do_work`:
   ```python
   if not self._enabled_cb(self._worker_name):
       return {"status": "disabled"}
   ```
   This is universal — no exceptions. The 18-loop retrofit (PR #8430) was
   this convention being applied codebase-wide.

3. **Static config gate** (`*_enabled` env var) for deploy-time disable
   that doesn't require the UI being up. Defense-in-depth alongside the
   in-body `enabled_cb` gate.

4. **Functional area assignment** in `docs/arch/functional_areas.yml`. The
   architecture tests (`tests/architecture/test_functional_area_coverage.py`)
   fail if a loop or port is unassigned.

5. **Architecture-generated docs regen** (`make arch-regen`). The
   `tests/architecture/test_curated_drift.py` test fails on stale generated
   docs — easy to forget after adding a new module.

### 2.2 Subprocess runner conventions

Either inherit from `BaseRunner` (you get auth-retry + telemetry + tracing
context for free) OR replicate explicitly:

- **3-attempt auth-retry loop with exponential backoff** (5s, 10s, 20s) on
  `AuthenticationRetryError` from `runner_utils`. Transient OAuth blips
  shouldn't burn the per-issue attempt cap.
- **`reraise_on_credit_or_bug(exc)`** in the broad `except` to propagate
  `CreditExhaustedError` and terminal `AuthenticationError` from
  `subprocess_util`. Without this, the loop continues ticking against an
  exhausted billing signal.
- **`PromptTelemetry.record(source=...)`** on every attempt for cost rollup
  attribution. Use a unique `source` string so the dashboard can break out
  spend per runner.
- **Never-raises contract**: every failure path returns a typed result
  (e.g., `PreflightSpawn(crashed=True, ...)`), never propagates a generic
  `RuntimeError`. The caretaker loop's outer handler shouldn't need to know
  about subprocess internals.

The Auto-Agent partial-landing → wiring follow-up (PRs #8431 → #8439)
exposed all four of these as load-bearing — the first runner cut missed
auth-retry AND `reraise_on_credit_or_bug`, and both were caught only by
fresh-eyes review.

### 2.3 Audit-on-everything

JSONL audit stream is the source of truth. Use `file_util.append_jsonl`
(does fsync) + `file_util.file_lock` (advisory lock) for durability.
StateData fields cache for fast dashboard reads; the JSONL is canonical.
This is the spec §6.3 contract for `PreflightAuditStore` — and the same
pattern applies to any new audit/cost/event JSONL stream.

### 2.4 Observability-first guardrails

Wire caps (cost, wall-clock, daily budget) into code paths but default to
`None` (unlimited). Dashboard surfaces data without alerting. Operator
decides when to impose policy. From spec §5.1 of the Auto-Agent design:
"observability-first; operator can set when needed". Avoid premature
gating that wastes operator attention on cap-hits before they have data
to know what the right cap is.

### 2.5 Honor-system + post-hoc CI enforcement

When runtime can't enforce a rule (e.g., file-path restrictions on a Claude
Code subprocess where the CLI flag operates on tool names not paths),
document clearly in the prompt envelope AND rely on principles-audit + CI
to catch violations. Don't lie about enforcement boundaries — operators
reading docs during incident triage need to know what's runtime-enforced
vs what's post-hoc-audited. The Auto-Agent `_envelope.md` revision
(`prompts/auto_agent/_envelope.md`) is the reference: clearly separates
"Enforced by the Claude Code CLI" from "Enforced post-hoc by CI /
principles audit".

### 2.6 Partial-landing visibility

If you ship scaffolding with a placeholder for a load-bearing piece, make
the placeholder OPERATIONALLY OBSERVABLE: zero spend on the dashboard,
zero resolution rate, distinct status string in the loop's payload. Document
in the ADR's Consequences section, not just a code TODO. Auto-Agent shipped
with a placeholder `_build_spawn_fn` in PR #8431; the dashboard's
`resolution_rate=0` + `spend_usd=$0` was the operational signal. PR #8439
removed the placeholder, and ADR-0050 §Consequences was updated to mark
the wiring landed.

### 2.7 Sub-label deny-list for recursion safety

Caretaker agents that act on the system shouldn't act on the system that
judges them. Auto-Agent's deny-list (`auto_agent_skip_sublabels = ["principles-stuck", "cultural-check"]`)
prevents auto-agent attempts on principles violations — letting auto-agent
"fix" a principles audit failure by editing the auditor would defeat the
audit. Hard tool restrictions in the prompt envelope reinforce this for
file-level rules (`auto_agent_preflight_loop.py`,
`principles_audit_loop.py`, ADR-0044/0049/0050 implementation files).

## §3 — The production-readiness convergence loop

For substantial features (new loop, new runner, spec → implementation):

1. **Brainstorming → spec → plan → implementation.** Standard workflow.
2. **Per-task review during implementation.** Subagent-driven development
   (`superpowers:subagent-driven-development`) does spec-compliance review
   + code-quality review per task. The trust-arch and auto-agent features
   used this — every task got 2 reviews.
3. **Fresh-eyes review iterations after implementation.** A reviewer who
   doesn't see the conversation context catches things you've grown blind
   to. Plan for **2–3 iterations** before merge. Each pass finds fewer
   issues. **Convergence = next pass finds nothing material.**
4. **Smoke-test before merge.** `make quality` is the actual gate, not
   `pytest tests/test_*.py`. Architecture tests (`test_functional_area_coverage`,
   `test_curated_drift`, `test_loop_wiring_completeness`,
   `test_port_conformance`) catch a class of issues unit tests don't.
5. **PR-merge collisions.** When main moves while your PR waits:
   `git rebase origin/main -X theirs` for arch-generated conflicts, then
   `make arch-regen`, then re-CI. Don't try to manually merge generated
   files — they're stale baselines, not real conflicts.

Feature-by-feature data points:
- Trust-fleet (PR #8390) → 5 audit passes to convergence.
- Auto-Agent spec (PR #8431) → 3 spec review + fix iterations.
- Auto-Agent subprocess wiring (PR #8439) → 3 fresh-eyes review iterations.

The convergence point is reliably ~3 passes for substantial work. Plan
for it; don't merge before it.

### Sandbox-tier expectations (added 2026-04-28 — ADR-0052)

For substantial features, the convergence loop now extends to the
sandbox tier:

- All 12 sandbox scenarios must pass on the rc/* promotion PR before
  the staging→main merge can complete. CI gates this via the
  sandbox-full job.
- Failures auto-dispatch `SandboxFailureFixerLoop`, which gives the
  auto-agent up to 3 attempts before escalating to the System tab
  HITL queue (via `/api/sandbox-hitl`).
- Nightly sandbox runs catch slow drift; failures open
  `hydraflow-find` issues per the 3-strikes-then-bug pattern.

The same MockWorld substrate (`src/mockworld/fakes/`) backs both
in-process Tier 1 and sandbox Tier 2; Port↔Fake conformance tests
keep them aligned.

## §4 — Recurring footguns

### 4.1 Subagent claims DONE without committing

Subagents sometimes report `DONE` with edits applied but not committed,
or with a partial commit that left some files staged. Always run
`git status --porcelain` and `git log -1 --stat` after a subagent reports
DONE before moving on. Hit twice during the auto-agent work (T12 wiring
and T13 close-reconciliation tasks).

### 4.2 AsyncMock hides PRPort method-name typos

Tests that use `AsyncMock(pr)` auto-create any attribute name on access,
so a typo like `pr.remove_labels(...)` (plural) when the real method is
`remove_label` (singular) passes the test but crashes in production. The
`tests/scenarios/fakes/test_port_conformance.py` is the safety net —
make sure any new method on a real Port is also added to the corresponding
Fake AND the conformance test runs. The C2/C3 critical findings on PR
#8439 were exactly this class of break.

### 4.3 Pyright IDE noise on Pydantic dynamic attrs

Pyright's static analysis can't follow the indirection from `self._data: StateData`
to fields on dynamically-composed mixin classes. Diagnostics like
`Cannot access attribute "auto_agent_attempts" for class "StateData"` are
expected noise and tolerated by the build's pyright config. **Trust the
build, not the IDE diagnostics.** Every existing mixin (`_flake_tracker.py`,
`_contract_refresh.py`, etc.) shows identical IDE warnings while passing CI.

### 4.4 Ruff strips unused imports during TDD

If you add an import (e.g., `from x import field`) before the code that
uses it, ruff's auto-fix on save strips the import as unused. The fix:
**append the implementation that uses the import FIRST, then add the
import.** Or use locally-scoped imports inside test functions when ruff
keeps stripping. Already in user memory; surfaces every few tasks.

### 4.5 Generated-file rebase pain

Conflicts in `docs/arch/generated/`, `docs/arch/.meta.json`, etc. on
rebase aren't real conflicts — they're stale baselines that need
regeneration. Recipe:
```bash
git rebase origin/main -X theirs
make arch-regen
git add -A && git commit -m "chore(arch): regen after rebase"
git push --force-with-lease
```
Hit twice during auto-agent work; both times the `-X theirs` + `make arch-regen`
recipe resolved cleanly.

### 4.6 `Tests` job timing race on auto-merge

The CI `Tests` job runs the full ~11k-test suite (~7 min). Force-pushes
during this window invalidate the run and trigger a fresh CI cycle —
which is fine, but `gh pr merge` will reject the merge as "Pull Request
has merge conflicts" if main moved during CI. The `--auto` flag is the
ideal recipe but only works if the repo enables it; otherwise, monitor
CI completion and manually merge.

## §5 — Verifying the contract is honored

Auto-discovery tests that fail when a load-bearing convention is broken:

| Test | What it catches |
|---|---|
| `tests/test_loop_wiring_completeness.py` | Loop missing one of the five checkpoints |
| `tests/architecture/test_functional_area_coverage.py` | New loop or port unassigned in `functional_areas.yml` |
| `tests/architecture/test_curated_drift.py` | Generated docs out of sync after a source-file change |
| `tests/scenarios/fakes/test_port_conformance.py` | Fake adapter drifts from Port protocol |
| `tests/test_loop_kill_switch_completeness.py` | Loop without ADR-0049 in-body gate |
| `tests/test_config_consistency.py` | `*_interval` config field without matching `_INTERVAL_BOUNDS` entry |

Before marking work complete: run `make quality`. It runs all of these
plus the full suite. **Unit tests passing is necessary but not sufficient.**

## §6 — The meta-pattern

Across every Critical finding caught in review across the last six PRs,
the pattern was: a load-bearing convention was something a careful engineer
remembers, not something the codebase forces.

The meta-improvement is **moving conventions from "remembered" to
"structurally enforced"** — base classes that auto-apply patterns,
scaffold scripts that generate boilerplate with all the conventions
correct, conformance tests that catch contract drift, pre-commit checks
that block the most common omissions.

See ADR-0051 (when written) for the formal "iterative production-readiness
review" process and the planned infrastructure improvements
(`BaseSubprocessRunner`, `scripts/scaffold-loop.py`, auto-PRPort
conformance, subagent-verify wrapper, pre-commit arch-regen).

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
