# ADR-0056: LabelDriftWatcherLoop — Cross-Entity State-Machine Drift Caretaker

- **Status:** Accepted
- **Date:** 2026-05-07
- **Supersedes:** none
- **Superseded by:** none
- **Related:** [ADR-0002](0002-labels-as-state-machine.md) (label state machine), [ADR-0029](0029-caretaker-loop-pattern.md) (caretaker-loop pattern), [ADR-0049](0049-trust-loop-kill-switch-convention.md) (kill-switch convention). Code: `src/label_drift_watcher_loop.py`, `src/pr_manager.py` (`find_label_drift`), `src/models.py` (`LabelDrift`).

## Context

ADR-0002 enforces "exactly one pipeline label per issue" via the atomic
`swap_pipeline_labels` primitive and `tests/test_state_machine.py`.
That invariant is per-entity. In May 2026 we discovered three distinct
sources of *cross-entity* drift between issues and their linked PRs:

1. `implement_phase` published partial work for failed attempts
   (fixed in PR-A).
2. `_is_zero_commit_failure` was too narrowly typed (PR-B).
3. `pr_unsticker` re-applied issue origin to PR on HITL release (PR-D).

We don't have evidence we've found all the drift sources. A periodic
scan-and-reconcile loop catches the long tail without us having to
enumerate every code path.

## Decision

Add `LabelDriftWatcherLoop` extending `BaseBackgroundLoop` per
ADR-0029 caretaker pattern. Each tick:

1. Query GitHub for open PRs and parse `Fixes #N` from each body.
2. For each pair, fetch the issue's labels and the PR's commits count.
3. Detect drift: issue at `hydraflow-ready`/`hydraflow-plan` while
   PR is at `hydraflow-review` with commits.
4. Detect drift: PR at `hydraflow-ready`/`hydraflow-plan` with
   commits (PR-stage labels are review/hitl/fixed, never ready/plan).
5. Reconcile by calling `swap_pipeline_labels` with the correct
   per-entity target (mirroring Phase D's split-call pattern).

Default interval: 600s (10 min). Operator-tunable via dashboard.

## Consequences

- Zero new infrastructure: reuses `BaseBackgroundLoop`, `DedupStore`,
  `ServiceRegistry` plumbing per ADR-0029.
- One tick is O(open PRs at review). On a fleet of 50 open PRs that's
  ~50 issue-label fetches + ~50 PR-commit-count fetches per tick.
- Risk: a misclassified "drift" reconciles a label the operator wanted.
  Mitigation: the loop logs each reconcile, posts a comment on the
  issue explaining the swap, and is dashboard-toggleable to off.
- Caretaker covers gaps; per-call-site fixes (PRs A/B/D) remain the
  primary defense. The caretaker's job is "we missed one — catch it
  before a human does."

## Related

- ADR-0002 (label state machine)
- ADR-0029 (caretaker loop pattern)
- docs/superpowers/plans/2026-05-07-implement-phase-state-machine-drift-remediation.md
