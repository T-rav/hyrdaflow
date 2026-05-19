# ADR-0074 — RetrospectiveLoop: Durable-Queue Pattern Analysis

**Status:** Proposed
**Date:** 2026-05-19

## Context

After each successful PR merge and after each review phase, HydraFlow has the raw material to detect cross-pipeline patterns: recurring review findings, code areas with repeated implementation failures, slow phases, and model-output trends. Without a dedicated worker, this analysis either runs synchronously on the merge path (blocking) or never runs at all.

The retrospective concerns are also temporally decoupled from the work that produces them: a PR merges in seconds; the useful analysis window spans days or weeks of prior merges. A synchronous callback can't see that history.

## Decision

`RetrospectiveLoop` (`src/retrospective_loop.py`) processes analysis work from a durable `RetrospectiveQueue`. Producers (`PostMergeHandler`, `ReviewPhase`) append items asynchronously; the loop polls and processes. Items are acknowledged only after successful processing so unacknowledged items survive crashes and replay on restart.

The loop delegates to `RetrospectiveCollector` for:
- Pattern detection across the recent merge history.
- Review-insight proposal verification against current state.

Events are published to the dashboard via `EventType`. The loop deduplicates HITL stale-insight filings within a 1-hour window (`_HITL_DEDUP_WINDOW`) to avoid issue spam when the GitHub search index lags a freshly-created issue.

Kill-switch: `enabled_cb("retrospective")` (ADR-0049). Default interval: `config.retrospective_interval`.

## Consequences

- The merge path stays non-blocking; retrospective analysis runs asynchronously.
- Items survive process restarts: the durable queue is the safety net.
- The 1-hour dedup window trades recency for accuracy on back-to-back ticks; it is intentionally much shorter than the default interval.

## Alternatives considered

- **Inline on merge.** Rejected: synchronous analysis blocks the merge handler and doesn't have access to historical patterns.
- **GitHub Actions trigger.** Rejected: adds external CI dependency for internal pattern analysis.

## Related

- [ADR-0029](0029-caretaker-loop-pattern.md) — caretaker loop pattern
- [ADR-0049](0049-trust-loop-kill-switch-convention.md) — kill-switch convention
- `src/retrospective_loop.py:RetrospectiveLoop`
- `src/retrospective_queue.py:RetrospectiveQueue`
- `src/retrospective.py:RetrospectiveCollector`
