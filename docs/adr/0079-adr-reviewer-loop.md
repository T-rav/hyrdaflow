# ADR-0079 — ADRReviewerLoop: Autonomous Council Review for Proposed ADRs

**Status:** Proposed
**Date:** 2026-05-19

## Context

HydraFlow accumulates proposed ADRs as architectural decisions are drafted.
Without an automated review path, proposed ADRs wait indefinitely for a human
to run the council review process manually. The `ADRCouncilReviewer` in
`src/adr_reviewer.py` already encapsulates the full review pipeline
(`review_proposed_adrs` scans for Proposed-status files, runs duplicate
detection, scores against the 8-criterion rubric, and advances status to
Accepted or escalates for human review), but nothing called it on a schedule.

The review is a bounded, deterministic operation: find Proposed ADRs, run
the council review, update status. There is no reason to require human
initiation of each cycle.

## Decision

`ADRReviewerLoop` (`src/adr_reviewer_loop.py`) subclasses `BaseBackgroundLoop`
and runs on the `adr_review_interval` cadence (default: 3600 seconds). Each tick:

1. Checks the `enabled_cb` kill-switch (`worker_name="adr_reviewer"`).
2. Checks `config.adr_reviewer_loop_enabled`; returns `{status: config_disabled}` if false.
3. Delegates to `ADRCouncilReviewer.review_proposed_adrs()`, which:
   - Scans `docs/adr/` for files with `**Status:** Proposed`.
   - Runs duplicate detection and the 8-criterion rubric review.
   - Advances ADR status to Accepted or files a `hydraflow-find` issue for
     council escalation (per ADR-0040 — Proposed-only filter is the intentional scope).

The loop is wired into the orchestrator and registered in the caretaker catalog
via the `"adr_reviewer"` key. It follows the ADR-0029 caretaker loop pattern
and the ADR-0049 kill-switch convention.

## Consequences

- Proposed ADRs receive automated council review without operator scheduling.
- The review scope is intentionally bounded to Proposed-status ADRs (ADR-0040);
  Accepted, Rejected, and Superseded ADRs are not re-processed.
- Operators who want to pause review can set the kill-switch or disable
  `adr_reviewer_loop_enabled` in config.
- The loop does not open PRs; ADR status changes land via the
  `ADRCouncilReviewer` toolchain, which writes files directly.

## Alternatives considered

- **Manual invocation only.** Rejected: the existing `ADRCouncilReviewer`
  already supports the full pipeline; the loop is the steady-state driver.
- **Trigger on PR merge.** Rejected: PR hooks are unreliable for long-running
  reviews; a background loop with a configurable cadence is simpler and
  consistent with all other caretaker loops.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker background loop pattern
- [ADR-0040](0040-adr-reviewer-proposed-only-filter.md) — Proposed-only filter scope (Rejected: content below threshold, but design is valid)
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/adr_reviewer_loop.py:ADRReviewerLoop`
- `src/adr_reviewer.py:ADRCouncilReviewer`
