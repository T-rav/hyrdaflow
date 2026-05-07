# Factory Autonomy Caretaker Loops — Design

**Date:** 2026-05-07
**Status:** Draft (pre-plan)
**Scope:** Three new background loops that automate the recurring manual fixes the factory autonomy standard describes. Closes the keystone gap: standards as docs become standards as enforced control.
**Related:**
- [`docs/standards/factory_operation/README.md`](../../standards/factory_operation/README.md) (the kernel)
- [`docs/standards/factory_autonomy/README.md`](../../standards/factory_autonomy/README.md) (the directive)
- ADR-0029 (Caretaker Loop Pattern)
- ADR-0042 (Two-tier branch model)

## 1. Problem & Goal

The factory autonomy standard says agents should auto-fix tractable + reversible CI blockers. Today that depends on an LLM session being live to do the work — a human-tethered factory. The standard names three recurring patterns explicitly: stale arch-regen artifacts, PRs targeting the wrong base branch, and ADR-gate failures on implementation-level touchpoints. Each has been observed three or more times in recent operation.

Goal: convert each from "agent reacts in-session" to "loop reacts always", so factory autonomy holds even when no LLM session is active.

Non-goals (deferred):
- The meta `LessonsCaretakerLoop` that mines patterns to propose new caretaker loops. Designed in a follow-up spec once these three have shipped enough data to mine.
- `PRUnsticker` extension to inline-classify failures. Bigger refactor; defer until these loops show how often they fire.
- Cross-repo application (these loops watch one repo at a time).

## 2. The three loops

Each loop is a `BaseBackgroundLoop` subclass per ADR-0029, gated on a config flag (kill-switch convention per ADR-0049), wired through `service_registry.py` and `loop_catalog.py`.

| Loop | Trigger | Action | Kill-switch flag |
|---|---|---|---|
| `ArchRegenAutoFixer` | PR check `Tests` failed with the `test_curated_drift` failure mode | Pull PR head into a temp worktree, run `make arch-regen`, push a single commit `chore(arch): regen artifacts after upstream change` back to the PR head | `HYDRAFLOW_ARCH_REGEN_AUTOFIXER_ENABLED` |
| `BaseBranchAutoRetargeter` | New PR opened against `main` from a non-`rc/*` head ref while `staging_enabled=true` | `gh pr edit <N> --base staging`; post a comment explaining the retarget cited at ADR-0042 | `HYDRAFLOW_BASE_BRANCH_AUTORETARGET_ENABLED` |
| `SkipADRAdvisor` | PR check `ADR gate` failed and PR body lacks `Skip-ADR:` marker | Classify touchpoints (decorator-add / kwarg-add / import-path = implementation-level → auto-add `Skip-ADR:`; signature change / decision-changing modification = surface to HITL with the proposed `Skip-ADR:` text in a comment) | `HYDRAFLOW_SKIP_ADR_ADVISOR_ENABLED` |

All three loops share:
- A standard tick interval driven by `staging_promotion_interval` (default 300s) — fast enough to catch PR-CI events, slow enough to not hammer the GitHub API.
- A `processed_pr_marker` on each PR (`hydraflow-arch-regened`, `hydraflow-retargeted`, `hydraflow-skip-adr-advised`) so the loop doesn't double-process the same PR.
- A budget cap (`max_actions_per_tick`, default 5) to prevent runaway action on a CI storm.

## 3. Architecture

### 3.1 Where each loop watches

| Loop | Source signal |
|---|---|
| `ArchRegenAutoFixer` | `gh pr list --search "is:pr is:open status:failure"` filtered by check name `Tests`, then job log search for `test_curated_drift` |
| `BaseBranchAutoRetargeter` | `gh pr list --base main --search "is:open"` filtered by head ref not matching `rc/*` |
| `SkipADRAdvisor` | `gh pr list --search "is:pr is:open status:failure"` filtered by check name `ADR gate` |

Each filter is one `gh` call per tick. Cheap.

### 3.2 ArchRegenAutoFixer flow

```
1. List open PRs whose Tests check failed.
2. For each PR not already processed-marked:
   a. Fetch the failed Tests log; check for the curated-drift failure marker.
   b. If matched: clone the PR head into a temp dir, run `make arch-regen`,
      git diff for changes.
   c. If diff is non-empty: commit, push to PR head, label the PR
      `hydraflow-arch-regened`.
   d. If diff is empty (regen was a no-op): the failure is something
      else; skip and let it surface.
3. Cap at max_actions_per_tick.
```

