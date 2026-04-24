# ADR-0048: Auto-revert on RC red (extends ADR-0042)

- **Status:** Proposed
- **Date:** 2026-04-23
- **Supersedes:** none
- **Superseded by:** none
- **Extends:** [ADR-0042](0042-two-tier-branch-release-promotion.md) (two-tier branch model)
- **Related:** [ADR-0045](0045-trust-architecture-hardening.md) §4.3
- **Enforced by:** `src/staging_bisect_loop.py` (the loop that performs the auto-revert); `tests/test_staging_bisect_loop.py`; `tests/scenarios/test_staging_bisect_scenario.py`; `tests/test_staging_bisect_e2e.py` (three-commit fixture); watchdog in `_check_pending_watchdog`; guardrail in `_check_guardrail_and_maybe_escalate`.

## Context

ADR-0042 introduced the two-tier branch model: PRs land on `staging`, release candidates promote `staging → main` after the scenario suite passes. That gave HydraFlow a green-before-production guarantee — but it did not specify what happens when the RC gate goes **red**. The historical behavior was "a human reads the failure and opens a revert PR manually," which undercuts the dark-factory property: the release-cadence loop stalls on human attention.

At the same time, auto-reverting is dangerous. A wrong auto-revert can:
- Break bisectability by rewriting recent history.
- Revert a partial fix that a human was already iterating on.
- Loop on a flaky RC (every flaky red causes a revert, which itself is a new red, which causes another revert, etc.).

We needed an auto-revert policy that is aggressive enough to keep the release cadence lights-off, conservative enough not to thrash history, and observable enough that operators can see when it's active.

## Decision

`StagingBisectLoop` (spec §4.3) auto-reverts on confirmed RC red, with four guardrails:

### 1. Confirm red with a second probe
Before bisecting, re-run the RC's gate command (`make bisect-probe`) against the same SHA. If the second probe passes, the red was a flake — increment `flake_reruns_total`, dedup the SHA, and move on. No revert.

### 2. Bisect to attribute the culprit commit
Run `git bisect` between `last_green_rc_sha` and `last_rc_red_sha` using `make bisect-probe` as the is-broken predicate. The result is a single culprit SHA.

### 3. Guardrail: one auto-revert per RC cycle
`state.get_auto_reverts_in_cycle()` tracks reverts within the current RC cycle (a cycle starts when a new `last_rc_red_sha` is observed). If `>= 1`, `_check_guardrail_and_maybe_escalate` fires — file a `hitl-escalation` + `rc-red-attribution-unsafe` issue and do NOT revert. This prevents the loop from thrashing: two failed reverts mean a human needs to look.

### 4. Open a revert PR that auto-merges
The revert PR has labels `[hydraflow-find, auto-revert, rc-red-attribution]`. It flows through the same reviewer + quality-gate + auto-merge path as any other PR — no special privileges. On successful merge, a watchdog (`_check_pending_watchdog`) waits 8 hours for the next green RC. If the next RC is green, the cycle completes. If not, `hitl-escalation` + `rc-red-verify-timeout` fires.

### The kill-switch is live
Per ADR-0049, `StagingBisectLoop` gates on `enabled_cb`. An operator who wants to stop auto-reverts can do so from the System tab in the UI — no config edit, no restart.

## Consequences

**Positive:**
- RC red no longer stalls the release cadence for a human. Most reds get bisected, reverted, and unblocked in < 1 hour.
- Bisect attribution writes the culprit SHA into the revert PR body, giving the next human a specific place to look.
- One-auto-revert-per-cycle guardrail prevents history thrashing.

**Negative:**
- An auto-revert is a public action with git-history implications. A wrong revert means the author of the legitimately-good commit has to re-open a fixed-forward PR. Acceptable tradeoff because (a) the guardrail stops thrashing after one revert, (b) the flake-filter and bisect-attribution reduce wrong-revert rate, (c) the cost of a stalled release cadence is higher than the cost of occasionally re-opening a PR.
- The watchdog state (`_pending_watchdog`) is in-memory. An orchestrator restart during the 8-hour watchdog window loses the pending-watch. Next red re-starts the cycle.
- Bisect wall-clock cost: for a 10-commit range at ~5 min per probe, the loop ties up a worker for ~25 min. Acceptable because the alternative is a human's hour.

**Neutral:**
- Auto-reverts use the standard auto-merge channel. If the reviewer agent refuses, the revert sits as an open PR — an operator sees "auto-revert: CONFLICT needs human" in the issue queue.

## When auto-revert is wrong

If the bisect-probe is non-deterministic (e.g. depends on external wall-clock state that the probe's env can't reproduce), bisect attribution is unreliable and every revert is a gamble. Fix by making the probe deterministic, not by disabling auto-revert.

If the RC gate is too fast (sub-5-minute probes) AND the commit velocity is high, the loop can exhaust its one-revert budget on a single RC cycle before humans can triage. Fix by tuning `staging_bisect_runtime_cap_seconds` and reserving auto-revert for commits older than N minutes — proposals would supersede this ADR.

## Related

- Revert PR body template: `StagingBisectLoop._create_revert_pr` in `src/staging_bisect_loop.py`
- Watchdog state: `state.get_rc_cycle_id()` + `_pending_watchdog`
- Per-cycle counter: `state.get_auto_reverts_in_cycle()` / `state.increment_auto_reverts_in_cycle()`
- Kill-switch: `enabled_cb("staging_bisect")` (ADR-0049)