The push reuses the existing `PRPort.push_branch` pattern. No new port methods.

### 3.3 BaseBranchAutoRetargeter flow

```
1. Skip entirely if config.staging_enabled is false (the directive only
   applies when the two-tier model is active).
2. List open PRs --base main from non-rc/* heads.
3. For each PR not already processed-marked:
   a. Call PRPort.update_pr_base(pr_number, "staging").
   b. Post a comment citing ADR-0042 + linking
      docs/standards/factory_autonomy/README.md.
   c. Label hydraflow-retargeted.
```

New port method needed: `PRPort.update_pr_base(pr_number, base) -> bool`. Wraps `gh pr edit <N> --base <base>`. Mirrors `update_pr_branch` (added by ADR-0042's auto-rebase work).

### 3.4 SkipADRAdvisor flow

This is the loop with judgment. Most ADR-gate failures are auto-applicable Skip-ADR; some need HITL.

```
1. List open PRs whose ADR gate check failed and body lacks
   `^Skip-ADR:`.
2. For each PR not already processed-marked:
   a. Fetch the ADR-gate log; extract the touchpoint list.
   b. For each touchpoint, classify the diff (see §3.5).
   c. If ALL touchpoints are implementation-level: prepend
      `Skip-ADR: <reason citing the touchpoints>` to the PR body.
   d. If ANY touchpoint is decision-changing: post a comment with
      proposed Skip-ADR text + a request for human review.
      Mark hydraflow-skip-adr-needs-review.
   e. Mark hydraflow-skip-adr-advised.
```

### 3.5 Touchpoint classification heuristics

Per the autonomy directive's worked examples, implementation-level touchpoints follow a small fixed pattern:

- **Decorator-add**: diff adds `@<decorator>` lines; no method body changes.
- **Kwarg-add**: diff adds a new keyword-only parameter with a default; no caller signature changes that aren't backward-compatible.
- **Import-path**: diff changes only `from X import Y` lines (not the imported names).
- **Method-rename-only**: diff renames a method and updates all call sites; no semantic changes.

Decision-changing touchpoints look like:

- Removed methods.
- Changed positional parameter signatures.
- Changed return types.
- Changed control-flow (added/removed conditional branches).
- Changes to the file the cited ADR's "Source-file citations" §lists by name.

If the heuristic is uncertain, default to NEEDS_REVIEW. False negatives (auto-apply when human should review) are worse than false positives (escalate when bot could've handled). The advisor errs toward escalation.

## 4. Components

### 4.1 New files

| File | Purpose |
|---|---|
| `src/arch_regen_autofixer_loop.py` | The loop |
| `src/base_branch_autoretarget_loop.py` | The loop |
| `src/skip_adr_advisor_loop.py` | The loop + classifier |
| `docs/adr/0056-arch-regen-autofixer-loop.md` | ADR per ADR-0029 convention |
| `docs/adr/0057-base-branch-autoretarget-loop.md` | ADR |
| `docs/adr/0058-skip-adr-advisor-loop.md` | ADR (includes the classifier rationale) |

### 4.2 Touched files

| File | Change |
|---|---|
| `src/config.py` | 3 new bool kill-switch fields + env overrides |
| `src/loop_catalog.py` | Register 3 new loops |
| `src/service_registry.py` | Wire 3 new loop instances |
| `src/ports.py` | New `PRPort.update_pr_base` method |
| `src/pr_manager.py` | Implementation of `update_pr_base` |
| `src/mockworld/fakes/fake_github.py` | Fake of `update_pr_base` |
| `.env.sample` | Document the 3 new flags |
| `docs/wiki/architecture-async-control.md` | Add the loops to the catalog |

### 4.3 Tests (per the test pyramid)

| Loop | Unit tests | MockWorld scenario | Sandbox e2e |
|---|---|---|---|
| `ArchRegenAutoFixer` | `tests/test_arch_regen_autofixer_loop.py` (fetch, classify, push, dedupe) | `tests/scenarios/test_arch_regen_autofixer_scenario.py` (Pattern B with FakeGitHub scripted to return a stale-drift failure log) | `tests/sandbox_scenarios/scenarios/sNN_arch_regen_autofix.py` |
| `BaseBranchAutoRetargeter` | `tests/test_base_branch_autoretarget_loop.py` | `tests/scenarios/test_base_branch_autoretarget_scenario.py` | `tests/sandbox_scenarios/scenarios/sNN_base_branch_retarget.py` |
| `SkipADRAdvisor` | `tests/test_skip_adr_advisor_loop.py` (incl. classifier) | `tests/scenarios/test_skip_adr_advisor_scenario.py` | `tests/sandbox_scenarios/scenarios/sNN_skip_adr_advisor.py` |

Sandbox scenarios may ship as placeholders if the harness needs work (per the s10/s11/s13 pattern), with a `hydraflow-find` issue for the harness gap.

## 5. Data Flow

For each loop, one tick:

```
Loop._do_work()
  ├─ Filter open PRs by signal (gh pr list)
  ├─ For each candidate PR:
  │    ├─ Skip if processed-marker label present
  │    ├─ Apply the loop's specific action
  │    └─ Set the processed-marker label
  └─ Return WorkCycleResult({"actions_taken": N})
```

Identical shape across all three loops; differs only in the filter and action.

## 6. Failure Modes

| # | Failure | Behavior |
|---|---|---|
| 1 | `gh` rate limit | Existing `_run_gh` retry-with-backoff. If still failing: log WARN, skip tick. |
| 2 | Push to PR head fails (e.g. force-push protection) | Log WARN, label `hydraflow-arch-regen-failed`, file `hydraflow-find` with reason |
| 3 | Touchpoint classification ambiguous | Default to NEEDS_REVIEW path (escalate to human) — worse to silently bypass review than to over-escalate |
| 4 | Loop's own subprocess crashes mid-tick | Existing `BaseBackgroundLoop` error handling; status reported as `error`; next tick retries |
| 5 | A PR is processed-marked but the underlying issue resurfaces (e.g. arch-regen ran but main moved again) | Marker is per-action-type; CI re-runs and the loop re-evaluates. If user removes the marker, loop re-processes — manual override path |
| 6 | Two loops act on the same PR simultaneously | Per-loop labels are distinct; no contention. Each loop is single-tick-per-PR-per-cycle. |

## 7. Volume estimate

Cadence: every 300s = 12 ticks/hour = 288 ticks/day per loop. Most ticks find zero candidates. When CI is running normally, expect <5 actions/day per loop combined. Negligible event volume.

## 8. Out of scope

- `LessonsCaretakerLoop` (the meta-loop that mines patterns). Separate spec once these three have shipped enough data.
- `PRUnsticker` inline classification (bigger refactor).
- Cross-repo operation (each loop watches the orchestrator's configured repo).
- Auto-approval of agent PRs (orthogonal — review still requires the existing reviewer flow).
- Self-fixing other classes of CI failure (lint formatting, type errors). Those are different fix recipes; could become loops later if observed 3+ times.

## 9. Verification Bar (before declaring complete)

1. `make quality` green.
2. All three loops have tests in all three pyramid layers; unit + scenario green; sandbox at least placeholder.
3. Each loop's kill-switch verified — set the flag false, observe no actions taken across 5 ticks.
4. Live observation: each loop fires at least once on a real PR matching its trigger and successfully completes the action. (Can be retroactive — a recently-merged PR that would have triggered the loop, replayed.)

## 10. Open Questions

1. Should `BaseBranchAutoRetargeter` retarget PRs from external contributors (forks)? Probably not — they may have legitimate reasons. Default: only retarget PRs from same-org head refs.
2. Should `SkipADRAdvisor` ever AMEND an existing Skip-ADR (e.g. if the touchpoints expanded)? Default: no — once advised, leave it alone unless a human edits the body.
3. Should the loops respect a `do-not-touch` label on the PR? Default: yes, treat the label as an opt-out. Document in each ADR.

## 11. Decisions Log

| # | Decision | Rationale |
|---|---|---|
| D1 | Three separate loops, not one combined `FactoryAutonomyLoop` | Each has different trigger sources, different test surfaces, different kill-switches. Combining would conflate observability. |
| D2 | Sandbox e2e tests OK to ship as placeholders | Per s10/s11/s13 precedent; harness gaps tracked as find-issues; loop coverage at unit + scenario layers is the safety bar. |
| D3 | Touchpoint classifier defaults to NEEDS_REVIEW | False negatives (auto-bypass when human should review) violate the autonomy directive's escape hatch ("when in doubt, escalate"). |
| D4 | Process markers are GitHub labels, not state-tracker entries | Labels are visible in the GitHub UI, survive orchestrator restart, easy for humans to remove for re-processing. |
| D5 | Defer `LessonsCaretakerLoop` to follow-up spec | These three give us 4 weeks of mining-source data first. Build the meta-loop on evidence. |
